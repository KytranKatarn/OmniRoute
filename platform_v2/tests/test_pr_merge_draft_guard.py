"""#5403 — a Tier-2/3 merge approval must never be raised for, or burned by, a draft PR.

Live incident 2026-07-29 (approval 6485 / PR #2549): Kytran approved on
Telegram, GitHub 405'd ("Pull Request is still a draft"), the row flipped
'failed' TERMINALLY, nothing re-raised. The human's DECISION was valid; the
MECHANISM failed — conflating the two spent the authorization for nothing.

Two independent defenses, both pinned here:
1. RAISE-TIME GUARD: open_pr_merge_approval / send_pr_merge_buttons refuse to
   ask a human to authorize a structurally un-mergeable draft (fail-open on an
   unreadable draft state).
2. EXECUTE-TIME CLASSIFICATION: _is_infra_failure treats draft-405 and
   transient GitHub failures as MECHANICAL → the executor requeues (bounded)
   instead of terminal-failing the approval.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLATFORM))
sys.path.insert(0, str(_PLATFORM.parent / "ai_bridge"))

from tools.repair_bay.services import pr_review_service as prs  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Raise-time guard
# ---------------------------------------------------------------------------


def test_open_refuses_draft_and_spends_nothing():
    fake_mod = mock.MagicMock()
    fake_mod.request_approval = mock.Mock(return_value=777)
    with mock.patch.object(prs, "_pr_is_draft", return_value=True), mock.patch.object(
        prs, "get_db_cursor"
    ) as gdc, mock.patch.dict(sys.modules, {"ai_bridge.agent_loop": fake_mod}):
        gdc.return_value.__enter__.return_value = (mock.Mock(), mock.Mock())
        out = prs.open_pr_merge_approval(2549, "draft pr", "summary")
    assert out is None, "a draft PR must not create an approval row"
    fake_mod.request_approval.assert_not_called()


def test_open_fails_open_when_draft_state_unreadable():
    fake_mod = mock.MagicMock()
    fake_mod.request_approval = mock.Mock(return_value=88)
    with mock.patch.object(prs, "_pr_is_draft", return_value=None), mock.patch.dict(
        sys.modules, {"ai_bridge.agent_loop": fake_mod}
    ):
        out = prs.open_pr_merge_approval(2550, "t", "s")
    assert out == 88, "an UNREADABLE draft state must not block a legitimate approval"


def test_buttons_skipped_for_draft():
    with mock.patch.object(prs, "_pr_is_draft", return_value=True), mock.patch(
        "services.telegram_service.send_with_buttons"
    ) as swb:
        prs.send_pr_merge_buttons(2549, "draft pr", "summary")
    swb.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Execute-time mechanical classification
# ---------------------------------------------------------------------------


def _infra(result):
    import agent_loop as al  # noqa: PLC0415

    return al.AgentLoop._is_infra_failure(result)


def test_draft_405_is_mechanical_not_terminal():
    assert _infra({"executed": False, "error": 'HTTP 405 {"message":"Pull Request is still a draft"}'}) is True


def test_transient_github_5xx_is_mechanical():
    assert _infra({"executed": False, "error": "GitHub API 502 Bad Gateway"}) is True
    assert _infra({"executed": False, "error": "merge failed: 503 Service Unavailable"}) is True


def test_authorization_refusals_stay_terminal():
    # governance/authority refusals are the human-decision layer working as
    # designed — they must NEVER be retried mechanically.
    assert _infra({"executed": False, "error": "merge refused"}) is False
    assert _infra({"executed": False, "error": "pr_merge has no human approver — refusing"}) is False
    assert _infra({"executed": False, "error": "governance_blocked: verdict is needs_changes"}) is False
