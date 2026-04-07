# C.O.D.E.X. Weekly Knowledge Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a weekly scheduled job that generates per-project knowledge digest reports via pure SQL aggregation, stored as vault_notes attributed to C.O.D.E.X.

**Architecture:** New `weekly_report_service.py` handles data aggregation + report formatting + storage. Consciousness job runs weekly (Sunday 03:00). Gap analysis updated to exclude weekly_report source_type.

**Tech Stack:** Python, PostgreSQL, psycopg2 (RealDictCursor via get_db_cursor).

**Spec:** `docs/superpowers/specs/2026-04-05-codex-weekly-report-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/services/weekly_report_service.py` | Report generation, cooldown check, data aggregation |
| Modify | `platform_v2/tools/consciousness/jobs.py` | Register weekly job + job function |
| Modify | `platform_v2/services/knowledge_link_service.py` | Exclude weekly_report from gap score |

---

### Task 1: Weekly Report Service

**Files:**
- Create: `platform_v2/services/weekly_report_service.py`

- [ ] **Step 1: Create the service file with constants and cooldown check**

Create `platform_v2/services/weekly_report_service.py`:

```python
"""weekly_report_service.py -- C.O.D.E.X. Weekly Knowledge Reports.

Generates per-project weekly digests via pure SQL aggregation.
Stores as vault_notes with source_type='weekly_report'.
No LLM dispatch needed — data-driven reports only.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

REPORT_SOURCE_TYPE = "weekly_report"
REPORT_QUALITY_SCORE = 0.65
COOLDOWN_DAYS = 6
REPORT_PERIOD_DAYS = 7


def check_cooldown(project_slug: str) -> bool:
    """Return True if a weekly report was generated for this project in the last 6 days."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT COUNT(*) as cnt FROM knowledge_base
                   WHERE source_type = %s
                   AND tags @> ARRAY[%s]
                   AND created_at > NOW() - INTERVAL '%s days'""",
                (REPORT_SOURCE_TYPE, project_slug, COOLDOWN_DAYS),
            )
            return cur.fetchone()["cnt"] > 0
    except Exception as e:
        logger.error("[WeeklyReport] Cooldown check failed: %s", e)
        return True  # Fail safe: skip if unsure
```

- [ ] **Step 2: Add the data aggregation function**

Append to the same file:

```python
def _gather_project_data(project_id: int, days: int = REPORT_PERIOD_DAYS) -> Dict:
    """Gather all weekly metrics for a project."""
    data = {
        "new_links": [],
        "decisions": [],
        "tasks_completed": [],
        "dispatches": [],
        "completeness": 0,
        "gaps": {},
    }

    try:
        with get_db_cursor() as (conn, cur):
            # New knowledge links this period (by type)
            cur.execute(
                """SELECT kb.knowledge_type, COUNT(*) as cnt
                   FROM project_knowledge_links pkl
                   JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                   WHERE pkl.project_id = %s
                   AND pkl.created_at > NOW() - INTERVAL '%s days'
                   GROUP BY kb.knowledge_type
                   ORDER BY cnt DESC""",
                (project_id, days),
            )
            data["new_links"] = [dict(row) for row in cur.fetchall()]

            # Decisions made this period
            cur.execute(
                """SELECT title FROM project_decisions
                   WHERE project_id = %s
                   AND created_at > NOW() - INTERVAL '%s days'
                   ORDER BY created_at DESC""",
                (project_id, days),
            )
            data["decisions"] = [row["title"] for row in cur.fetchall()]

            # Tasks completed this period
            cur.execute(
                """SELECT title FROM unified_tasks
                   WHERE project_id = %s AND status = 'completed'
                   AND updated_at > NOW() - INTERVAL '%s days'
                   ORDER BY updated_at DESC""",
                (project_id, days),
            )
            data["tasks_completed"] = [row["title"] for row in cur.fetchall()]

            # Agent dispatches this period
            cur.execute(
                """SELECT agent_name, COUNT(*) as cnt,
                          COUNT(*) FILTER (WHERE status = 'completed') as successes
                   FROM bridge_jobs
                   WHERE project_id = %s AND agent_name IS NOT NULL
                   AND created_at > NOW() - INTERVAL '%s days'
                   GROUP BY agent_name
                   ORDER BY cnt DESC""",
                (project_id, days),
            )
            data["dispatches"] = [dict(row) for row in cur.fetchall()]

    except Exception as e:
        logger.error("[WeeklyReport] Data gathering failed for project %s: %s", project_id, e)

    # Gap analysis (uses existing service)
    try:
        from services.knowledge_link_service import get_project_knowledge_gaps

        gaps = get_project_knowledge_gaps(project_id)
        data["completeness"] = gaps.get("completeness", 0)
        data["gaps"] = gaps.get("gaps", {})
    except Exception as e:
        logger.error("[WeeklyReport] Gap analysis failed for project %s: %s", project_id, e)

    return data
```

