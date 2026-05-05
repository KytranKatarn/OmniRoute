"""budget_jobs.py — Budget reset job registrations.

Registers the daily budget reset and cooldown recovery jobs
with job_service. Called at app startup.
"""

import logging
from services.agent_service import reset_budgets, transition_cleared_cooldowns

logger = logging.getLogger(__name__)


def _run_budget_reset():
    return reset_budgets()


def _run_cooldown_recovery():
    return transition_cleared_cooldowns()


def register_budget_jobs(job_service):
    """Register budget lifecycle jobs with the central job service."""
    job_service.register_job(
        name="budget_reset",
        func=_run_budget_reset,
        cron_hour=4,
        cron_minute=0,
        department="Operations & Infrastructure",
        description="Daily zero-out of agent task counts and token usage (04:00 EDT)",
    )
    job_service.register_job(
        name="cooldown_recovery",
        func=_run_cooldown_recovery,
        cron_hour=4,
        cron_minute=5,
        department="Operations & Infrastructure",
        description="Transition cooldown agents with cleared budgets back to active (04:05 EDT)",
    )
    logger.info("[BudgetJobs] Registered budget_reset and cooldown_recovery jobs")
