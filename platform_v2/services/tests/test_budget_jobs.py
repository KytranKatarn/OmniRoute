"""Tests for budget_jobs."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.job_service import JobService


def test_register_budget_jobs():
    from services.budget_jobs import register_budget_jobs

    svc = JobService(scheduler=None)
    register_budget_jobs(svc)
    jobs = svc.list_jobs()
    names = [j["name"] for j in jobs]
    assert "budget_reset" in names
    assert "cooldown_recovery" in names


def test_budget_reset_job_runs():
    from services.budget_jobs import register_budget_jobs

    svc = JobService(scheduler=None)
    register_budget_jobs(svc)
    outcome = svc.run_job("budget_reset")
    assert outcome["status"] == "success"
    assert "reset_count" in outcome["result"]


def test_cooldown_recovery_job_runs():
    from services.budget_jobs import register_budget_jobs

    svc = JobService(scheduler=None)
    register_budget_jobs(svc)
    outcome = svc.run_job("cooldown_recovery")
    assert outcome["status"] == "success"
    assert "transitioned_count" in outcome["result"]