- [ ] **Step 3: Add the report formatting function**

Append:

```python
def _format_report(project_name: str, data: Dict) -> str:
    """Format gathered data into a markdown report."""
    now = datetime.now()
    start = now - timedelta(days=REPORT_PERIOD_DAYS)
    date_fmt = "%Y-%m-%d"

    # Knowledge growth
    total_links = sum(item["cnt"] for item in data["new_links"])
    if data["new_links"]:
        type_lines = "\n".join(
            f"  - {item['knowledge_type']}: {item['cnt']}"
            for item in data["new_links"]
        )
    else:
        type_lines = "  - No new entries linked this week."

    # Decisions
    decision_count = len(data["decisions"])
    if data["decisions"]:
        decision_lines = "\n".join(f"- {d}" for d in data["decisions"][:10])
    else:
        decision_lines = "No decisions recorded this week."

    # Tasks
    task_count = len(data["tasks_completed"])
    if data["tasks_completed"]:
        task_lines = "\n".join(f"- {t}" for t in data["tasks_completed"][:10])
    else:
        task_lines = "No tasks completed this week."

    # Agent activity
    dispatch_count = sum(d["cnt"] for d in data["dispatches"])
    if data["dispatches"]:
        agent_lines = "\n".join(
            f"- {d['agent_name']}: {d['cnt']} dispatches ({d['successes']} succeeded)"
            for d in data["dispatches"][:10]
        )
    else:
        agent_lines = "No agent dispatches recorded for this project."

    # Gaps
    completeness = data["completeness"]
    if data["gaps"]:
        gap_list = ", ".join(data["gaps"].keys())
    else:
        gap_list = "All clear"

    return f"""# Weekly Knowledge Report: {project_name}
**Period:** {start.strftime(date_fmt)} to {now.strftime(date_fmt)} | **Generated by:** C.O.D.E.X.

## Knowledge Growth
- **{total_links} new entries linked** this week
{type_lines}

## Decisions ({decision_count})
{decision_lines}

## Tasks Completed ({task_count})
{task_lines}

## Agent Activity ({dispatch_count} dispatches)
{agent_lines}

## Current Health
- Completeness: **{completeness}%**
- Gaps: {gap_list}

---
*Auto-generated by C.O.D.E.X. on {now.strftime(date_fmt)}. Weekly digest — not scored toward completeness.*"""
```

- [ ] **Step 4: Add the main generation function**

Append:

