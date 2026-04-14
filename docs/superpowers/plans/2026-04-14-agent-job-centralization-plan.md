# Agent & Job Centralization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize all agent management, job scheduling, and LLM lifecycle under Department HQ as the single source of truth — eliminating scattered registrations, fixing 227 failed jobs/day, and reducing RAM from 107GB to within the 102GB budget.

**Architecture:** Department HQ Roster Tab owns agent identity + model assignment. Department HQ Jobs registry owns all scheduled jobs organized by department. C.R.E.E.D. owns runtime welfare/behavioral data. Dispatcher checks both Roster (qualified?) and C.R.E.E.D. (healthy?) before assigning work. C.R.E.E.D. standalone shows live governance data publicly.

**Tech Stack:** Python/Flask, PostgreSQL, APScheduler, Ollama API, Jinja2/LCARS UI

**Spec:** `docs/superpowers/specs/2026-04-14-agent-job-centralization-design.md`
**Project:** #261 (LLM Resource Management)
**Decision:** ADR #440

---

## File Map

### Files to Modify

| File | Responsibility | Phase |
|------|---------------|-------|
| `docker-compose.yml` | OLLAMA_KEEP_ALIVE 24h → 5m | 1A |
| `ai_bridge/agent_loop.py` | Remove job registrations, keep scheduler init only | 2D |
| `platform_v2/tools/security_network/jobs.py` | Disable broken jobs; later remove register_security_jobs | 1B, 2D |
| `platform_v2/tools/department_hq/jobs.py` | Expand to be single job registry for all departments | 2A |
| `platform_v2/tools/department_hq/dispatch_routes.py` | Add job monitoring API endpoints | 2C |
| `platform_v2/tools/department_hq/roster_routes.py` | Add Modelfile sync, public-roster endpoint | 3A, 3D |
| `platform_v2/services/agent_service.py` | Add Modelfile export on system_prompt save | 3A |
| `platform_v2/tools/department_hq/templates/department_hq.html` | Job monitoring UI, C.R.E.E.D. badges | 2C, 3C |

### Files to Create

| File | Responsibility | Phase |
|------|---------------|-------|
| `database/migrations/XXX_add_department_to_loop_log.sql` | Add department column to autonomy_loop_log | 2B |
| `database/migrations/XXX_agent_welfare_alerts.sql` | Create welfare alerts + workload history tables | 4A |
| `platform_v2/tools/department_hq/services/job_registry.py` | Job metadata registry — maps job_name → department, agent, description | 2A |
| `platform_v2/tools/department_hq/services/modelfile_sync.py` | DB system_prompt → Ollama Modelfile export | 3A |
| `platform_v2/tools/department_hq/creed_routes.py` | /api/creed/public-stats endpoint | 4A |
| `platform_v2/services/ram_budget.py` | Model load/unload with RAM budget enforcement | 5A |

---

## Phase 1: Immediate Relief (Task #1900-1902)

### Task 1: Reduce Ollama KEEP_ALIVE (Task #1900)

**Files:**
- Modify: `docker-compose.yml` — OLLAMA_KEEP_ALIVE line

- [ ] **Step 1: Read current docker-compose.yml Ollama config**

Find the `OLLAMA_KEEP_ALIVE=24h` line in the Ollama service environment.

- [ ] **Step 2: Change KEEP_ALIVE to 5m**

```yaml
- OLLAMA_KEEP_ALIVE=5m
```

- [ ] **Step 3: Restart Ollama**

```bash
sudo systemctl restart ollama
```

Note: Ollama runs on the HOST, not in Docker. The env var is set via systemd override or /etc/environment.
Check: `systemctl show ollama --property=Environment` to find where it's configured.
If set in systemd: edit the override file. If in docker-compose: it's for the platform container's reference only.

- [ ] **Step 4: Verify models unload after 5 minutes idle**

```bash
# Check loaded models
curl -s http://192.168.1.200:11434/api/ps | python3 -m json.tool
# Wait 6 minutes, check again — idle models should be gone
```

- [ ] **Step 5: Verify RAM drops**

```bash
free -h
# Expected: used RAM should drop from ~105GB toward ~60-70GB as idle models unload
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "perf: reduce Ollama KEEP_ALIVE from 24h to 5m — immediate RAM relief"
```

---

### Task 2: Disable Broken Jobs (Task #1901)

