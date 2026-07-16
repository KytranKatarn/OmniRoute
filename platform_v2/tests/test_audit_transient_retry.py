"""Regression test: the Code Health fix-gen batch must RETRY transient dispatch
failures, not mark them permanently attempted.

Root cause (investigated 2026-07-16): of 855 attempted proposals, ~441 failed for
TRANSIENT reasons — the assigned agent was resting (C.R.E.E.D. welfare gate:
shift_state winding_down/cooldown) or the model returned an empty response
(cold-load / Ollama saturation / timeout). dispatch_audit_proposals called
_mark_dispatch_attempted() on ALL non-queued failures, so these self-resolving
failures were marked permanent (dispatch_attempted=true) and NEVER retried — the
whole self-heal backlog silently died with a ~0.35% fix-gen yield.

_is_transient_dispatch_error() classifies a failure as retryable (True) vs
permanent (False). Transient failures defer (like cold-load) instead of being
marked attempted; a bounded defer count prevents head-of-line starvation.
"""

import services.audit_pipeline as ap


# ── transient (retryable): agent resting / model busy ────────────────────────
def test_transient_shift_state_denial():
    assert (
        ap._is_transient_dispatch_error(
            "C.R.E.E.D. Gate 1 denied: agent shift_state is 'winding_down', expected active or deployed"
        )
        is True
    )


def test_transient_bridge_empty_response():
    assert ap._is_transient_dispatch_error("Bridge returned empty response") is True


def test_transient_queued_cold_load():
    assert ap._is_transient_dispatch_error("queued_cold_load") is True


def test_transient_timeout():
    assert ap._is_transient_dispatch_error("dispatch timeout after 360s") is True


# ── permanent (NOT retryable): must still be marked attempted ─────────────────
def test_permanent_file_not_found():
    assert ap._is_transient_dispatch_error("Source file not found: [APP_CORE]/tools/security/routes.py") is False


def test_permanent_fix_apply_reject():
    assert ap._is_transient_dispatch_error("fix_apply:find_not_located") is False


def test_permanent_synthetic_placeholder():
    assert ap._is_transient_dispatch_error("Synthetic placeholder, no file to fix") is False


def test_empty_and_none_are_not_transient():
    assert ap._is_transient_dispatch_error("") is False
    assert ap._is_transient_dispatch_error(None) is False
