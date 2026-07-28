"""Unit tests for services.fleet_identity_monitor (task #5278 item 3).

Scripted-cursor fakes — no live DB, no Telegram (same pattern as
test_dr_posture_monitor.py). What these pin down: the 2026-07-27 drill proved
detection AND delivery both worked — twelve identical "[WARNING] Fleet: 3 nodes
OFFLINE" Telegrams were sent overnight and none registered. The fix is that a
PERSISTING mass-offline escalates to a DISTINCT title at critical severity,
while the title stays stable per condition so the cooldown dedup keeps working.
"""

import contextlib
import time

import pytest

import services.fleet_identity_monitor as fim


class ScriptedCursor:
    """Returns one pre-scripted fetchall() result per execute() call, in order."""

    def __init__(self, results):
        self._results = list(results)
        self._current = []

    def execute(self, sql, params=None):
        self._current = self._results.pop(0) if self._results else []

    def fetchall(self):
        return self._current


def _offline_row(node_id, age_s=999):
    return {"node_id": node_id, "node_name": node_id, "deployment_mode": "starbase_outpost", "age_s": age_s}


@pytest.fixture
def harness(monkeypatch):
    """Patch is_enabled / get_db_cursor / send_system; returns (set_results, alerts)."""
    alerts = []
    state = {"results": []}

    import services.work_control_service as wcs
    import services.telegram_service as tg
    import database

    monkeypatch.setattr(wcs, "is_enabled", lambda key, default=True: True)
    monkeypatch.setattr(
        tg,
        "send_system",
        lambda title, body="", **kw: alerts.append((title, kw.get("severity", "warning"), body)),
    )

    @contextlib.contextmanager
    def fake_cursor(*args, **kwargs):
        yield None, ScriptedCursor(state["results"])

    monkeypatch.setattr(database, "get_db_cursor", fake_cursor)

    def set_results(results):
        state["results"] = results

    # Isolate the module-level persistence clock between tests.
    fim._mass_offline_since = None
    return set_results, alerts


# Query order in check_fleet_identity: offline rows -> duplicate-identity rows.


def test_all_online_no_alert_and_clock_reset(harness):
    set_results, alerts = harness
    fim._mass_offline_since = time.time() - 3600  # stale leftover from a prior condition
    set_results([[], []])
    result = fim.check_fleet_identity()
    assert result["mass_offline"] == 0
    assert alerts == []
    assert fim._mass_offline_since is None  # recovery must reset the clock


def test_fresh_mass_offline_alerts_as_warning(harness):
    set_results, alerts = harness
    set_results([[_offline_row("outpost_a"), _offline_row("outpost_b"), _offline_row("outpost_c")], []])
    result = fim.check_fleet_identity()
    assert result["alerted"] == ["mass_offline"]
    (title, severity, body) = alerts[0]
    assert title == "Fleet: 3 nodes OFFLINE"
    assert severity == "warning"
    # The DR-mispoint hint must ship with the alert — it is what turns a 9.6h
    # head-scratcher into a one-command fix.
    assert "repoint.sh" in body
    assert fim._mass_offline_since is not None


def test_persisting_mass_offline_escalates_to_critical(harness):
    set_results, alerts = harness
    fim._mass_offline_since = time.time() - (fim.PERSIST_CRITICAL_MIN + 5) * 60
    set_results([[_offline_row("outpost_a"), _offline_row("outpost_b"), _offline_row("outpost_c")], []])
    result = fim.check_fleet_identity()
    assert result["alerted"] == ["mass_offline_persisting"]
    (title, severity, body) = alerts[0]
    assert title == "Fleet: 3 nodes OFFLINE — PERSISTING"  # distinct dedup key
    assert severity == "critical"
    assert "persisted for" in body
    # Title must NOT embed the minutes — a changing title defeats the cooldown
    # dedup and floods every 5-min check.
    assert "min" not in title


def test_rest_excluded_starships_do_not_count(harness):
    set_results, alerts = harness
    ships = [_offline_row(n) for n in sorted(fim.REST_EXCLUDED)]
    set_results([ships + [_offline_row("outpost_a")], []])
    result = fim.check_fleet_identity()
    # One non-excluded node is not MORE than the threshold — no alert.
    assert result["mass_offline"] == 1
    assert alerts == []


def test_single_offline_node_stays_quiet(harness):
    set_results, alerts = harness
    set_results([[_offline_row("outpost_a")], []])
    result = fim.check_fleet_identity()
    assert result["mass_offline"] == 1
    assert alerts == []
    assert fim._mass_offline_since is None  # below threshold is not "the condition"