**Files:**
- Modify: `platform_v2/tools/security_network/jobs.py:1867-1874` — track_device_presence
- Modify: `ai_bridge/agent_loop.py` — email_inbox, health_probe (if found)

- [ ] **Step 1: Identify the 3 broken jobs in code**

The failing jobs from autonomy_loop_log:
- `track_device_presence` — 120 fails/day, returning 0. Located in `security_network/jobs.py:1223` (function) and `:1867` (registration)
- `health_probe` — 77 fails/day, "No module named tools.dev_hq". Find with: `grep -rn "health_probe" platform_v2/`
- `email_inbox` — 25 fails/day. Located in `ai_bridge/agent_loop.py:479` (`_check_email_inbox`)

- [ ] **Step 2: Comment out track_device_presence registration**

In `platform_v2/tools/security_network/jobs.py`, comment out the registration block at line ~1867:

```python
    # --- Device presence & ARP spoof detection --- DISABLED: 120 fails/day, needs rework
    # scheduler.add_job(
    #     with_ctx(track_device_presence),
    #     trigger=IntervalTrigger(minutes=5),
    #     id="agent_device_presence",
    #     name="Agent Loop: Device Presence & ARP Spoof Detection",
    #     replace_existing=True,
    # )
```

- [ ] **Step 3: Comment out email_inbox registration**

In `ai_bridge/agent_loop.py`, comment out the email inbox check at line ~479:

```python
        # DISABLED: 25 fails/day, old email integration code
        # self.scheduler.add_job(
        #     with_app_context(self._check_email_inbox),
        #     trigger=IntervalTrigger(minutes=5),
        #     id="agent_email_inbox",
        #     name="Agent Loop: Email Inbox Check",
        #     replace_existing=True,
        # )
```

- [ ] **Step 4: Find and disable health_probe**

Search all jobs files for health_probe registration. Comment it out with note about the import error.

- [ ] **Step 5: Deploy and verify**

```bash
docker compose restart archie_platform
# Wait 5 minutes, then check:
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute(\"\"\"SELECT job_name, COUNT(*) FROM autonomy_loop_log
                   WHERE status = 'error' AND created_at > NOW() - INTERVAL '10 minutes'
                   GROUP BY job_name\"\"\")
    print([dict(r) for r in cur.fetchall()])
"
# Expected: no errors for disabled jobs
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/security_network/jobs.py ai_bridge/agent_loop.py
git commit -m "fix: disable 3 broken jobs — 227 failed runs/day eliminated"
```

---

### Task 3: Quick Roster Audit (Task #1902)

**Files:** No code changes — research task

- [ ] **Step 1: Query agents with zero dispatches**

```bash
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute(\"\"\"
        SELECT a.id, a.name, a.display_name, a.department, a.shift_state,
               a.worker_type, a.acronym, a.model,
               (SELECT COUNT(*) FROM bridge_jobs bj WHERE bj.agent_name = a.name
                AND bj.created_at > NOW() - INTERVAL '30 days') as recent_dispatches
        FROM agents a
        ORDER BY recent_dispatches ASC, a.name
    \"\"\")
    for r in cur.fetchall():
        marker = 'ACRONYM' if r['acronym'] else 'human'
        print(f'{r[\"id\"]:4d} {r[\"name\"]:25s} {r[\"department\"]:20s} {r[\"shift_state\"]:12s} {marker:8s} dispatches={r[\"recent_dispatches\"]}')
"
```

- [ ] **Step 2: Identify removal candidates**

Apply rules:
- KEEP: any agent with `acronym` field set (branded agents)
- KEEP: agents named like "Human Lawyer", "Human Doctor"
- KEEP: any agent with dispatches > 0 in last 30 days
- REMOVE CANDIDATE: human agents with 0 dispatches, no acronym

- [ ] **Step 3: Report findings to user**

Present the list: "X agents identified for removal, Y acronym agents kept, Z active agents kept. Here are the removal candidates: ..."

Do NOT delete without user approval. This is research only.

---

## Phase 2: Job Centralization (Tasks #1903-1906)

### Task 4: Create Department Job Registry (Task #1903)

**Files:**
- Create: `platform_v2/tools/department_hq/services/job_registry.py`
- Modify: `platform_v2/tools/department_hq/jobs.py`

- [ ] **Step 1: Create job_registry.py — metadata mapping**

