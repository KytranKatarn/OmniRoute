"""Tests for expanded dispatch_service (Phase 2).

Run: docker exec archie_platform python -m pytest services/tests/test_phase2_dispatch.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from database import get_db_cursor


def _cleanup_test_jobs():
    """Remove test jobs."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM bridge_jobs WHERE module_source = 'test_phase2'")


def test_create_job_returns_id():
    """create_job should return an integer job_id."""
    from services.dispatch_service import get_dispatch_service

    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job_id = svc.create_job(
            job_type="test_job",
            module_source="test_phase2",
            description="Phase 2 test job",
            total_steps=5,
        )
        assert isinstance(job_id, int)
        assert job_id > 0
    finally:
        _cleanup_test_jobs()


def test_create_job_blocks_duplicate():
    """Duplicate job (same type+module, still running) should return None."""
    from services.dispatch_service import get_dispatch_service

    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job1 = svc.create_job("test_dup", "test_phase2", "first", 5)
        job2 = svc.create_job("test_dup", "test_phase2", "second", 5)
        assert job1 is not None
        assert job2 is None
    finally:
        _cleanup_test_jobs()


def test_update_job_progress():
    """update_job_progress should increment completed_steps."""
    from services.dispatch_service import get_dispatch_service

    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job_id = svc.create_job("test_progress", "test_phase2", "progress test", 10)
        svc.update_job_progress(job_id, completed_delta=3)
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT completed_steps FROM bridge_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
            assert row["completed_steps"] == 3
    finally:
        _cleanup_test_jobs()


def test_complete_job_auto_status():
    """complete_job with status='auto' should determine from counters."""
    from services.dispatch_service import get_dispatch_service

    svc = get_dispatch_service()
    _cleanup_test_jobs()
    try:
        job_id = svc.create_job("test_complete", "test_phase2", "complete test", 5)
        svc.update_job_progress(job_id, completed_delta=5)
        result = svc.complete_job(job_id)
        assert result is True
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT status FROM bridge_jobs WHERE id = %s", (job_id,))
            assert cur.fetchone()["status"] == "completed"
    finally:
        _cleanup_test_jobs()
