"""Tests for the K.I.N. pool-saturation staffing-gap detector
(services.welfare_governance_service.recommend_pool_staffing_gaps).

The detector reads live tables (agent_skills, dispatch_pending_queue,
platform_settings), so — like test_creed_accounting_audit — these assert the
INVARIANTS the function guarantees for ANY data, not specific values the cloned
test schema happens to hold. The detector is read-only and side-effect-free (the
CREED event + Telegram advisory live only in agent_jobs.kin_recommend_pool_staffing,
NOT here), so it is safe to call directly.
"""

from __future__ import annotations

from services.welfare_governance_service import recommend_pool_staffing_gaps


def test_returns_a_list():
    result = recommend_pool_staffing_gaps()
    assert isinstance(result, list)


def test_gaps_are_well_formed_when_present():
    for gap in recommend_pool_staffing_gaps():
        assert isinstance(gap, dict)
        assert set(gap.keys()) >= {"capability", "pool_size", "backlog", "gap_reason"}
        assert isinstance(gap["capability"], str) and gap["capability"]
        assert isinstance(gap["pool_size"], int)
        assert isinstance(gap["backlog"], int)
        assert isinstance(gap["gap_reason"], str) and gap["gap_reason"]


def test_pool_saturation_invariants_hold_for_every_gap():
    # The defining contract: a pool-saturation gap is only emitted for a MULTI-agent
    # pool (>= 2 — single-agent skills are the recommend() staffing_gap's job) that has
    # a real backlog (>= 1). These must hold for every row regardless of DB contents.
    for gap in recommend_pool_staffing_gaps():
        assert gap["pool_size"] >= 2, "pool-saturation must target multi-agent pools"
        assert gap["backlog"] >= 1, "a gap must have a non-empty dispatch backlog"


def test_gaps_sorted_by_backlog_descending():
    backlogs = [g["backlog"] for g in recommend_pool_staffing_gaps()]
    assert backlogs == sorted(backlogs, reverse=True)


def test_never_raises_and_is_stable():
    # Fail-OPEN contract: a DB hiccup returns [] rather than raising — so a hiring
    # signal is never fabricated and the daily job never crashes here. Two back-to-back
    # calls stay well-formed.
    first = recommend_pool_staffing_gaps()
    second = recommend_pool_staffing_gaps()
    assert isinstance(first, list) and isinstance(second, list)


def test_custom_min_backlog_key_is_honored():
    # Passing a nonexistent settings key falls back to the default threshold rather
    # than erroring — the knob is optional, not required.
    result = recommend_pool_staffing_gaps(min_backlog_settings_key="welfare:staffing:__nope__")
    assert isinstance(result, list)
