# Agent Lifecycle Coordination — Phase 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create job_service.py, add the missing budget reset job, and unblock the consciousness embedding pipeline.

**Architecture:** New `job_service.py` provides a `register_job()` / `run_job()` API that wraps APScheduler. It runs alongside the existing `agent_loop.py` (no breakage). A new budget reset job zeroes `current_task_count` daily and transitions cleared cooldown agents back to active. The embedding batch job can then find available agents.

**Tech Stack:** Python 3.11, Flask, APScheduler, psycopg2, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-31-agent-lifecycle-coordination-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/services/job_service.py` | Job registry, runner, budget reset |
| Create | `platform_v2/services/tests/test_job_service.py` | Unit tests for job_service |
| Create | `platform_v2/services/tests/__init__.py` | Test package init |
| Modify | `platform_v2/services/agent_service.py` | Add `reset_budgets()` and `transition_cleared_cooldowns()` |
| Modify | `platform_v2/app.py` (~lines 3224-3241) | Wire job_service alongside AgentLoop |
| Create | `database/migrations/075_budget_reset_job.sql` | Ensure agent_budgets defaults are sane |

---

### Task 1: Add budget reset functions to agent_service.py

**Files:**
- Modify: `platform_v2/services/agent_service.py` (append after line 664)
- Create: `platform_v2/services/tests/__init__.py`
- Create: `platform_v2/services/tests/test_agent_service_budget.py`

- [ ] **Step 1: Create test directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/services/tests
touch /mnt/archie_brain/platform_v2/services/tests/__init__.py
```

- [ ] **Step 2: Write failing tests for reset_budgets and transition_cleared_cooldowns**

Create `platform_v2/services/tests/test_agent_service_budget.py`:

```python
"""Tests for agent_service budget reset functions.

These tests require a live database connection (integration tests).
Run from platform_v2/: python -m pytest services/tests/test_agent_service_budget.py -v
"""
import os
import sys

# Ensure platform_v2 is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor


@pytest.fixture
def setup_test_agent():
    """Create a test agent with exhausted budget, clean up after."""
    agent_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        # Create test agent
        cur.execute("""
            INSERT INTO agents (name, display_name, department, status, shift_state, model)
            VALUES ('TestBudgetAgent', 'Test Budget Agent', 'Analytics & Intelligence',
                    'active', 'cooldown', 'test-model')
            RETURNING id
        """)
        agent_id = cur.fetchone()["id"]

        # Create exhausted budget
        cur.execute("""
            INSERT INTO agent_budgets (agent_id, current_task_count, task_queue_limit,
                                       tokens_used_today, token_limit_per_day, token_reset_at)
            VALUES (%s, 10, 10, 50000, 100000, NOW() - INTERVAL '1 day')
            ON CONFLICT (agent_id) DO UPDATE SET
                current_task_count = 10, task_queue_limit = 10,
                tokens_used_today = 50000, token_reset_at = NOW() - INTERVAL '1 day'
        """, (agent_id,))

    yield agent_id

    # Cleanup
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM agent_budgets WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))


def test_reset_budgets_zeroes_task_count(setup_test_agent):
    """reset_budgets() should zero current_task_count and tokens_used_today."""
    from services.agent_service import reset_budgets

    result = reset_budgets()

    assert result["reset_count"] > 0

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT current_task_count, tokens_used_today FROM agent_budgets WHERE agent_id = %s",
            (setup_test_agent,),
        )
        row = cur.fetchone()
        assert row["current_task_count"] == 0
        assert row["tokens_used_today"] == 0


def test_transition_cleared_cooldowns(setup_test_agent):
    """Cooldown agents with cleared budgets should transition back to active."""
    from services.agent_service import reset_budgets, transition_cleared_cooldowns

    # First reset budgets so the agent's count is 0
    reset_budgets()

    result = transition_cleared_cooldowns()

    assert result["transitioned_count"] > 0

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT shift_state FROM agents WHERE id = %s",
            (setup_test_agent,),
        )
        row = cur.fetchone()
        assert row["shift_state"] == "active"


def test_transition_cleared_cooldowns_skips_high_stress(setup_test_agent):
    """Cooldown agents with high stress should NOT transition back to active."""
    from services.agent_service import reset_budgets, transition_cleared_cooldowns

    reset_budgets()

    # Set high stress on the agent
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level)
            VALUES (%s, 0.90, 0.10)
            ON CONFLICT (agent_id) DO UPDATE SET stress_level = 0.90, energy_level = 0.10
        """, (setup_test_agent,))

    result = transition_cleared_cooldowns()

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT shift_state FROM agents WHERE id = %s",
            (setup_test_agent,),
        )
        row = cur.fetchone()
        # Should still be cooldown because stress is too high
        assert row["shift_state"] == "cooldown"

        # Cleanup emotional state
        cur.execute(
            "DELETE FROM agent_emotional_state WHERE agent_id = %s",
            (setup_test_agent,),
        )
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /mnt/archie_brain/platform_v2
docker exec archie_platform python -m pytest services/tests/test_agent_service_budget.py -v 2>&1 | tail -20
```