```python
"""Department Job Registry — maps every job to its department and metadata.

Single source of truth for which department owns which job.
Used by: jobs.py (registration), dispatch_routes.py (monitoring UI),
         autonomy_loop_log (department column).
"""

# Each entry: job_id -> {department, director, description, interval, source_module}
JOB_REGISTRY = {
    # === BRIDGE (A.R.C.H.I.E.) ===
    "agent_approvals": {
        "department": "BRIDGE",
        "director": "A.R.C.H.I.E.",
        "description": "Process approval queue",
        "interval": "60s",
        "source": "ai_bridge.agent_loop",
        "function": "_process_approval_queue",
    },
    "agent_briefings": {
        "department": "BRIDGE",
        "director": "A.R.C.H.I.E.",
        "description": "Generate daily briefings",
        "interval": "5m",
        "source": "ai_bridge.agent_loop",
        "function": "_generate_briefings",
    },
    "agent_anomaly_detection": {
        "department": "BRIDGE",
        "director": "A.R.C.H.I.E.",
        "description": "Platform anomaly detection",
        "interval": "5m",
        "source": "ai_bridge.agent_loop",
        "function": "_check_anomalies",
    },

    # === OPERATIONS (B.A.S.E.) ===
    "agent_stale_job_reaper": {
        "department": "OPERATIONS",
        "director": "B.A.S.E.",
        "description": "Clean up stale jobs",
        "interval": "2m",
        "source": "ai_bridge.agent_loop",
        "function": "_reap_stale_jobs",
    },
    "agent_stuck_job_watchdog": {
        "department": "OPERATIONS",
        "director": "B.A.S.E.",
        "description": "Detect and recover stuck jobs",
        "interval": "5m",
        "source": "ai_bridge.agent_loop",
        "function": "_reap_stuck_jobs",
    },
    "ddns_ip_monitor": {
        "department": "OPERATIONS",
        "director": "B.A.S.E.",
        "description": "Monitor public IP for DDNS",
        "interval": "15m",
        "source": "ai_bridge.agent_loop",
        "function": "_check_ddns",
    },

    # === ENGINEERING (F.O.R.G.E.) ===
    "agent_proactive_scan": {
        "department": "ENGINEERING",
        "director": "F.O.R.G.E.",
        "description": "Proactive code quality scanning",
        "interval": "6h",
        "source": "ai_bridge.agent_loop",
        "function": "_run_proactive_scan",
    },
    "dependency_audit": {
        "department": "ENGINEERING",
        "director": "F.O.R.G.E.",
        "description": "Dependency CVE audit",
        "interval": "6h",
        "source": "ai_bridge.agent_loop",
        "function": "_run_dependency_audit",
    },
    "qa_scheduled_run": {
        "department": "ENGINEERING",
        "director": "F.O.R.G.E.",
        "description": "P.R.O.B.E. QA scheduled run",
        "interval": "6h",
        "source": "ai_bridge.agent_loop",
        "function": "_run_qa_scheduled",
    },

    # === SECURITY (V.I.G.I.L.) ===
    "agent_network_discovery": {
        "department": "SECURITY",
        "director": "V.I.G.I.L.",
        "description": "Network device discovery",
        "interval": "5m",
        "source": "security_network.jobs",
        "function": "discover_network_devices",
    },
    "agent_traffic_stats": {
        "department": "SECURITY",
        "director": "V.I.G.I.L.",
        "description": "ntopng traffic collection",
        "interval": "5m",
        "source": "security_network.jobs",
        "function": "collect_traffic_stats",
    },
    "agent_dns_history": {
        "department": "SECURITY",
        "director": "V.I.G.I.L.",
        "description": "DNS history collection",
        "interval": "5m",
        "source": "security_network.jobs",
        "function": "collect_dns_history",
    },
    "agent_compliance_scan": {
        "department": "SECURITY",
        "director": "V.I.G.I.L.",
        "description": "Compliance scanning (STIG/CIS/HIPAA)",
        "interval": "6h",
        "source": "security_network.jobs",
        "function": "run_scheduled_compliance_scan",
    },
    "agent_auto_block": {
        "department": "SECURITY",
        "director": "V.I.G.I.L.",
        "description": "Auto-block malicious IPs",
        "interval": "15m",
        "source": "security_network.jobs",
        "function": "run_auto_block",
    },
    "agent_ssl_expiry_check": {
        "department": "SECURITY",
        "director": "V.I.G.I.L.",
        "description": "SSL certificate expiry monitoring",
        "interval": "24h",
        "source": "security_network.jobs",
        "function": "check_ssl_expiry",
    },

    # === DOCUMENTATION (C.O.D.E.X.) ===
    "knowledge_auto_link": {
        "department": "DOCUMENTATION",
        "director": "C.O.D.E.X.",
        "description": "Knowledge base cross-linking",
        "interval": "5m",
        "source": "consciousness.jobs",
        "function": "run_knowledge_auto_link",
    },

    # === SERVICES (R.E.S.O.L.V.E.) ===
    "agent_email_queue": {
        "department": "SERVICES",
        "director": "R.E.S.O.L.V.E.",
        "description": "Outbound email processing",
        "interval": "60s",
        "source": "ai_bridge.agent_loop",
        "function": "_process_email_queue",
    },
    "agent_telegram_notify": {
        "department": "SERVICES",
        "director": "R.E.S.O.L.V.E.",
        "description": "Telegram notification forwarding",
        "interval": "15s",
        "source": "ai_bridge.agent_loop",
        "function": "_forward_notifications_to_telegram",
    },

    # === HR (K.I.N.) ===
    "crew_wellness_tick": {
        "department": "HR",
        "director": "K.I.N.",
        "description": "Agent welfare threshold checks",
        "interval": "5m",
        "source": "department_hq.jobs",
        "function": "crew_wellness_tick",
    },
    "hr_tracker": {
        "department": "HR",
        "director": "K.I.N.",
        "description": "Agent shift and workload tracking",
        "interval": "5m",
        "source": "department_hq.jobs",
        "function": "hr_tracker",
    },
    "idle_volunteering": {
        "department": "HR",
        "director": "K.I.N.",
        "description": "Idle agent task pickup",
        "interval": "15m",
        "source": "department_hq.jobs",
        "function": "idle_volunteering",
    },
    "ethics_monitoring": {
        "department": "HR",
        "director": "K.I.N.",
        "description": "C.R.E.E.D. ethics compliance monitoring",
        "interval": "15m",
        "source": "department_hq.jobs",
        "function": "ethics_monitoring",
    },
    "training_tick": {
        "department": "HR",
        "director": "K.I.N.",
        "description": "Agent training progression",
        "interval": "5m",
        "source": "department_hq.jobs",
        "function": "training_tick",
    },
}


def get_department_for_job(job_name):
    """Look up department for a job name."""
    entry = JOB_REGISTRY.get(job_name)
    return entry["department"] if entry else "UNKNOWN"


def get_jobs_by_department(department=None):
    """Get all jobs, optionally filtered by department."""
    if department:
        return {k: v for k, v in JOB_REGISTRY.items() if v["department"] == department}
    return JOB_REGISTRY
```

