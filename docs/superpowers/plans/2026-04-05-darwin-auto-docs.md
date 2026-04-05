# D.A.R.W.I.N. Auto-Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-generate project intelligence reports via D.A.R.W.I.N. agent for projects with knowledge gaps, with anti-feedback-loop protection and dashboard integration.

**Architecture:** New `auto_doc_service.py` handles doc generation logic. Consciousness job dispatches D.A.R.W.I.N. every 6 hours for up to 3 projects below 50% completeness. Dashboard gets a "Generate Report" button. Gap analysis adjusted to not count auto-generated docs as real documentation.

**Tech Stack:** Python/Flask, PostgreSQL, Bridge Dispatcher (Ollama LLM), consciousness jobs pattern.

**Spec:** `docs/superpowers/specs/2026-04-05-darwin-auto-docs-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/services/auto_doc_service.py` | Core logic: generate, store, cooldown check, candidate selection |
| Modify | `platform_v2/services/knowledge_link_service.py` | Gap analysis: exclude auto-docs from vault_note count, add has_draft_docs |
| Modify | `platform_v2/tools/consciousness/jobs.py` | Register + implement auto_generate_project_docs job |
| Modify | `platform_v2/tools/consciousness/dashboard_routes.py` | New generate-docs API endpoint |
| Modify | `platform_v2/static/js/consciousness-dashboard-v2.js` | Generate Report button + DRAFT badge |
| Modify | `platform_v2/static/css/consciousness-dashboard-v2.css` | DRAFT badge + button styles |

---

### Task 1: Auto Doc Service

**Files:**
- Create: `platform_v2/services/auto_doc_service.py`

- [ ] **Step 1: Create the service file**

