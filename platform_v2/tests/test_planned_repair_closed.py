"""Closed-PR pilot checks: preserve evidence, invalidate stale intent, never execute."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
from threading import RLock
from types import SimpleNamespace, ModuleType
import sys

import pytest
from services import planned_repair_closed as service
from services import audit_pipeline, planned_repair_service, delegation_service


@pytest.fixture
def closed(monkeypatch):
    package = ModuleType("tools.repair_bay")
    package.__path__ = [str(Path(__file__).parents[1] / "tools/repair_bay")]
    monkeypatch.setitem(sys.modules, "tools.repair_bay", package)
    from tools.repair_bay.services import github_service

    row = {
        "id": 19,
        "status": "pr_open",
        "metadata": {
            "source": "code_health_audit",
            "apply_mode": "planned_codex_pr",
            "pr_number": 123,
            "file_path": "platform_v2/tools/department_hq/jobs.py",
            "issue_code": "LARGE_FILE",
            "planned_repair": {"task_id": 77},
            "repair_artifacts": {"head_sha": "a" * 40},
        },
    }
    task = {
        "id": 77,
        "status": "review",
        "metadata": {"codex_pr": 123, "codex_branch": "codex/repair"},
        "delegation_args": {"capability": "codex_task", "args": {"repair_proposal_id": 19}},
    }
    pr = {
        "number": 123,
        "state": "closed",
        "merged": False,
        "closed_at": "2026-10-09T20:00:00Z",
        "merged_at": None,
        "head": {"sha": "a" * 40, "ref": "codex/repair", "repo": {"full_name": service.REPO}},
        "base": {"ref": "main", "repo": {"full_name": service.REPO}},
    }
    data = {"row": row, "task": task, "pr": pr, "writes": [], "available": True, "race": False}
    lock = RLock()

    class Cursor:
        def execute(self, sql, params):
            self.sql = sql
            if sql.startswith("UPDATE"):
                data["writes"].append((sql, params))
                if "SET status=" in sql:
                    data["row"]["status"] = params[0]
                    updates = params[1].adapted
                else:
                    updates = params[0].adapted
                data["row"]["metadata"].update(updates)
                if data.get("fail_write"):
                    raise RuntimeError("write failed")

        def fetchone(self):
            if "unified_tasks" in self.sql:
                return deepcopy(data["task"])
            row = deepcopy(data["row"])
            if data["race"]:
                row["metadata"]["planned_repair"]["task_id"] = 88
            return row

        def fetchall(self):
            return [deepcopy(data["row"])]

    @contextmanager
    def db(commit=False):
        with lock:
            before = deepcopy(data)
            try:
                yield None, Cursor()
            except Exception:
                data.clear()
                data.update(before)
                raise

    monkeypatch.setattr(service, "get_db_cursor", db)
    monkeypatch.setattr(github_service, "_api_get", lambda *a: (data["available"], deepcopy(data["pr"])))
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": True})
    monkeypatch.setattr(planned_repair_service, "classify", lambda _: {"eligible": True})
    monkeypatch.setattr(
        delegation_service, "delegate_task", lambda *a, **k: pytest.fail("replacement intent must never create work")
    )
    return data


def request():
    return service.request_replacement(19, "42", 77, 123, "a" * 40)


def test_closed_tracking_preserves_original_artifacts_and_counts(closed):
    original = deepcopy(closed["row"]["metadata"])
    assert service.reconcile_closed_planned()["tracked"] == 1
    row = closed["row"]
    assert row["status"] == "fix_requested"
    for key, value in original.items():
        assert row["metadata"][key] == value
    assert row["metadata"]["planned_pr_observation"]["state"] == "closed"
    assert "code_applied" not in row["metadata"] and "repair_verification" not in row["metadata"]


def test_request_is_intent_only_even_with_worker_stop_field(closed):
    service.reconcile_closed_planned()
    closed["task"]["metadata"]["worker_stop_receipt"] = {"stopped": True}
    result = request()
    assert result["recorded"] and result["execution_enabled"] is False
    assert closed["row"]["status"] == "fix_requested"
    projection = service.replacement_progress(closed["row"], closed["task"])
    assert not projection["can_request"] and not projection["execution_enabled"]


def test_concurrent_duplicate_requests_record_one_intent(closed):
    service.reconcile_closed_planned()
    closed["writes"].clear()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: request(), range(4)))
    assert all(r["success"] for r in results)
    assert len({r["request_id"] for r in results}) == 1
    assert sum(bool(r.get("recorded")) for r in results) == 1
    assert len(closed["writes"]) == 1


@pytest.mark.parametrize("state", ["open", "merged"])
def test_reopened_or_merged_pr_invalidates_old_request_and_resumes_tracking(closed, state):
    service.reconcile_closed_planned()
    request()
    closed["pr"].update(state="closed" if state == "merged" else "open", merged=state == "merged")
    service.reconcile_closed_planned()
    assert closed["row"]["status"] == "pr_open"
    assert closed["row"]["metadata"]["planned_replacement_request"]["status"] == "invalidated"
    assert not request()["success"]
    assert "merged_pr" not in closed["row"]["metadata"]  # completion authority still needs reviewed merge proof


def test_changed_head_invalidates_request_and_requires_fresh_identity(closed):
    service.reconcile_closed_planned()
    request()
    closed["pr"]["head"]["sha"] = "b" * 40
    service.reconcile_closed_planned()
    assert closed["row"]["metadata"]["planned_replacement_request"]["status"] == "invalidated"
    assert not request()["success"]
    result = service.request_replacement(19, "42", 77, 123, "b" * 40)
    assert result["recorded"]
    assert len(closed["row"]["metadata"]["planned_replacement_history"]) == 1


@pytest.mark.parametrize(
    "problem",
    [
        "unavailable",
        "foreign_repo",
        "foreign_branch",
        "foreign_pr",
        "foreign_task",
        "invalid_head",
        "missing_close",
        "contradictory_merge",
    ],
)
def test_unknown_or_foreign_evidence_blocks_requests_without_clearing_history(closed, problem):
    service.reconcile_closed_planned()
    request()
    original = deepcopy(closed["row"]["metadata"]["planned_replacement_request"])
    if problem == "unavailable":
        closed["available"] = False
    elif problem == "foreign_repo":
        closed["pr"]["head"]["repo"]["full_name"] = "other/repo"
    elif problem == "foreign_branch":
        closed["pr"]["head"]["ref"] = "codex/other"
    elif problem == "foreign_pr":
        closed["pr"]["number"] = 124
    elif problem == "foreign_task":
        closed["task"]["delegation_args"]["args"]["repair_proposal_id"] = 20
    elif problem == "invalid_head":
        closed["pr"]["head"]["sha"] = "bad"
    elif problem == "missing_close":
        closed["pr"]["closed_at"] = None
    else:
        closed["pr"]["merged_at"] = "2026-10-09T20:00:00Z"
    assert service.reconcile_closed_planned()["blocked"] == 1
    assert closed["row"]["metadata"]["planned_replacement_request"] == original
    assert not request()["success"]
    assert not service.replacement_progress(closed["row"], closed["task"])["can_request"]


def test_attempt_change_while_observing_cannot_overwrite_new_link(closed):
    closed["race"] = True
    service.reconcile_closed_planned()
    assert closed["writes"] == []


def test_request_write_failure_rolls_back(closed):
    service.reconcile_closed_planned()
    before = deepcopy(closed["row"])
    closed["fail_write"] = True
    with pytest.raises(RuntimeError, match="write failed"):
        request()
    assert closed["row"] == before


def test_current_governance_and_scope_refusal_apply_to_intent(closed, monkeypatch):
    service.reconcile_closed_planned()
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": False, "reason": "protected"})
    assert request()["error"] == "protected"
    monkeypatch.setattr(audit_pipeline, "creed_gate_pre_dispatch", lambda _: {"approved": True})
    monkeypatch.setattr(planned_repair_service, "classify", lambda _: {"eligible": False, "reason": "outside scope"})
    assert request()["error"] == "outside scope"


def test_route_requires_login_admin_and_ignores_browser_stop_claim(closed, monkeypatch):
    service.reconcile_closed_planned()
    from flask import Flask, Blueprint, jsonify
    from flask_login import LoginManager
    from functools import wraps

    spec = importlib.util.spec_from_file_location(
        "closed_routes", Path(__file__).parents[1] / "tools/repair_bay/proposal_routes.py"
    )
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    monkeypatch.setattr(routes, "current_user", SimpleNamespace(get_id=lambda: "42"))
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True, SECRET_KEY="test-only")
    LoginManager(app)
    app.login_manager.user_loader(lambda _: None)
    permitted = [False]

    def admin(fn):
        @wraps(fn)
        def checked(*a, **k):
            return fn(*a, **k) if permitted[0] else (jsonify(success=False), 403)

        return checked

    bp = Blueprint("closed", __name__)
    routes.register_proposal_routes(bp, admin)
    app.register_blueprint(bp)
    client = app.test_client()
    url = "/api/proposals/19/planned-replacement"
    body = {"task_id": 77, "pr_number": 123, "head_sha": "a" * 40, "worker_stopped": True, "execute": True}
    assert client.post(url, json=body).status_code == 403
    permitted[0] = True
    assert client.post(url, json=["bad"]).status_code == 422
    response = client.post(url, json=body)
    assert response.status_code == 200 and response.json["recorded"] and not response.json["execution_enabled"]
    assert client.post(url, json=body).json["already_requested"]
    app.config["LOGIN_DISABLED"] = False
    assert client.post(url, json=body).status_code == 401


@pytest.mark.parametrize(
    "state,error,expected",
    [
        ("open", None, "pr_review"),
        ("closed", None, "pr_closed_unmerged"),
        ("merged", None, "merged_awaiting_verification"),
        ("closed", "GitHub unavailable", "blocked"),
    ],
)
def test_progress_uses_observed_state_and_requires_review_of_observed_head(closed, monkeypatch, state, error, expected):
    from services import repair_progress

    review = {
        "state": "closed" if state != "open" else "open",
        "review_status": "reviewed",
        "ai_summary": "APPROVE",
        "metadata": {"head_sha": "a" * 40, "reviewed_head_sha": "a" * 40},
    }
    row = deepcopy(closed["row"])
    row["metadata"].update(
        planned_pr_observation={"state": state, "head_sha": "b" * 40}, planned_pr_tracking_error=error
    )

    class Cursor:
        def execute(self, *args):
            pass

        def fetchone(self):
            return review

    @contextmanager
    def db(**kwargs):
        yield None, Cursor()

    monkeypatch.setattr(repair_progress, "get_db_cursor", db)
    monkeypatch.setattr(planned_repair_service, "planned_progress", lambda *a: {})
    fake = ModuleType("tools.repair_bay.services.pr_review_service")
    fake.classify_pr_tier = lambda _: 3
    fake.verdict_is_approved = lambda _: True
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    assert repair_progress.progress(row)["stage"] == expected