- [ ] **Step 2: Update department_hq/jobs.py to use registry**

Read current `department_hq/jobs.py` (653 lines). Refactor `register_department_hq_jobs()` to iterate the registry and register all jobs from all departments. Import job functions from their source modules.

- [ ] **Step 3: Update _log_cycle to include department**

Every job logs to `autonomy_loop_log`. Update the log function to include `department` from the registry:

```python
from tools.department_hq.services.job_registry import get_department_for_job

def _log_cycle(job_name, status, items_processed=0, items_failed=0, duration_ms=0, details=None, error_message=None):
    department = get_department_for_job(job_name)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO autonomy_loop_log
               (job_name, status, items_processed, items_failed, duration_ms, details, error_message, department)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (job_name, status, items_processed, items_failed, duration_ms,
             Json(details) if details else None, error_message, department)
        )
```

- [ ] **Step 4: Test registration**

```bash
docker compose restart archie_platform
# Verify jobs are running:
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute('SELECT job_name, department FROM autonomy_loop_log ORDER BY created_at DESC LIMIT 10')
    for r in cur.fetchall():
        print(r['job_name'], '|', r['department'])
"
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/department_hq/services/job_registry.py platform_v2/tools/department_hq/jobs.py
git commit -m "feat: centralized job registry — all jobs organized by department"
```

---

### Task 5: Add department column to autonomy_loop_log (Task #1904)

**Files:**
- Create: `database/migrations/XXX_add_department_to_loop_log.sql`

- [ ] **Step 1: Write migration**

