"""weekly_report_service.py — C.O.D.E.X. weekly per-project knowledge digest.

Generates a markdown summary of project activity over the past 7 days via
pure SQL aggregation. No LLM dispatch — just data queries and formatting.

Usage:
    from services.weekly_report_service import generate_weekly_report, get_report_candidates
"""

import logging
from datetime import date

from database import get_db_cursor
from services.knowledge_link_service import get_project_knowledge_gaps, link_knowledge_to_project

logger = logging.getLogger(__name__)

# --- Constants ---
REPORT_SOURCE_TYPE = "weekly_report"
REPORT_QUALITY_SCORE = 0.65
COOLDOWN_DAYS = 6
REPORT_PERIOD_DAYS = 7


# --- Cooldown Check ---


def check_cooldown(project_slug: str) -> bool:
    """Return True if a weekly_report already exists for this project in the last COOLDOWN_DAYS.

    Fail-safe: returns True on error (prevents duplicate reports on DB issues).
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id FROM knowledge_base
                WHERE source_type = %s
                  AND tags @> ARRAY[%s]::text[]
                  AND created_at > NOW() - INTERVAL '6 days'
                LIMIT 1
                """,
                (REPORT_SOURCE_TYPE, project_slug),
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.error("[WeeklyReport] check_cooldown error for %s: %s", project_slug, e)
        return True  # fail safe — don't generate duplicate


# --- Data Gathering ---


def _gather_project_data(project_id: int, days: int = REPORT_PERIOD_DAYS) -> dict:
    """Aggregate project activity for the past `days` days.

    Returns dict with keys: new_links, decisions, tasks_completed, dispatches,
    completeness, gaps.
    """
    data = {
        "new_links": {},
        "decisions": [],
        "tasks_completed": [],
        "dispatches": [],
        "completeness": 0.0,
        "gaps": {},
    }

    try:
        with get_db_cursor() as (conn, cur):
            # New knowledge links grouped by type
            cur.execute(
                """
                SELECT kb.knowledge_type, COUNT(*) as cnt
                FROM project_knowledge_links pkl
                JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                WHERE pkl.project_id = %s
                  AND pkl.created_at > NOW() - INTERVAL '%s days'
                GROUP BY kb.knowledge_type
                """,
                (project_id, days),
            )
            data["new_links"] = {row["knowledge_type"]: row["cnt"] for row in cur.fetchall()}

            # Recent decisions
            cur.execute(
                """
                SELECT decision FROM project_decisions
                WHERE project_id = %s
                  AND created_at > NOW() - INTERVAL '%s days'
                ORDER BY created_at DESC
                """,
                (project_id, days),
            )
            data["decisions"] = [row["decision"] for row in cur.fetchall()]

            # Completed tasks
            cur.execute(
                """
                SELECT title FROM unified_tasks
                WHERE project_id = %s
                  AND status = 'completed'
                  AND updated_at > NOW() - INTERVAL '%s days'
                ORDER BY updated_at DESC
                """,
                (project_id, days),
            )
            data["tasks_completed"] = [row["title"] for row in cur.fetchall()]

            # Agent dispatch activity grouped by agent
            cur.execute(
                """
                SELECT agent_name,
                       COUNT(*) as total,
                       COUNT(*) FILTER (WHERE status = 'completed') as completed
                FROM bridge_jobs
                WHERE project_id = %s
                  AND agent_name IS NOT NULL
                  AND created_at > NOW() - INTERVAL '%s days'
                GROUP BY agent_name
                ORDER BY total DESC
                """,
                (project_id, days),
            )
            data["dispatches"] = [
                {
                    "agent": row["agent_name"],
                    "total": row["total"],
                    "completed": row["completed"],
                }
                for row in cur.fetchall()
            ]

    except Exception as e:
        logger.error("[WeeklyReport] _gather_project_data error for project %s: %s", project_id, e)

    # Knowledge gaps (separate connection call is fine — service handles its own cursor)
    try:
        gap_data = get_project_knowledge_gaps(project_id)
        data["completeness"] = gap_data.get("completeness_score", 0.0)
        data["gaps"] = gap_data.get("gaps", {})
    except Exception as e:
        logger.warning("[WeeklyReport] Could not fetch gap data for project %s: %s", project_id, e)

    return data


# --- Formatting ---


