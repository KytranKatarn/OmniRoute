"""Planned work is atomic, explicitly gated, and never implies a completed repair."""

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import importlib.util
from pathlib import Path

from flask import Blueprint, Flask
import pytest

from services import audit_pipeline, delegation_service
from services import planned_repair_service as service
from services import work_control_service


@pytest.fixture
def state(monkeypatch, tmp_path):
    source = tmp_path / "routes.py"
    source.write_text("# current source\n")
    data = {
        "proposal": {
            "id": 19,
            "status": "approved",
            "metadata": {
                "source": "code_health_audit",
                "issue_code": "LARGE_FILE",
                "module_name": "department_hq",
                "file_path": "platform_v2/tools/department_hq/jobs.py",
            },
        },
        "tasks": {},
        "enabled": True,
        "fail_link": False,
    }
    lock = RLock()

    class Cursor:
        def execute(self, sql, params):
            if "SELECT * FROM improvement_proposals" in sql:
                assert "FOR UPDATE" in sql
                self.row = data["proposal"]
            elif "INSERT INTO unified_tasks" in sql:
                task_id = len(data["tasks"]) + 1
                # Use the real delegate_task insertion contract.
                data["tasks"][task_id] = {"status": params[3], "metadata": {}}
                self.row = {"id": task_id}
            elif "UPDATE improvement_proposals" in sql:
                if data["fail_link"]:
                    raise RuntimeError("link write failed")
                data["proposal"]["metadata"].update(params[0].adapted)
            elif "SELECT status,metadata,delegation_args FROM unified_tasks" in sql:
                self.row = data["tasks"].get(params[0])
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
    # A second connection would expose an orphan task before the proposal link commits.
    monkeypatch.setattr(delegation_service, "get_db_cursor", lambda **kw: pytest.fail("must use linking transaction"))
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": True})
    monkeypatch.setattr(
        audit_pipeline,
        "resolve_proposal_source",
        lambda path: (str(source), path.replace("[APP_CORE]", "platform_v2"), "ok"),
    )
    monkeypatch.setattr(work_control_service, "is_enabled", lambda key, default=True: data["enabled"])
    data["db"] = db
    return data


def test_concurrent_clicks_create_one_linked_task(state):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.request_planned_work(19, "42"), range(4)))
    assert all(r["success"] and r["task_id"] == 1 for r in results)
    assert sum(bool(r.get("queued")) for r in results) == 1
    assert len(state["tasks"]) == 1
    assert state["tasks"][1]["status"] == "deferred"
    assert state["proposal"]["metadata"]["planned_repair"]["task_id"] == 1
    assert state["proposal"]["status"] == "approved"


def test_failed_link_rolls_back_task_and_retry_is_safe(state):
    state["fail_link"] = True
    with pytest.raises(RuntimeError, match="link write failed"):
        service.request_planned_work(19, "42")
    assert not state["tasks"] and "planned_repair" not in state["proposal"]["metadata"]
    state["fail_link"] = False
    assert service.request_planned_work(19, "42")["task_id"] == 1


@pytest.mark.parametrize(
    "change",
    ["disabled", "pending", "security", "protected", "outside_scope", "existing_pr", "existing_patch", "other_source"],
)
def test_ineligible_work_creates_no_task(state, change):
    row = state["proposal"]
    meta = row["metadata"]
    if change == "disabled":
        state["enabled"] = False
    elif change == "pending":
        row["status"] = "pending"
    elif change == "security":
        meta["issue_code"] = "SQL_INJECTION_RISK"
    elif change == "protected":
        meta["file_path"] = "platform_v2/tools/department_hq/services/smart_router.py"
    elif change == "outside_scope":
        meta["file_path"] = "config/agents/codex.yaml"
    elif change == "existing_pr":
        meta["pr_number"] = 22
    elif change == "existing_patch":
        meta["repair_submission"] = {"stage": "sandbox_testing"}
    else:
        meta["source"] = "other"
    assert not service.request_planned_work(19, "42")["success"]
    assert not state["tasks"]


def test_governance_denial_cannot_be_bypassed(state, monkeypatch):
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": False, "reason": "protected"})
    assert service.request_planned_work(19, "42") == {"success": False, "error": "protected"}
    assert not state["tasks"]


def test_legacy_path_uses_current_scope(state):
    state["proposal"]["metadata"]["file_path"] = "[APP_CORE]/tools/department_hq/jobs.py"
    assert service.classify(state["proposal"])["eligible"]


@pytest.mark.parametrize("status", ["deferred", "in_progress", "review", "completed", "blocked", "cancelled"])
def test_progress_never_closes_or_verifies_a_finding(state, status):
    service.request_planned_work(19, "42")
    state["tasks"][1].update(status=status, metadata={"codex_pr": 123})
    before = deepcopy(state["proposal"])
    with state["db"]() as (_, cur):
        result = service.planned_progress(state["proposal"], cur)
    assert result["task_status"] == status and result["pr_number"] == 123
    assert result["stage"] != "verified_complete"
    assert state["proposal"] == before


def test_missing_linked_task_blocks_without_requeue(state):
    service.request_planned_work(19, "42")
    state["tasks"].clear()
    with state["db"]() as (_, cur):
        assert service.planned_progress(state["proposal"], cur)["stage"] == "planned_blocked"
    assert service.request_planned_work(19, "42")["already_queued"]
    assert not state["tasks"]


def test_control_registry_defaults_off():
    assert work_control_service.BACKLOGS[service.CONTROL_KEY]["default"] is False


def test_plan_route_requires_login_and_queues_without_inference(state, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "planned_proposal_routes", Path(__file__).parents[1] / "tools/repair_bay/proposal_routes.py"
    )
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    monkeypatch.setattr(routes, "current_user", SimpleNamespace(get_id=lambda: "42"))
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    from flask_login import LoginManager

    LoginManager(app)
    app.config["SECRET_KEY"] = "test-only"
    app.login_manager.user_loader(lambda _: None)
    bp = Blueprint("repairs", __name__)
    routes.register_proposal_routes(bp, lambda fn: fn)
    app.register_blueprint(bp)
    client = app.test_client()
    first = client.post("/api/proposals/19/plan-repair")
    second = client.post("/api/proposals/19/plan-repair")
    assert first.status_code == 202 and first.json["queued"]
    assert second.status_code == 200 and second.json["already_queued"]
    app.config["LOGIN_DISABLED"] = False
    # login_required must refuse before it reaches the admin/service layers.
    assert client.post("/api/proposals/19/plan-repair").status_code == 401
