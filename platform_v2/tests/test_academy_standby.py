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


# --------------------------------------------------------------------------
# The state write — one transaction, never an orphan
# --------------------------------------------------------------------------


def _mem_state(monkeypatch, initial=None):
    """Route arm()/release() DB writes through an in-memory dict so the guards
    can be tested without a live table, and assert 'written in one commit' as
    'called once'."""
    store = dict(initial or {})
    calls = []

    def _fake_set_many(values):
        calls.append(dict(values))
        store.update(values)

    def _fake_get(key, default=None):
        return store.get(key, default)

    monkeypatch.setattr("services.academy_standby._set_many", _fake_set_many)
    monkeypatch.setattr("services.academy_standby._get", _fake_get)
    return store, calls


def _fake_controls(monkeypatch):
    held_live = {}
    monkeypatch.setattr(
        "services.work_control_service.list_controls",
        lambda: [
            {"key": "agent_browser_tasks", "enabled": True},
            {"key": "chronicle_story_worker", "enabled": True},
            {"key": "agent_approvals", "enabled": True},
        ],
    )
    monkeypatch.setattr(
        "services.work_control_service.set_enabled",
        lambda key, enabled: held_live.__setitem__(key, enabled),
    )
    return held_live


def test_arm_writes_the_whole_state_in_one_call(monkeypatch):
    """arm() must land armed+snapshot+expires+note TOGETHER. Four separate
    commits is how a crash produced an unarmed snapshot orphan — a snapshot
    with no flag reads as 'not armed' yet shadows the keys forever."""
    from services.academy_standby import _KEY_ARMED, _KEY_EXPIRES, _KEY_NOTE, _KEY_SNAPSHOT, arm

    store, calls = _mem_state(monkeypatch)
    _fake_controls(monkeypatch)
    monkeypatch.setattr("services.academy_standby.status", lambda: {"armed": False, "held_count": 0})

    out = arm(30, dry_run=False, note="bench win A")

    assert out["ok"] is True
    assert len(calls) == 1, "state must be written in a single transaction"
    assert calls[0][_KEY_ARMED] == "true"
    assert calls[0][_KEY_NOTE] == "bench win A"
    assert {_KEY_SNAPSHOT, _KEY_EXPIRES, _KEY_ARMED, _KEY_NOTE} <= set(calls[0])


def test_arm_refuses_when_an_unarmed_orphan_snapshot_is_present(monkeypatch):
    """A snapshot with no armed flag is a crash-orphan. Overwriting it would
    discard the only record of what the previous arm() was about to hold."""
    from services.academy_standby import _KEY_SNAPSHOT, arm

    store, calls = _mem_state(monkeypatch)
    store[_KEY_SNAPSHOT] = '{"agent_browser_tasks": true, "something_else": true}'
    _fake_controls(monkeypatch)
    monkeypatch.setattr("services.academy_standby.status", lambda: {"armed": False, "held_count": 2})

    out = arm(30, dry_run=False)

    assert out["ok"] is False
    assert "release()" in out["error"]
    assert calls == [], "must not write state over an un-released orphan"


def test_release_clears_an_unarmed_orphan_snapshot(monkeypatch):
    """release() is the operator's tool for the orphan: even 'not armed', it must
    sweep the stale keys so status() stops reporting phantom held controls."""
    from services.academy_standby import _KEY_EXPIRES, _KEY_NOTE, _KEY_SNAPSHOT, release

    store, calls = _mem_state(
        monkeypatch,
        initial={
            _KEY_SNAPSHOT: '{"agent_browser_tasks": true, "something_else": true}',
            _KEY_EXPIRES: "9999999999",
            _KEY_NOTE: "bench win A",
        },
    )
    monkeypatch.setattr(
        "services.academy_standby.status",
        lambda: {"armed": False, "held_count": 2},
    )

    out = release()

    assert out["ok"] is True and out["note"] == "not armed"
    assert calls and calls[-1][_KEY_SNAPSHOT] == "{}"
    assert calls[-1][_KEY_EXPIRES] == "0"
    assert calls[-1][_KEY_NOTE] == ""
    assert store[_KEY_SNAPSHOT] == "{}"


def test_release_restores_the_snapshot_when_armed(monkeypatch):
    """The happy path, pinned: release must replay the exact prior values, set
    the flag back to false and clear the snapshot — all before saying done."""
    from services.academy_standby import (
        _KEY_ARMED,
        _KEY_EXPIRES,
        _KEY_SNAPSHOT,
        _KEY_NOTE,
        release,
    )

    store, calls = _mem_state(
        monkeypatch,
        initial={
            _KEY_ARMED: "true",
            _KEY_SNAPSHOT: '{"agent_browser_tasks": true, "fleet_backlog_runner": false}',
            _KEY_EXPIRES: "9999999999",
            _KEY_NOTE: "bench win A",
        },
    )
    toggled = {}
    monkeypatch.setattr(
        "services.work_control_service.set_enabled",
        lambda key, enabled: toggled.__setitem__(key, enabled),
    )
    monkeypatch.setattr("services.academy_standby.status", lambda: {"armed": True, "held_count": 2})

    out = release()

    assert out["ok"] is True
    assert toggled == {"agent_browser_tasks": True, "fleet_backlog_runner": False}
    assert calls[-1][_KEY_ARMED] == "false"
    assert calls[-1][_KEY_SNAPSHOT] == "{}"
    assert calls[-1][_KEY_EXPIRES] == "0"
    assert calls[-1][_KEY_NOTE] == ""
    assert out["restored"] == ["agent_browser_tasks", "fleet_backlog_runner"]
