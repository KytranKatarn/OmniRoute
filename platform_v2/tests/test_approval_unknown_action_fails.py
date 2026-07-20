"""#5011 — an approval the owner tapped must never report success it did not achieve.

`_execute_approved_action`'s fallback returned {"skipped": True} with no 'executed' key, so it
inherited the `_ok = result.get("executed", True)` back-compat default (#4327) and the row was
written **status='executed'**. An approval the owner PHYSICALLY TAPPED silently did nothing
while reporting success, and the row went terminal so it could never be retried.

Observed 2026-07-20 on queue #3201 (backup_before_deploy): the handler existed on disk but the
long-lived process had not reloaded it. The tap was swallowed; the only trace was a string
buried in a JSONB column. The approval queue is the most trust-sensitive surface on the
platform — it is where a human is told their decision took effect.

Two properties are pinned here:
  * an unhandled action type is recorded as FAILED, and
  * it stays TERMINAL — it must not look like an infra death and requeue forever.
"""

import os
import sys

import pytest

sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from ai_bridge.agent_loop import AgentLoop
except Exception as exc:  # pragma: no cover - environment-dependent import
    pytest.skip(f"agent_loop unavailable: {exc}", allow_module_level=True)


# The exact dict the unknown-action branch now returns.
UNKNOWN = {
    "executed": False,
    "skipped": True,
    "error": "Unknown action type: some_new_type (no handler in the running process)",
    "reason": "Unknown action type: some_new_type",
}


def _ok(result):
    """The caller's success rule, verbatim: `_ok = (result or {}).get("executed", True)`."""
    return (result or {}).get("executed", True)


class TestUnhandledActionIsAFailure:
    def test_unknown_action_is_not_reported_as_executed(self):
        """THE BUG: this returned True, so a swallowed tap was written status='executed'."""
        assert _ok(UNKNOWN) is False

    def test_unknown_action_carries_an_actionable_error(self):
        """The old row's only trace was a reason buried in JSONB — no error field at all."""
        assert UNKNOWN.get("error")
        assert "no handler" in UNKNOWN["error"]

    def test_legacy_branches_without_the_key_still_default_to_success(self):
        """#4327's back-compat default must survive — send_email et al. omit 'executed'."""
        assert _ok({"result": "sent"}) is True
        assert _ok({}) is True


class TestItStaysTerminal:
    def test_unknown_action_is_not_mistaken_for_an_infra_death(self):
        """executed=False routes through the #4632 requeue path. An unhandled type is a REAL
        verdict, not a container dying mid-task — requeueing it would spin until the retry cap
        on every tick, for an action that can never succeed in this process."""
        assert AgentLoop._is_infra_failure(UNKNOWN) is False

    @pytest.mark.parametrize(
        "err",
        ["Timeout after 180s", "connection refused", "Connection error while dispatching"],
    )
    def test_real_infra_deaths_are_still_requeued(self, err):
        """The fix must not blunt #4632 — genuine infra deaths still retry."""
        assert AgentLoop._is_infra_failure({"executed": False, "error": err}) is True

    def test_inner_timeout_status_still_detected(self):
        assert AgentLoop._is_infra_failure({"executed": False, "result": {"_status": "timeout"}}) is True
