"""Explicit retry must reset stale state without bypassing repair governance."""

from contextlib import contextmanager
import json
from unittest.mock import Mock

from flask import Blueprint, Flask
import pytest

from services import audit_pipeline as pipeline

# Load the thin route file without Repair Bay package initialization/DB DDL.
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "repair_proposal_routes_under_test", Path(__file__).parents[1] / "tools/repair_bay/proposal_routes.py"
)
proposal_routes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proposal_routes)


@pytest.fixture
def retry(monkeypatch):
    row = {
        "status": "fix_requested",
        "code_changes": "old patch",
        "metadata": {
            "source": "code_health_audit",
            "issue_code": "PYFLAKES",
            "module_name": "department_hq",
            "file_path": "platform_v2/tools/department_hq/fleet_dashboard_routes.py",
            "dispatch_attempted": True,
            "dispatch_error": "old failure",
            "defer_count": 9,
            "fix_debug": {"reason": "find_not_located"},
            "diff_stats": {"added": 3},
        },
    }
    updates = []

    class Cursor:
        def execute(self, sql, params):
            if sql.lstrip().startswith("UPDATE"):
                updates.append((sql, params))

        def fetchone(self):
            return row

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    gate = Mock(return_value={"approved": True})
    monkeypatch.setattr(pipeline, "get_db_cursor", db)
    monkeypatch.setattr(pipeline, "creed_gate_pre_dispatch", gate)
    monkeypatch.setattr("services.work_control_service.is_enabled", lambda key, default: default)
    return row, updates, gate


def test_retry_clears_stale_attempt_and_preserves_failure_evidence(retry):
    row, updates, _ = retry
    result = pipeline.request_audit_fix_retry(12875, "Re-review the generated patch")
    assert result["queued"] is True and result["status"] == "fix_requested"
    sql, params = updates[0]
    assert "code_changes = ''" in sql and params[1] == 12875
    saved = json.loads(params[0])
    assert "dispatch_attempted" not in saved and "defer_count" not in saved
    assert "diff_stats" not in saved
    assert saved["previous_dispatch_outcome"]["dispatch_error"] == "old failure"
    assert saved["previous_dispatch_outcome"]["patch_size"] == len("old patch")
    assert saved["fix_debug"] == row["metadata"]["fix_debug"]
    assert saved["file_path"] == row["metadata"]["file_path"]
    assert saved["fix_retry_requests"] == 1 and saved["fix_retry_reason"] == "Re-review the generated patch"
    assert row["metadata"]["dispatch_attempted"] is True  # input snapshot unchanged


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "archived"),
        ("source", "qa_pipeline"),
        ("issue_code", "SQL_INJECTION_RISK"),
        ("issue_code", "LARGE_FILE"),
    ],
)
def test_retry_refuses_terminal_other_sources_and_manual_findings(retry, field, value):
    row, updates, _ = retry
    if field == "status":
        row[field] = value
    else:
        row["metadata"][field] = value
    assert not pipeline.request_audit_fix_retry(1)["success"]
    assert updates == []


def test_retry_does_not_approve_pending_security_finding(retry):
    row, updates, _ = retry
    row["status"] = "pending"
    row["metadata"].update(issue_code="HARDCODED_SECRET", severity_tier="red")
    assert not pipeline.request_audit_fix_retry(1)["success"] and not updates


def test_oversight_denial_prevents_retry(retry):
    _, updates, gate = retry
    gate.return_value = {"approved": False, "reason": "Protected oversight machinery"}
    result = pipeline.request_audit_fix_retry(1)
    assert result["manual_review"] and not result["success"] and not updates


def test_retry_route_queues_without_running_inference(retry, monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    bp = Blueprint("repairs", __name__)
    proposal_routes.register_proposal_routes(bp, lambda fn: fn)
    app.register_blueprint(bp)
    dispatch = Mock(side_effect=AssertionError("web thread must not run inference"))
    monkeypatch.setattr(pipeline, "dispatch_proposal_fix", dispatch)
    proposal_routes._proposals_cache["old"] = (0, {})
    response = app.test_client().post("/api/proposals/12875/retry-fix", json={"reason": "Retry"})
    assert response.status_code == 202 and response.json["queued"]
    assert response.json["worker_enabled"] is False
    assert proposal_routes._proposals_cache == {}
    dispatch.assert_not_called()


def test_retry_route_refusal_is_not_reported_as_queued(retry):
    row, _, _ = retry
    row["metadata"]["issue_code"] = "LARGE_FILE"
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    bp = Blueprint("repairs", __name__)
    proposal_routes.register_proposal_routes(bp, lambda fn: fn)
    app.register_blueprint(bp)
    response = app.test_client().post("/api/proposals/1/retry-fix", json={})
    assert response.status_code == 422 and not response.json["success"]


def test_scoped_preview_binds_module_paths_and_never_dispatches(monkeypatch):
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchall(self):
            return [{"id": 12875, "metadata": {}}]

    @contextmanager
    def db(commit=False):
        assert not commit
        yield None, Cursor()

    monkeypatch.setattr(pipeline, "get_db_cursor", db)
    dispatch = Mock(side_effect=AssertionError("preview must not dispatch"))
    monkeypatch.setattr(pipeline, "dispatch_proposal_fix", dispatch)
    result = pipeline.dispatch_audit_proposals(limit=1, module_name="department_hq", dry_run=True)
    assert result["eligible"] == [12875]
    _, params = calls[0]
    assert params[1:3] == (r"platform_v2/tools/department\_hq/%", r"[APP_CORE]/tools/department\_hq/%")
    assert params[-1] == 1
    dispatch.assert_not_called()


@pytest.mark.parametrize("module", ["", "../faith", "department%", "department/hq", 42])
def test_invalid_scope_rejected_before_database(monkeypatch, module):
    db = Mock(side_effect=AssertionError("invalid scope must not touch database"))
    monkeypatch.setattr(pipeline, "get_db_cursor", db)
    with pytest.raises(ValueError):
        pipeline.dispatch_audit_proposals(module_name=module, dry_run=True)
    db.assert_not_called()
