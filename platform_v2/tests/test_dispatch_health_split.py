"""Unit tests for dispatch_health_service FAILED split (#4538).

Verifies the Python aggregation that derives failed_real / failed_timeout /
success_rate_real from the SQL row — genuine dispatch failures vs infra
queue/timeouts — so a GPU-contention backlog event (e.g. 240s fact_check
timeouts) doesn't read as a dispatch regression. The SQL is_timeout
classification itself is exercised at runtime against the live DB.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_dispatch_health_split.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import dispatch_health_service as dhs  # noqa: E402


class _FakeCur:
    def __init__(self, row):
        self._row = row

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self._row


class _FakeCtx:
    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, row):
    # dispatch_health_service imports get_db_cursor at module top, so patch it in
    # THIS module's namespace (patching database.get_db_cursor would not take).
    monkeypatch.setattr(dhs, "get_db_cursor", lambda *a, **k: _FakeCtx(_FakeCur(row)))


def test_splits_failed_into_real_and_timeout(monkeypatch):
    # 1500 failed, 1295 infra timeouts → 205 real; combined 'failed' unchanged.
    _patch(
        monkeypatch,
        {
            "total": 5000,
            "success": 3000,
            "failed": 1500,
            "failed_timeout": 1295,
            "pending": 500,
            "tokens": 0,
            "avg_duration_ms": 1200.0,
        },
    )
    h = dhs.dispatch_health(24)
    assert h["failed"] == 1500  # back-compat: combined bucket untouched
    assert h["failed_timeout"] == 1295
    assert h["failed_real"] == 205


def test_real_success_rate_excludes_timeouts(monkeypatch):
    _patch(
        monkeypatch,
        {
            "total": 5000,
            "success": 3000,
            "failed": 1500,
            "failed_timeout": 1295,
            "pending": 0,
            "tokens": 0,
            "avg_duration_ms": 0,
        },
    )
    h = dhs.dispatch_health(24)
    assert h["success_rate"] == round(3000 / 4500 * 100, 1)  # all failures
    assert h["success_rate_real"] == round(3000 / 3205 * 100, 1)  # real only (3000+205)
    assert h["success_rate_real"] > h["success_rate"]


def test_no_timeouts_real_equals_combined(monkeypatch):
    _patch(
        monkeypatch,
        {
            "total": 100,
            "success": 90,
            "failed": 10,
            "failed_timeout": 0,
            "pending": 0,
            "tokens": 0,
            "avg_duration_ms": 0,
        },
    )
    h = dhs.dispatch_health(24)
    assert h["failed_real"] == 10
    assert h["success_rate_real"] == h["success_rate"]


def test_failed_timeout_never_makes_real_negative(monkeypatch):
    # defensive: clamp failed_real at 0 if the timeout count somehow exceeds failed.
    _patch(
        monkeypatch,
        {
            "total": 10,
            "success": 5,
            "failed": 3,
            "failed_timeout": 5,
            "pending": 2,
            "tokens": 0,
            "avg_duration_ms": 0,
        },
    )
    h = dhs.dispatch_health(24)
    assert h["failed_real"] == 0
    assert h["success_rate_real"] == 100.0  # decided_real = 5 + 0


def test_empty_window_zero_rates(monkeypatch):
    _patch(
        monkeypatch,
        {
            "total": 0,
            "success": 0,
            "failed": 0,
            "failed_timeout": 0,
            "pending": 0,
            "tokens": 0,
            "avg_duration_ms": 0,
        },
    )
    h = dhs.dispatch_health(24)
    assert h["success_rate"] == 0.0
    assert h["success_rate_real"] == 0.0
    assert h["failed_real"] == 0
