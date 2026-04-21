"""Unit tests for services.delegation_service (Project #276 Phase 1).

Covers delegate_task() validation, persistence, and execute_delegated_task()
routing (known-tool shortcut vs dispatcher fallback). DB boundaries are
mocked; the real integration coverage comes post-merge when the worker
loop fires against a real unified_tasks row.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# Stub tools.department_hq.services.department_dispatcher in sys.modules
# so patch() can target it. The real module pulls ``from db import ...``
# where ``db`` is under ai_bridge — not on the test sys.path. Same pattern
# as test_propose_hire.py's ai_bridge.agent_loop stub.
_pkg_tools = sys.modules.setdefault("tools", types.ModuleType("tools"))
_pkg_dhq = sys.modules.setdefault("tools.department_hq", types.ModuleType("tools.department_hq"))
_pkg_services = sys.modules.setdefault("tools.department_hq.services", types.ModuleType("tools.department_hq.services"))
_stub_dispatcher = types.ModuleType("tools.department_hq.services.department_dispatcher")
_stub_dispatcher.dispatch = MagicMock(return_value=MagicMock(success=False))
sys.modules["tools.department_hq.services.department_dispatcher"] = _stub_dispatcher
_pkg_services.department_dispatcher = _stub_dispatcher


def _mock_cursor(row=None, rows=None):
    """Return a context-manager mock that fetches ``row`` / ``rows``."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    return _CM()


@pytest.fixture
def delegation_service():
    from services import delegation_service

    return delegation_service


# ---------------------------------------------------------------------------
# delegate_task — persistence + validation
# ---------------------------------------------------------------------------


class TestDelegateTaskValidation:
    def test_missing_capability_rejected(self, delegation_service):
        result = delegation_service.delegate_task(capability="", reason="r")
        assert result["success"] is False
        assert "capability" in result["error"]

    def test_missing_reason_rejected(self, delegation_service):
        result = delegation_service.delegate_task(capability="c", reason="")
        assert result["success"] is False
        assert "reason" in result["error"]

    def test_invalid_source_rejected(self, delegation_service):
        result = delegation_service.delegate_task(
            capability="c",
            reason="r",
            delegation_source="totally_made_up",
        )
        assert result["success"] is False
        assert "Invalid delegation_source" in result["error"]
        assert "claude" in result["error"]  # surfaces valid options

    def test_priority_out_of_range_rejected(self, delegation_service):
        for bad in (0, 11, -1, 99):
            result = delegation_service.delegate_task(
                capability="c",
                reason="r",
                priority=bad,
            )
            assert result["success"] is False
            assert "priority" in result["error"]


class TestDelegateTaskPersistence:
    def test_happy_path_persists_row(self, delegation_service):
        with patch.object(
            delegation_service,
            "get_db_cursor",
            return_value=_mock_cursor(row={"id": 12345}),
        ):
            result = delegation_service.delegate_task(
                capability="run_qa_suite",
                reason="Verify PR #243 landed",
                args={"module": "autonomy"},
                delegation_source="claude",
                requested_by="claude_session_abc",
                priority=7,
            )
        assert result["success"] is True
        assert result["task_id"] == 12345
        assert "DELEGATE:claude" in result["title"]
        assert result["uses_known_tool"] is True

    def test_unknown_capability_flagged_not_known_tool(self, delegation_service):
        with patch.object(
            delegation_service,
            "get_db_cursor",
            return_value=_mock_cursor(row={"id": 7}),
        ):
            result = delegation_service.delegate_task(
                capability="summarize_knowledge",  # not in KNOWN_TOOL_CAPABILITIES
                reason="Summarize recent vault notes",
            )
        assert result["success"] is True
        assert result["uses_known_tool"] is False


# ---------------------------------------------------------------------------
# execute_delegated_task — routing logic
# ---------------------------------------------------------------------------


