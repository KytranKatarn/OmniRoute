"""Recovery preserves attempt history and never replaces an uncertain live worker."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

from flask import Blueprint, Flask
import pytest
from services import audit_pipeline, delegation_service, work_control_service
from services import planned_repair_recovery as service
from services import planned_repair_service


@pytest.fixture
def recovery(monkeypatch):
    data = {
        "proposal": {
            "id": 19,
            "status": "approved",
            "metadata": {
                "source": "code_health_audit",
                "issue_code": "LARGE_FILE",
                "file_path": "platform_v2/tools/department_hq/jobs.py",
                "planned_repair": {"task_id": 1, "kind": "planned_refactor"},
            },
        },
        "tasks": {
            1: {
                "id": 1,
                "status": "deferred",
                "metadata": {},
                "delegation_args": {"capability": "codex_task", "args": {"repair_proposal_id": 19}},
            }
        },
        "enabled": True,
        "fail_link": False,
    }
    lock = RLock()

    class Cursor:
        def execute(self, sql, params):
            if "SELECT * FROM improvement_proposals" in sql:
                assert "FOR UPDATE" in sql
                self.row = data["proposal"]
            elif "SELECT * FROM unified_tasks" in sql:
                assert "FOR UPDATE" in sql
                self.row = data["tasks"].get(params[0])
            elif "UPDATE unified_tasks" in sql:
                task = data["tasks"][params[1]]
                assert task["status"] == "deferred"
                task.update(status="cancelled", metadata=dict(task["metadata"], **params[0].adapted))
            elif "INSERT INTO unified_tasks" in sql:
                task_id = len(data["tasks"]) + 1
                data["tasks"][task_id] = {
                    "id": task_id,
                    "status": params[3],
                    "metadata": {},
                    "delegation_args": json.loads(params[6]),
                }
                self.row = {"id": task_id}
            elif "UPDATE improvement_proposals" in sql:
                if data["fail_link"]:
                    raise RuntimeError("link failed")
                data["proposal"]["metadata"].update(params[0].adapted)
            else:
                raise AssertionError(sql)

        def fetchone(self):
            return self.row

    @contextmanager
    def db(commit=True):
        with lock:
            before = deepcopy(data)
            try:
                yield None, Cursor()
            except Exception:
                data.clear()
                data.update(before)
                raise

    monkeypatch.setattr(service, "get_db_cursor", db)
    monkeypatch.setattr(
        delegation_service, "get_db_cursor", lambda **kw: pytest.fail("must share recovery transaction")
    )
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": True})
    monkeypatch.setattr(work_control_service, "is_enabled", lambda *a, **k: data["enabled"])
    monkeypatch.setattr(
        planned_repair_service,
        "classify",
        lambda _: {
            "eligible": True,
            "kind": "planned_refactor",
            "file_path": "platform_v2/tools/department_hq/jobs.py",
        },
    )
    return data


def act(action="cancel", task_id=1):
    return service.recover_planned_work(19, "42", action, task_id)


def test_cancel_and_retry_preserve_original_task_and_history(recovery):
    assert act()["cancelled"]
    assert recovery["tasks"][1]["status"] == "cancelled"
    result = act("retry")
    assert result["queued"] and result["task_id"] == 2
    assert recovery["tasks"][1]["status"] == "cancelled"
    assert recovery["tasks"][2]["status"] == "deferred"
    meta = recovery["proposal"]["metadata"]
    assert meta["planned_repair"]["previous_task_id"] == 1
    assert meta["planned_repair_attempts"][0]["task_id"] == 1
    assert meta["planned_repair_attempts"][0]["cancelled_by"] == "42"
    assert recovery["proposal"]["status"] == "approved" and "repair_verification" not in meta


def test_concurrent_retry_creates_one_replacement(recovery):
    act()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: act("retry"), range(4)))
    assert sum(bool(r["success"]) for r in results) == 1
    assert len(recovery["tasks"]) == 2


def test_concurrent_cancellation_only_succeeds_once(recovery):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: act(), range(4)))
    assert sum(bool(r["success"]) for r in results) == 1


@pytest.mark.parametrize("status", ["in_progress", "blocked", "failed", "pending", "review", "completed", "cancelled"])
def test_uncertain_or_unmarked_workers_are_never_replaced(recovery, status):
    recovery["tasks"][1]["status"] = status
    assert not act()["success"] and not act("retry")["success"]
    assert len(recovery["tasks"]) == 1


@pytest.mark.parametrize(
    "change",
    [
        "task_id",
        "foreign_task",
        "foreign_capability",
        "pr",
        "branch",
        "proposal_pr",
        "merged",
        "status",
        "source",
        "marker",
    ],
)
def test_foreign_attempt_or_existing_pr_refuses_recovery(recovery, change):
    task = recovery["tasks"][1]
    row = recovery["proposal"]
    if change == "task_id":
        row["metadata"]["planned_repair"]["task_id"] = 99
    elif change == "foreign_task":
        task["delegation_args"]["args"]["repair_proposal_id"] = 20
    elif change == "foreign_capability":
        task["delegation_args"]["capability"] = "other"
    elif change == "pr":
        task["metadata"]["codex_pr"] = 123
    elif change == "branch":
        task["metadata"]["codex_branch"] = "codex/orphan"
    elif change == "proposal_pr":
        row["metadata"]["pr_number"] = 123
    elif change == "merged":
        row["metadata"]["merged_pr"] = 123
    elif change == "status":
        row["status"] = "pr_open"
    elif change == "source":
        row["metadata"]["source"] = "other"
    else:
        act()
        task["metadata"]["planned_cancellation"]["token"] = "wrong"
    assert not act()["success"] and not act("retry")["success"]
    assert len(recovery["tasks"]) == 1


@pytest.mark.parametrize("action", ["cancel", "retry"])
def test_link_failure_rolls_back_task_mutation_and_creation(recovery, action):
    if action == "retry":
        act()
    before = deepcopy(recovery)
    recovery["fail_link"] = True
    with pytest.raises(RuntimeError, match="link failed"):
        act(action)
    assert recovery["tasks"] == before["tasks"] and recovery["proposal"] == before["proposal"]


def test_pause_allows_withdrawal_but_refuses_new_attempt(recovery):
    recovery["enabled"] = False
    assert act()["success"]
    assert not act("retry")["success"]
    assert len(recovery["tasks"]) == 1


def test_retry_rechecks_governance_and_scope(recovery, monkeypatch):
    act()
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": False, "reason": "refused"})
    assert act("retry")["error"] == "refused"
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": True})
    monkeypatch.setattr(planned_repair_service, "classify", lambda _: {"eligible": False, "reason": "protected"})
    assert act("retry")["error"] == "protected"
    assert len(recovery["tasks"]) == 1


@pytest.mark.parametrize("task_id", [None, True, 0, -1, "1"])
def test_invalid_identity_creates_no_task(recovery, task_id):
    assert not act(task_id=task_id)["success"]


def test_routes_require_login_and_admin_and_ignore_forged_evidence(recovery, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "recovery_routes", Path(__file__).parents[1] / "tools/repair_bay/proposal_routes.py"
    )
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    monkeypatch.setattr(routes, "current_user", SimpleNamespace(get_id=lambda: "42"))
    from flask_login import LoginManager

    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True, SECRET_KEY="test-only")
    LoginManager(app)
    app.login_manager.user_loader(lambda _: None)
    allowed = [False]

    def admin(fn):
        from functools import wraps
        from flask import jsonify

        @wraps(fn)
        def check(*a, **k):
            return fn(*a, **k) if allowed[0] else (jsonify(success=False), 403)

        return check

    bp = Blueprint("recovery", __name__)
    routes.register_proposal_routes(bp, admin)
    app.register_blueprint(bp)
    client = app.test_client()
    url = "/api/proposals/19/planned-recovery"
    body = {"action": "cancel", "task_id": 1, "worker_stopped": True}
    assert client.post(url, json=body).status_code == 403
    allowed[0] = True
    assert client.post(url, json=[]).status_code == 422
    assert client.post(url, json=body).json["cancelled"]
    assert client.post(url, json={"action": "retry", "task_id": 1}).status_code == 202
    assert client.post(url, json=body).status_code == 422
    app.config["LOGIN_DISABLED"] = False
    assert client.post(url, json=body).status_code == 401
