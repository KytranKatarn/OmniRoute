"""#5012 — an orphaned backup lock must not block backups for 2 hours.

`acquire_backup_lock` recorded a pid and then never checked it: staleness was decided purely
by LOCK_TIMEOUT (7200s). So a backup killed mid-run leaves a lock that blocks EVERY backup —
and therefore every medium-risk deploy, since the W.A.R.D.E.N. gate requires a fresh one —
for two hours, with the only symptom being "in progress by <someone>" naming a dead process.

Both orphans below actually happened on 2026-07-20 and are kept as regression cases.

SAFETY DIRECTION: the dangerous failure is declaring a LIVE backup dead, which would run two
backups concurrently over the same paths. `lock_owner_is_dead` is therefore asymmetric — every
uncertain input must return False (keep the lock). Most tests here assert that conservatism.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.backup_manager._shared import lock_owner_is_dead  # noqa: E402

NOW = 1_784_560_000.0


def _alive(*pids):
    return lambda p: p in pids


class TestProvablyDead:
    """Only these two shapes may release a lock."""

    def test_orphan_1_killed_wrapper_pid_gone(self):
        """REAL: a `docker exec` wrapper (pid 1550) was killed mid-backup; /proc/1550 vanished."""
        lock = {"pid": 1550, "timestamp": NOW, "backup_name": "x"}
        dead, why = lock_owner_is_dead(lock, _exists=_alive(), _start_time=lambda p: None)
        assert dead is True
        assert "no longer exists" in why

    def test_orphan_2_container_restart_pid_1_reused(self):
        """REAL: backup started 15:35:57 as pid 1; container restarted 15:37:10; pid 1 exists again.

        This is why a bare 'is the pid alive?' check is insufficient — pid 1 is always alive
        in a container, so proof #1 alone would keep this orphan for the full 2h.
        """
        lock = {"pid": 1, "timestamp": NOW, "backup_name": "x"}
        dead, why = lock_owner_is_dead(lock, _exists=_alive(1), _start_time=lambda p: NOW + 73)
        assert dead is True
        assert "started after the lock" in why


class TestKeepsTheLock:
    """Everything else. A wrong 'dead' here means two concurrent backups."""

    def test_live_owner_is_not_dead(self):
        lock = {"pid": 42, "timestamp": NOW, "backup_name": "x"}
        dead, why = lock_owner_is_dead(lock, _exists=_alive(42), _start_time=lambda p: NOW - 5)
        assert dead is False
        assert "alive" in why

    def test_owner_started_marginally_after_lock_is_tolerated(self):
        """Clock coarseness must not evict a live backup — 2s tolerance."""
        lock = {"pid": 42, "timestamp": NOW, "backup_name": "x"}
        dead, _ = lock_owner_is_dead(lock, _exists=_alive(42), _start_time=lambda p: NOW + 1)
        assert dead is False

    def test_unknown_start_time_keeps_the_lock(self):
        """Can't prove it's dead -> assume alive."""
        lock = {"pid": 42, "timestamp": NOW}
        dead, why = lock_owner_is_dead(lock, _exists=_alive(42), _start_time=lambda p: None)
        assert dead is False
        assert "start time unavailable" in why

    def test_lock_without_pid_keeps_the_lock(self):
        """Locks written before pid was recorded must still be honoured until LOCK_TIMEOUT."""
        dead, why = lock_owner_is_dead({"timestamp": NOW}, _exists=_alive(), _start_time=lambda p: None)
        assert dead is False
        assert "no pid" in why

    def test_unreadable_pid_keeps_the_lock(self):
        dead, why = lock_owner_is_dead({"pid": "bogus", "timestamp": NOW}, _exists=_alive(), _start_time=lambda p: None)
        assert dead is False
        assert "unreadable pid" in why

    def test_missing_timestamp_keeps_the_lock(self):
        """No timestamp -> the started-after comparison is impossible, so don't guess."""
        lock = {"pid": 42}
        dead, why = lock_owner_is_dead(lock, _exists=_alive(42), _start_time=lambda p: NOW)
        assert dead is False
        assert "no timestamp" in why


class TestRealProcStartTime:
    """The /proc reader itself, against this actual process."""

    def test_reports_a_plausible_start_for_self(self):
        import time as _t

        from tools.backup_manager._shared import _proc_start_time

        started = _proc_start_time(os.getpid())
        assert started is not None
        age = _t.time() - started
        assert 0 <= age < 3600, f"implausible start age {age}s"

    def test_returns_none_for_a_nonexistent_pid(self):
        from tools.backup_manager._shared import _proc_start_time

        assert _proc_start_time(999_999) is None