def _format_report(project_name: str, data: dict) -> str:
    """Render the weekly digest markdown string."""
    lines = [f"# Weekly Knowledge Digest: {project_name}", ""]

    # Knowledge Growth
    lines.append("## Knowledge Growth")
    if data["new_links"]:
        for ktype, cnt in sorted(data["new_links"].items()):
            lines.append(f"- **{ktype}**: {cnt} new entr{'y' if cnt == 1 else 'ies'} linked")
    else:
        lines.append("- No new knowledge linked this week")
    lines.append("")

    # Decisions
    lines.append("## Decisions")
    if data["decisions"]:
        for decision in data["decisions"]:
            lines.append(f"- {decision}")
    else:
        lines.append("- No decisions recorded this week")
    lines.append("")

    # Tasks Completed
    lines.append("## Tasks Completed")
    if data["tasks_completed"]:
        for task in data["tasks_completed"]:
            lines.append(f"- {task}")
    else:
        lines.append("- No tasks completed this week")
    lines.append("")

    # Agent Activity
    lines.append("## Agent Activity")
    if data["dispatches"]:
        for d in data["dispatches"]:
            lines.append(
                f"- **{d['agent']}**: {d['total']} dispatch{'es' if d['total'] != 1 else ''}"
                f" ({d['completed']} completed)"
            )
    else:
        lines.append("- No agent dispatches this week")
    lines.append("")

    # Current Health
    lines.append("## Current Health")
    score_pct = int(data["completeness"] * 100)
    lines.append(f"- Knowledge completeness: **{score_pct}%**")
    if data["gaps"]:
        lines.append("- Gaps identified:")
        for gap_type, gap_desc in data["gaps"].items():
            lines.append(f"  - *{gap_type}*: {gap_desc}")
    else:
        lines.append("- No gaps identified")
    lines.append("")

    # Footer
    today = date.today().strftime("%Y-%m-%d")
    lines.append(f"---\n*Auto-generated by C.O.D.E.X. on {today}. " "Weekly digest — not scored toward completeness.*")

    return "\n".join(lines)


# --- Main Entry Point ---


def generate_weekly_report(project_id: int) -> dict:
    """Generate and store the weekly knowledge digest for a project.

    Returns:
        {"success": True, "kb_id": int} on success
        {"success": False, "error": str} on failure or skip
    """
    # 1. Fetch project name + slug
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT name, slug FROM unified_projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"success": False, "error": f"Project {project_id} not found"}
            project_name = row["name"]
            project_slug = row["slug"]
    except Exception as e:
        logger.error("[WeeklyReport] Failed to fetch project %s: %s", project_id, e)
        return {"success": False, "error": str(e)}

    # 2. Cooldown check
    if check_cooldown(project_slug):
        logger.info("[WeeklyReport] Skipping %s — within cooldown window", project_slug)
        return {"success": False, "error": "within_cooldown"}

    # 3. Gather data
    data = _gather_project_data(project_id)

    # 4. Skip if ALL sections are empty (no activity)
    has_activity = (
        bool(data["new_links"]) or bool(data["decisions"]) or bool(data["tasks_completed"]) or bool(data["dispatches"])
    )
    if not has_activity:
        logger.info("[WeeklyReport] Skipping %s — no activity this week", project_slug)
        return {"success": False, "error": "no_activity"}

    # 5. Format report
    content = _format_report(project_name, data)
    title = f"Weekly Digest: {project_name} ({date.today().strftime('%Y-%m-%d')})"

    # 6. Store as vault_note in knowledge_base
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                    (title, content, knowledge_type, source_type, importance_score, tags)
                VALUES (%s, %s, 'vault_note', %s, %s, %s)
                RETURNING id
                """,
                (
                    title,
                    content,
                    REPORT_SOURCE_TYPE,
                    REPORT_QUALITY_SCORE,
                    "{" + f"{project_slug},weekly-report,codex" + "}",
                ),
            )
            kb_id = cur.fetchone()["id"]
    except Exception as e:
        logger.error("[WeeklyReport] Failed to store report for %s: %s", project_slug, e)
        return {"success": False, "error": str(e)}

    # 7. Link to project
    link_knowledge_to_project(kb_id, project_id, link_type="auto", confidence=0.95)

    logger.info("[WeeklyReport] Generated report for %s (kb_id=%s)", project_slug, kb_id)
    return {"success": True, "kb_id": kb_id}


# --- Candidate Discovery ---


def get_report_candidates() -> list:
    """Return list of active/planning projects that don't have a recent weekly report.

    Each entry: {"id": int, "name": str, "slug": str}
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, name, slug FROM unified_projects
                WHERE status IN ('active', 'planning')
                ORDER BY name
                """
            )
            projects = [dict(row) for row in cur.fetchall()]

        candidates = []
        for project in projects:
            if not check_cooldown(project["slug"]):
                candidates.append(project)

        return candidates
    except Exception as e:
        logger.error("[WeeklyReport] get_report_candidates error: %s", e)
        return []
