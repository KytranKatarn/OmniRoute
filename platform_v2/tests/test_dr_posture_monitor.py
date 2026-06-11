"""Unit tests for services.dr_posture_monitor (task #4031).

Scripted-cursor fakes — no live DB, no Telegram. The check function imports its
dependencies lazily, so monkeypatching the source modules is sufficient.
"""

import contextlib

import pytest

import services.dr_posture_monitor as dpm


class ScriptedCursor:
    """Returns one pre-scripted fetchone() result per execute() call, in order."""

    def __init__(self, results):
        self._results = list(results)
        self._current = None

    def execute(self, sql, params=None):
        self._current = self._results.pop(0) if self._results else None

    def fetchone(self):
        return self._current


@pytest.fixture
def harness(monkeypatch):
    """Patch is_enabled / get_db_cursor / send_system; returns (set_results, alerts)."""
    alerts = []
    state = {"results": []}

    import services.work_control_service as wcs
    import services.telegram_service as tg
    import database

    monkeypatch.setattr(wcs, "is_enabled", lambda key, default=True: True)
    monkeypatch.setattr(tg, "send_system", lambda title, body, **kw: alerts.append(title))

    @contextlib.contextmanager
    def fake_cursor(*args, **kwargs):
        yield None, ScriptedCursor(state["results"])

    monkeypatch.setattr(database, "get_db_cursor", fake_cursor)

    def set_results(results):
        state["results"] = results

    return set_results, alerts


# Query order in check_dr_posture: slot -> waldir -> replay lag -> backup age
HEALTHY = [
    {"active": True, "retained_bytes": 1024},
    {"sum": 200 * 1024**2},
    {"lag_s": 0},
    {"age_h": 5.0},
]


def test_healthy_posture_no_alerts(harness):
    set_results, alerts = harness
    set_results(list(HEALTHY))
    result = dpm.check_dr_posture()
    assert alerts == []
    assert result["slot_active"] is True
    assert result["alerted"] == []


def test_inactive_slot_fires_not_streaming(harness):
    set_results, alerts = harness
    set_results(
        [
            {"active": False, "retained_bytes": 48 * 1024**3},  # the 06-04 incident shape
            {"sum": 200 * 1024**2},
            None,  # no pg_stat_replication row when not streaming
            {"age_h": 5.0},
        ]
    )
    result = dpm.check_dr_posture()
    assert "not_streaming" in result["alerted"]
    assert any("NOT STREAMING" in t for t in alerts)


def test_missing_slot_fires_slot_missing(harness):
    set_results, alerts = harness
    set_results(
        [
            None,  # slot gone entirely
            {"sum": 200 * 1024**2},
            None,
            {"age_h": 5.0},
        ]
    )
    result = dpm.check_dr_posture()
    assert "slot_missing" in result["alerted"]


def test_active_but_retaining_fires_retained_wal(harness):
    set_results, alerts = harness
    set_results(
        [
            {"active": True, "retained_bytes": 6 * 1024**3},
            {"sum": 200 * 1024**2},
            {"lag_s": 30},
            {"age_h": 5.0},
        ]
    )
    result = dpm.check_dr_posture()
    assert "retained_wal" in result["alerted"]
    assert "not_streaming" not in result["alerted"]


def test_wal_dir_bloat_and_replay_lag(harness):
    set_results, alerts = harness
    set_results(
        [
            {"active": True, "retained_bytes": 1024},
            {"sum": 20 * 1024**3},
            {"lag_s": 1200},
            {"age_h": 5.0},
        ]
    )
    result = dpm.check_dr_posture()
    assert "wal_dir" in result["alerted"]
    assert "replay_lag" in result["alerted"]


def test_stale_and_missing_dr_backup(harness):
    set_results, alerts = harness
    set_results(
        [
            {"active": True, "retained_bytes": 1024},
            {"sum": 200 * 1024**2},
            {"lag_s": 0},
            {"age_h": 80.0},  # > 48h
        ]
    )
    assert "dr_backup_stale" in dpm.check_dr_posture()["alerted"]

    set_results(
        [
            {"active": True, "retained_bytes": 1024},
            {"sum": 200 * 1024**2},
            {"lag_s": 0},
            {"age_h": None},  # no dr rows at all
        ]
    )
    assert "dr_backup_stale" in dpm.check_dr_posture()["alerted"]


def test_disabled_toggle_skips(harness, monkeypatch):
    import services.work_control_service as wcs

    monkeypatch.setattr(wcs, "is_enabled", lambda key, default=True: False)
    assert dpm.check_dr_posture() == {"skipped": "disabled"}