```python
"""auto_doc_service.py -- Auto-generate project documentation via D.A.R.W.I.N.

Dispatches D.A.R.W.I.N. (R&D director) to generate project intelligence reports
for projects with knowledge gaps. Stores as vault_notes with source_type='auto_documentation'.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

MAX_PROJECTS_PER_RUN = 3
COOLDOWN_DAYS = 7
AUTO_DOC_QUALITY_SCORE = 0.60
AUTO_DOC_SOURCE_TYPE = "auto_documentation"


def check_cooldown(project_slug: str) -> bool:
    """Return True if an auto-doc was generated for this project in the last 7 days."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT COUNT(*) as cnt FROM knowledge_base
                   WHERE source_type = %s
                   AND tags @> ARRAY[%s]
                   AND created_at > NOW() - INTERVAL '%s days'""",
                (AUTO_DOC_SOURCE_TYPE, project_slug, COOLDOWN_DAYS),
            )
            return cur.fetchone()["cnt"] > 0
    except Exception as e:
        logger.error("[AutoDoc] Cooldown check failed: %s", e)
        return True  # Fail safe: skip if unsure


def get_doc_candidates() -> List[Dict]:
    """Get projects below 50% completeness, no cooldown, sorted worst first, max 3."""
    from services.knowledge_link_service import get_all_gaps

    all_gaps = get_all_gaps(status="active,planning")
    candidates = []
    for gap in all_gaps:
        if gap["completeness"] >= 50:
            continue
        if check_cooldown(gap["slug"]):
            continue
        candidates.append(gap)
        if len(candidates) >= MAX_PROJECTS_PER_RUN:
            break
    return candidates


def _build_prompt(project_id: int, gap_data: Dict) -> str:
    """Build the prompt for D.A.R.W.I.N. with project context."""
    try:
        with get_db_cursor() as (conn, cur):
            # Get project details
            cur.execute(
                "SELECT name, description FROM unified_projects WHERE id = %s",
                (project_id,),
            )
            proj = cur.fetchone()
            if not proj:
                return ""

            # Get tasks
            cur.execute(
                """SELECT title, status, priority
                   FROM unified_tasks
                   WHERE project_id = %s
                   ORDER BY priority DESC LIMIT 20""",
                (project_id,),
            )
            tasks = cur.fetchall()

            # Get recent decisions
            cur.execute(
                """SELECT title, decision
                   FROM project_decisions
                   WHERE project_id = %s
                   ORDER BY created_at DESC LIMIT 10""",
                (project_id,),
            )
            decisions = cur.fetchall()

        # Format tasks
        task_lines = []
        for t in tasks:
            status_icon = "[x]" if t["status"] == "completed" else "[ ]"
            task_lines.append(f"  {status_icon} {t['title']} (P{t['priority']})")
        task_summary = "\n".join(task_lines) if task_lines else "  No tasks found."

        completed = sum(1 for t in tasks if t["status"] == "completed")

        # Format decisions
        decision_lines = []
        for d in decisions:
            decision_lines.append(f"  - {d['title']}: {(d['decision'] or '')[:100]}")
        decision_summary = "\n".join(decision_lines) if decision_lines else "  No decisions recorded."

        # Format gaps
        gap_list = ", ".join(gap_data.get("gaps", {}).keys()) or "none identified"

        return f"""You are generating a project intelligence report for "{proj['name']}".

Project description: {(proj['description'] or 'No description')[:500]}
Current completeness: {gap_data.get('completeness', 0)}%
Missing: {gap_list}

Tasks ({len(tasks)} total, {completed} completed):
{task_summary}

Recent decisions:
{decision_summary}

Generate a JSON response with:
- title: A descriptive title for this project report
- summary: 2-3 paragraph overview of the project state, what has been accomplished, what remains
- recommendations: List of 3-5 specific actions to improve this project knowledge coverage
- key_findings: List of 2-3 insights about the project trajectory or risks"""

    except Exception as e:
        logger.error("[AutoDoc] Failed to build prompt for project %s: %s", project_id, e)
        return ""


def generate_project_docs(project_id: int, gap_data: Optional[Dict] = None) -> Dict:
    """Generate a project intelligence report via D.A.R.W.I.N. and store as vault_note.

    Args:
        project_id: Project to document
        gap_data: Optional pre-fetched gap data (from get_doc_candidates). If None, fetched fresh.

    Returns:
        {success: bool, kb_id: int or None, error: str or None}
    """
    try:
        # Get project slug for tags
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

        # Build gap data if not provided
        if gap_data is None:
            from services.knowledge_link_service import get_project_knowledge_gaps

            gap_data = get_project_knowledge_gaps(project_id)

        # Build prompt
        prompt = _build_prompt(project_id, gap_data)
        if not prompt:
            return {"success": False, "kb_id": None, "error": "Failed to build prompt"}

        # Dispatch to D.A.R.W.I.N.
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            capability="auto_document",
            prompt=prompt,
            module_id="consciousness",
            system_prompt="You are D.A.R.W.I.N., Research & Development director. Generate structured project intelligence reports. Always respond with valid JSON.",
            json_mode=True,
            project_id=project_id,
            prefer_agent="D.A.R.W.I.N.",
            timeout=120,
        )

        if not result or not result.success:
            error_msg = getattr(result, "error", "Dispatch failed") if result else "No result"
            return {"success": False, "kb_id": None, "error": str(error_msg)}

        # Parse response
        try:
            response_data = json.loads(result.response) if isinstance(result.response, str) else result.response
        except (json.JSONDecodeError, TypeError):
            response_data = {
                "title": f"Project Report: {project_name}",
                "summary": result.response if result.response else "Report generation produced no content.",
                "recommendations": [],
                "key_findings": [],
            }

        title = response_data.get("title", f"Project Report: {project_name}")
        summary = response_data.get("summary", "")
        recommendations = response_data.get("recommendations", [])
        key_findings = response_data.get("key_findings", [])

        # Format content as markdown
        date_str = datetime.now().strftime("%Y-%m-%d")
        rec_lines = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations)) if recommendations else "No recommendations generated."
        finding_lines = "\n".join(f"- {f}" for f in key_findings) if key_findings else "No findings generated."

        content = f"""## Summary

{summary}

## Recommendations

{rec_lines}

## Key Findings

{finding_lines}

---
*Auto-generated by D.A.R.W.I.N. on {date_str}. Review and promote quality score to validate.*"""

        # Store as vault_note
        full_title = f"Project Report: {project_name} -- {date_str}"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO knowledge_base
                   (title, content, knowledge_type, source_type, importance_score, tags, category)
                   VALUES (%s, %s, 'vault_note', %s, %s, %s, %s)
                   RETURNING id""",
                (
                    full_title,
                    content,
                    AUTO_DOC_SOURCE_TYPE,
                    AUTO_DOC_QUALITY_SCORE,
                    [project_slug, "auto-generated", "project-report"],
                    project_slug,
                ),
            )
            kb_id = cur.fetchone()["id"]

        # Link to project
        from services.knowledge_link_service import link_knowledge_to_project

        link_knowledge_to_project(kb_id, project_id, link_type="auto", confidence=0.90)

        logger.info("[AutoDoc] Generated report for '%s' (kb_id=%s)", project_name, kb_id)
        return {"success": True, "kb_id": kb_id, "error": None}

    except Exception as e:
        logger.error("[AutoDoc] generate_project_docs failed for project %s: %s", project_id, e)
        return {"success": False, "kb_id": None, "error": str(e)}
```

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/auto_doc_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/auto_doc_service.py
git commit -m "feat: add auto_doc_service for D.A.R.W.I.N. project report generation"
```

---

### Task 2: Gap Analysis Adjustment

**Files:**
- Modify: `platform_v2/services/knowledge_link_service.py`

- [ ] **Step 1: Read the gap analysis function**

Read `platform_v2/services/knowledge_link_service.py` starting at the `get_project_knowledge_gaps` function (around line 138). Find the query that counts knowledge types:

```python
cur.execute(
    """SELECT kb.knowledge_type, COUNT(*) as cnt
       FROM project_knowledge_links pkl
       JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
       WHERE pkl.project_id = %s
       GROUP BY kb.knowledge_type""",
    (project_id,),
)
type_counts = {row["knowledge_type"]: row["cnt"] for row in cur.fetchall()}
```

- [ ] **Step 2: Add a separate count for auto-docs**

After the `type_counts` query, add a query to check for auto-generated vault_notes:

```python
            # Check for auto-generated docs (don't count toward completeness)
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