Expected: FAIL — `ImportError: cannot import name 'reset_budgets' from 'services.agent_service'`

- [ ] **Step 4: Implement reset_budgets and transition_cleared_cooldowns**

Append to `platform_v2/services/agent_service.py` after the last function (~line 664):

```python
# ---------------------------------------------------------------------------
# Budget reset (Phase 1 — Agent Lifecycle Coordination)
# ---------------------------------------------------------------------------

COOLDOWN_STRESS_THRESHOLD = 0.85
COOLDOWN_ENERGY_THRESHOLD = 0.15


def reset_budgets():
    """Zero out all agent budget counters. Called daily by job_service.

    Resets current_task_count and tokens_used_today to 0 for every agent,
    and updates token_reset_at to now.

    Returns dict with reset_count.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            UPDATE agent_budgets
            SET current_task_count = 0,
                tokens_used_today = 0,
                token_reset_at = NOW()
            WHERE current_task_count > 0 OR tokens_used_today > 0
        """)
        count = cur.rowcount
    logger.info("[BudgetReset] Reset %d agent budgets", count)
    return {"reset_count": count}


def transition_cleared_cooldowns():
    """Transition cooldown agents back to active if their budgets are clear
    and their welfare is acceptable.

    Only transitions agents where:
    - shift_state = 'cooldown'
    - status = 'active' (not deactivated)
    - current_task_count = 0 (budget was reset)
    - stress < COOLDOWN_STRESS_THRESHOLD or energy > COOLDOWN_ENERGY_THRESHOLD

    Returns dict with transitioned_count and agent names.
    """
    transitioned = []
    with get_db_cursor(commit=True) as (conn, cur):
        # Find cooldown agents with cleared budgets
        cur.execute("""
            SELECT a.id, a.name, a.department,
                   COALESCE(ab.current_task_count, 0) AS task_count,
                   COALESCE(es.stress_level, 0.0) AS stress,
                   COALESCE(es.energy_level, 0.8) AS energy
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            LEFT JOIN agent_emotional_state es ON a.id = es.agent_id
            WHERE a.shift_state = 'cooldown'
              AND a.status = 'active'
              AND COALESCE(ab.current_task_count, 0) = 0
        """)
        candidates = cur.fetchall()

        for agent in candidates:
            # Skip if stress is still too high
            if (agent["stress"] >= COOLDOWN_STRESS_THRESHOLD
                    and agent["energy"] <= COOLDOWN_ENERGY_THRESHOLD):
                logger.info(
                    "[BudgetReset] Skipping %s — stress=%.2f energy=%.2f",
                    agent["name"], agent["stress"], agent["energy"],
                )
                continue

            cur.execute(
                "UPDATE agents SET shift_state = 'active' WHERE id = %s",
                (agent["id"],),
            )

            # Log the rotation
            cur.execute("""
                INSERT INTO agent_rotation_log
                    (agent_id, agent_name, new_state, department, reason, started_at)
                VALUES (%s, %s, 'active', %s, 'budget_reset_recovery', NOW())
            """, (agent["id"], agent["name"], agent["department"]))

            transitioned.append(agent["name"])
            logger.info("[BudgetReset] %s -> active (budget cleared)", agent["name"])

    logger.info(
        "[BudgetReset] Transitioned %d agents: %s",
        len(transitioned), ", ".join(transitioned) if transitioned else "none",
    )
    return {"transitioned_count": len(transitioned), "agents": transitioned}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /mnt/archie_brain/platform_v2
docker exec archie_platform python -m pytest services/tests/test_agent_service_budget.py -v 2>&1 | tail -20
```

