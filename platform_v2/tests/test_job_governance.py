"""Tests for services/job_governance.py — DHQ Job Governance (project #332, #2741).

Verifies the shared governed_job wrapper:
  * writes governance_audit_log start→success | start→failed
  * swallows a job exception (never crashes the scheduler)
  * notifies on failure via the given channel, quiet-hours-gated (ET)
  * preserves fn.__name__
  * in_quiet_hours parses the 'H-H' window with midnight wrap-around, fail-open
"""

from __future__ import annotations

import pytest

from services import job_governance as jg


@pytest.fixture
def audit_spy(monkeypatch):
    """Capture _audit(...) calls without touching the DB."""
    calls: list[tuple] = []
    monkeypatch.setattr(jg, "_audit", lambda job, outcome, dept, details=None: calls.append((job, outcome)))
    return calls


# --------------------------------------------------------------------------- #
# success / failure paths
# --------------------------------------------------------------------------- #
def test_success_path_audits_running_then_success(audit_spy):
    ran = []
    notified = []

    def do_work():
        ran.append(1)

    wrapped = jg.governed_job(do_work, department="Test", notify_fn=lambda t, m: notified.append(1))
    wrapped()

    assert ran == [1]
    assert [o for _, o in audit_spy] == ["running", "success"]
    assert notified == []  # no alert on success
    assert wrapped.__name__ == "do_work"  # APScheduler id preserved


def test_failure_path_swallows_audits_failed_and_notifies(audit_spy, monkeypatch):
    monkeypatch.setattr(jg, "in_quiet_hours", lambda: False)
    notified = []

    def boom():
        raise ValueError("kaboom")

    wrapped = jg.governed_job(boom, department="Test", notify_fn=lambda t, m: notified.append((t, m)))

    # must NOT raise — a job failure cannot crash the scheduler
    wrapped()

    assert [o for _, o in audit_spy] == ["running", "failed"]
    assert len(notified) == 1
    assert "boom" in notified[0][0]  # title carries the job name


def test_failure_alert_suppressed_during_quiet_hours(audit_spy, monkeypatch):
    monkeypatch.setattr(jg, "in_quiet_hours", lambda: True)
    notified = []

    def boom():
        raise RuntimeError("late night")

    wrapped = jg.governed_job(boom, department="Test", notify_fn=lambda t, m: notified.append(1))
    wrapped()

    # audit still records the failure; only the Telegram ping is suppressed
    assert [o for _, o in audit_spy] == ["running", "failed"]
    assert notified == []


def test_notify_on_fail_false_skips_alert(audit_spy, monkeypatch):
    monkeypatch.setattr(jg, "in_quiet_hours", lambda: False)
    notified = []

    def boom():
        raise Exception("x")

    wrapped = jg.governed_job(boom, department="Test", notify_fn=lambda t, m: notified.append(1), notify_on_fail=False)
    wrapped()
    assert notified == []


def test_governance_write_failure_never_breaks_the_job(monkeypatch):
    """A broken audit writer must not stop the job from running."""

    def exploding_audit(*a, **k):
        raise Exception("db down")

    monkeypatch.setattr(jg, "_audit", exploding_audit)
    ran = []

    def do_work():
        ran.append(1)

    jg.governed_job(do_work, department="Test")()
    assert ran == [1]  # job still executed despite audit blowing up


# --------------------------------------------------------------------------- #
# quiet-hours window parsing (ET, wrap-around, fail-open)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "window,hour,expected",
    [
        ("22-7", 23, True),  # inside, after start
        ("22-7", 3, True),  # inside, wrapped past midnight
        ("22-7", 22, True),  # inclusive start
        ("22-7", 7, False),  # exclusive end
        ("22-7", 12, False),  # daytime — outside
        ("9-17", 12, True),  # non-wrapping window, inside
        ("9-17", 8, False),  # non-wrapping, before
        ("", 3, False),  # disabled
        ("bogus", 3, False),  # unparseable → fail-open (not quiet)
        ("5-5", 5, False),  # empty window (start==end)
    ],
)
def test_in_quiet_hours(monkeypatch, window, hour, expected):
    class _T:
        def __init__(self, h):
            self.hour = h

    monkeypatch.setattr(jg, "_setting", lambda key: window)
    monkeypatch.setattr("services.time_utils.now_local", lambda: _T(hour))
    assert jg.in_quiet_hours() is expected


def test_quiet_hours_defaults_when_setting_missing(monkeypatch):
    """Missing platform_settings key → default '22-7' applies."""

    class _T:
        hour = 2

    monkeypatch.setattr(jg, "_setting", lambda key: None)
    monkeypatch.setattr("services.time_utils.now_local", lambda: _T())
    assert jg.in_quiet_hours() is True  # 2 AM ET falls in default 22-7
