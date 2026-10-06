"""is_account_locked must compare like with like (it used to raise TypeError for every account at the threshold).

2026-10-06: the QA harness account `probe` could not sign in through the form. Its failed_login_count had been
stuck at 5 since June; the lockout check then stripped the timezone off the stored timestamp and compared it to
an aware datetime.now(utc), which Python refuses (`can't compare offset-naive and offset-aware datetimes`). The
login route's catch-all showed "An error occurred. Please try again." — no password was ever checked. A real
lockout crashed the same way, and the "lockout expired - reset count" branch was unreachable.

failed_logins.attempted_at is `timestamp WITHOUT time zone` filled by CURRENT_TIMESTAMP in a UTC session, so the
database hands back NAIVE UTC datetimes: that is the case these tests are built around.
"""

import os
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import auth_service as a  # noqa: E402

USER = {"id": 62, "username": "probe", "failed_login_count": 5}


def _utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class _Cur:
    def __init__(self, last_attempt):
        self.last_attempt = last_attempt

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return {"last_attempt": self.last_attempt}

    def close(self):
        pass


class _Conn:
    def __init__(self, last_attempt):
        self.last_attempt = last_attempt

    def cursor(self, **k):
        return _Cur(self.last_attempt)


@pytest.fixture
def db(monkeypatch):
    """Patch the DB: .returns(<last failed attempt>) and record reset_failed_login_count calls."""
    state = {"resets": [], "touched": False}

    @contextmanager
    def fake_conn():
        state["touched"] = True
        yield _Conn(state["last"])

    monkeypatch.setattr(a, "get_db_connection", fake_conn)
    monkeypatch.setattr(a, "reset_failed_login_count", lambda uid: state["resets"].append(uid))

    def returns(last):
        state["last"] = last
        return state

    state["returns"] = returns
    return state


def test_below_the_threshold_never_touches_the_database(db):
    assert a.is_account_locked({**USER, "failed_login_count": 4}) == (False, 0)
    assert db["touched"] is False


def test_the_exact_regression_a_stale_count_with_an_old_naive_timestamp_does_not_raise(db):
    """probe: count 5, last failure months ago, naive UTC from the DB. Raised TypeError before the fix."""
    db["returns"](datetime(2026, 6, 18, 21, 11, 45, 576617))
    assert a.is_account_locked(USER) == (False, 0)


def test_an_expired_lockout_resets_the_count_so_the_account_heals(db):
    db["returns"](datetime(2026, 6, 18, 21, 11, 45))
    a.is_account_locked(USER)
    assert db["resets"] == [62]


def test_a_recent_failure_locks_the_account_and_says_for_how_long(db):
    db["returns"](_utc_now_naive() - timedelta(minutes=2))
    locked, remaining = a.is_account_locked(USER)
    assert locked is True and 12 <= remaining <= 15
    assert db["resets"] == []  # a live lockout must NOT reset the count


def test_the_lockout_boundary_follows_LOCKOUT_MINUTES(db):
    db["returns"](_utc_now_naive() - timedelta(minutes=a.LOCKOUT_MINUTES + 1))
    assert a.is_account_locked(USER) == (False, 0)
    db["returns"](_utc_now_naive() - timedelta(minutes=a.LOCKOUT_MINUTES - 1))
    assert a.is_account_locked(USER)[0] is True


def test_an_aware_utc_timestamp_works_too(db):
    db["returns"](datetime.now(timezone.utc) - timedelta(minutes=2))
    assert a.is_account_locked(USER)[0] is True


@pytest.mark.parametrize("offset_hours", [5, -5, 14])
def test_an_aware_non_utc_timestamp_is_converted_not_just_stripped(db, offset_hours):
    """The old code dropped tzinfo, so +05:00 wall-clock read as 5h in the future (locked for 5h); -05:00 as 5h in the
    past (never locked). Converting gives the same 2-minutes-ago instant whatever the offset."""
    tz = timezone(timedelta(hours=offset_hours))
    db["returns"]((datetime.now(timezone.utc) - timedelta(minutes=2)).astimezone(tz))
    locked, remaining = a.is_account_locked(USER)
    assert locked is True and 12 <= remaining <= 15


def test_no_failed_login_row_at_all_is_not_locked(db):
    db["returns"](None)
    assert a.is_account_locked(USER) == (False, 0)


def test_as_utc_helper():
    assert a._as_utc(datetime(2026, 1, 1, 12, 0)).tzinfo is timezone.utc
    assert a._as_utc(datetime(2026, 1, 1, 12, 0)).hour == 12  # naive is taken AS UTC, not shifted
    assert a._as_utc(datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-5)))).hour == 17
