"""The Approvals tab must not merge on a STALE verdict (#5834).

The tab merges with human_override=True, which bypasses the whole governance
gate. That is right for the ALLOWLIST — a sensitive path deliberately requires a
human and the tap is that human — but it must not also excuse staleness.

Nearly shipped 2026-08-19: approval #11693 (PR #2710) was raised at 22:57 and the
fix removing a query that took the Approvals endpoint from ~70ms to 57-84s landed
AFTER it. A tap in that window would have merged the slow version.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_bridge.agent_loop import tab_merge_refusal  # noqa: E402

_STALE = "STALE VERDICT for PR #2710: the review covers 34e82b7e but the head is now b875058b"
_ALLOWLIST = "PR #2710 changes files outside the auto-merge allowlist (services/x.py) — a human must merge it"
_TIER = "Tier 2 > FORGE_AUTO_MERGE_MAX_TIER=1 for authority 'forge' — gated for the next level up"


def test_fresh_approved_pr_is_allowed():
    assert tab_merge_refusal("VERDICT: APPROVE", True, True, "") is None


def test_stale_verdict_is_REFUSED():
    why = tab_merge_refusal("VERDICT: APPROVE", True, False, _STALE)
    assert why and "STALE" in why


def test_head_is_now_phrasing_also_caught():
    """The gate words it two ways; both must refuse."""
    assert tab_merge_refusal("VERDICT: APPROVE", True, False, "the head is now abc1234") is not None


def test_allowlist_refusal_does_NOT_block_the_tab():
    """This is what human_override exists for — the tap IS the deliberate human.
    Blocking it here would make every sensitive-path PR unmergeable from the tab,
    which is the tab's entire purpose."""
    assert tab_merge_refusal("VERDICT: APPROVE", True, False, _ALLOWLIST) is None


def test_tier_ceiling_does_NOT_block_the_tab():
    """An authority limit is the human's to clear; only safety binds everyone."""
    assert tab_merge_refusal("VERDICT: APPROVE", True, False, _TIER) is None


def test_missing_review_is_refused():
    assert tab_merge_refusal("", False, True, "") is not None


def test_non_approval_verdict_is_refused():
    why = tab_merge_refusal("VERDICT: REQUEST CHANGES", False, True, "")
    assert why and "NOT an approval" in why


def test_empty_summary_beats_a_true_verdict_flag():
    """Defensive: a caller that passes verdict_ok=True with no summary must still
    be refused — the summary is the evidence, the flag is only a derivation."""
    assert tab_merge_refusal("", True, True, "") is not None