Expected: 3 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/agent_service.py platform_v2/services/tests/
git commit -m "feat(agent-service): add reset_budgets and transition_cleared_cooldowns

Phase 1 of Agent Lifecycle Coordination. Adds daily budget reset
and cooldown recovery functions to agent_service.py."
```

---

### Task 2: Create job_service.py

**Files:**
- Create: `platform_v2/services/job_service.py`
- Create: `platform_v2/services/tests/test_job_service.py`

- [ ] **Step 1: Write failing tests for job_service**

Create `platform_v2/services/tests/test_job_service.py`:

```python
"""Tests for job_service — the central job registry and runner.

Run from platform_v2/: python -m pytest services/tests/test_job_service.py -v
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest


@pytest.fixture
def job_service():
    """Create a JobService instance without a real scheduler."""
    from services.job_service import JobService

    svc = JobService(scheduler=None)
    return svc


def test_register_job(job_service):
    """register_job should store job metadata."""
    called = []

    def my_job():
        called.append(True)

    job_service.register_job(
        name="test_job",
        func=my_job,
        interval_hours=6,
        department="Analytics & Intelligence",
    )

    jobs = job_service.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "test_job"
    assert jobs[0]["department"] == "Analytics & Intelligence"
    assert jobs[0]["enabled"] is True


def test_run_job(job_service):
    """run_job should execute the registered function."""
    results = []

    def my_job():
        results.append("executed")
        return {"items": 1}

    job_service.register_job(name="test_run", func=my_job, interval_hours=1)
    outcome = job_service.run_job("test_run")

    assert outcome["status"] == "success"
    assert len(results) == 1


def test_run_job_logs_failure(job_service):
    """run_job should catch exceptions and log them."""

    def bad_job():
        raise ValueError("something broke")

    job_service.register_job(name="bad_job", func=bad_job, interval_hours=1)
    outcome = job_service.run_job("bad_job")

    assert outcome["status"] == "error"
    assert "something broke" in outcome["error_message"]


def test_disable_job(job_service):
    """disable_job should prevent run_job from executing."""
    called = []

    def my_job():
        called.append(True)

    job_service.register_job(name="toggle_job", func=my_job, interval_hours=1)
    job_service.disable_job("toggle_job")

    outcome = job_service.run_job("toggle_job")

    assert outcome["status"] == "skipped"
    assert len(called) == 0


def test_enable_job(job_service):
    """enable_job should re-enable a disabled job."""
    called = []

    def my_job():
        called.append(True)

    job_service.register_job(name="toggle_job2", func=my_job, interval_hours=1)
    job_service.disable_job("toggle_job2")
    job_service.enable_job("toggle_job2")

    outcome = job_service.run_job("toggle_job2")

    assert outcome["status"] == "success"
    assert len(called) == 1


def test_get_job_status(job_service):
    """get_job_status should return job metadata and last run info."""
    job_service.register_job(
        name="status_job", func=lambda: None, interval_hours=2
    )
    status = job_service.get_job_status("status_job")

    assert status["name"] == "status_job"
    assert status["interval_hours"] == 2
    assert status["last_run"] is None
    assert status["run_count"] == 0


def test_run_job_unknown_name(job_service):
    """run_job with unknown name should return error."""
    outcome = job_service.run_job("nonexistent")
    assert outcome["status"] == "error"
    assert "not found" in outcome["error_message"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain/platform_v2
docker exec archie_platform python -m pytest services/tests/test_job_service.py -v 2>&1 | tail -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.job_service'`

- [ ] **Step 3: Implement job_service.py**

Create `platform_v2/services/job_service.py`:

```python
"""job_service.py — Central job registry and runner.

Phase 1 of Agent Lifecycle Coordination.
Provides register_job / run_job / list_jobs API wrapping APScheduler.
Runs alongside existing agent_loop.py with no conflicts.

