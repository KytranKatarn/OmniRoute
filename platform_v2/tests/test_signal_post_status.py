"""Unit tests for services.signal_post_status (Phase 1)."""

from __future__ import annotations

import pytest


@pytest.fixture
def svc():
    from services import signal_post_status

    return signal_post_status


class TestStatusClassifier:
    def test_pending_when_approval_pending(self, svc):
        approval = {"id": 1, "status": "pending", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "pending"

    def test_executing_when_approved_no_result(self, svc):
        approval = {"id": 1, "status": "approved", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "executing"

    def test_posted_when_post_log_status_posted(self, svc):
        approval = {"id": 1, "status": "executed", "execution_result": {"success": True}}
        post_log = {"approval_id": 1, "status": "posted"}
        assert svc.classify(approval, post_log=post_log) == "posted"

    def test_posted_when_executed_success_no_post_log(self, svc):
        approval = {"id": 1, "status": "executed", "execution_result": {"success": True}}
        assert svc.classify(approval, post_log=None) == "posted"

    def test_failed_when_executed_with_error(self, svc):
        approval = {
            "id": 1,
            "status": "executed",
            "execution_result": {"success": False, "_status": "failed", "error": "..."},
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_failed_when_executed_with_timeout(self, svc):
        approval = {
            "id": 1,
            "status": "executed",
            "execution_result": {"success": False, "_status": "timeout"},
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_rejected_when_approval_rejected(self, svc):
        approval = {"id": 1, "status": "rejected", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "rejected"

    def test_deferred_when_approval_deferred_session(self, svc):
        approval = {"id": 1, "status": "deferred_session", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "deferred"

    def test_handles_string_execution_result_jsonb(self, svc):
        # psycopg2 sometimes returns jsonb as a string depending on driver
        import json

        approval = {
            "id": 1,
            "status": "executed",
            "execution_result": json.dumps({"success": False, "error": "x"}),
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_rejected_when_status_abandoned(self, svc):
        """Phase 4: 'abandoned' status maps to 'rejected' chip color."""
        approval = {"id": 1, "status": "abandoned", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "rejected"

    def test_unknown_status_falls_back_to_pending(self, svc):
        # Defensive — unrecognised approval status defaults to pending
        approval = {"id": 1, "status": "weird_unknown_state", "execution_result": None}
        assert svc.classify(approval, post_log=None) == "pending"

    def test_handles_nested_result_in_execution_result(self, svc):
        # Real shape from agent_loop: execution_result = {"executed": True, "result": {...}}
        approval = {
            "id": 1,
            "status": "executed",
            "execution_result": {
                "executed": True,
                "result": {"success": False, "_status": "failed", "error": "boom"},
            },
        }
        assert svc.classify(approval, post_log=None) == "failed"

    def test_handles_nested_result_with_success(self, svc):
        approval = {
            "id": 1,
            "status": "executed",
            "execution_result": {
                "executed": True,
                "result": {"success": True, "result": "Posted 982 chars"},
            },
        }
        assert svc.classify(approval, post_log=None) == "posted"
