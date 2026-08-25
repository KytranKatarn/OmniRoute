"""A DR snooze must end as soon as the hub is demonstrably back (owner ask 2026-07-26).

A snooze has to be sized for the WORST case — a 90-minute PSU/GPU job — which left
DR disarmed for the full 90 minutes even when the hub returned in 20. Every unused
minute is a minute with no cover. Early close ends the snooze once the hub is
confirmed healthy for K_UP CONSECUTIVE cycles.

The streak matters. During maintenance we restart the platform repeatedly, so the
hub bounces; a single healthy probe is a blip, not a recovery. This mirrors the
watchdog's existing confirmed-DOWN quorum (K) in the opposite direction.

Early close is safe by construction: clearing a snooze resumes SCANNING, it never
fails over. `.watchdog_disabled` is deliberately NOT auto-cleared — an indefinite
kill switch is a human decision.

These drive the REAL dr_watchdog.sh as a subprocess with a stubbed hub probe,
rather than reimplementing its logic.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest
from tests.repo_root import repo_root as _shared_repo_root

_MARKER = Path("scripts") / "dr" / "watchdog" / "dr_watchdog.sh"


def _find_repo():
    for base in list(Path(__file__).resolve().parents) + [Path("/mnt/archie_brain")]:
        if (base / _MARKER).exists():
            return base
    return _shared_repo_root()  # one resolver for the whole suite (#5994)


REPO = _find_repo()
WATCHDOG = REPO / _MARKER

pytestmark = pytest.mark.skipif(not WATCHDOG.exists(), reason="dr_watchdog.sh not present in this checkout")


def _run_cycle(tmp_path, hub_up, snooze_left=600, k_up=2, early_close="1"):
    """Run ONE real watchdog cycle against a sandboxed $DR. Returns combined output."""
    dr = tmp_path
    probe = dr / "probe_hub.sh"
    probe.write_text("#!/bin/bash\nexit %d\n" % (0 if hub_up else 1))
    probe.chmod(0o755)

    if snooze_left is not None:
        (dr / ".snooze_until").write_text(str(int(time.time()) + snooze_left))

    env = {
        **os.environ,
        "DR": str(dr),
        "PROBE_SCRIPT": str(probe),
        "SNOOZE_FILE": str(dr / ".snooze_until"),
        "SNOOZE_UP_STREAK": str(dr / ".snooze_up_streak"),
        "K_UP": str(k_up),
        "SNOOZE_EARLY_CLOSE": early_close,
        "DRY_RUN": "1",
        "FLEET_KEY": str(dr / "nonexistent_key"),
    }
    proc = subprocess.run(["bash", str(WATCHDOG)], capture_output=True, text=True, timeout=90, env=env)
    return proc.stdout + proc.stderr


def _snoozed(tmp_path):
    return (tmp_path / ".snooze_until").exists()


def test_hub_up_for_k_consecutive_cycles_closes_the_snooze_early(tmp_path):
    """THE FEATURE: hub back and stable -> stop wasting the rest of the window."""
    out = _run_cycle(tmp_path, hub_up=True, k_up=2)
    assert _snoozed(tmp_path), f"should still be snoozed after 1 of 2:\n{out}"
    assert "1/2" in out, f"expected streak progress in log:\n{out}"

    out = _run_cycle(tmp_path, hub_up=True, k_up=2, snooze_left=None)
    assert "CLOSED EARLY" in out, f"expected early close on the 2nd healthy cycle:\n{out}"
    assert not _snoozed(tmp_path), f"snooze file should be gone:\n{out}"


def test_a_single_healthy_probe_does_not_close_it(tmp_path):
    """One good probe is a blip. Must NOT re-arm DR mid-maintenance."""
    out = _run_cycle(tmp_path, hub_up=True, k_up=3)
    assert "CLOSED EARLY" not in out, f"closed on a single probe:\n{out}"
    assert _snoozed(tmp_path)


def test_a_bouncing_hub_resets_the_streak(tmp_path):
    """Deploys restart the platform repeatedly — that is not a recovery."""
    _run_cycle(tmp_path, hub_up=True, k_up=2)  # streak 1
    out = _run_cycle(tmp_path, hub_up=False, k_up=2, snooze_left=None)  # bounce
    assert not (tmp_path / ".snooze_up_streak").exists(), f"streak survived a down cycle:\n{out}"
    out = _run_cycle(tmp_path, hub_up=True, k_up=2, snooze_left=None)  # back to 1, not 2
    assert "CLOSED EARLY" not in out, f"a flap must not reach the threshold:\n{out}"
    assert _snoozed(tmp_path)


def test_hub_still_down_keeps_the_snooze(tmp_path):
    """The normal case: still working, stay silent."""
    out = _run_cycle(tmp_path, hub_up=False, k_up=2)
    assert "until scanning resumes" in out, f"expected the plain snooze log:\n{out}"
    assert "CLOSED EARLY" not in out
    assert _snoozed(tmp_path)


def test_early_close_can_be_switched_off(tmp_path):
    """SNOOZE_EARLY_CLOSE=0 restores the old always-run-the-full-window behaviour."""
    for _ in range(3):
        out = _run_cycle(tmp_path, hub_up=True, k_up=2, snooze_left=600, early_close="0")
    assert "CLOSED EARLY" not in out, f"early close fired while disabled:\n{out}"
    assert _snoozed(tmp_path)


def test_watchdog_disabled_is_never_auto_cleared(tmp_path):
    """An indefinite kill switch is a human decision — only a human retracts it."""
    (tmp_path / ".watchdog_disabled").write_text("planned maintenance\n")
    out = _run_cycle(tmp_path, hub_up=True, k_up=1)
    assert (tmp_path / ".watchdog_disabled").exists(), f"kill switch was removed:\n{out}"
    assert "disabled" in out.lower(), f"expected the disabled short-circuit:\n{out}"
    assert "CLOSED EARLY" not in out