Usage:
    svc = JobService(scheduler=apscheduler_instance)
    svc.register_job("my_job", my_func, interval_hours=6, department="R&D")
    svc.run_job("my_job")  # manual trigger
    # OR scheduler triggers automatically via interval
"""
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Job department mapping for autonomy_loop_log
JOB_DEPARTMENT_MAP = {
    "budget_reset": "Operations & Infrastructure",
    "cooldown_recovery": "Operations & Infrastructure",
    "embedding_batch": "Analytics & Intelligence",
    "skill_sync": "Research & Development",
    "skill_analyzer": "Research & Development",
    "fleet_health": "Operations & Infrastructure",
}


class JobService:
    """Central registry for all scheduled jobs.

    Modules register their jobs at startup. JobService handles:
    - Job metadata tracking (name, schedule, department, enabled)
    - Execution with timing, error handling, and logging
    - Enable/disable/reschedule without restarting
    - Logging to autonomy_loop_log table
    """

    def __init__(self, scheduler=None):
        self._scheduler = scheduler
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def register_job(
        self,
        name: str,
        func: Callable,
        interval_hours: float = 1,
        department: str = "",
        enabled: bool = True,
        description: str = "",
        cron_hour: int = None,
        cron_minute: int = 0,
    ) -> None:
        """Register a job. If scheduler is available, also schedule it.

        Use interval_hours for recurring jobs (e.g. every 4h).
        Use cron_hour/cron_minute for daily jobs at a fixed time (e.g. 04:00 UTC).
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
            self._schedule_with_apscheduler(
                name, func, interval_hours,
                cron_hour=cron_hour, cron_minute=cron_minute,
            )

        logger.info(
            "[JobService] Registered job '%s' (every %.1fh, dept=%s, enabled=%s)",
            name, interval_hours, department, enabled,
        )

    def _schedule_with_apscheduler(
        self, name: str, func: Callable, interval_hours: float,
        cron_hour: int = None, cron_minute: int = 0,
    ) -> None:
        """Add job to APScheduler with app context wrapper.

        If cron_hour is set, uses CronTrigger (runs at specific time daily).
        Otherwise uses IntervalTrigger (runs every N hours from startup).
        """
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.cron import CronTrigger

        # Wrap in run_job for logging/error handling
        def wrapped():
            self.run_job(name)

        if cron_hour is not None:
            trigger = CronTrigger(hour=cron_hour, minute=cron_minute)
        else:
            trigger = IntervalTrigger(hours=interval_hours)

        self._scheduler.add_job(
            wrapped,
            trigger=trigger,
            id=f"jobsvc_{name}",
            name=f"JobService: {name}",
            replace_existing=True,
        )

    def run_job(self, name: str) -> Dict[str, Any]:
        """Execute a job by name. Returns outcome dict."""
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

            logger.info(
                "[JobService] Job '%s' completed in %dms", name, duration_ms
            )
            return {"status": "success", "duration_ms": duration_ms, "result": result}

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)

            job["last_run"] = datetime.now()
            job["last_status"] = "error"
            job["last_duration_ms"] = duration_ms
            job["run_count"] += 1
            job["error_count"] += 1

            self._log_to_db(
                name, "error", 0, 1, duration_ms, job["department"],
                error_message=str(e),
            )

            logger.error("[JobService] Job '%s' failed: %s", name, e)
            return {
                "status": "error",
                "duration_ms": duration_ms,
                "error_message": str(e),
            }

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Return metadata for all registered jobs."""
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

    def get_job_status(self, name: str) -> Optional[Dict[str, Any]]:
        """Return detailed status for a single job."""
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

    def enable_job(self, name: str) -> bool:
        """Enable a disabled job."""
        job = self._jobs.get(name)
        if not job:
            return False
        job["enabled"] = True
        logger.info("[JobService] Enabled job '%s'", name)
        return True

    def disable_job(self, name: str) -> bool:
        """Disable a job (skips execution on next trigger)."""
        job = self._jobs.get(name)
        if not job:
            return False
        job["enabled"] = False
        logger.info("[JobService] Disabled job '%s'", name)
        return True

    def _log_to_db(
        self,
        job_name: str,
        status: str,
        items_processed: int,
        items_failed: int,
        duration_ms: int,
        department: str,
        error_message: str = None,
    ) -> None:
        """Log job execution to autonomy_loop_log table."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("""
                    INSERT INTO autonomy_loop_log
                        (job_name, status, items_processed, items_failed,
                         duration_ms, department, error_message, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """, (
                    job_name, status, items_processed, items_failed,
                    duration_ms, department, error_message,
                ))
        except Exception as e:
            logger.warning("[JobService] Failed to log job '%s': %s", job_name, e)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain/platform_v2
docker exec archie_platform python -m pytest services/tests/test_job_service.py -v 2>&1 | tail -20
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/job_service.py platform_v2/services/tests/test_job_service.py
git commit -m "feat(job-service): create central job registry and runner

Phase 1 of Agent Lifecycle Coordination. JobService provides
register_job/run_job/list_jobs API wrapping APScheduler.
Logs all executions to autonomy_loop_log."
```

---

### Task 3: Register budget reset jobs with job_service

**Files:**
- Create: `platform_v2/services/budget_jobs.py`
- Create: `platform_v2/services/tests/test_budget_jobs.py`

- [ ] **Step 1: Write failing test for budget jobs registration**

Create `platform_v2/services/tests/test_budget_jobs.py`:

```python
"""Tests for budget_jobs — the budget reset job registration.

Run from platform_v2/: python -m pytest services/tests/test_budget_jobs.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from services.job_service import JobService


def test_register_budget_jobs():
    """register_budget_jobs should register 2 jobs with job_service."""
    from services.budget_jobs import register_budget_jobs

    svc = JobService(scheduler=None)
    register_budget_jobs(svc)

    jobs = svc.list_jobs()
    names = [j["name"] for j in jobs]

    assert "budget_reset" in names
    assert "cooldown_recovery" in names


def test_budget_reset_job_runs():
    """The budget_reset job should call reset_budgets when executed."""
    from services.budget_jobs import register_budget_jobs

    svc = JobService(scheduler=None)
    register_budget_jobs(svc)

    # This hits the real DB — integration test
    outcome = svc.run_job("budget_reset")
    assert outcome["status"] == "success"
    assert "reset_count" in outcome["result"]


def test_cooldown_recovery_job_runs():
    """The cooldown_recovery job should call transition_cleared_cooldowns."""
    from services.budget_jobs import register_budget_jobs

    svc = JobService(scheduler=None)
    register_budget_jobs(svc)

    outcome = svc.run_job("cooldown_recovery")
    assert outcome["status"] == "success"
    assert "transitioned_count" in outcome["result"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/archie_brain/platform_v2
docker exec archie_platform python -m pytest services/tests/test_budget_jobs.py -v 2>&1 | tail -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.budget_jobs'`

- [ ] **Step 3: Implement budget_jobs.py**

Create `platform_v2/services/budget_jobs.py`:

```python
"""budget_jobs.py — Budget reset job registrations.

Registers the daily budget reset and cooldown recovery jobs
with job_service. Called at app startup.

Usage:
    from services.budget_jobs import register_budget_jobs
    register_budget_jobs(job_service)
"""
import logging
from services.agent_service import reset_budgets, transition_cleared_cooldowns

logger = logging.getLogger(__name__)


def _run_budget_reset():
    """Daily budget reset — zeroes task counts and token usage."""
    return reset_budgets()


def _run_cooldown_recovery():
    """After budget reset, transition cleared cooldown agents back to active."""
    return transition_cleared_cooldowns()


def register_budget_jobs(job_service):
    """Register budget lifecycle jobs with the central job service.

    Two jobs:
    - budget_reset: runs daily at 04:00 UTC, zeroes all agent budgets
    - cooldown_recovery: runs daily at 04:05 UTC, recovers cooldown agents
    """
    job_service.register_job(
        name="budget_reset",
        func=_run_budget_reset,
        cron_hour=4,
        cron_minute=0,
        department="Operations & Infrastructure",
        description="Daily zero-out of agent task counts and token usage (04:00 UTC)",
    )

    job_service.register_job(
        name="cooldown_recovery",
        func=_run_cooldown_recovery,
        cron_hour=4,
        cron_minute=5,
        department="Operations & Infrastructure",
        description="Transition cooldown agents with cleared budgets back to active (04:05 UTC)",
    )

    logger.info("[BudgetJobs] Registered budget_reset and cooldown_recovery jobs")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /mnt/archie_brain/platform_v2
docker exec archie_platform python -m pytest services/tests/test_budget_jobs.py -v 2>&1 | tail -20
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/services/budget_jobs.py platform_v2/services/tests/test_budget_jobs.py
git commit -m "feat(budget-jobs): register daily budget reset and cooldown recovery

Two jobs registered with job_service:
- budget_reset: daily zero-out of current_task_count + tokens_used_today
- cooldown_recovery: transition cleared cooldown agents back to active"
```

---

### Task 4: Wire job_service into app.py startup

**Files:**
- Modify: `platform_v2/app.py` (~lines 3224-3241)

- [ ] **Step 1: Read the current startup code**

```bash
cd /mnt/archie_brain
# Read lines around the AgentLoop startup
```

Read `platform_v2/app.py` lines 3220-3250 to get exact current code.

- [ ] **Step 2: Add job_service initialization alongside AgentLoop**

In `platform_v2/app.py`, find the block that starts with:

```python
if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
    _scheduler = init_consciousness_scheduler(app)
    if _scheduler:
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from agent_loop import AgentLoop
        _agent_loop = AgentLoop(scheduler=_scheduler, flask_app=app)
        _agent_loop.start()
        app.config["AGENT_LOOP"] = _agent_loop
```

Add after the `app.config["AGENT_LOOP"] = _agent_loop` line:

```python
        # Phase 1: Job Service — runs alongside AgentLoop
        try:
            from services.job_service import JobService
            from services.budget_jobs import register_budget_jobs

            _job_service = JobService(scheduler=_scheduler)
            register_budget_jobs(_job_service)
            app.config["JOB_SERVICE"] = _job_service
            logger.info("[Startup] JobService initialized with budget reset jobs")
        except Exception as e:
            logger.error("[Startup] JobService failed to initialize: %s", e)
```

- [ ] **Step 3: Verify the container can import the new modules**

```bash
docker exec archie_platform python -c "
from services.job_service import JobService
from services.budget_jobs import register_budget_jobs
print('Imports OK')
svc = JobService(scheduler=None)
register_budget_jobs(svc)
print(f'Jobs registered: {[j[\"name\"] for j in svc.list_jobs()]}')
"
```

Expected: `Imports OK` and `Jobs registered: ['budget_reset', 'cooldown_recovery']`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/app.py
git commit -m "feat(startup): wire job_service with budget reset jobs at app startup

JobService runs alongside existing AgentLoop. Registers
budget_reset and cooldown_recovery jobs. Stored in
app.config['JOB_SERVICE'] for access from Autonomy routes."
```

---

### Task 5: Database migration — ensure agent_budgets defaults

**Files:**
- Create: `database/migrations/075_budget_reset_job.sql`

- [ ] **Step 1: Write the migration**

Create `database/migrations/075_budget_reset_job.sql`:

```sql
-- Migration 075: Ensure agent_budgets has sane defaults for budget reset
-- Part of Phase 1: Agent Lifecycle Coordination
-- Idempotent: safe to run multiple times

-- Ensure all active agents have a budget row
INSERT INTO agent_budgets (agent_id, task_queue_limit, current_task_count,
                           token_limit_per_day, tokens_used_today, token_reset_at)
SELECT a.id, 10, 0, 100000, 0, NOW()
FROM agents a
LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
WHERE ab.id IS NULL AND a.status = 'active'
ON CONFLICT (agent_id) DO NOTHING;

-- Ensure token_reset_at is never null (causes issues with reset logic)
UPDATE agent_budgets
SET token_reset_at = NOW()
WHERE token_reset_at IS NULL;

-- Add index for the budget reset query (finds agents needing reset)
CREATE INDEX IF NOT EXISTS idx_agent_budgets_needs_reset
ON agent_budgets (current_task_count, tokens_used_today)
WHERE current_task_count > 0 OR tokens_used_today > 0;

-- Add index for cooldown recovery query
CREATE INDEX IF NOT EXISTS idx_agents_cooldown_recovery
ON agents (shift_state, status)
WHERE shift_state = 'cooldown' AND status = 'active';
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/075_budget_reset_job.sql 2>&1
```

Note: If the migrations path isn't mounted, copy first:

```bash
docker cp /mnt/archie_brain/database/migrations/075_budget_reset_job.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/075_budget_reset_job.sql
```

Expected: `INSERT`, `UPDATE`, `CREATE INDEX` messages, no errors.

- [ ] **Step 3: Verify all agents have budget rows**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT COUNT(*) AS agents_without_budget
FROM agents a
LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
WHERE ab.id IS NULL AND a.status = 'active';
"
```

Expected: `agents_without_budget = 0`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add database/migrations/075_budget_reset_job.sql
git commit -m "db(migration-075): ensure agent_budgets defaults for budget reset

All active agents get a budget row. token_reset_at never null.
Indexes for budget reset and cooldown recovery queries."
```

---

### Task 6: Deploy and verify end-to-end

**Files:** None (deployment + verification only)

- [ ] **Step 1: Rebuild and restart the container**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
```

Wait 15 seconds for startup.

- [ ] **Step 2: Check logs for JobService startup**

```bash
docker logs --since=60s archie_platform 2>&1 | grep -i 'jobservice\|budget\|job_service'
```

Expected: `[Startup] JobService initialized with budget reset jobs`

- [ ] **Step 3: Manually trigger budget_reset to verify**

```bash
docker exec archie_platform python -c "
from app import app
with app.app_context():
    svc = app.config.get('JOB_SERVICE')
    if svc:
        print('budget_reset:', svc.run_job('budget_reset'))
        print('cooldown_recovery:', svc.run_job('cooldown_recovery'))
    else:
        print('ERROR: JOB_SERVICE not in app config')
"
```

Expected: Both jobs return `status: success`

- [ ] **Step 4: Verify agents are available for embedding**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT a.name, a.shift_state, ab.current_task_count, ab.task_queue_limit
FROM agents a
JOIN agent_budgets ab ON a.id = ab.agent_id
WHERE a.department = 'Analytics & Intelligence'
ORDER BY a.name;
"
```

Expected: At least some agents showing `shift_state = 'active'` and `current_task_count = 0`

- [ ] **Step 5: Check the autonomy_loop_log for job_service entries**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT job_name, status, items_processed, duration_ms, created_at
FROM autonomy_loop_log
WHERE job_name IN ('budget_reset', 'cooldown_recovery')
ORDER BY created_at DESC LIMIT 5;
"
```

Expected: Rows showing the manual triggers from step 3.

- [ ] **Step 6: Wait for next embedding batch cycle (or trigger manually)**

The embedding batch runs every 4 hours. To test immediately:

```bash
docker exec archie_platform python -c "
from app import app
with app.app_context():
    loop = app.config.get('AGENT_LOOP')
    if loop:
        loop._consciousness_embedding_batch()
        print('Embedding batch triggered')
    else:
        print('ERROR: AGENT_LOOP not in app config')
"
```

Then check logs:

```bash
docker logs --since=60s archie_platform 2>&1 | grep -i 'embedding\|consciousness.*batch'
```

Expected: No more "All agents blocked" — the batch should process or at least find available agents.

- [ ] **Step 7: Commit verification notes**

No code changes. Log the verification:

```bash
cd /mnt/archie_brain
git add -A
git status
# Only commit if there are changes (there shouldn't be code changes here)
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Budget reset functions in agent_service | agent_service.py + tests | 1 |
| 2 | job_service.py — central job registry | job_service.py + tests | 1 |
| 3 | Budget jobs registration module | budget_jobs.py + tests | 1 |
| 4 | Wire into app.py startup | app.py | 1 |
| 5 | Database migration | 075_budget_reset_job.sql | 1 |
| 6 | Deploy + verify end-to-end | None | 0 |

**Total: 5 commits, 6 new files, 1 modified file, 1 migration**

After Phase 1 is complete:
- Budget resets happen daily (04:00 UTC)
- Cooldown agents recover automatically when budgets clear
- Embedding pipeline has available agents
- job_service is ready for Phase 2+ to register more jobs
- Existing agent_loop.py is untouched — zero risk of breaking running jobs
