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


import pytest  # noqa: E402
from tests.modstub import stub_module_scoped  # noqa: E402

# Stub tools.department_hq.services.department_dispatcher in sys.modules
# so patch() can target it. The real module pulls ``from db import ...``
# where ``db`` is under ai_bridge — not on the test sys.path. Same pattern
# as test_propose_hire.py's ai_bridge.agent_loop stub.
_pkg_tools = sys.modules.setdefault("tools", types.ModuleType("tools"))
_pkg_dhq = sys.modules.setdefault("tools.department_hq", types.ModuleType("tools.department_hq"))
_pkg_services = sys.modules.setdefault("tools.department_hq.services", types.ModuleType("tools.department_hq.services"))
_stub_dispatcher = types.ModuleType("tools.department_hq.services.department_dispatcher")
_stub_dispatcher.dispatch = MagicMock(return_value=MagicMock(success=False))

# PEP 562 catch-all: a sys.modules stub replaces the module for the WHOLE session, so
# ANY name a later-collected module imports from it must resolve or collection aborts
# for all 3,332 tests (#5665). Enumerating names is whack-a-mole — dispatch_json,
# DispatchResult and resolve_department_escalation_owner each surfaced in turn.
# Explicitly-set attributes above still win; this only catches the rest.
_stub_dispatcher.__getattr__ = lambda _n: MagicMock()
# ── Installed for THIS MODULE'S TESTS ONLY, not the whole session (#6018) ────────────
# This used to be a bare, permanent assignment here at import time. pytest imports every
# test module during COLLECTION, so from that moment the stub was what the ENTIRE session
# saw, and any later module wanting the real dispatcher got the stub instead — silently,
# and only when the suite ran as a whole. That is #6017: 8 tests in
# test_fleet_candidate_welfare_gate failing together while passing 8/8 in isolation.
#
# Safe to defer because delegation_service imports the dispatcher LAZILY, inside a function
# (services/delegation_service.py:999 `from ...department_dispatcher import dispatch`), so
# the stub is only needed while these tests RUN — never at collection.
_DISPATCHER = "tools.department_hq.services.department_dispatcher"


@pytest.fixture(scope="module", autouse=True)
def _dispatcher_stub():
    """Scope the dispatcher stub to this module; restore both bindings afterwards."""
    with stub_module_scoped(_DISPATCHER, _stub_dispatcher):
        yield


# Stub telegram_service too — hitting the live service during tests would
# try to reach archie_comms (http://192.168.1.200:3002). delegation_service
# imports it lazily inside emit_delegation_event, so we only need the
# module to be resolvable when patch() looks it up.
# NOT a sys.modules stub (see test_delegate_late_result_salvage.py for the full note).
# FIVE test modules each installed a bare `types.ModuleType("services.telegram_service")`
# via setdefault at import time, with DIFFERENT attribute sets — one of them empty. Because
# setdefault means first-writer-wins, whichever file pytest collected first silently defined
# the telegram API that every later test saw, and the rest inherited it. Removing only one
# handed the slot to a poorer stub and turned 10 failures into 38 errors.
# Patching the real module keeps sys.modules honest and makes collection order irrelevant.
@pytest.fixture(scope="module", autouse=True)
def _telegram_quiet():
    """Silence Telegram sends for this module without replacing the module object."""
    with patch("services.telegram_service.send_info", MagicMock(return_value={"sent": True})), patch(
        "services.telegram_service.send_system", MagicMock(return_value={"sent": True})
    ):
        yield


