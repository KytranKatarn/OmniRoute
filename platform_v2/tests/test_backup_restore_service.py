"""Tests for backup_restore_service."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_importable():
    from services.backup_restore_service import (
        get_restore_status,
        initiate_sandbox_restore,
        promote_to_production,
    )

    assert all(callable(f) for f in [get_restore_status, initiate_sandbox_restore, promote_to_production])


def test_get_restore_status_missing_backup():
    from services.backup_restore_service import get_restore_status

    r = get_restore_status(backup_id=999999999)
    assert r["success"] is False
    assert r["error"] == "backup_not_found"


def test_initiate_sandbox_restore_missing_backup():
    from services.backup_restore_service import initiate_sandbox_restore

    r = initiate_sandbox_restore(backup_id=999999999, triggered_by="test")
    assert r["success"] is False
    assert r["error"] == "backup_not_found"


def test_restore_status_table_exists():
    """module_restore_sessions table should exist after migration 374."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='module_restore_sessions'")
        assert cur.fetchone() is not None, "Run migration 374 first"


# ---------------------------------------------------------------------------
# #5080 follow-up: which psql ERRORs mean the restore is actually broken.
#
# The sqlgz restore path counts ERROR lines and fails the session if any remain.
# Two families are expected on every healthy run and must NOT fail it, or the gate
# cries wolf and gets ignored — which is how this whole class of defect survives:
#   * pg_dump 17 (image) vs server 16 emits SETs the server rejects
#   * restoring into a sandbox that was not dropped first
# Everything else — syntax errors, invalid json, constraint failures — is real.
# ---------------------------------------------------------------------------


class TestRestoreErrorClassification:
    def _f(self):
        from services.backup_restore_service import count_real_restore_errors

        return count_real_restore_errors

    def test_version_mismatch_set_is_not_a_failure(self):
        """pg_dump 17 against a 16 server emits this on EVERY plain dump."""
        assert self._f()('ERROR:  unrecognized configuration parameter "transaction_timeout"') == 0

    def test_already_exists_is_not_a_failure(self):
        err = 'ERROR:  relation "task_execution_log" already exists\nERROR:  relation "idx_tel_job_id" already exists'
        assert self._f()(err) == 0

    def test_the_5080_errors_still_count(self):
        """The exact errors that proved the old dumps unrestorable must still fail."""
        err = 'ERROR:  invalid input syntax for type json\nERROR:  syntax error at or near "ARRAY"'
        assert self._f()(err) == 2

    def test_real_errors_survive_a_pile_of_benign_ones(self):
        """A genuine failure must not be masked by benign noise around it."""
        err = "\n".join(
            [
                'ERROR:  unrecognized configuration parameter "transaction_timeout"',
                'ERROR:  relation "x" already exists',
                "ERROR:  invalid input syntax for type json",
                'ERROR:  relation "y" already exists',
            ]
        )
        assert self._f()(err) == 1

    def test_missing_relation_is_real(self):
        """`does not exist` is NOT in the allowlist — a missing table is a broken restore."""
        assert self._f()('ERROR:  relation "agent_daily_summary" does not exist') == 1

    def test_empty_and_none_are_zero(self):
        assert self._f()("") == 0
        assert self._f()(None) == 0
