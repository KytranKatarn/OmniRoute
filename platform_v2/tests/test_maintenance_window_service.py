"""Maintenance windows must PROVE the watchdog is suppressed, and must stay honest.

Context: on 2026-07-25 a planned power-down was read as a hub failure and triggered
a real failover that took ~20 healthy services offline. The safety already existed
(`.watchdog_disabled`); nobody set it. This service makes it automatic — including
when WE are the cause (restarts, migrations, power-down, long restores).

The two properties that actually matter, and that these tests pin:

1. WRITING A FILE IS NOT PROOF IT IS HONOURED. `start_window` runs a real watchdog
   cycle afterwards and must refuse to report SAFE unless the watchdog itself says
   it is snoozed/disabled. This is the same discipline that caught the loopback
   probe (#5219 follow-up) and the 30s-window count bug (#2472).

2. CLOSING A WINDOW DOES NOT RESTORE DR. boston-2 is currently a promoted fork;
   clearing our flags makes the watchdog scan again but does NOT give it a replica
   to fail over to. `end_window` must say so rather than imply cover it lacks.

All SSH goes through one `_ssh` helper, so these run with no infra.
"""

import sys

import pytest

sys.path.insert(0, "/app")

mws = pytest.importorskip("services.maintenance_window_service")


@pytest.fixture(autouse=True)
def _no_announce(monkeypatch):
    """Never touch Telegram from a test."""
    monkeypatch.setattr(mws, "_announce", lambda *a, **k: None)


@pytest.fixture
def ssh(monkeypatch):
    """Scriptable _ssh. `calls` records every remote command issued."""

    class Fake:
        def __init__(self):
            self.calls = []
            self.watchdog_says = "snoozed — 5400s until scanning resumes."
            self.failed_over = False
            self.disabled_note = ""
            self.snooze_value = None
            self.write_rc = 0

        def __call__(self, cmd, timeout=30):
            self.calls.append(cmd)
            if "dr_watchdog.sh" in cmd:
                return 0, self.watchdog_says
            if cmd.startswith("echo ") and ">" in cmd:  # arming a snooze
                return self.write_rc, ""
            if "printf" in cmd and "watchdog_disabled" in cmd:
                return self.write_rc, ""
            if "rm -f" in cmd:
                return 0, "cleared"
            # NOTE: the composite read must be matched FIRST — it also contains
            # ".failed_over" and "echo yes", so the single-probe branches below
            # would otherwise shadow it (this fake got that wrong once).
            if "---" in cmd:  # window_status composite read
                snooze = str(self.snooze_value) if self.snooze_value else "none"
                dis = self.disabled_note or "none"
                fo = "yes" if self.failed_over else "no"
                return 0, f"{snooze}\n---\n{dis}\n---\n{fo}"
            if ".failed_over" in cmd and "echo yes" in cmd:
                return 0, "yes" if self.failed_over else "no"
            if "cat" in cmd and "watchdog_disabled" in cmd:
                return 0, self.disabled_note
            return 0, ""

    f = Fake()
    monkeypatch.setattr(mws, "_ssh", f)
    monkeypatch.setattr(mws, "_posture_warnings", lambda: [])
    return f


# ------------------------------------------------------------------ start ----
def test_start_verifies_the_watchdog_actually_reports_itself_snoozed(ssh):
    rep = mws.start_window(minutes=90, reason="PSU swap")
    assert rep["ok"] is True
    assert rep["suppression_verified"] is True
    assert rep["safe_to_power_off"] is True
    assert any("dr_watchdog.sh" in c for c in ssh.calls), "never ran a verification cycle"


def test_start_refuses_SAFE_when_the_watchdog_does_not_confirm(ssh):
    """THE CORE GUARD: the file was written but the watchdog kept scanning."""
    ssh.watchdog_says = "no quorum (0/3 down) → transient blip. Reset."
    rep = mws.start_window(minutes=90, reason="PSU swap")
    assert rep["ok"] is False
    assert rep["suppression_verified"] is False
    assert rep["safe_to_power_off"] is False
    assert "do NOT power off" in rep["error"]


def test_start_reports_failure_when_it_cannot_arm_at_all(ssh):
    ssh.write_rc = 1
    rep = mws.start_window(minutes=30, reason="x")
    assert rep["ok"] is False
    assert "could not arm suppression" in rep["error"]


def test_degraded_dr_posture_warns_but_does_not_block(ssh, monkeypatch):
    """Owner call: a watchdog aimed at a dead replica is MORE dangerous armed."""
    monkeypatch.setattr(mws, "_posture_warnings", lambda: ["replication slot INACTIVE", ".failed_over is SET"])
    rep = mws.start_window(minutes=90, reason="hardware")
    assert rep["ok"] is True, "a degraded posture must not block the window"
    assert len(rep["warnings"]) == 2, "but it must be reported, itemised"


def test_indefinite_is_flagged_as_not_auto_expiring(ssh):
    ssh.watchdog_says = "disabled (/opt/archie-dr/.watchdog_disabled present) — exit."
    rep = mws.start_window(indefinite=True, reason="long job")
    assert rep["mode"] == "indefinite"
    assert rep["expires_at"] is None
    assert rep["ok"] is True


# ----------------------------------------------------------------- status ----
def test_status_reports_a_half_applied_window(ssh):
    import time as _t

    ssh.snooze_value = int(_t.time()) + 600
    ssh.failed_over = True
    st = mws.window_status()
    assert st["open"] is True
    assert 0 < st["snooze_remaining_s"] <= 600
    assert st["failed_over"] is True


def test_status_with_no_window_open(ssh):
    st = mws.window_status()
    assert st["open"] is False
    assert st["snooze_remaining_s"] is None


# -------------------------------------------------------------------- end ----
def test_end_does_not_claim_dr_is_restored_when_it_is_not(ssh, monkeypatch):
    """boston-2 is a promoted fork — scanning again != covered."""
    ssh.watchdog_says = "no quorum (0/3 down) → transient blip. Reset."
    monkeypatch.setattr(mws, "_posture_warnings", lambda: [".failed_over is SET on boston-2"])
    rep = mws.end_window()
    assert rep["watchdog_scanning"] is True
    assert rep["dr_cover_restored"] is False, "must not imply cover it does not have"
    assert "not fully restored" in rep["note"].lower()


def test_end_is_idempotent_with_no_window_open(ssh):
    ssh.watchdog_says = "no quorum (0/3 down) → transient blip. Reset."
    first = mws.end_window()
    second = mws.end_window()
    assert first["ok"] and second["ok"]


# -------------------------------------------------- internal auto-announce ---
def test_context_manager_opens_and_closes_around_the_work(ssh):
    ran = []
    with mws.maintenance_window("platform restart", minutes=15):
        ran.append(True)
    assert ran == [True]
    assert sum("rm -f" in c for c in ssh.calls) == 1, "window was not closed"


def test_context_manager_is_FAIL_OPEN_when_dr_host_is_unreachable(ssh):
    """Blocking a deploy because a REMOTE host is down would be a worse failure."""
    ssh.write_rc = 1
    ran = []
    with mws.maintenance_window("migration", minutes=15):
        ran.append(True)
    assert ran == [True], "wrapped work must still run"
    assert sum("rm -f" in c for c in ssh.calls) == 0, "nothing was opened, so nothing to close"


def test_context_manager_closes_even_if_the_work_raises(ssh):
    with pytest.raises(RuntimeError):
        with mws.maintenance_window("restart", minutes=15):
            raise RuntimeError("deploy blew up")
    assert sum("rm -f" in c for c in ssh.calls) == 1, "window leaked on an exception"