```sql
-- Add department ownership to autonomy loop log
ALTER TABLE autonomy_loop_log ADD COLUMN IF NOT EXISTS department VARCHAR(50);

-- Index for department-based queries
CREATE INDEX IF NOT EXISTS idx_autonomy_loop_department ON autonomy_loop_log (department);

-- Backfill existing rows based on job_name patterns
UPDATE autonomy_loop_log SET department = 'SECURITY' WHERE department IS NULL AND job_name IN ('track_device_presence', 'collect_traffic_stats', 'collect_dns_history', 'network_discovery', 'ssl_expiry', 'auto_block', 'compliance_scan');
UPDATE autonomy_loop_log SET department = 'HR' WHERE department IS NULL AND job_name IN ('crew_wellness_tick', 'hr_tracker', 'idle_volunteering', 'ethics_monitoring', 'training_tick');
UPDATE autonomy_loop_log SET department = 'BRIDGE' WHERE department IS NULL AND job_name IN ('approvals', 'briefings', 'anomaly_detection');
UPDATE autonomy_loop_log SET department = 'OPERATIONS' WHERE department IS NULL AND job_name IN ('stale_job_reaper', 'stuck_job_watchdog', 'ddns_monitor');
UPDATE autonomy_loop_log SET department = 'ENGINEERING' WHERE department IS NULL AND job_name IN ('proactive_scan', 'dependency_audit', 'qa_scheduled');
UPDATE autonomy_loop_log SET department = 'DOCUMENTATION' WHERE department IS NULL AND job_name IN ('knowledge_auto_link', 'embedding_loop');
UPDATE autonomy_loop_log SET department = 'SERVICES' WHERE department IS NULL AND job_name IN ('email_queue', 'email_inbox', 'telegram_notify', 'email_analyze');
UPDATE autonomy_loop_log SET department = 'UNKNOWN' WHERE department IS NULL;
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /path/to/migration.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT department, COUNT(*) FROM autonomy_loop_log GROUP BY department ORDER BY count DESC"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/
git commit -m "feat: add department column to autonomy_loop_log with backfill"
```

---

### Task 6: Build Job Monitoring View in Department HQ UI (Task #1905)

**Files:**
- Modify: `platform_v2/tools/department_hq/dispatch_routes.py` — add API endpoints
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` — add Jobs section

- [ ] **Step 1: Add /api/jobs/by-department endpoint**

```python
@bp.route("/api/jobs/by-department")
@login_required
@admin_required
def jobs_by_department():
    from tools.department_hq.services.job_registry import JOB_REGISTRY
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        # Get failure counts and last run per job (last 24h)
        cur.execute("""
            SELECT job_name, department,
                   COUNT(*) FILTER (WHERE status = 'error') as fail_count,
                   COUNT(*) FILTER (WHERE status = 'success') as success_count,
                   MAX(created_at) as last_run,
                   MAX(error_message) FILTER (WHERE status = 'error') as last_error
            FROM autonomy_loop_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY job_name, department
        """)
        log_data = {r["job_name"]: dict(r) for r in cur.fetchall()}

    departments = {}
    for job_id, meta in JOB_REGISTRY.items():
        dept = meta["department"]
        if dept not in departments:
            departments[dept] = {"name": dept, "director": meta["director"], "jobs": [], "total_fails": 0}
        log = log_data.get(job_id, {})
        job_info = {
            "id": job_id,
            "description": meta["description"],
            "interval": meta["interval"],
            "fail_count": log.get("fail_count", 0),
            "success_count": log.get("success_count", 0),
            "last_run": log.get("last_run", "").isoformat() if log.get("last_run") else None,
            "last_error": log.get("last_error", ""),
        }
        departments[dept]["jobs"].append(job_info)
        departments[dept]["total_fails"] += job_info["fail_count"]

    return jsonify({"success": True, "departments": departments})
