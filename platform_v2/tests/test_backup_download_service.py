"""Tests for backup_download_service — async download preparation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_importable():
    from services.backup_download_service import (
        prepare_download,
        get_download_status,
        cleanup_expired,
    )

    assert all(callable(f) for f in [prepare_download, get_download_status, cleanup_expired])


def test_get_status_unknown_job():
    from services.backup_download_service import get_download_status

    r = get_download_status(job_id=999999999)
    assert r["success"] is False
    assert r["error"] == "job_not_found"


def test_prepare_download_missing_backup():
    from services.backup_download_service import prepare_download

    r = prepare_download(backup_name="nonexistent_backup_xyz_abc", triggered_by="test")
    assert r["success"] is False
    assert "not_found" in r["error"]


def test_cleanup_expired_runs_without_error():
    from services.backup_download_service import cleanup_expired

    result = cleanup_expired()
    assert isinstance(result, int)  # returns count of cleaned jobs
