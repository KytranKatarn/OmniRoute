"""#5627 — a failed LinkedIn post that SAW the authwall must mark the profile stale.

2026-08-15: five linkedin_post approvals burned over 50 minutes, each recording
'https://www.linkedin.com/uas/login?...' in its own execution_result, while the
#1831 release guard stayed open because only the 4-hourly probe could set
browser_sessions.status='stale' — and no re-auth alert ever reached the owner.
These tests pin the feedback loop: authwall diagnostics in a failed linkedin_*
result → mark_stale + deduped alert; non-linkedin and non-authwall failures
touch nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLATFORM))
sys.path.insert(0, str(_PLATFORM.parent / "ai_bridge"))

import agent_loop as al  # noqa: E402

_AUTHWALL_RESULT = {
    "executed": False,
    "error": (
        "Could not find feed share box. diagnostics={'label': 'share_box_miss', "
        "'url': 'https://www.linkedin.com/uas/login?session_redirect=https%3A%2F%2F"
        "www.linkedin.com%2Ffeed%2F'}"
    ),
}


def _run(item, result):
    with mock.patch("services.browser_session_service.mark_stale") as ms, mock.patch(
        "services.signal_calendar_service._alert_linkedin_stale"
    ) as al_alert:
        al.AgentLoop._maybe_flag_linkedin_authwall(item, result)
    return ms, al_alert


def test_authwall_failure_marks_profile_stale_and_alerts():
    item = {"id": 10803, "action_type": "linkedin_post", "action_data": {"content": "x"}}
    ms, alert = _run(item, _AUTHWALL_RESULT)
    ms.assert_called_once()
    args = ms.call_args[0]
    assert args[0] == 342 and args[1] == "linkedin", "default profile is the shared majors 342"
    alert.assert_called_once()


def test_non_linkedin_action_untouched():
    ms, alert = _run({"id": 1, "action_type": "send_email", "action_data": {}}, _AUTHWALL_RESULT)
    ms.assert_not_called()
    alert.assert_not_called()


def test_non_authwall_failure_untouched():
    # An ordinary skill verdict (e.g. comment not confirmed) must NOT stale the
    # profile — that would pause the whole calendar on a one-off content failure.
    item = {"id": 2, "action_type": "linkedin_post", "action_data": {}}
    ms, alert = _run(item, {"executed": False, "error": "comment could not be confirmed on the page"})
    ms.assert_not_called()
    alert.assert_not_called()


def test_account_resolves_browser_identity():
    item = {"id": 3, "action_type": "linkedin_post", "action_data": {"account": "terry"}}
    with mock.patch("services.browser_session_service.mark_stale") as ms, mock.patch(
        "services.signal_calendar_service._alert_linkedin_stale"
    ), mock.patch("services.signal_accounts.browser_id_for", return_value=377):
        al.AgentLoop._maybe_flag_linkedin_authwall(item, _AUTHWALL_RESULT)
    assert ms.call_args[0][0] == 377, "terry's failures must stale profile 377, not 342"


def test_never_raises_into_executor():
    # Garbage action_data must be swallowed (best-effort contract) — the
    # authwall path still completes with the default profile.
    ms, alert = _run({"action_type": "linkedin_post", "action_data": object()}, _AUTHWALL_RESULT)
    ms.assert_called_once()  # unparseable data degrades to defaults, never raises
    # And a None result short-circuits before any service call:
    ms2, alert2 = _run({"action_type": "linkedin_post", "action_data": {}}, None)
    ms2.assert_not_called()