```

- [ ] **Step 2: Build UI section in Department HQ template**

Add a "Jobs" section/tab in the Department HQ dashboard showing jobs grouped by department. Each department card shows: director name, job count, failure count. Expandable to show individual jobs with status, last run, error message. Style with LCARS cards matching existing department_hq patterns.

- [ ] **Step 3: Test in browser**

Navigate to `http://192.168.1.200:3000/tools/department-hq` and verify the Jobs section loads with real data.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/dispatch_routes.py platform_v2/tools/department_hq/templates/department_hq.html
git commit -m "feat: job monitoring dashboard in Department HQ — jobs by department with failure tracking"
```

---

### Task 7: Remove Old Job Registration Points (Task #1906)

**Files:**
- Modify: `ai_bridge/agent_loop.py` — remove all add_job calls, keep scheduler init
- Modify: `platform_v2/tools/security_network/jobs.py` — remove register_security_jobs
- Modify: `platform_v2/tools/consciousness/jobs.py` — remove register_consciousness_jobs

- [ ] **Step 1: Verify all jobs are registered via department_hq/jobs.py**

Cross-reference: every job_id in the old files must exist in JOB_REGISTRY. List any gaps.

- [ ] **Step 2: Remove add_job calls from agent_loop.py**

Keep the scheduler initialization and the `with_app_context` wrapper. Remove all `self.scheduler.add_job(...)` blocks. Replace with a single call:

```python
from tools.department_hq.jobs import register_department_hq_jobs
register_department_hq_jobs(self.scheduler, flask_app)
```

- [ ] **Step 3: Remove register_security_jobs from security_network/jobs.py**

Keep the job FUNCTIONS (they're imported by the registry). Remove the `register_security_jobs()` function and its call site.

- [ ] **Step 4: Remove register calls from consciousness/jobs.py**

Same pattern — keep functions, remove registration.

- [ ] **Step 5: Test all jobs still fire**

```bash
docker compose restart archie_platform
# Wait 5 minutes
docker exec archie_platform python3 -c "
from database import get_db_cursor
with get_db_cursor() as (conn, cur):
    cur.execute('SELECT department, COUNT(*) FROM autonomy_loop_log WHERE created_at > NOW() - INTERVAL \'5 minutes\' GROUP BY department')
    for r in cur.fetchall():
        print(r['department'], r['count'])
"
# Expected: jobs firing across multiple departments
```

- [ ] **Step 6: Commit**

```bash
git add ai_bridge/agent_loop.py platform_v2/tools/security_network/jobs.py platform_v2/tools/consciousness/jobs.py
git commit -m "refactor: remove scattered job registrations — all jobs now via Department HQ registry"
```

---

## Phase 3: Roster Consolidation (Tasks #1907-1910)

### Task 8: Modelfile DB Sync (Task #1907)

**Files:**
- Create: `platform_v2/tools/department_hq/services/modelfile_sync.py`
- Modify: `platform_v2/services/agent_service.py` — call sync on system_prompt update

- [ ] **Step 1: Create modelfile_sync.py**

```python
"""Modelfile Sync — exports agent system_prompt from DB to Ollama Modelfile.

Called automatically when system_prompt is updated via Roster UI.
"""
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

MODELFILE_DIR = "/mnt/llm_drive/ollama"


