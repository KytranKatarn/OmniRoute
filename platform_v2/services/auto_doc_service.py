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
                   AND category = %s
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

        # Dispatch to D.A.R.W.I.N. via canonical dispatcher
        from tools.department_hq.services.department_dispatcher import dispatch

        result = dispatch(
            capability="research",
            prompt=prompt,
            module_id="consciousness",
            system_prompt="You are D.A.R.W.I.N., Research & Development director. Generate structured project intelligence reports. Always respond with valid JSON.",
            json_mode=True,
            project_id=project_id,
            prefer_agent="D.A.R.W.I.N.",
            timeout=600,
        )

        if result and result.queued:
            logger.info(
                "[AutoDoc] Deferred to queue for project %s — D.A.R.W.I.N. model cold, will retry automatically",
                project_id,
            )
            return {"success": True, "kb_id": None, "queued": True}
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

        response_data.get("title", f"Project Report: {project_name}")
        summary = response_data.get("summary", "")
        recommendations = response_data.get("recommendations", [])
        key_findings = response_data.get("key_findings", [])

        # Format content as markdown
        date_str = datetime.now().strftime("%Y-%m-%d")
        rec_lines = (
            "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations))
            if recommendations
            else "No recommendations generated."
        )
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
