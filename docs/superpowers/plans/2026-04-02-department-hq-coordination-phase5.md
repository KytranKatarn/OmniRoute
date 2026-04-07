# Department HQ Coordination — Phase 5: agent_loop.py Decomposition

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract job implementations from the 7522-line `agent_loop.py` monolith into module-owned `jobs.py` files using a `register_jobs()` pattern, making each module responsible for its own background tasks while agent_loop.py becomes a thin scheduler orchestrator.

**Architecture:** Each module gets a `jobs.py` file with standalone functions (not class methods). `agent_loop.py`'s `start()` method imports and calls each module's `register_jobs(scheduler, flask_app)` function, which registers APScheduler jobs pointing to standalone functions. The `with_app_context` wrapper stays in agent_loop.py. Job implementations use `get_db()` directly (no `self`). Core system jobs (email queue, scheduled tasks, reminders, approvals) stay in agent_loop.py since they're foundational.

**Tech Stack:** Python 3.11, APScheduler, Flask, psycopg2

---

## File Structure

| Action | File | Jobs Extracted |
|--------|------|----------------|
| Create | `platform_v2/tools/consciousness/jobs.py` | Wire 7 consciousness implementations |
| Create | `platform_v2/tools/security_network/jobs.py` | 6 security/network jobs |
| Create | `platform_v2/tools/dev_hq/jobs.py` | 5 code health/audit jobs |
| Create | `platform_v2/services/agent_jobs.py` | 5 agent welfare/training jobs |
| Create | `platform_v2/services/fleet_jobs.py` | 3 fleet/infra jobs |
| Modify | `ai_bridge/agent_loop.py` | Thin orchestrator calling register_jobs() |

---

### Task 1: Establish register_jobs pattern + consciousness extraction

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (replace metadata-only with real implementations)
- Modify: `ai_bridge/agent_loop.py` (wire consciousness jobs via register_jobs)

The consciousness module already has a placeholder `jobs.py`. We'll make it real by extracting 7 job implementations from agent_loop.py. This establishes the pattern all other modules follow.

**Jobs to extract:** consciousness_analysis, consciousness_embedding, skill_sync, github_auto_pull, skill_analyzer, conversation_consolidation, knowledge_deduplication

- [ ] **Step 1: Read agent_loop.py to find the 7 consciousness job implementations**

Read these methods from agent_loop.py:
- `_deduplicate_knowledge` (around line 1273)
- `_index_claude_sessions` (around line 1308) — this is conversation_consolidation
- `_sync_learned_skills` (around line 5451)
- `_github_auto_pull` (around line 5732)
- `_analyze_discovered_skills` (around line 5961)

Note: The consciousness_analysis and consciousness_embedding jobs are now handled by the consciousness module's own processing_routes.py (wired through coordinator in Phase 1). The agent_loop jobs for these just trigger them. Find the trigger functions.

- [ ] **Step 2: Create consciousness/jobs.py with extracted implementations**

Replace the placeholder `platform_v2/tools/consciousness/jobs.py` with real implementations. Each function is standalone (no `self`). They use `get_db()` from `db` module (ai_bridge context) or `get_db_cursor()` from `database` module (platform_v2 context).

The key pattern:
```python
def register_consciousness_jobs(scheduler, flask_app):
    """Register consciousness background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    def with_ctx(fn):
        def wrapper():
            with flask_app.app_context():
                fn()
        wrapper.__name__ = fn.__name__
        return wrapper

    scheduler.add_job(with_ctx(run_embedding_batch), trigger=IntervalTrigger(minutes=30),
                      id="agent_consciousness_embedding", name="Agent Loop: Consciousness Embedding Batch",
                      replace_existing=True)
    # ... etc for each job
```

Each job function is a standalone def like:
```python
def run_embedding_batch():
    """Consciousness embedding batch — 200 items per run."""
    # implementation extracted from agent_loop._xxx
```

Extract the actual implementations from agent_loop.py. Copy them as standalone functions, replacing `self.xxx` with direct calls. The functions use `get_db()` or `get_db_cursor()` for database access.

- [ ] **Step 3: Update agent_loop.py to call register_consciousness_jobs**