```python
def generate_weekly_report(project_id: int) -> Dict:
    """Generate a weekly knowledge report for a project and store as vault_note.

    Returns:
        {success: bool, kb_id: int or None, error: str or None}
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT name, slug FROM unified_projects WHERE id = %s",
                (project_id,),
            )
            proj = cur.fetchone()
            if not proj:
                return {"success": False, "kb_id": None, "error": "Project not found"}

        project_name = proj["name"]
        project_slug = proj["slug"]

        # Check cooldown
        if check_cooldown(project_slug):
            return {"success": False, "kb_id": None, "error": "Report generated within cooldown period"}

        # Gather data
        data = _gather_project_data(project_id)

        # Check if report would be empty (no activity at all)
        total_links = sum(item["cnt"] for item in data["new_links"])
        if (
            total_links == 0
            and len(data["decisions"]) == 0
            and len(data["tasks_completed"]) == 0
            and len(data["dispatches"]) == 0
        ):
            return {"success": False, "kb_id": None, "error": "No activity to report"}

        # Format report
        content = _format_report(project_name, data)
        date_str = datetime.now().strftime("%Y-%m-%d")
        title = f"Weekly Report: {project_name} -- {date_str}"

        # Store as vault_note
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO knowledge_base
                   (title, content, knowledge_type, source_type, importance_score, tags, category)
                   VALUES (%s, %s, 'vault_note', %s, %s, %s, %s)
                   RETURNING id""",
                (
                    title,
                    content,
                    REPORT_SOURCE_TYPE,
                    REPORT_QUALITY_SCORE,
                    "{" + ",".join([project_slug, "weekly-report", "codex"]) + "}",
                    project_slug,
                ),
            )
            kb_id = cur.fetchone()["id"]

        # Link to project
        from services.knowledge_link_service import link_knowledge_to_project

        link_knowledge_to_project(kb_id, project_id, link_type="auto", confidence=0.95)

        logger.info("[WeeklyReport] Generated report for '%s' (kb_id=%s)", project_name, kb_id)
        return {"success": True, "kb_id": kb_id, "error": None}

    except Exception as e:
        logger.error("[WeeklyReport] generate_weekly_report failed for project %s: %s", project_id, e)
        return {"success": False, "kb_id": None, "error": str(e)}


def get_report_candidates() -> List[Dict]:
    """Get all active/planning projects that don't have a recent weekly report."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, name, slug FROM unified_projects WHERE status IN ('active', 'planning') ORDER BY priority DESC"
            )
            projects = cur.fetchall()

        candidates = []
        for proj in projects:
            if not check_cooldown(proj["slug"]):
                candidates.append(dict(proj))
        return candidates

    except Exception as e:
        logger.error("[WeeklyReport] get_report_candidates failed: %s", e)
        return []
```

- [ ] **Step 5: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/weekly_report_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/weekly_report_service.py
git commit -m "feat: add C.O.D.E.X. weekly knowledge report service"
```

---

### Task 2: Register Consciousness Job

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py`

- [ ] **Step 1: Add the job function**

After the `auto_link_knowledge_batch()` function (line 1137, before `register_consciousness_jobs`), add:

```python
def generate_weekly_reports():
    """Job: C.O.D.E.X. weekly knowledge reports.

    Generates a weekly digest for each active/planning project
    that doesn't already have a report from the last 6 days.
    """
    start = time.time()
    try:
        from services.weekly_report_service import get_report_candidates, generate_weekly_report

        candidates = get_report_candidates()
        if not candidates:
            logger.debug("[WeeklyReport Job] No candidates for weekly reports")
            _log_cycle("weekly_knowledge_report", 0, 0, int((time.time() - start) * 1000))
            return

        logger.info("[WeeklyReport Job] Generating reports for %d projects", len(candidates))
        succeeded = 0
        failed = 0

        for proj in candidates:
            result = generate_weekly_report(proj["id"])
            if result["success"]:
                succeeded += 1
            elif result["error"] == "No activity to report":
                pass  # Not a failure, just skip
            else:
                failed += 1
                logger.warning(
                    "[WeeklyReport Job] Failed for '%s': %s",
                    proj.get("name", "unknown"),
                    result.get("error", "unknown"),
                )

        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "weekly_knowledge_report",
            succeeded,
            failed,
            duration,
            details={
                "candidates": len(candidates),
                "succeeded": succeeded,
                "failed": failed,
            },
        )
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        _log_cycle("weekly_knowledge_report", 0, 1, duration, error_message=str(e))
        logger.warning(f"[WeeklyReport Job] Batch failed: {e}")
```

- [ ] **Step 2: Register the job in `register_consciousness_jobs()`**

Find the last `scheduler.add_job` block (the `auto_generate_project_docs` one ending at line 1256). After it, before the logger.info line, add:

```python
    scheduler.add_job(
        with_ctx(generate_weekly_reports),
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="agent_weekly_knowledge_report",
        name="Agent Loop: C.O.D.E.X. Weekly Knowledge Reports",
        replace_existing=True,
    )
```

