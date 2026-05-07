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