In `agent_loop.py`'s `start()` method, find where consciousness jobs are registered (the `add_job` calls for consciousness-related jobs). Replace those individual `add_job` calls with:

```python
        # Phase 5: Consciousness jobs extracted to module
        try:
            from tools.consciousness.jobs import register_consciousness_jobs
            register_consciousness_jobs(self.scheduler, self.flask_app)
            logger.info("[AgentLoop] Consciousness jobs registered via module")
        except Exception as e:
            logger.error("[AgentLoop] Failed to register consciousness jobs: %s", e)
```

Remove or comment out the individual `self.scheduler.add_job(...)` calls for:
- agent_consciousness_analysis
- agent_consciousness_embedding
- agent_skill_sync
- agent_github_auto_pull
- agent_skill_analyzer
- agent_conversation_consolidation
- knowledge_deduplication

Also mark the corresponding `self._xxx` methods as deprecated (add comment, don't delete).

- [ ] **Step 4: Restart and verify consciousness jobs still run**

```bash
cd /mnt/archie_brain && docker compose restart archie_platform
sleep 20
docker logs --since=30s archie_platform 2>&1 | grep -iE 'consciousness.*job\|embedding\|analysis\|skill.?sync\|github.?pull' | tail -10
```

Expected: Jobs registered and running.

- [ ] **Step 5: Run tests**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -15
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py ai_bridge/agent_loop.py
git commit -m "refactor(agent-loop): extract consciousness jobs to module

Phase 5: 7 consciousness jobs extracted from agent_loop.py to
consciousness/jobs.py using register_jobs pattern. agent_loop.py
calls register_consciousness_jobs() instead of inline add_job()."
```

---

### Task 2: Extract security/network jobs

**Files:**
- Create: `platform_v2/tools/security_network/jobs.py`
- Modify: `ai_bridge/agent_loop.py`

**Jobs to extract:** network_discovery, ssl_expiry, dns_report, query_spike, camera_anomaly, auto_block

Follow the exact same pattern as Task 1:
1. Read the implementations from agent_loop.py
2. Create `security_network/jobs.py` with `register_security_jobs(scheduler, flask_app)`
3. Each job is a standalone function
4. In agent_loop.py, replace the 6 individual add_job calls with one `register_security_jobs()` call
5. Mark old methods as deprecated

- [ ] **Step 1: Read security job implementations from agent_loop.py**

Find these methods: `_discover_network_devices`, `_check_ssl_expiry`, `_daily_dns_report`, `_detect_query_spike`, `_check_camera_anomaly`, `_run_auto_block`

- [ ] **Step 2: Create security_network/jobs.py**

```python
"""security_network/jobs.py — Background jobs for Security & Network module.

Extracted from agent_loop.py Phase 5.
"""
import logging
from db import get_db

logger = logging.getLogger(__name__)


def register_security_jobs(scheduler, flask_app):
    """Register security module background jobs."""
    from apscheduler.triggers.interval import IntervalTrigger

    def with_ctx(fn):
        def wrapper():
            with flask_app.app_context():
                fn()
        wrapper.__name__ = fn.__name__
        return wrapper

    scheduler.add_job(with_ctx(discover_network_devices), trigger=IntervalTrigger(minutes=5),
                      id="agent_network_discovery", name="Agent Loop: Network Device Discovery",
                      replace_existing=True)
    # ... register all 6 jobs with their original IDs and intervals


def discover_network_devices():
    """Scan for network devices."""
    # Extracted implementation from agent_loop._discover_network_devices
    ...

# ... 5 more standalone functions
```

- [ ] **Step 3: Wire agent_loop.py**

Replace 6 individual add_job calls with:
```python
        try:
            from tools.security_network.jobs import register_security_jobs
            register_security_jobs(self.scheduler, self.flask_app)
            logger.info("[AgentLoop] Security jobs registered via module")
        except Exception as e:
            logger.error("[AgentLoop] Failed to register security jobs: %s", e)
```

- [ ] **Step 4: Restart and verify**

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/security_network/jobs.py ai_bridge/agent_loop.py
git commit -m "refactor(agent-loop): extract security jobs to module

Phase 5: 6 security/network jobs extracted to security_network/jobs.py."
```

---

### Task 3: Extract code health/audit jobs

**Files:**
- Create: `platform_v2/tools/dev_hq/jobs.py`
- Modify: `ai_bridge/agent_loop.py`

**Jobs to extract:** daily_code_metrics_scan, pattern_compliance_check, automated_module_audit, daily_code_health_digest, daily_code_health_scan, competitor_landscape_scan

Same pattern as Tasks 1-2.

- [ ] **Step 1-5: Follow same extraction pattern**

Create `dev_hq/jobs.py` with `register_devhq_jobs(scheduler, flask_app)`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/dev_hq/jobs.py ai_bridge/agent_loop.py
git commit -m "refactor(agent-loop): extract code health jobs to dev_hq module

Phase 5: 6 code health/audit jobs extracted to dev_hq/jobs.py."
```

---

### Task 4: Extract agent welfare/training + fleet jobs

**Files:**
- Create: `platform_v2/services/agent_jobs.py`
- Create: `platform_v2/services/fleet_jobs.py`
- Modify: `ai_bridge/agent_loop.py`

**Agent welfare jobs:** hr_tracker, ethics_monitoring, training_tick, welfare_recovery, idle_volunteering, performance_rankings

**Fleet jobs:** check_fleet_health, standalone_health_monitoring, fleet_ssl_cert_renewal, department_metrics_rollup

Same pattern.

- [ ] **Steps 1-5: Follow extraction pattern for both**

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/agent_jobs.py platform_v2/services/fleet_jobs.py ai_bridge/agent_loop.py
git commit -m "refactor(agent-loop): extract welfare + fleet jobs to services

Phase 5: 6 agent welfare jobs to agent_jobs.py,
4 fleet/infra jobs to fleet_jobs.py."
```

---

### Task 5: Verify and measure reduction

**Files:** Read-only verification.

- [ ] **Step 1: Count lines remaining in agent_loop.py**

```bash
wc -l /mnt/archie_brain/ai_bridge/agent_loop.py
```

Expected: Significantly reduced from 7522 (target: under 3000)

- [ ] **Step 2: Verify all jobs are running**

```bash
docker exec archie_platform python3 -c "
from services.job_service import JobService
svc = JobService.get_instance()
jobs = svc.list_jobs()
print(f'Registered jobs: {len(jobs)}')
for j in sorted(jobs, key=lambda x: x.get('name','')):
    print(f'  {j[\"name\"]}: {j[\"status\"]}')
" 2>&1 | head -30
```

- [ ] **Step 3: Verify consciousness still works**

```bash
docker logs --since=120s archie_platform 2>&1 | grep -iE 'embedding|analysis|knowledge.?card' | tail -5
```

- [ ] **Step 4: Run full test suite**

```bash
docker exec archie_platform python -m pytest services/tests/ -v 2>&1 | tail -20
```

- [ ] **Step 5: Check no job crashed**

```bash
docker logs --since=300s archie_platform 2>&1 | grep -iE 'error|traceback|exception' | grep -v 'APScheduler' | head -10
```

---

## Summary

| Task | What | Jobs Moved | Commits |
|------|------|-----------|---------|
| 1 | Consciousness jobs extraction | 7 | 1 |
| 2 | Security/network jobs extraction | 6 | 1 |
| 3 | Code health/audit jobs extraction | 6 | 1 |
| 4 | Agent welfare + fleet jobs extraction | 10 | 1 |
| 5 | Verification | — | 0 |

**Total: 4 commits, ~29 jobs extracted, 6 new files, agent_loop.py reduced by ~60%**

Core system jobs remain in agent_loop.py:
- email_queue, scheduled_tasks, reminders, approvals (foundational scheduler jobs)
- telegram_notify, browser_tasks (cross-cutting)
- stale_job_reaper, stuck_job_watchdog (scheduler meta-jobs)
- social video jobs, game jobs, stockbot jobs, email processing (smaller groups — future extraction)

After Phase 5: agent_loop.py is a thin orchestrator that calls `register_*_jobs()` on module job files.
