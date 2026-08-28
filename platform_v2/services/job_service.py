"""job_service.py — Central job registry and runner.

Phase 1 of Agent Lifecycle Coordination.
Provides register_job / run_job / list_jobs API wrapping APScheduler.
Runs alongside existing agent_loop.py with no conflicts.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)

JOB_DEPARTMENT_MAP = {
    "budget_reset": "Operations & Infrastructure",
    "cooldown_recovery": "Operations & Infrastructure",
    "embedding_batch": "Analytics & Intelligence",
    "skill_sync": "Research & Development",
    "skill_analyzer": "Research & Development",
    "fleet_health": "Operations & Infrastructure",
}


class JobService:
    def __init__(self, scheduler=None):
        self._scheduler = scheduler
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def register_job(
        self, name, func, interval_hours=1, department="", enabled=True, description="", cron_hour=None, cron_minute=0
    ):
        """Register a job. If scheduler available, also schedule it.
        Use cron_hour/cron_minute for daily fixed-time jobs.
        Use interval_hours for recurring interval jobs.
        """
        self._jobs[name] = {
            "name": name,
            "func": func,
            "interval_hours": interval_hours,
            "department": department or JOB_DEPARTMENT_MAP.get(name, ""),
            "enabled": enabled,
            "description": description,
            "cron_hour": cron_hour,
            "cron_minute": cron_minute,
            "last_run": None,
            "last_status": None,
            "last_duration_ms": None,
            "run_count": 0,
            "error_count": 0,
        }
        if self._scheduler and enabled:
            self._schedule_with_apscheduler(name, func, interval_hours, cron_hour=cron_hour, cron_minute=cron_minute)
        logger.info("[JobService] Registered '%s' (dept=%s, enabled=%s)", name, department, enabled)

    def _schedule_with_apscheduler(self, name, func, interval_hours, cron_hour=None, cron_minute=0):
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

        def wrapped():
            self.run_job(name)

        if cron_hour is not None:
            trigger = CronTrigger(hour=cron_hour, minute=cron_minute, timezone="America/Toronto")
        else:
            trigger = IntervalTrigger(hours=interval_hours)

        self._scheduler.add_job(
            wrapped, trigger=trigger, id=f"jobsvc_{name}", name=f"JobService: {name}", replace_existing=True
        )

    def run_job(self, name):
        job = self._jobs.get(name)
        if not job:
            return {"status": "error", "error_message": f"Job '{name}' not found"}
        if not job["enabled"]:
            return {"status": "skipped", "reason": "disabled"}

        start = time.time()
        try:
            result = job["func"]()
            duration_ms = int((time.time() - start) * 1000)
            job["last_run"] = datetime.now()
            job["last_status"] = "success"
            job["last_duration_ms"] = duration_ms
            job["run_count"] += 1
            self._log_to_db(name, "success", 1, 0, duration_ms, job["department"])
            return {"status": "success", "duration_ms": duration_ms, "result": result}
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            job["last_run"] = datetime.now()
            job["last_status"] = "error"
            job["last_duration_ms"] = duration_ms
            job["run_count"] += 1
            job["error_count"] += 1
            self._log_to_db(name, "error", 0, 1, duration_ms, job["department"], error_message=str(e))
            logger.error("[JobService] Job '%s' failed: %s", name, e)
            return {"status": "error", "duration_ms": duration_ms, "error_message": str(e)}

    def list_jobs(self):
        return [
            {
                "name": j["name"],
                "department": j["department"],
                "interval_hours": j["interval_hours"],
                "enabled": j["enabled"],
                "last_run": j["last_run"],
                "last_status": j["last_status"],
                "run_count": j["run_count"],
                "error_count": j["error_count"],
            }
            for j in self._jobs.values()
        ]

    def get_job_status(self, name):
        job = self._jobs.get(name)
        if not job:
            return None
        return {
            "name": job["name"],
            "department": job["department"],
            "interval_hours": job["interval_hours"],
            "enabled": job["enabled"],
            "last_run": job["last_run"],
            "last_status": job["last_status"],
            "last_duration_ms": job["last_duration_ms"],
            "run_count": job["run_count"],
            "error_count": job["error_count"],
        }

    def enable_job(self, name):
        job = self._jobs.get(name)
        if not job:
            return False
        job["enabled"] = True
        return True

    def disable_job(self, name):
        job = self._jobs.get(name)
        if not job:
            return False
        job["enabled"] = False
        return True

    def reschedule_job(self, name, interval_hours):
        """Change a job's interval. Updates metadata and APScheduler if available."""
        job = self._jobs.get(name)
        if not job:
            return False
        job["interval_hours"] = interval_hours
        # Update APScheduler if the job was scheduled by us
        if self._scheduler:
            try:
                sched_id = f"jobsvc_{name}"
                existing = self._scheduler.get_job(sched_id)
                if existing:
                    from apscheduler.triggers.interval import IntervalTrigger

                    self._scheduler.reschedule_job(
                        sched_id,
                        trigger=IntervalTrigger(hours=interval_hours),
                    )
            except Exception as e:
                logger.warning("[JobService] Could not reschedule '%s' in APScheduler: %s", name, e)
        logger.info("[JobService] Rescheduled '%s' to every %.1fh", name, interval_hours)
        return True

    def _log_to_db(self, job_name, status, items_processed, items_failed, duration_ms, department, error_message=None):
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO autonomy_loop_log
                        (job_name, status, items_processed, items_failed,
                         duration_ms, department, error_message, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                    (job_name, status, items_processed, items_failed, duration_ms, department, error_message),
                )
        except Exception as e:
            logger.warning("[JobService] Failed to log job '%s': %s", job_name, e)