- [ ] **Step 3: Adjust vault_note count to exclude auto-docs**

Change the vault_note gap check from:

```python
if type_counts.get("vault_note", 0) > 0:
    score += GAP_WEIGHTS["vault_note"]
else:
    gaps["vault_note"] = "No documentation linked"
```

To:

```python
            human_vault_notes = type_counts.get("vault_note", 0) - auto_doc_count
            if human_vault_notes > 0:
                score += GAP_WEIGHTS["vault_note"]
            elif auto_doc_count > 0:
                gaps["vault_note"] = "Drafts only (auto-generated)"
            else:
                gaps["vault_note"] = "No documentation linked"
```

- [ ] **Step 4: Add has_draft_docs to return value**

In the return dict, add `has_draft_docs`:

Find the return statement and add after `"needs_attention"`:

```python
                "has_draft_docs": auto_doc_count > 0,
```

- [ ] **Step 5: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/knowledge_link_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add platform_v2/services/knowledge_link_service.py
git commit -m "feat: exclude auto-generated docs from vault_note gap score, add has_draft_docs"
```

---

### Task 3: Consciousness Job Registration

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py`

- [ ] **Step 1: Add the job function**

Find the `auto_link_knowledge_batch` function (grep for `def auto_link_knowledge_batch`). Add the new job function right BEFORE it:

```python
def auto_generate_project_docs():
    """Job: Auto-generate project intelligence reports via D.A.R.W.I.N.

    Finds projects below 50% completeness with no recent auto-doc (7-day cooldown),
    generates up to 3 reports per run via Bridge dispatch.
    """
    start = time.time()
    try:
        from services.auto_doc_service import get_doc_candidates, generate_project_docs

        candidates = get_doc_candidates()
        if not candidates:
            logger.debug("[AutoDoc Job] No candidates for doc generation")
            _log_cycle("auto_generate_docs", 0, 0, int((time.time() - start) * 1000))
            return

        logger.info("[AutoDoc Job] Generating docs for %d projects", len(candidates))
        succeeded = 0
        failed = 0

        for gap_data in candidates:
            result = generate_project_docs(gap_data["project_id"], gap_data=gap_data)
            if result["success"]:
                succeeded += 1
            else:
                failed += 1
                logger.warning(
                    "[AutoDoc Job] Failed for '%s': %s",
                    gap_data.get("name", "unknown"),
                    result.get("error", "unknown"),
                )

        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "auto_generate_docs",
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
        _log_cycle("auto_generate_docs", 0, 1, duration, error_message=str(e))
        logger.warning(f"[AutoDoc Job] Batch failed: {e}")
```