# Stub the translation orchestrator. The real module imports ``database`` and
# scanner submodules; the test only needs the symbol resolvable for patch().
_pkg_consciousness = sys.modules.setdefault("tools.consciousness", types.ModuleType("tools.consciousness"))
_pkg_translation_scanners = sys.modules.setdefault(
    "tools.consciousness.translation_scanners",
    types.ModuleType("tools.consciousness.translation_scanners"),
)
_stub_orchestrator = types.ModuleType("tools.consciousness.translation_scanners.orchestrator")
_stub_orchestrator.run_translation_coverage_scan = MagicMock(return_value={})
sys.modules["tools.consciousness.translation_scanners.orchestrator"] = _stub_orchestrator
_pkg_translation_scanners.orchestrator = _stub_orchestrator


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

    def test_run_qa_suite_without_suite_id_runs_all(self, delegation_service):
        """A bare run_qa_suite (full health scan) runs every active suite and
        succeeds even when some tests are red — the scan completing is success,
        not a per-test pass. Previously this hard-failed 'requires suite_id'."""
        suites = [{"id": 1, "name": "platform"}, {"id": 2, "name": "wtf"}]

        def _fake_run(sid, **kw):
            return {1: [{"status": "pass"}], 2: [{"status": "pass"}, {"status": "fail"}]}[sid]

        with patch("services.qa_service.get_suites", return_value=suites), patch(
            "services.qa_service.run_suite", side_effect=_fake_run
        ):
            result = delegation_service.execute_delegated_task(
                {"id": 1, "delegation_args": {"capability": "run_qa_suite", "args": {}}}
            )
        assert result["success"] is True, "scan ran → success, despite a red test"
        assert result["result"]["suites_ran"] == 2
        assert result["result"]["failed"] == 1
        assert result["result"]["suites_with_failures"] == ["wtf#2: 1/2"]

    def test_run_qa_suite_no_active_suites_fails(self, delegation_service):
        with patch("services.qa_service.get_suites", return_value=[]):
            result = delegation_service.execute_delegated_task(
                {"id": 1, "delegation_args": {"capability": "run_qa_suite", "args": {}}}
            )
        assert result["success"] is False
        assert "no active QA suites" in result["summary"]

    def test_routes_translation_coverage_scan(self, delegation_service):
        with patch(
            "tools.consciousness.translation_scanners.orchestrator.run_translation_coverage_scan",
            return_value={
                "gaps_found": 7,
                "auto_fixed": 3,
                "routed": 2,
                "bundles_written": 1,
                "duration_ms": 4250,
            },
        ) as run:
            result = delegation_service.execute_delegated_task(
                {
                    "id": 4,
                    "delegation_args": {
                        "capability": "translation_coverage_scan",
                        "args": {"trigger": "git_hook", "changed_count": 2},
                    },
                }
            )
        run.assert_called_once_with()
        assert result["success"] is True
        assert "gaps=7" in result["summary"]
        assert "auto_fixed=3" in result["summary"]
        assert "bundles=1" in result["summary"]
        assert result["result"]["duration_ms"] == 4250

    def test_translation_coverage_scan_is_known_tool(self, delegation_service):
        """Regression guard — capability must stay in KNOWN_TOOL_CAPABILITIES.
        If it falls out of the set, dispatcher fallback would route the
        request to an LLM agent and bypass the deterministic orchestrator.
        """
        assert "translation_coverage_scan" in delegation_service.KNOWN_TOOL_CAPABILITIES

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


class TestCodexDelegation:
    """Phase B — capability='codex_task' must be DEFERRED, not dispatched.

    The host poller (codex-delegation-worker.sh) owns these rows. Creating them
    'deferred' makes them invisible to the pending-only delegate_task_worker, so
    they never reach the cluster dispatcher (Codex can't run on Ollama).
    """

    @staticmethod
    def _capturing_cm(row):
        cur = MagicMock()
        cur.fetchone.return_value = row
        conn = MagicMock()

        class _CM:
            def __enter__(self):
                return (conn, cur)

            def __exit__(self, *args):
                return False

        return _CM(), cur

    def test_codex_task_inserts_deferred_status(self, delegation_service):
        cm, cur = self._capturing_cm({"id": 555})
        with patch.object(delegation_service, "get_db_cursor", return_value=cm):
            result = delegation_service.delegate_task(
                capability="codex_task",
                reason="add a docstring to faith routes",
                delegation_source="claude",
                project_id=310,
            )
        assert result["success"] is True
        assert result["task_id"] == 555
        assert result.get("deferred_to") == "codex"
        sql, params = cur.execute.call_args.args
        assert "INSERT INTO unified_tasks" in sql
        # status param must be 'deferred', NOT 'pending'
        assert "deferred" in params
        assert "pending" not in params

    def test_non_codex_task_stays_pending(self, delegation_service):
        cm, cur = self._capturing_cm({"id": 556})
        with patch.object(delegation_service, "get_db_cursor", return_value=cm):
            result = delegation_service.delegate_task(
                capability="run_qa_suite",
                reason="run autonomy suite",
                delegation_source="claude",
            )
        assert result["success"] is True
        assert result.get("deferred_to") is None
        sql, params = cur.execute.call_args.args
        assert "pending" in params
        assert "deferred" not in params

    def test_pending_fetch_excludes_deferred(self, delegation_service):
        """Regression guard: the pending-only worker query must keep its
        status='pending' filter so deferred codex rows are never claimed."""
        import inspect

        src = inspect.getsource(delegation_service.fetch_pending_delegations)
        assert "status = 'pending'" in src


