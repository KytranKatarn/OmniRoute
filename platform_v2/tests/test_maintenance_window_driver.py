"""The job that actually drives maintenance windows (#5217/#5235).

The window services were merged, tested and applied — and NOTHING CALLED THEM.
A window no job advances is a window that never happens, which is the same
"built but not wired" gap #5226 closed for the maintenance splash.

TWO PROPERTIES CARRY THIS JOB, and both are safety properties:

1. **CLOSE RUNS FIRST.** An open window SUPPRESSES THE DR WATCHDOG. A window
   that never closes leaves DR disarmed indefinitely while the operator believes
   it is armed — strictly worse than never opening one. So expiry is swept
   before anything else, and a failure in announce/open can never prevent it.

2. **NEVER AUTO-OPENS AN UNANNOUNCED WINDOW.** The owner asked to be told the
   fix list beforehand. `open_scheduled(force_unannounced=True)` exists; this job
   must never pass it. One tick late beats a silent production change.

These drive the REAL job with the schedule service stubbed, so nothing here can
arm DR suppression or SSH to boston-2.
"""

from datetime import timedelta

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import import_or_skip  # noqa: E402
from tests.modstub import install_module_stub, uninstall_module  # noqa: E402

try:
    from services.time_utils import now_utc
    from tools.department_hq import jobs
except Exception as exc:  # pragma: no cover
    import_or_skip(exc, "department_hq.jobs")


class _FakeSchedule:
    """Stands in for maintenance_schedule_service. Records the call order."""

    def __init__(self, windows):
        self._w = windows
        self.calls = []
        self.open_kwargs = []
        self.fail_announce = False

    def list_windows(self, status=None, limit=20):
        return [w for w in self._w if w["status"] == status]

    def announce_plan(self, wid, announce=True):
        self.calls.append(("announce", wid))
        if self.fail_announce:
            raise RuntimeError("announce exploded")
        return {"ok": True}

    def open_scheduled(self, wid, **kw):
        self.calls.append(("open", wid))
        self.open_kwargs.append(kw)
        return {"ok": True}

    def close_scheduled(self, wid, outcomes=None):
        self.calls.append(("close", wid))
        return {"ok": True}


def _install(monkeypatch, windows):
    """#5987 — jobs.py says `from services import maintenance_schedule_service as mss`, which
    reads the PACKAGE ATTRIBUTE and ignores a sys.modules-only stub once anything has imported
    the submodule. install_module_stub patches both, so import order stops mattering."""
    fake = _FakeSchedule(windows)
    install_module_stub(
        monkeypatch,
        "services.maintenance_schedule_service",
        **{n: getattr(fake, n) for n in ("list_windows", "announce_plan", "open_scheduled", "close_scheduled")},
    )
    return fake


def _win(wid, status, start_offset_min, duration=30):
    return {
        "id": wid,
        "status": status,
        "scheduled_start": now_utc() + timedelta(minutes=start_offset_min),
        "duration_minutes": duration,
    }


# --------------------------------------------------------------- close first ---
def test_expired_open_window_is_closed(monkeypatch):
    """Otherwise DR stays suppressed forever."""
    _install(monkeypatch, [_win(1, "open", -120, duration=30)])
    res = jobs.maintenance_window_driver()
    assert res["closed"] == [1]


def test_open_window_still_within_duration_is_left_alone(monkeypatch):
    fake = _install(monkeypatch, [_win(1, "open", -5, duration=30)])
    res = jobs.maintenance_window_driver()
    assert res["closed"] == []
    assert ("close", 1) not in fake.calls


def test_close_is_attempted_before_announce_and_open(monkeypatch):
    """ORDER IS THE SAFETY PROPERTY — releasing DR must not queue behind anything."""
    fake = _install(
        monkeypatch,
        [_win(1, "open", -120, duration=30), _win(2, "planned", 10), _win(3, "announced", -1)],
    )
    jobs.maintenance_window_driver()
    kinds = [c[0] for c in fake.calls]
    assert kinds.index("close") < kinds.index("announce")
    assert kinds.index("close") < kinds.index("open")


def test_announce_failure_does_not_prevent_close(monkeypatch):
    """A broken announce must never strand DR suppression."""
    fake = _install(monkeypatch, [_win(1, "open", -120, duration=30), _win(2, "planned", 10)])
    fake.fail_announce = True
    res = jobs.maintenance_window_driver()
    assert res["closed"] == [1], "close was blocked by an unrelated announce failure"
    assert any("announce" in e for e in res["errors"])


# ------------------------------------------------------- never force-opens ---
def test_never_passes_force_unannounced(monkeypatch):
    """THE OWNER DIRECTIVE. 'Advise and coordinate before' is not optional."""
    fake = _install(monkeypatch, [_win(3, "announced", -1)])
    jobs.maintenance_window_driver()
    assert fake.open_kwargs, "open was never called"
    for kw in fake.open_kwargs:
        assert not kw.get("force_unannounced"), "job force-opened an unannounced window"


def test_planned_window_at_start_time_is_announced_not_opened(monkeypatch):
    """A window that reaches its start still un-announced gets announced and
    left for the next tick — one tick late beats a silent prod change."""
    fake = _install(monkeypatch, [_win(2, "planned", -1)])
    res = jobs.maintenance_window_driver()
    assert res["announced"] == [2]
    assert res["opened"] == []
    assert ("open", 2) not in fake.calls


def test_announced_window_before_its_start_is_not_opened(monkeypatch):
    _install(monkeypatch, [_win(3, "announced", 30)])
    res = jobs.maintenance_window_driver()
    assert res["opened"] == []


def test_planned_window_far_out_is_not_announced_yet(monkeypatch):
    """Default lead is 60 min; announcing days early is noise."""
    _install(monkeypatch, [_win(2, "planned", 600)])
    res = jobs.maintenance_window_driver()
    assert res["announced"] == []


# --------------------------------------------------------------- resilience ---
def test_one_bad_window_does_not_stop_the_others(monkeypatch):
    fake = _install(monkeypatch, [_win(1, "open", -120, duration=30), _win(4, "open", -120, duration=30)])
    orig = fake.close_scheduled

    def flaky(wid, outcomes=None):
        if wid == 1:
            fake.calls.append(("close", wid))
            raise RuntimeError("boom")
        return orig(wid, outcomes)

    monkeypatch.setitem(
        __import__("sys").modules["services.maintenance_schedule_service"].__dict__, "close_scheduled", flaky
    )
    res = jobs.maintenance_window_driver()
    assert res["closed"] == [4], "a failing window blocked the rest of the sweep"
    assert any("close 1" in e for e in res["errors"])


def test_missing_service_does_not_raise(monkeypatch):
    """Unattended job: never raise into the scheduler.

    #5987 — a sys.modules-only removal is NOT enough: `from services import x` still resolves
    off the cached package attribute, so this test used to exercise the HEALTHY path and pass
    for the wrong reason. uninstall_module removes both bindings, so the service really is gone.
    """
    uninstall_module(monkeypatch, "services.maintenance_schedule_service")
    res = jobs.maintenance_window_driver()
    assert res.get("ok") is False