- [ ] **Step 2: Register the job in `register_consciousness_jobs`**

Find `register_consciousness_jobs` function. Add before the final `logger.info` line that says "Registered N consciousness jobs":

```python
    scheduler.add_job(
        with_ctx(auto_generate_project_docs),
        trigger=IntervalTrigger(hours=6),
        id="agent_auto_generate_docs",
        name="Agent Loop: D.A.R.W.I.N. Auto-Documentation",
        replace_existing=True,
    )
```

Update the job count in the log message (e.g., "Registered 13 consciousness jobs").

- [ ] **Step 3: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/tools/consciousness/jobs.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: register D.A.R.W.I.N. auto-doc generation job (every 6h, max 3 projects)"
```

---

### Task 4: Dashboard API Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/dashboard_routes.py`

- [ ] **Step 1: Add generate-docs endpoint**

Find the last route inside `register_dashboard_routes` (the `api_unlink_knowledge` DELETE route). Add after it:

```python
    @bp.route("/api/dashboard/generate-docs", methods=["POST"])
    @login_required
    @admin_required
    def api_generate_docs():
        """Trigger D.A.R.W.I.N. doc generation for a specific project."""
        from services.auto_doc_service import generate_project_docs, check_cooldown

        data = request.get_json() or {}
        project_id = data.get("project_id")
        if not project_id:
            return jsonify({"success": False, "error": "project_id required"}), 400

        try:
            project_id = int(project_id)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid project_id"}), 400

        # Check cooldown (but allow override with force=true)
        force = data.get("force", False)
        if not force:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT slug FROM unified_projects WHERE id = %s", (project_id,))
                row = cur.fetchone()
                if row and check_cooldown(row["slug"]):
                    return jsonify({"success": False, "error": "Report generated within last 7 days. Use force=true to override."}), 429

        result = generate_project_docs(project_id)
        if result["success"]:
            return jsonify({"success": True, "kb_id": result["kb_id"], "message": "Report generated successfully"})
        return jsonify({"success": False, "error": result["error"]}), 500
```

- [ ] **Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/tools/consciousness/dashboard_routes.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/dashboard_routes.py
git commit -m "feat: add generate-docs API endpoint for on-demand D.A.R.W.I.N. reports"
```

---

### Task 5: Dashboard JS — Generate Report Button + DRAFT Badge

**Files:**
- Modify: `platform_v2/static/js/consciousness-dashboard-v2.js`

- [ ] **Step 1: Add Generate Report button to Knowledge Gaps panel**

Read `consciousness-dashboard-v2.js`. Find the `renderKnowledgeGaps` function (renamed from `loadKnowledgeGaps`). Inside the gap row rendering, find where the "+ Decision" and "+ Docs" buttons are created. Add a "Generate Report" button after them:

```javascript
        var btnReport = document.createElement("button");
        btnReport.className = "cs-gap-action-btn cs-generate-report-btn";
        btnReport.textContent = proj.has_draft_docs ? "Report Pending" : "Generate Report";
        btnReport.disabled = proj.has_draft_docs;
        btnReport.addEventListener("click", function (e) {
          e.stopPropagation();
          btnReport.textContent = "Generating...";
          btnReport.disabled = true;
          api("/api/dashboard/generate-docs", {
            method: "POST",
            body: { project_id: proj.project_id },
          }).then(function (data) {
            if (data && data.success) {
              btnReport.textContent = "Report Generated";
              loadDashboardV2Panels();
            } else {
              btnReport.textContent = "Failed";
              btnReport.disabled = false;
            }
          });
        });
        actions.appendChild(btnReport);
```

- [ ] **Step 2: Add DRAFT badge in project card expansion**

Find the `toggleProjectCard` function where KB entries are rendered. Where the link_type badge is created:

```javascript
        var badge = document.createElement("span");
        badge.className = "cs-link-badge " + entry.link_type;
        badge.textContent = entry.link_type;