class TestEmitDelegationEvent:
    """Phase 3 — Unified Comms streaming. Verifies the shape of the
    message handed to telegram_service and that failures are suppressed
    so streaming bugs can never break the worker loop."""

    def test_start_event_uses_send_info(self, delegation_service):
        import services.telegram_service as tg

        tg.send_info.reset_mock()
        tg.send_system.reset_mock()
        delegation_service.emit_delegation_event(
            task_id=42,
            event_type="start",
            capability="run_qa_suite",
            delegation_source="claude",
        )
        tg.send_info.assert_called_once()
        tg.send_system.assert_not_called()
        title = tg.send_info.call_args.args[0]
        body = tg.send_info.call_args.args[1]
        assert "#42" in title
        assert "picking up" in title
        assert "run_qa_suite" in body
        assert "claude" in body

    def test_complete_event_includes_summary(self, delegation_service):
        import services.telegram_service as tg

        tg.send_info.reset_mock()
        tg.send_system.reset_mock()
        delegation_service.emit_delegation_event(
            task_id=43,
            event_type="complete",
            capability="run_misroute_audit",
            summary="severity=info, 13 anomalies",
            delegation_source="claude",
        )
        tg.send_info.assert_called_once()
        body = tg.send_info.call_args.args[1]
        assert "Result: severity=info, 13 anomalies" in body

    def test_fail_event_uses_send_system_escalation(self, delegation_service):
        import services.telegram_service as tg

        tg.send_info.reset_mock()
        tg.send_system.reset_mock()
        delegation_service.emit_delegation_event(
            task_id=44,
            event_type="fail",
            capability="obscure_thing",
            summary="Dispatcher refused: no agent available",
            delegation_source="claude",
        )
        tg.send_system.assert_called_once()
        tg.send_info.assert_not_called()
        assert "failed" in tg.send_system.call_args.args[0]

    def test_telegram_streaming_channel_routes_to_chat_id(self, delegation_service):
        import services.telegram_service as tg

        tg.send_info.reset_mock()
        tg.send_system.reset_mock()
        delegation_service.emit_delegation_event(
            task_id=45,
            event_type="start",
            capability="health_check",
            delegation_source="claude",
            streaming_channel="telegram:5551234567",
        )
        kwargs = tg.send_info.call_args.kwargs
        assert kwargs.get("chat_id") == "5551234567"

    def test_exception_in_streaming_is_suppressed(self, delegation_service):
        """If telegram_service explodes, emit must NOT raise — it would
        break the worker loop otherwise."""
        import services.telegram_service as tg

        tg.send_info.side_effect = RuntimeError("comms bridge down")
        tg.send_info.reset_mock()
        try:
            delegation_service.emit_delegation_event(
                task_id=46,
                event_type="start",
                capability="run_qa_suite",
                delegation_source="claude",
            )
        except Exception as exc:  # pragma: no cover — failure path
            pytest.fail(f"emit_delegation_event must suppress exceptions, raised: {exc}")
        finally:
            tg.send_info.side_effect = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
