"""#5332 — UNDOCKED means "leave the ships alone".

Pins the dock predicate + force-undock expiry math in
tools.department_hq.fleet_helpers: the schedule used to gate only TWO call
sites while pinned dispatches, ComfyUI routing, keep-warms and model-control
all still reached a resting Starship. Every gate now consults ONE predicate,
and a manual force-undock always auto-expires at the next window END boundary
so it can never permanently strand a node.
"""

import contextlib
import json
from datetime import datetime

import pytest
import pytz

import tools.department_hq.fleet_helpers as fh

TZ = pytz.timezone("America/Toronto")


def _at(hour, minute=0, day=15):
    return TZ.localize(datetime(2026, 7, day, hour, minute))


@pytest.fixture
def cfg(monkeypatch):
    state = {"enabled": False, "start_hour": 20, "end_hour": 6}
    monkeypatch.setattr(fh, "get_fleet_rest_config", lambda: dict(state))
    return state


def _fake_cursor(monkeypatch, row_value):
    """Patch fh.get_db_cursor to return one scripted row for the force key."""

    class Cur:
        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return {"value": row_value} if row_value is not None else None

    @contextlib.contextmanager
    def fake(commit=False):
        yield None, Cur()

    monkeypatch.setattr(fh, "get_db_cursor", fake)


class TestBoundaryMath:
    def test_evening_expires_tomorrow_morning(self, cfg):
        until = fh.next_rest_end_boundary(_at(21))
        assert (until.day, until.hour) == (16, 6)

    def test_early_morning_expires_today(self, cfg):
        until = fh.next_rest_end_boundary(_at(4))
        assert (until.day, until.hour) == (15, 6)

    def test_exactly_at_boundary_rolls_to_tomorrow(self, cfg):
        until = fh.next_rest_end_boundary(_at(6))
        assert (until.day, until.hour) == (16, 6)

    def test_always_within_24h(self, cfg):
        for hour in range(24):
            now = _at(hour)
            until = fh.next_rest_end_boundary(now)
            assert now < until <= now.replace(hour=0, minute=0) + fh.timedelta(days=2)
            assert (until - now).total_seconds() <= 24 * 3600


class TestForceUndock:
    def test_future_until_is_active(self, cfg, monkeypatch):
        until = _at(6, day=16)
        _fake_cursor(monkeypatch, json.dumps({"until": until.isoformat()}))
        assert fh.force_undock_until(_at(22)) == until

    def test_past_until_is_expired(self, cfg, monkeypatch):
        _fake_cursor(monkeypatch, json.dumps({"until": _at(6, day=14).isoformat()}))
        assert fh.force_undock_until(_at(22)) is None

    def test_no_row_and_garbage_fail_open_to_docked(self, cfg, monkeypatch):
        _fake_cursor(monkeypatch, None)
        assert fh.force_undock_until(_at(22)) is None
        _fake_cursor(monkeypatch, "not-json{{")
        assert fh.force_undock_until(_at(22)) is None


class TestPredicate:
    def test_docked_when_nothing_active(self, monkeypatch):
        monkeypatch.setattr(fh, "is_fleet_rest_active", lambda: False)
        monkeypatch.setattr(fh, "force_undock_until", lambda now=None: None)
        assert fh.is_starships_undocked() is False

    def test_schedule_undocks(self, monkeypatch):
        monkeypatch.setattr(fh, "is_fleet_rest_active", lambda: True)
        monkeypatch.setattr(fh, "force_undock_until", lambda now=None: None)
        assert fh.is_starships_undocked() is True

    def test_force_undocks_even_with_schedule_off(self, monkeypatch):
        monkeypatch.setattr(fh, "is_fleet_rest_active", lambda: False)
        monkeypatch.setattr(fh, "force_undock_until", lambda now=None: _at(6, day=16))
        assert fh.is_starships_undocked() is True

    def test_predicate_errors_fail_open_to_docked(self, monkeypatch):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(fh, "is_fleet_rest_active", boom)
        assert fh.is_starships_undocked() is False