```

Change to check for auto_documentation source_type. The API returns `knowledge_type` but not `source_type` — we need to add `source_type` to the `get_project_knowledge` query. For now, check if the title starts with "Project Report:" as a proxy:

```javascript
        var badge = document.createElement("span");
        var isDraft = (entry.title || "").indexOf("Project Report:") === 0;
        badge.className = "cs-link-badge " + (isDraft ? "draft" : entry.link_type);
        badge.textContent = isDraft ? "DRAFT" : entry.link_type;
```

- [ ] **Step 3: Update the gap chip for DRAFTS ONLY**

In the `renderKnowledgeGaps` function, find the `gapChipMap` object. The vault_note gap text now can be "Drafts only (auto-generated)" instead of "No documentation linked". Update the chip rendering to handle both:

After the existing `gapChipMap`, add handling for the "drafts only" case. Find where gap chips are created:

```javascript
        Object.keys(proj.gaps || {}).forEach(function (key) {
          var info = gapChipMap[key];
          if (info) {
            var chip = document.createElement("span");
            var gapText = proj.gaps[key];
            var isDraftOnly = gapText && gapText.indexOf("Drafts only") === 0;
            chip.className = "cs-gap-chip " + (isDraftOnly ? "drafts" : info.cls);
            chip.textContent = isDraftOnly ? "DRAFTS ONLY" : info.label;
            chips.appendChild(chip);
          }
        });
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/consciousness-dashboard-v2.js
git commit -m "feat: add Generate Report button and DRAFT badge to dashboard panels"
```

---

### Task 6: Dashboard CSS — DRAFT Badge + Button Styles

**Files:**
- Modify: `platform_v2/static/css/consciousness-dashboard-v2.css`

- [ ] **Step 1: Add DRAFT badge and DRAFTS ONLY chip styles**

Add at the end of the CSS file, before the `@media` queries:

```css
.cs-link-badge.draft {
    background: rgba(251, 146, 60, 0.15);
    color: #fb923c;
}

.cs-gap-chip.drafts {
    background: rgba(251, 146, 60, 0.15);
    color: #fb923c;
}

.cs-generate-report-btn {
    border-color: rgba(16, 185, 129, 0.3);
}

.cs-generate-report-btn:hover:not(:disabled) {
    background: rgba(16, 185, 129, 0.15);
    color: #10b981;
    border-color: #10b981;
}

.cs-generate-report-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/css/consciousness-dashboard-v2.css
git commit -m "feat: add DRAFT badge and Generate Report button styles"
```

---

### Task 7: Deploy, Verify, Complete

**Files:** None (verification only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify job registration**

```bash
docker logs archie_platform 2>&1 | grep -i "auto.*doc\|13 consciousness"
```

Expected: "Registered 13 consciousness jobs" and the auto-doc job listed.

- [ ] **Step 3: Test generate-docs API**

```bash
curl -s -c /tmp/cookies.txt -d "username=admin&password=Kyt%2413ran2025" http://192.168.1.200:3000/login > /dev/null
curl -s -b /tmp/cookies.txt -X POST -H "Content-Type: application/json" \
  -d '{"project_id": 214}' \
  http://192.168.1.200:3000/tools/consciousness/api/dashboard/generate-docs
```

Expected: JSON with `"success": true` and a `kb_id`, or an error if Ollama model isn't available (acceptable — the endpoint works).

- [ ] **Step 4: Verify gap analysis excludes auto-docs**

```bash
docker exec archie_platform python3 -c "
from services.knowledge_link_service import get_project_knowledge_gaps
gaps = get_project_knowledge_gaps(214)
print(f'Completeness: {gaps[\"completeness\"]}%')
print(f'Has draft docs: {gaps.get(\"has_draft_docs\", False)}')
print(f'Gaps: {gaps[\"gaps\"]}')
"
```

- [ ] **Step 5: Verify dashboard renders Generate Report button**

Open `http://192.168.1.200:3000/tools/consciousness` > Dashboard tab. Scroll to Knowledge Gaps panel. Verify "Generate Report" buttons appear next to each project.

- [ ] **Step 6: Complete MCP task**

```
mcp complete_task 1635 "D.A.R.W.I.N. auto-doc generation: consciousness job every 6h, max 3 projects below 50%, 7-day cooldown. Dashboard Generate Report button. Anti-feedback-loop: auto-docs don't count toward vault_note gap score. DRAFT badge for auto-generated entries."
```