def export_modelfile(agent_name, model_base, system_prompt):
    """Write a Modelfile and register it with Ollama.

    Args:
        agent_name: Agent code name (used as Modelfile suffix)
        model_base: Base model (e.g., 'mistral:7b')
        system_prompt: The agent's system prompt text
    """
    if not system_prompt or not model_base:
        logger.warning("Cannot export Modelfile for %s — missing model or prompt", agent_name)
        return False

    modelfile_path = os.path.join(MODELFILE_DIR, f"Modelfile.{agent_name}")
    content = f'FROM {model_base}\n\nSYSTEM """\n{system_prompt}\n"""\n'

    try:
        with open(modelfile_path, "w") as f:
            f.write(content)
        logger.info("Exported Modelfile for %s to %s", agent_name, modelfile_path)

        # Register with Ollama
        result = subprocess.run(
            ["ollama", "create", agent_name, "-f", modelfile_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            logger.info("Ollama registered model %s", agent_name)
            return True
        else:
            logger.error("Ollama create failed for %s: %s", agent_name, result.stderr)
            return False
    except Exception as e:
        logger.error("Modelfile export failed for %s: %s", agent_name, e)
        return False
```

- [ ] **Step 2: Hook into agent_service.py update_agent**

In `agent_service.py`, after a successful `system_prompt` update, call `export_modelfile()`.

- [ ] **Step 3: Test via Roster UI**

Update an agent's system_prompt in Roster Tab. Verify:
- Modelfile written to `/mnt/llm_drive/ollama/Modelfile.{name}`
- `ollama list` shows the agent-named model

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/department_hq/services/modelfile_sync.py platform_v2/services/agent_service.py
git commit -m "feat: Modelfile DB sync — system_prompt auto-exports to Ollama on save"
```

---

### Task 9: Roster Cleanup (Task #1908)

**Files:** Database changes only (via agent_service)

- [ ] **Step 1: Run the audit query from Task 3**

Get the list of removal candidates approved by user.

- [ ] **Step 2: Deactivate (not delete) unused agents**

```python
# Set shift_state to 'decommissioned' rather than hard delete
agent_service.update_agent(agent_id, {"shift_state": "decommissioned"})
```

- [ ] **Step 3: Validate remaining agents have required fields**

Query all active/barracked agents. Flag any missing: department, model, skills.

- [ ] **Step 4: Report final roster count**

Expected: ~60-70 total agents (was 131).

- [ ] **Step 5: Commit any code changes**

---

### Task 10: C.R.E.E.D. Wellness Badge (Task #1909)

**Files:**
- Modify: `platform_v2/tools/department_hq/roster_routes.py` — include welfare data
- Modify: `platform_v2/tools/department_hq/templates/department_hq.html` — badge rendering

- [ ] **Step 1: Add welfare data to roster API response**

Join `agent_emotional_state` in the roster query to include stress_level, mood_intensity, fatigue per agent. Compute badge color: green (all < 0.5), yellow (any > 0.5), red (any > 0.8).

- [ ] **Step 2: Render badge in Roster cards**

Small colored dot with tooltip showing stress/mood/fatigue values.

- [ ] **Step 3: Test in browser**

- [ ] **Step 4: Commit**

---

### Task 11: Public Roster Endpoint (Task #1910)

**Files:**
- Modify: `platform_v2/tools/department_hq/roster_routes.py`

- [ ] **Step 1: Add /api/agents/public-roster endpoint**

```python
@bp.route("/api/agents/public-roster")
def public_roster():
    """Public read-only agent roster for website and C.R.E.E.D. standalone."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT display_name, title, department, acronym, acronym_expansion,
                   avatar_url, bio, is_department_ai, floor
            FROM agents
            WHERE shift_state NOT IN ('decommissioned', 'off_duty')
            AND acronym IS NOT NULL
            ORDER BY floor, department, display_name
        """)
        agents = [dict(r) for r in cur.fetchall()]
    return jsonify({"success": True, "agents": agents, "total": len(agents)})
```

No auth required — public data only (no IDs, no internal fields).

- [ ] **Step 2: Test endpoint**

```bash
curl http://192.168.1.200:3000/api/agents/public-roster | python3 -m json.tool | head -20
```

- [ ] **Step 3: Commit**

---

## Phase 4: C.R.E.E.D. Live Dashboard (Tasks #1911-1912)

### Task 12: Public Stats Endpoint (Task #1911)

**Files:**
- Create: `platform_v2/tools/department_hq/creed_routes.py`
- Modify: `platform_v2/tools/department_hq/__init__.py` — register routes

- [ ] **Step 1: Create creed_routes.py**

Build `/api/creed/public-stats` endpoint returning:
- Agent counts by shift_state
- Aggregate welfare stats by department (avg stress, avg fatigue)
- Job health: success/failure counts by department (last 24h)
- Ethics compliance score (platform-wide)
- Workload distribution across departments

Cache response for 5 minutes. No auth required.

- [ ] **Step 2: Register routes in __init__.py**

- [ ] **Step 3: Test endpoint**

- [ ] **Step 4: Commit**

---

### Task 13: C.R.E.E.D. Standalone Live Dashboard (Task #1912)

**Files:**
- Modify: `kytran-creed/` standalone application

- [ ] **Step 1: Add platform API polling**

Fetch from `http://192.168.1.200:3000/api/creed/public-stats` every 5 minutes. Cache locally.

- [ ] **Step 2: Build welfare dashboard section**

Show department-by-department health: agent count, avg stress, avg fatigue, job success rate.

- [ ] **Step 3: Build ethics compliance score display**

Large grade display (A+ to F) with breakdown.

- [ ] **Step 4: Build job health visualization**

Success vs failure rates by department. Trend over last 7 days.

- [ ] **Step 5: Deploy and verify**

```bash
cd /mnt/archie_brain/kytran-creed && docker compose restart
# Verify at http://192.168.1.200:8086
```

- [ ] **Step 6: Commit**

---

## Phase 5: LLM Lifecycle + Academy (Tasks #1913-1914)

### Task 14: RAM Budget Enforcer (Task #1913)

**Files:**
- Create: `platform_v2/services/ram_budget.py`
- Modify: `platform_v2/tools/department_hq/services/bridge_dispatcher.py` — integrate budget check

- [ ] **Step 1: Create ram_budget.py**

```python
"""RAM Budget Enforcer — manages model loading within the 80% memory budget.

Budget: 102GB for LLM models (80% of 128GB).
Always loaded: arctic-embed-cpu (embeddings).
Strategy: LRU eviction when budget exceeded.
"""
import urllib.request
import json
import logging

logger = logging.getLogger(__name__)

RAM_BUDGET_GB = 102
ALWAYS_LOADED = {"arctic-embed-cpu"}
OLLAMA_URL = "http://host.docker.internal:11434"


def get_loaded_models():
    """Get currently loaded models with their sizes."""
    resp = urllib.request.urlopen(f"{OLLAMA_URL}/api/ps")
    data = json.loads(resp.read())
    return data.get("models", [])


def get_total_loaded_gb():
    """Get total RAM used by loaded models in GB."""
    models = get_loaded_models()
    return sum(m.get("size", 0) / (1024**3) for m in models)


def can_load_model(model_size_gb):
    """Check if loading a model would exceed the budget."""
    current = get_total_loaded_gb()
    return (current + model_size_gb) <= RAM_BUDGET_GB


def evict_lru_model():
    """Evict the least-recently-used model (excluding always-loaded)."""
    models = get_loaded_models()
    # Sort by expires_at (earliest = least recently used)
    evictable = [m for m in models if m["name"].split(":")[0] not in ALWAYS_LOADED]
    if not evictable:
        return False
    evictable.sort(key=lambda m: m.get("expires_at", ""))
    target = evictable[0]
    logger.info("Evicting LRU model: %s (%.1fGB)", target["name"], target["size"] / (1024**3))
    # Unload by setting keep_alive to 0
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps({"model": target["name"], "keep_alive": 0}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req)
    return True


def ensure_budget_for(model_size_gb):
    """Ensure there's room in the budget, evicting if necessary."""
    while not can_load_model(model_size_gb):
        if not evict_lru_model():
            logger.error("Cannot free enough RAM for %.1fGB model", model_size_gb)
            return False
    return True
```

- [ ] **Step 2: Integrate into dispatcher ensure_model_ready()**

In `bridge_dispatcher.py`, before loading a model, call `ensure_budget_for()`.

- [ ] **Step 3: Test**

Load a large model, verify LRU eviction happens when budget exceeded.

- [ ] **Step 4: Commit**

---

### Task 15: Academy Benchmark → Roster Pipeline (Task #1914)

**Files:**
- Modify: `platform_v2/tools/agent_academy/` — benchmark result storage
- Modify: `platform_v2/services/agent_service.py` — model assignment update

- [ ] **Step 1: Add benchmark results table**

```sql
CREATE TABLE IF NOT EXISTS agent_benchmark_results (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id),
    model_name VARCHAR(100) NOT NULL,
    skill_category VARCHAR(50),
    score DECIMAL(5,2),
    response_time_ms INTEGER,
    quality_rating DECIMAL(3,2),
    benchmark_date TIMESTAMP DEFAULT NOW()
);
```

- [ ] **Step 2: Build benchmark → assignment pipeline**

After Academy runs benchmarks for a skill category, find the model with the highest average score. Update `agents.model` for all agents in that skill category.

- [ ] **Step 3: Add monthly re-evaluation job**

Register a monthly cron job in the ENGINEERING department that re-runs key benchmarks and updates assignments if results changed.

- [ ] **Step 4: Commit**

---

## Execution Order Summary

| Phase | Tasks | Priority | Effort | Dependencies |
|-------|-------|----------|--------|-------------|
| **1: Immediate Relief** | #1900, #1901, #1902 | P10 | Tiny-Small | None |
| **2: Job Centralization** | #1903, #1904, #1905, #1906 | P9-P8 | Medium-Large | Phase 1 |
| **3: Roster Consolidation** | #1907, #1908, #1909, #1910 | P8-P7 | Small-Medium | Phase 1 |
| **4: C.R.E.E.D. Dashboard** | #1911, #1912 | P7 | Medium-Large | Phase 3 |
| **5: LLM Lifecycle** | #1913, #1914 | P7-P6 | Medium-Large | Phase 2, 3 |

Phases 2 and 3 can run in parallel. Phases 4 and 5 depend on earlier phases.