class TestExecuteKnownTools:
    def test_missing_capability_surfaces_error(self, delegation_service):
        result = delegation_service.execute_delegated_task({"id": 1, "delegation_args": {}})
        assert result["success"] is False
        assert result["error"] == "missing_capability"

    def test_routes_misroute_audit_to_service(self, delegation_service):
        with patch(
            "services.misroute_audit_service.run_misroute_audit",
            return_value={
                "severity": "info",
                "anomaly_count": 0,
                "window_hours": 24,
                "findings": {},
            },
        ) as run:
            result = delegation_service.execute_delegated_task(
                {
                    "id": 1,
                    "delegation_args": {
                        "capability": "run_misroute_audit",
                        "args": {"window_hours": 48},
                    },
                }
            )
        run.assert_called_once_with(window_hours=48)
        assert result["success"] is True
        assert "severity=info" in result["summary"]
        assert "window=24h" in result["summary"]

    def test_routes_misroute_adapter(self, delegation_service):
        with patch(
            "services.misroute_to_proposal_adapter.run",
            return_value={"proposals_created": 2, "skipped_duplicates": 1},
        ) as run:
            result = delegation_service.execute_delegated_task(
                {
                    "id": 2,
                    "delegation_args": {
                        "capability": "run_misroute_to_proposal_adapter",
                        "args": {},
                    },
                }
            )
        run.assert_called_once()
        assert result["success"] is True
        assert "proposals_created=2" in result["summary"]

    def test_delegation_args_json_string_still_parses(self, delegation_service):
        """Worker fetch may return jsonb as a string depending on driver."""
        import json as _json

        with patch(
            "services.misroute_audit_service.run_misroute_audit",
            return_value={
                "severity": "warning",
                "anomaly_count": 3,
                "window_hours": 24,
                "findings": {},
            },
        ):
            result = delegation_service.execute_delegated_task(
                {
                    "id": 3,
                    "delegation_args": _json.dumps({"capability": "run_misroute_audit", "args": {}}),
                }
            )
        assert result["success"] is True
        assert "severity=warning" in result["summary"]


class TestExecuteViaDispatcher:
    def test_unknown_capability_falls_through_to_dispatcher(self, delegation_service):
        fake_dispatch_result = MagicMock()
        fake_dispatch_result.success = True
        fake_dispatch_result.agent_name = "CODEX"
        fake_dispatch_result.model_used = "mistral:7b"
        fake_dispatch_result.response = "Summarized."
        fake_dispatch_result.tier = "local"
        fake_dispatch_result.cost_usd = 0.0

        with patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            return_value=fake_dispatch_result,
        ) as dispatch:
            result = delegation_service.execute_delegated_task(
                {
                    "id": 1,
                    "delegation_args": {
                        "capability": "summarize_vault_notes",
                        "args": {"limit": 5},
                        "reason": "Digest recent vault notes",
                    },
                }
            )
        dispatch.assert_called_once()
        call_kwargs = dispatch.call_args.kwargs
        assert call_kwargs["capability"] == "summarize_vault_notes"
        assert call_kwargs["module_id"] == "delegation_service"
        # Prompt should carry reason + args for the LLM
        prompt = call_kwargs["prompt"]
        assert "summarize_vault_notes" in prompt
        assert "Digest recent vault notes" in prompt
        assert result["success"] is True
        assert "CODEX" in result["summary"]
        assert result["result"]["agent"] == "CODEX"

    def test_dispatcher_failure_surfaces(self, delegation_service):
        fake_dispatch_result = MagicMock()
        fake_dispatch_result.success = False
        fake_dispatch_result.error = "No agent available for capability"

        with patch(
            "tools.department_hq.services.department_dispatcher.dispatch",
            return_value=fake_dispatch_result,
        ):
            result = delegation_service.execute_delegated_task(
                {
                    "id": 2,
                    "delegation_args": {
                        "capability": "obscure_thing",
                        "args": {},
                        "reason": "r",
                    },
                }
            )
        assert result["success"] is False
        assert "Dispatcher refused" in result["summary"]
        assert "No agent available" in result["summary"]


class TestExecutorExceptionHandling:
    def test_exception_wrapped_as_failure(self, delegation_service):
        with patch(
            "services.misroute_audit_service.run_misroute_audit",
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = delegation_service.execute_delegated_task(
                {
                    "id": 99,
                    "delegation_args": {
                        "capability": "run_misroute_audit",
                        "args": {},
                    },
                }
            )
        assert result["success"] is False
        assert "RuntimeError" in result["summary"]
        assert result["error"] == "DB connection lost"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
