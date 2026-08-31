"""DR degraded mode (#6216).

This module sits on the LIVE READ PATH for what-the-fact.com, so the property
that matters most is the boring one: with no fallback configured it must behave
exactly as before. Everything else is secondary to not breaking the site while
adding a safety net for an outage that has not happened yet.

Run: python3 -m pytest tests/test_dr_mode.py -q
"""
import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, ProgrammingError

from consumer import dr_mode


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("WTF_DATABASE_URL", "postgresql+psycopg2://u:p@primary/wtf")
    monkeypatch.delenv("WTF_DATABASE_URL_FALLBACK", raising=False)
    dr_mode.reset_for_tests()
    # Never build a real engine in tests — record what was asked for instead.
    made = []
    monkeypatch.setattr(dr_mode, "_engine_for", lambda url: made.append(url) or f"engine:{url}")
    yield made
    dr_mode.reset_for_tests()


def _oper(msg="connection refused"):
    return OperationalError("SELECT 1", {}, Exception(msg))


# ── the property that protects the live site ───────────────────────────────
def test_unconfigured_returns_primary_and_builds_nothing_else(clean):
    assert dr_mode.get_engine() == "engine:postgresql+psycopg2://u:p@primary/wtf"
    assert len(clean) == 1, "an unconfigured deployment must build ONE engine"


def test_unconfigured_never_degrades_even_on_connection_failure():
    """No fallback means no safety net — but it must also mean no NEW failure
    mode. Flipping to a nonexistent replica would be worse than the outage."""
    assert dr_mode.note_failure(_oper()) is False
    assert dr_mode.is_degraded() is False


def test_unconfigured_status_is_reported_as_unprotected_not_healthy():
    s = dr_mode.status()
    assert s["degraded"] is False
    assert s["configured"] is False, (
        "an operator must be able to tell 'fine' from 'has no fallback at all'"
    )


# ── degradation ────────────────────────────────────────────────────────────
@pytest.fixture
def with_fallback(monkeypatch):
    monkeypatch.setenv("WTF_DATABASE_URL_FALLBACK",
                       "postgresql+psycopg2://u:p@127.0.0.1:5433/wtf")
    dr_mode.reset_for_tests()


def test_healthy_primary_is_used_while_configured(with_fallback):
    assert "primary" in dr_mode.get_engine()
    assert dr_mode.is_degraded() is False


def test_connection_failure_switches_to_the_replica(with_fallback):
    assert dr_mode.note_failure(_oper()) is True
    assert dr_mode.is_degraded() is True
    assert "5433" in dr_mode.get_engine()


def test_the_banner_says_paused_not_down(with_fallback):
    """A 122k-article archive served to the reader is NOT 'we are down'.

    Saying so would be a false statement about our own availability, and it
    would train readers to leave on a day the site still works.
    """
    dr_mode.note_failure(_oper())
    banner = dr_mode.status()["banner"]
    assert banner and "paused" in banner.lower()
    assert "down" not in banner.lower()


def test_degraded_status_carries_duration_for_the_operator(with_fallback):
    dr_mode.note_failure(_oper())
    s = dr_mode.status()
    assert s["degraded"] is True and s["degraded_since"] is not None
    assert s["degraded_seconds"] >= 0


# ── what must NOT degrade us ───────────────────────────────────────────────
def test_a_query_bug_does_not_reroute_to_the_replica(with_fallback):
    """A missing column is a BUG. Rerouting it would hide the bug AND make the
    same request behave differently depending on invisible state."""
    bad_sql = ProgrammingError("SELECT nope", {}, Exception('column "nope" does not exist'))
    assert dr_mode.note_failure(bad_sql) is False
    assert dr_mode.is_degraded() is False


def test_a_constraint_violation_does_not_reroute(with_fallback):
    dup = IntegrityError("INSERT", {}, Exception("duplicate key"))
    assert dr_mode.note_failure(dup) is False
    assert dr_mode.is_degraded() is False


def test_a_non_connection_dbapi_error_does_not_reroute(with_fallback):
    err = DBAPIError("stmt", {}, Exception("some driver complaint"))
    err.connection_invalidated = False
    assert dr_mode.note_failure(err) is False
    assert dr_mode.is_degraded() is False


# ── recovery ───────────────────────────────────────────────────────────────
def test_it_recovers_automatically_when_the_primary_returns(with_fallback, monkeypatch):
    """Staying degraded after the hub is back is an outage nobody gets paged for."""
    dr_mode.note_failure(_oper())
    assert dr_mode.is_degraded() is True

    monkeypatch.setattr(dr_mode, "_probe", lambda eng: True)
    monkeypatch.setattr(dr_mode, "_REPROBE_SECONDS", 0)
    dr_mode._state["last_probe"] = 0.0

    assert "primary" in dr_mode.get_engine()
    assert dr_mode.is_degraded() is False


def test_it_stays_degraded_while_the_primary_is_still_down(with_fallback, monkeypatch):
    dr_mode.note_failure(_oper())
    monkeypatch.setattr(dr_mode, "_probe", lambda eng: False)
    monkeypatch.setattr(dr_mode, "_REPROBE_SECONDS", 0)
    dr_mode._state["last_probe"] = 0.0

    assert "5433" in dr_mode.get_engine()
    assert dr_mode.is_degraded() is True


def test_repeated_failures_do_not_reset_the_degraded_start_time(with_fallback):
    """degraded_since answers 'how long has this been going on'. Resetting it on
    every failed request would make a 3-hour outage read as 2 seconds old."""
    dr_mode.note_failure(_oper())
    first = dr_mode.status()["degraded_since"]
    dr_mode.note_failure(_oper())
    assert dr_mode.status()["degraded_since"] == first


def test_the_probe_is_not_run_on_every_request_while_degraded(with_fallback, monkeypatch):
    """The happy path must cost nothing, and a hammered probe during an outage
    is load pointed at a system that is already struggling."""
    calls = []
    monkeypatch.setattr(dr_mode, "_probe", lambda eng: calls.append(1) or False)
    dr_mode.note_failure(_oper())
    for _ in range(20):
        dr_mode.get_engine()
    assert len(calls) <= 1, f"probed {len(calls)}x — must be rate-limited"


def test_degraded_state_without_a_fallback_url_still_returns_the_primary():
    """The belt to the `mode == primary` braces.

    If state ever reads 'degraded' while no fallback is configured — a restart
    mid-outage, a config removed under a running process — the unconfigured
    short-circuit is the only thing stopping _engine_for(None) from raising on
    every request. Removing it passes every other test in this file, which is
    exactly why this one exists.
    """
    dr_mode._state["mode"] = "degraded"          # force the impossible-ish state
    try:
        assert "primary" in dr_mode.get_engine()
    finally:
        dr_mode.reset_for_tests()
