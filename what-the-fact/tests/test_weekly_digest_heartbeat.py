"""Guard: the weekly digest must be OBSERVABLE (#6233).

The digest crashed every Monday for weeks with zero signal — run.py logs only when
sent/errors is truthy, crash tracebacks die with each container rebuild, and there
was no parliament.ingest_log heartbeat at all. drift_guard measures the last
SUCCESS, so a task with no rows is invisible rather than alarming.

These tests use a FAKE engine on purpose: no database, no fixtures, no network.
A guard that can silently SKIP is not a guard (same reason A.U.R.O.R.A.'s parsing
lives in stdlib-only modules — KB #290497).

The load-bearing test here is test_not_monday_writes_NOTHING. Writing a heartbeat
on the six non-Monday days would keep the freshness alarm permanently green and
recreate the exact "unmonitored while APPEARING monitored" bug being fixed.
"""
from __future__ import annotations

import datetime
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingest import weekly_digest_worker as wd  # noqa: E402
from ingest.parliament import drift_guard  # noqa: E402


class _FakeConn:
    def __init__(self, sink):
        self._sink = sink

    def execute(self, stmt, params=None):
        self._sink.append((str(stmt), dict(params or {})))
        return None


class _FakeEngine:
    """Captures every statement executed through engine.begin()."""

    def __init__(self):
        self.statements: list[tuple[str, dict]] = []

    def begin(self):
        sink = self.statements
        class _Ctx:
            def __enter__(self_inner):
                return _FakeConn(sink)
            def __exit__(self_inner, *a):
                return False
        return _Ctx()

    # Rows written specifically as ingest_log heartbeats
    def heartbeats(self):
        return [(s, p) for s, p in self.statements
                if "parliament.ingest_log" in s and p.get("t") == "weekly_digest"]


def _monday():
    d = datetime.date(2026, 9, 7)
    assert d.weekday() == 0, "fixture date must be a Monday"
    return d


@pytest.fixture()
def eng():
    return _FakeEngine()


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(wd, "_ENABLED", True)


# ---------------------------------------------------------------- writes

def test_successful_send_writes_a_success_heartbeat(eng, monkeypatch):
    monkeypatch.setattr(wd, "_already_sent_this_week", lambda e, s: False)
    monkeypatch.setattr(wd, "_fetch_recipients", lambda e, s: [("a@x.ca", None), ("b@x.ca", "tok")])
    monkeypatch.setattr(wd, "_fetch_digest_data", lambda e, s: {})
    monkeypatch.setattr(wd, "_build_html", lambda d, w: "<html>__UNSUB_LINK__</html>")
    monkeypatch.setattr(wd, "_send_digest", lambda *a, **k: True)
    monkeypatch.setattr(wd, "_mark_sent", lambda e, s: None)

    out = wd._run_weekly_digest_inner(eng, "wtf", _monday())

    assert out["sent"] == 2
    hb = eng.heartbeats()
    assert len(hb) == 1, "exactly one heartbeat per run"
    sql, params = hb[0]
    assert "error" not in sql, "a successful send must NOT write the error column"
    assert params["n"] == 2, "records should carry the sent count"


def test_crash_writes_an_error_heartbeat_and_does_not_raise(eng, monkeypatch):
    # Pin "today" to a Monday — otherwise run_weekly_digest short-circuits on
    # not_monday and never reaches the code under test. (Caught by this test
    # failing on a Tuesday, which is the point of running it.)
    # NOTE: compute the date BEFORE patching. The stub shadows datetime.date, so
    # calling _monday() afterwards would try to construct the stub itself.
    mon = _monday()
    monkeypatch.setattr(
        wd.datetime, "date",
        type("D", (), {"today": staticmethod(lambda: mon)}),
    )

    def boom(*a, **k):
        raise RuntimeError("smtp exploded")
    monkeypatch.setattr(wd, "_already_sent_this_week", boom)

    # Must not raise: a crashing digest must not take down the ingest loop.
    out = wd.run_weekly_digest(eng, "wtf")

    assert out["stopped"] == "error"
    hb = eng.heartbeats()
    assert len(hb) == 1
    sql, params = hb[0]
    assert "error" in sql, "a crash must be recorded as an ERROR row, not a success"
    assert "smtp exploded" in params["e"]


def test_all_sends_failed_is_an_error_not_a_success(eng, monkeypatch):
    monkeypatch.setattr(wd, "_already_sent_this_week", lambda e, s: False)
    monkeypatch.setattr(wd, "_fetch_recipients", lambda e, s: [("a@x.ca", None)])
    monkeypatch.setattr(wd, "_fetch_digest_data", lambda e, s: {})
    monkeypatch.setattr(wd, "_build_html", lambda d, w: "<html>__UNSUB_LINK__</html>")
    monkeypatch.setattr(wd, "_send_digest", lambda *a, **k: False)   # every send fails

    out = wd._run_weekly_digest_inner(eng, "wtf", _monday())

    assert out["sent"] == 0 and out["errors"] == 1
    sql, _ = eng.heartbeats()[0]
    assert "error" in sql, "recipients existed and nothing got through — that is a failed run"


# ---------------------------------------------------- deliberate silences

def test_not_monday_writes_NOTHING(eng, monkeypatch):
    """THE load-bearing test.

    run_weekly_digest returns not_monday six days out of seven. A heartbeat here
    would keep drift_guard permanently green and reproduce the original bug.
    """
    tuesday = datetime.date(2026, 9, 8)
    assert tuesday.weekday() == 1
    monkeypatch.setattr(wd.datetime, "date", type("D", (), {"today": staticmethod(lambda: tuesday)}))

    out = wd.run_weekly_digest(eng, "wtf")

    assert out["stopped"] == "not_monday"
    assert eng.heartbeats() == [], "a non-Monday wake-up is NOT a weekly run"


def test_disabled_writes_nothing(eng, monkeypatch):
    monkeypatch.setattr(wd, "_ENABLED", False)
    out = wd.run_weekly_digest(eng, "wtf")
    assert out["stopped"] == "disabled"
    assert eng.heartbeats() == []


# ------------------------------------------------- registry <-> writer link

def test_weekly_digest_is_watched_by_drift_guard():
    """A heartbeat nobody watches is not observability.

    Mirrors gov-watch's test_every_monitored_job_has_a_heartbeat_writer (#5799):
    the registry entry and the writer must agree on the task name.
    """
    assert wd._HEARTBEAT_TASK in drift_guard._MAX_AGE_DAYS, (
        "the writer's task name must appear in _MAX_AGE_DAYS or nothing measures it"
    )


def test_weekly_digest_alarms_on_ABSENCE_not_just_staleness():
    """It has zero ingest_log rows today. The freshness loop SKIPS a task with no
    rows, so without _REQUIRED_TASKS membership it reports green forever — which is
    the state that let it fail every Monday unnoticed."""
    assert wd._HEARTBEAT_TASK in drift_guard._REQUIRED_TASKS


def test_threshold_is_tighter_than_two_missed_sends():
    """The send is weekly, so a healthy age never exceeds 7 days. A 21-day window
    (the parliamentary default) would let three consecutive Mondays fail silently."""
    assert drift_guard._MAX_AGE_DAYS[wd._HEARTBEAT_TASK] < 14
