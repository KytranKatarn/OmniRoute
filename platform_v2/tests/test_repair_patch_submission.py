"""Stored patch advancement never regenerates or bypasses shipping gates."""

import hashlib
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask

from services import repair_submission as service


@pytest.fixture
def submission(monkeypatch):
    row = {
        "id": 42,
        "status": "ready_for_review",
        "code_changes": "saved diff",
        "metadata": {"source": "code_health_audit", "file_path": "platform_v2/tools/faith/routes.py"},
    }
    writes = []

    class Cursor:
        def execute(self, sql, params):
            if sql.startswith("UPDATE"):
                writes.append((sql, params))
                row["metadata"].update(json.loads(params[0]))

        def fetchone(self):
            return row

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(service, "get_db_cursor", db)
    monkeypatch.setattr("services.audit_pipeline.creed_gate_pre_dispatch", lambda _: {"approved": True})
    queue = Mock(return_value={"success": True, "queue_id": 17, "tier": 1, "approver": "F.O.R.G.E."})
    monkeypatch.setattr("services.proposal_service.request_tiered_deploy_approval", queue)
    fake = ModuleType("tools.repair_bay.services.forge_pipeline")
    fake._proposal_fix_fields = lambda p: {"file_path": p["metadata"]["file_path"], "code_diff": p["code_changes"]}
    fake._patched_content = Mock(return_value="patched source")
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    monkeypatch.setattr(
        service, "progress", lambda p: {"stage": p["metadata"].get("repair_submission", {}).get("stage")}
    )
    return row, writes, queue, fake


def test_saved_patch_is_preserved_and_submitted_once(submission):
    row, writes, queue, _ = submission
    result = service.request_submission(42)
    assert result["success"] and result["queued"]
    saved = result["submission"]
    assert saved["stage"] == "awaiting_review"
    assert saved["patch_sha256"] == hashlib.sha256(b"saved diff").hexdigest()
    assert saved["target_sha256"] == hashlib.sha256(b"patched source").hexdigest()
    assert row["code_changes"] == "saved diff"
    assert service.request_submission(42)["already_queued"]
    queue.assert_called_once_with(42)
    assert len(writes) == 1


def test_human_patch_approval_is_distinct_from_pr_merge_tier(submission):
    _, _, queue, _ = submission
    queue.return_value = {"success": True, "approval_id": 18, "tier": 2, "approver": "Kytran"}
    result = service.request_submission(42)["submission"]
    assert result["stage"] == "awaiting_approval"
    assert result["approval_queue_tier"] == 2
    assert "merge_tier" not in result


@pytest.mark.parametrize("status", ["pending", "approved", "fix_requested", "deployed", "pr_open"])
def test_unreviewed_or_terminal_proposals_never_ship(submission, status):
    row, writes, queue, _ = submission
    row["status"] = status
    assert not service.request_submission(42)["success"]
    queue.assert_not_called()
    assert writes == []


def test_empty_patch_never_queues(submission):
    row, writes, queue, _ = submission
    row["code_changes"] = ""
    assert not service.request_submission(42)["success"]
    queue.assert_not_called()
    assert writes == []


def test_drifted_or_invalid_patch_never_queues(submission):
    _, writes, queue, fake = submission
    fake._patched_content.return_value = None
    assert not service.request_submission(42)["success"]
    queue.assert_not_called()
    assert writes == []


def test_failed_queue_leaves_patch_and_submission_untouched(submission):
    row, writes, queue, _ = submission
    queue.return_value = {"success": False, "error": "queue unavailable"}
    assert service.request_submission(42)["error"] == "queue unavailable"
    assert row["code_changes"] == "saved diff" and "repair_submission" not in row["metadata"]
    assert writes == []


def test_governance_denial_never_queues(submission, monkeypatch):
    _, writes, queue, _ = submission
    monkeypatch.setattr(
        "services.audit_pipeline.creed_gate_pre_dispatch", lambda _: {"approved": False, "reason": "protected"}
    )
    assert service.request_submission(42)["error"] == "protected"
    queue.assert_not_called()
    assert writes == []


def test_submit_route_returns_202_and_requires_admin(monkeypatch):
    path = Path(__file__).parents[1] / "tools/repair_bay/proposal_routes.py"
    spec = importlib.util.spec_from_file_location("submission_routes_test", path)
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    monkeypatch.setattr(routes, "login_required", lambda f: f)
    allowed = {"value": True}

    def admin(fn):
        from functools import wraps
        from flask import jsonify

        @wraps(fn)
        def wrapped(*a, **kw):
            if not allowed["value"]:
                return jsonify(success=False), 403
            return fn(*a, **kw)

        return wrapped

    call = Mock(return_value={"success": True, "queued": True})
    monkeypatch.setattr(service, "request_submission", call)
    app = Flask(__name__)
    bp = Blueprint("submission-test", __name__)
    routes.register_proposal_routes(bp, admin)
    app.register_blueprint(bp)
    client = app.test_client()
    assert client.post("/api/proposals/42/submit-patch").status_code == 202
    allowed["value"] = False
    assert client.post("/api/proposals/42/submit-patch").status_code == 403
    call.assert_called_once_with(42)


@pytest.mark.parametrize("reply", ["", "UNKNOWN", "not approved", "REJECTED", "APPROVED then REJECTED", "DENIED"])
def test_ambiguous_review_cannot_authorize_shipping(reply):
    assert not service.approval_response_is_positive(reply)


@pytest.mark.parametrize("reply", ["APPROVED", "Approved - safe", "VERDICT: APPROVE"])
def test_explicit_positive_review_can_advance(reply):
    assert service.approval_response_is_positive(reply)


def test_changed_saved_patch_cannot_ship():
    proposal = {
        "code_changes": "changed",
        "metadata": {"repair_submission": {"patch_sha256": hashlib.sha256(b"original").hexdigest()}},
    }
    assert not service.patch_snapshot_matches(proposal)
    proposal["code_changes"] = "original"
    assert service.patch_snapshot_matches(proposal)


def test_existing_approval_worker_also_captures_patch_fingerprint(submission):
    row, writes, queue, _ = submission
    meta = service.ensure_patch_snapshot(42, row)
    assert meta["repair_submission"]["target_sha256"] == hashlib.sha256(b"patched source").hexdigest()
    assert len(writes) == 1
    queue.assert_not_called()


def test_stale_legacy_patch_cannot_claim_test_receipt(submission):
    row, writes, _, fake = submission
    fake._patched_content.return_value = None
    with pytest.raises(ValueError, match="no longer applies"):
        service.ensure_patch_snapshot(42, row)
    assert writes == []


def test_ready_patch_field_disagreement_never_queues(submission):
    row, writes, queue, _ = submission
    row["code_diff"] = "different saved patch"
    assert not service.request_submission(42)["success"]
    assert writes == []
    queue.assert_not_called()