Note: Use `CronTrigger` (already imported on line 1142) instead of `IntervalTrigger` since this is a weekly schedule.

- [ ] **Step 3: Update the job count in the logger.info line**

Change:
```python
    logger.info("[ConsciousnessJobs] Registered 13 consciousness jobs")
```
To:
```python
    logger.info("[ConsciousnessJobs] Registered 14 consciousness jobs")
```

- [ ] **Step 4: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/tools/consciousness/jobs.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: register C.O.D.E.X. weekly report consciousness job (Sunday 03:00)"
```

---

### Task 3: Exclude weekly_report from Gap Score

**Files:**
- Modify: `platform_v2/services/knowledge_link_service.py`

- [ ] **Step 1: Update the auto_doc exclusion to also exclude weekly_report**

In `get_project_knowledge_gaps()`, find the query that counts auto-docs (around line 153):

```python
            cur.execute(
                """SELECT COUNT(*) as cnt
                   FROM project_knowledge_links pkl
                   JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                   WHERE pkl.project_id = %s
                   AND kb.knowledge_type = 'vault_note'
                   AND kb.source_type = 'auto_documentation'""",
                (project_id,),
            )
            auto_doc_count = cur.fetchone()["cnt"]
```

Replace with a broader query that catches both auto_documentation AND weekly_report:

```python
            cur.execute(
                """SELECT COUNT(*) as cnt
                   FROM project_knowledge_links pkl
                   JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                   WHERE pkl.project_id = %s
                   AND kb.knowledge_type = 'vault_note'
                   AND kb.source_type IN ('auto_documentation', 'weekly_report')""",
                (project_id,),
            )
            auto_doc_count = cur.fetchone()["cnt"]
```

This single change ensures both D.A.R.W.I.N. auto-docs and C.O.D.E.X. weekly reports don't inflate the completeness score.

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/knowledge_link_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/knowledge_link_service.py
git commit -m "fix: exclude weekly_report source_type from gap score (anti-feedback-loop)"
```

---

### Task 4: Deploy, Verify, Complete

**Files:** None (verification only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Test report generation manually**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from services.weekly_report_service import generate_weekly_report, get_report_candidates

# Show candidates
candidates = get_report_candidates()
print(f'Candidates: {len(candidates)}')
for c in candidates:
    print(f'  {c[\"name\"][:50]}')

# Generate for the first candidate
if candidates:
    result = generate_weekly_report(candidates[0]['id'])
    print(f'Result: {result}')
"
```

Expected: Candidates listed, report generated for first project with `success: True` and a `kb_id`.

- [ ] **Step 3: Verify the stored report**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT id, title, source_type, importance_score, tags
FROM knowledge_base
WHERE source_type = 'weekly_report'
ORDER BY created_at DESC LIMIT 3;
"
```

Expected: At least 1 row with `source_type='weekly_report'`, correct tags, importance 0.65.

- [ ] **Step 4: Verify cooldown prevents duplicate**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from services.weekly_report_service import generate_weekly_report
# Try generating again for same project — should fail with cooldown
result = generate_weekly_report(210)
print(f'Second attempt: {result}')
"
```

Expected: `{success: False, error: "Report generated within cooldown period"}`

- [ ] **Step 5: Verify gap analysis excludes weekly_report**

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app')
from services.knowledge_link_service import get_project_knowledge_gaps
gaps = get_project_knowledge_gaps(210)
print(f'Completeness: {gaps[\"completeness\"]}%')
print(f'Gaps: {gaps[\"gaps\"]}')
print(f'Has draft docs: {gaps.get(\"has_draft_docs\", False)}')
"
```

Expected: Weekly reports don't inflate completeness. `has_draft_docs` reflects auto_documentation only.

- [ ] **Step 6: Complete MCP task**

```
mcp complete_task 1637 "C.O.D.E.X. Weekly Knowledge Report: pure SQL aggregation of weekly project metrics (KB growth, decisions, tasks, dispatches, gap health). Stored as vault_note with source_type='weekly_report'. Consciousness job runs Sunday 03:00 UTC. Anti-feedback-loop: excluded from gap score."
```
