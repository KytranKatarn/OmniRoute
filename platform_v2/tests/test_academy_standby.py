"""Guards for Academy Standby — quiescing the fleet for honest benchmarking (#383).

The load-bearing test is `test_security_controls_are_NEVER_held`. The first
version of the protect pattern would have stood down `agent_auto_block`,
`agent_anomaly_detection` and `agent_camera_anomaly` for the whole benchmark
window — caught by a dry run against the live control surface, not by unit
tests, which is why it is pinned here now.
"""

from __future__ import annotations

import pytest

from services.academy_standby import (
    DEFAULT_TTL_MIN,
    MAX_TTL_MIN,
    MIN_TTL_MIN,
    clamp_ttl,
    describe,
    is_protected,
    plan_standby,
)


def _c(key, enabled=True):
    return {"key": key, "enabled": enabled}


# --------------------------------------------------------------------------
# What must keep running
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "agent_auto_block",
        "agent_anomaly_detection",
        "agent_camera_anomaly",
        "vigilil_threat_responder",
        "vigilil_dns_anomaly",
    ],
)
def test_security_controls_are_NEVER_held(key):
    """A benchmark window is exactly when unusual load makes an incident easiest
    to miss. Standing down threat response to measure a model is not a trade
    worth making."""
    assert is_protected(key)
    assert key not in plan_standby([_c(key)])["hold"]


@pytest.mark.parametrize(
    "key",
    [
        "agent_approvals",
        "website_deploy_worker",
        "hub_deploy_advisor",
        "quality_review",
        "agent_stuck_job_watchdog",
        "agent_stale_job_reaper",
        "agent_fleet_health",
        "agent_mesh_health",
    ],
)
def test_ship_and_safety_controls_are_protected(key):
    """The whole point is to test AND still review/ship PRs, with the watchdogs
    watching."""
    assert is_protected(key)


@pytest.mark.parametrize(
    "key",
    [
        "agent_auto_generate_docs",
        "agent_browser_tasks",
        "agent_calendar_drive",
        "chronicle_story_worker",
        "agent_email_queue",
    ],
)
def test_ordinary_background_work_IS_held(key):
    """The noise this exists to silence — and the test that stops the protect
    pattern quietly widening until it protects everything and holds nothing."""
    assert not is_protected(key)
    assert key in plan_standby([_c(key)])["hold"]


# --------------------------------------------------------------------------
# The snapshot discipline
# --------------------------------------------------------------------------


def test_already_disabled_controls_are_not_held():
    """Disabling an already-off control would put it in the snapshot and then
    'restore' it to off — making release() look like it changed things it did
    not. fleet_backlog_runner is live proof this case is real."""
    p = plan_standby([_c("fleet_backlog_runner", enabled=False)])
    assert p["hold"] == []
    assert p["already_off"] == ["fleet_backlog_runner"]


def test_duplicate_keys_are_deduped():
    """list_controls() really does return duplicates — fleet_backlog_runner
    appears twice live. Counting it twice inflates the report and toggles it
    twice."""
    p = plan_standby([_c("dup"), _c("dup"), _c("other")])
    assert p["hold"] == ["dup", "other"]


def test_first_occurrence_wins_a_later_row_cannot_flip_the_decision():
    p = plan_standby([_c("x", enabled=True), _c("x", enabled=False)])
    assert p["hold"] == ["x"] and p["already_off"] == []


def test_every_control_lands_in_exactly_one_bucket():
    rows = [_c("agent_approvals"), _c("agent_browser_tasks"), _c("off_one", False)]
    p = plan_standby(rows)
    total = len(p["hold"]) + len(p["protected"]) + len(p["already_off"])
    assert total == 3
    assert set(p["hold"]) & set(p["protected"]) == set()


def test_malformed_rows_are_skipped():
    p = plan_standby([None, {}, "nope", {"key": "   "}, _c("real")])
    assert p["hold"] == ["real"]


def test_empty_input_is_clean():
    assert plan_standby([]) == {"hold": [], "protected": [], "already_off": []}
    assert plan_standby(None)["hold"] == []


# --------------------------------------------------------------------------
# The TTL — a standby nobody releases must not starve the platform
# --------------------------------------------------------------------------


def test_ttl_is_clamped_both_ways():
    assert clamp_ttl(1) == MIN_TTL_MIN
    assert clamp_ttl(99999) == MAX_TTL_MIN
    assert clamp_ttl(45) == 45


def test_ttl_garbage_falls_back_to_the_default_not_zero():
    """A 0 or None TTL would read as 'already expired' or 'never expires'
    depending on the caller — neither is a safe reading of bad input."""
    assert clamp_ttl(None) == DEFAULT_TTL_MIN
    assert clamp_ttl("banana") == DEFAULT_TTL_MIN


def test_describe_distinguishes_dry_run_from_applied():
    p = plan_standby([_c("agent_browser_tasks"), _c("agent_approvals")])
    assert "WOULD hold" in describe(p, 45, True)
    assert "HOLDING" in describe(p, 45, False)
    assert "1 protected" in describe(p, 45, True)
