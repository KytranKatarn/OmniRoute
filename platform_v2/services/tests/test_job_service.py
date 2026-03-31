"""Tests for job_service — the central job registry and runner.
These are unit tests — no database needed for core functionality.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from services.job_service import JobService


@pytest.fixture
def job_service():
    return JobService(scheduler=None)


def test_register_job(job_service):
    job_service.register_job(
        name="test_job", func=lambda: None, interval_hours=6, department="Analytics & Intelligence"
    )
    jobs = job_service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test_job"
    assert jobs[0]["department"] == "Analytics & Intelligence"
    assert jobs[0]["enabled"] is True


def test_run_job(job_service):
    results = []
    job_service.register_job(name="test_run", func=lambda: results.append("executed") or {"items": 1}, interval_hours=1)
    outcome = job_service.run_job("test_run")
    assert outcome["status"] == "success"
    assert len(results) == 1


def test_run_job_logs_failure(job_service):
    def bad_job():
        raise ValueError("something broke")

    job_service.register_job(name="bad_job", func=bad_job, interval_hours=1)
    outcome = job_service.run_job("bad_job")
    assert outcome["status"] == "error"
    assert "something broke" in outcome["error_message"]


def test_disable_job(job_service):
    called = []
    job_service.register_job(name="toggle_job", func=lambda: called.append(True), interval_hours=1)
    job_service.disable_job("toggle_job")
    outcome = job_service.run_job("toggle_job")
    assert outcome["status"] == "skipped"
    assert len(called) == 0


def test_enable_job(job_service):
    called = []
    job_service.register_job(name="toggle_job2", func=lambda: called.append(True), interval_hours=1)
    job_service.disable_job("toggle_job2")
    job_service.enable_job("toggle_job2")
    outcome = job_service.run_job("toggle_job2")
    assert outcome["status"] == "success"
    assert len(called) == 1


def test_get_job_status(job_service):
    job_service.register_job(name="status_job", func=lambda: None, interval_hours=2)
    status = job_service.get_job_status("status_job")
    assert status["name"] == "status_job"
    assert status["interval_hours"] == 2
    assert status["last_run"] is None
    assert status["run_count"] == 0


def test_run_job_unknown_name(job_service):
    outcome = job_service.run_job("nonexistent")
    assert outcome["status"] == "error"
    assert "not found" in outcome["error_message"].lower()
