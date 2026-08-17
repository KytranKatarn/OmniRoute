"""Tier-3 PR approval dual-surface tests (task #5283).

THE BUG: a Tier-3 PR notified via TELEGRAM ONLY, send-once
(`_mark_kytran_approval_sent`). Nothing was written to `autonomy_approval_queue`,
so nothing appeared in the Approvals tab. A missed, dismissed or undelivered
message stranded the PR with nothing visibly pending anywhere.

WORSE: the ✅ Merge button called `merge_pr(pr, "squash")` with no
`human_override`, so it ran the #5194 unattended-merge gate under the DEFAULT
authority `forge` (FORGE_AUTO_MERGE_MAX_TIER=1). Tier 3 > 1, so the gate refused
EVERY tap — the one escalation path for Tier 3 could never merge at all.

AND: `_pr_merge_callback` had NO authorization check, unlike every sibling
callback. Granting it `human_override=True` without adding one would have turned
a visibility bug into an authorization bypass — an unauthenticated callback able
to force-merge any PR past governance.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest import mock

import pytest

_PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PLATFORM))

from tools.repair_bay.services import pr_review_service as prs  # noqa: E402


# ---------------------------------------------------------------------------
# open_pr_merge_approval — the tier-conflation trap
# ---------------------------------------------------------------------------


def test_open_uses_queue_tier_2_never_1():
    """THE TRAP. Two different meanings of 'tier' meet here.

    PR merge-authority tier 3 = Kytran's, auto-merged by nobody.
    Approval-QUEUE tier 1 = AUTO-APPROVE, 2 = wait for a human.

    Filing a PR-authority Tier 3 as queue tier=1 would auto-approve instantly the
    one thing that must never auto-merge.
    """
    captured = {}

    def fake_request_approval(**kwargs):
        captured.update(kwargs)
        return 4242

    fake_mod = mock.MagicMock()
    fake_mod.request_approval = fake_request_approval
    # #5403 draft guard: None = unreadable = fail-open (pre-guard behaviour)
    with mock.patch.object(prs, "_pr_is_draft", return_value=None), mock.patch.dict(
        sys.modules, {"ai_bridge.agent_loop": fake_mod}
    ):
        out = prs.open_pr_merge_approval(2501, "some title", "some summary", repo="o/r")

    assert out == 4242
    assert captured["tier"] == 2, (
        "queue tier MUST be 2 (wait for human). tier=1 would AUTO-APPROVE a "
        "Tier-3 PR, which is auto-merged by nobody."
    )
    assert captured["action_type"] == "pr_merge"
    assert captured["action_data"]["pr_number"] == 2501
    assert captured["action_data"]["repo"] == "o/r"


def test_open_never_raises_so_telegram_still_fires():
    """Opening the row must not break the Telegram send that follows it."""
    fake_mod = mock.MagicMock()
    fake_mod.request_approval = mock.Mock(side_effect=RuntimeError("db down"))
    with mock.patch.object(prs, "_pr_is_draft", return_value=None), mock.patch.dict(
        sys.modules, {"ai_bridge.agent_loop": fake_mod}
    ):
        assert prs.open_pr_merge_approval(1, "t", "s") is None


# ---------------------------------------------------------------------------
# resolve_pr_merge_approval — shared by both surfaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("approved,expected", [(True, "approved"), (False, "rejected")])
def test_resolve_sets_status_and_scopes_to_pending_pr_merge(approved, expected):
    """Resolving must target ONLY this PR's PENDING pr_merge row.

    Scoping to status='pending' is what makes it idempotent: a second decision
    (e.g. tapping Telegram after already approving in the tab) matches no rows,
    so it cannot merge or re-decide twice.
    """
    cur = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.__enter__ = mock.Mock(return_value=(mock.MagicMock(), cur))
    ctx.__exit__ = mock.Mock(return_value=False)

    with mock.patch.object(prs, "get_db_cursor", return_value=ctx):
        prs.resolve_pr_merge_approval(2501, approved=approved, user_id=4)

    sql, params = cur.execute.call_args[0]
    assert "autonomy_approval_queue" in sql
    assert "status = 'pending'" in sql, "must not re-decide an already-resolved row"
    assert "action_type = 'pr_merge'" in sql, "must not touch other approval kinds"
    assert params[0] == expected
    assert params[1] == 4
    assert params[2] == 2501


def test_resolve_never_raises():
    """Bookkeeping failure must not turn a SUCCESSFUL merge into a reported failure."""
    with mock.patch.object(prs, "get_db_cursor", side_effect=RuntimeError("boom")):
        prs.resolve_pr_merge_approval(1, approved=True)  # must not raise


# ---------------------------------------------------------------------------
# The Telegram callback — auth and override must travel together
# ---------------------------------------------------------------------------


def _pr_merge_callback_ast():
    src = (_PLATFORM.parent / "ai_bridge" / "telegram_gateway.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_pr_merge_callback":
            return node
    raise AssertionError("_pr_merge_callback not found")


def test_callback_authorizes_before_merging():
    """human_override skips governance, so the auth check must come FIRST.

    Without it this handler is an unauthenticated force-merge of any PR.
    """
    fn = _pr_merge_callback_ast()
    auth_line = merge_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "_get_authorized_user":
                auth_line = node.lineno if auth_line is None else min(auth_line, node.lineno)
            if isinstance(f, ast.Name) and f.id == "merge_pr":
                merge_line = node.lineno if merge_line is None else min(merge_line, node.lineno)

    assert auth_line is not None, "_pr_merge_callback MUST call _get_authorized_user"
    assert merge_line is not None, "expected a merge_pr call"
    assert auth_line < merge_line, "authorization must be checked BEFORE merging"


def test_callback_passes_human_override():
    """Tier 3 > forge ceiling 1, so without the override the gate refuses every tap."""
    fn = _pr_merge_callback_ast()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "merge_pr":
            kw = {k.arg: k.value for k in node.keywords}
            assert "human_override" in kw, (
                "merge_pr must be called with human_override=True — the default "
                "authority 'forge' has ceiling 1, so a Tier-3 merge is refused"
            )
            assert isinstance(kw["human_override"], ast.Constant) and kw["human_override"].value is True
            return
    raise AssertionError("no merge_pr call found in _pr_merge_callback")
