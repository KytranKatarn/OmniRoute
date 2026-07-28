"""Regression: budget_reconciliation must be scheduled on WALL CLOCK, not uptime (#5007).

The counter safety net (``reconcile_task_counters``) was registered with
``IntervalTrigger(minutes=60)``. An interval trigger's first fire is 60 minutes
AFTER scheduler start, so every platform restart blinded the net for a full hour
— precisely when drift is most likely, because a restart orphans in-flight jobs.

Measured 2026-07-28 (EDT): runs at 00:44/01:44/02:45/03:45/04:45/05:45/06:45,
then gaps of 137 min, 116 min, and 169 min (the last one following the 14:03
deploy restart). During a gap, an agent whose ``current_task_count`` never got
decremented sits budget-blocked with nothing to rescue it.

These tests assert the registration itself, driving the real
``register_fleet_jobs`` with a stub scheduler. ``test_interval_trigger_would_fail``
proves the assertions are not vacuous: it applies the SAME checks to the OLD
trigger and requires them to fail, so this file cannot silently pass if someone
reverts the fix.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from apscheduler.triggers.cron import CronTrigger  # noqa: E402
from apscheduler.triggers.interval import IntervalTrigger  # noqa: E402

TZ = ZoneInfo("America/Toronto")
JOB_ID = "budget_reconciliation"


class _StubScheduler:
    """Records add_job(...) calls instead of scheduling them."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func=None, trigger=None, id=None, **kwargs):  # noqa: A002
        self.jobs[id] = trigger
        return None


def _registered_trigger():
    from services.fleet_jobs import register_fleet_jobs

    stub = _StubScheduler()
    register_fleet_jobs(stub, flask_app=None)
    assert JOB_ID in stub.jobs, f"{JOB_ID} is not registered at all — the safety net would never run"
    return stub.jobs[JOB_ID]


def _wall_clock_checks(trigger):
    """The three properties that make the net restart-independent.

    Returns a list of failure strings (empty == all good) so the same checks can
    be applied to the old trigger to prove they actually discriminate.
    """
    failures = []
    if not isinstance(trigger, CronTrigger):
        failures.append(f"not a CronTrigger (got {type(trigger).__name__})")
        return failures
    if getattr(trigger, "timezone", None) is None:
        failures.append("CronTrigger has no timezone (required by rules/timezone.md)")
    # Fire time must be a fixed wall-clock minute, not an offset from boot.
    nxt = trigger.get_next_fire_time(None, datetime(2026, 7, 28, 14, 6, tzinfo=TZ))
    if nxt is None or nxt.minute != 5:
        failures.append(f"next fire is not at a fixed :05 wall-clock minute (got {nxt})")
    return failures


def test_budget_reconciliation_is_wall_clock_scheduled():
    """The live registration must use a tz-aware CronTrigger at a fixed minute."""
    assert _wall_clock_checks(_registered_trigger()) == []


def test_budget_reconciliation_is_restart_independent():
    """Two schedulers booted 34 min apart must agree on the next run time.

    This is the property the bug violated: with an uptime-relative trigger the
    next run depends on when the process started.
    """
    trigger = _registered_trigger()
    booted_early = trigger.get_next_fire_time(None, datetime(2026, 7, 28, 14, 6, tzinfo=TZ))
    booted_late = trigger.get_next_fire_time(None, datetime(2026, 7, 28, 14, 40, tzinfo=TZ))
    assert booted_early == booted_late, "next run depends on boot time — a restart still moves the safety net"


def test_interval_trigger_would_fail():
    """Falsifiability guard: the OLD trigger must FAIL the checks above.

    Without this, the assertions could be trivially satisfiable and this file
    would pass even if the fix were reverted.
    """
    failures = _wall_clock_checks(IntervalTrigger(minutes=60))
    assert failures, "checks do not discriminate — they pass the very bug they target"


def test_interval_trigger_next_run_moves_with_boot_time():
    """Directly demonstrate the defect being fixed."""
    old = IntervalTrigger(minutes=60, start_date=datetime(2026, 7, 28, 14, 3, tzinfo=TZ))
    booted_early = old.get_next_fire_time(None, datetime(2026, 7, 28, 14, 6, tzinfo=TZ))

    later = IntervalTrigger(minutes=60, start_date=datetime(2026, 7, 28, 14, 37, tzinfo=TZ))
    booted_late = later.get_next_fire_time(None, datetime(2026, 7, 28, 14, 40, tzinfo=TZ))

    assert booted_early != booted_late, "expected the interval trigger's next run to shift with process start time"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
