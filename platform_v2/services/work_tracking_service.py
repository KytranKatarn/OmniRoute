"""Work tracking service — creates and manages department work sessions.

Provides helpers to create, complete, and fail work sessions in the
dept_work_sessions table, plus a compute_department_metrics() function
called by Agent Loop Job #60 (daily at 2:00 AM, owned by S.P.E.C.T.R.A.).

Import:
    from services.work_tracking_service import (
        create_work_session, complete_work_session, fail_work_session,
        get_active_sessions, get_session_history, compute_department_metrics,
    )
"""

import json
import logging
from datetime import datetime, timezone

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Static department FLOOR — compute_department_metrics() derives the real list
# from the agents table and unions it with this (#5703). Do NOT treat this as
# the authoritative roster; it predates News & Media (2026-04-14).
DEPARTMENTS = [
    "Executive Office",
    "Operations & Infrastructure",
    "Logistics & Supply Chain",
    "Finance & Accounting",
    "Engineering & Technology",
    "Security & Compliance",
    "Research & Development",
    "Creative & Design",
    "Marketing & Communications",
    "Documentation & Knowledge",
    "Customer Success & Support",
    "Human Resources & Culture",
    "Medical & Wellness",
    "Legal & Regulatory",
    "Diplomatic & External Relations",
    "Analytics & Intelligence",
]


# ---------------------------------------------------------------------------
# Work Session CRUD
# ---------------------------------------------------------------------------


def create_work_session(agent_id, department, session_type, title, metadata=None):
    """Create a new work session. Returns session_id."""
    meta_json = json.dumps(metadata) if metadata else None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO dept_work_sessions
                   (agent_id, department, session_type, title, status, started_at, metadata)
               VALUES (%s, %s, %s, %s, 'active', NOW(), %s)
               RETURNING id""",
            (agent_id, department, session_type, title, meta_json),
        )
        row = cur.fetchone()
        session_id = row["id"] if isinstance(row, dict) else row[0]
    logger.info(
        "Work session #%d created: dept=%s type=%s title=%s",
        session_id,
        department,
        session_type,
        title,
    )
    return session_id


def complete_work_session(session_id, jobs_completed=0, jobs_failed=0, tokens_used=0):
    """Mark a work session as completed."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE dept_work_sessions
               SET status = 'completed', ended_at = NOW(),
                   jobs_completed = %s, jobs_failed = %s, tokens_used = %s
               WHERE id = %s AND status = 'active'""",
            (jobs_completed, jobs_failed, tokens_used, session_id),
        )
        updated = cur.rowcount
    if updated:
        logger.info("Work session #%d completed: %d ok, %d failed", session_id, jobs_completed, jobs_failed)
    else:
        logger.warning("Work session #%d not updated (not active or missing)", session_id)
    return updated > 0


def fail_work_session(session_id, error_msg=""):
    """Mark a work session as failed."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Merge error into existing metadata JSONB
        cur.execute(
            """UPDATE dept_work_sessions
               SET status = 'failed', ended_at = NOW(),
                   metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
               WHERE id = %s AND status = 'active'""",
            (json.dumps({"error": error_msg}), session_id),
        )
        updated = cur.rowcount
    if updated:
        logger.info("Work session #%d failed: %s", session_id, error_msg[:120])
    else:
        logger.warning("Work session #%d not updated (not active or missing)", session_id)
    return updated > 0


def get_active_sessions(department=None):
    """Get active work sessions, optionally filtered by department."""
    with get_db_cursor(commit=False) as (conn, cur):
        if department:
            cur.execute(
                """SELECT * FROM dept_work_sessions
                   WHERE status = 'active' AND department = %s
                   ORDER BY started_at DESC""",
                (department,),
            )
        else:
            cur.execute(
                """SELECT * FROM dept_work_sessions
                   WHERE status = 'active'
                   ORDER BY started_at DESC"""
            )
        return cur.fetchall()


def get_session_history(department=None, limit=50):
    """Get recent completed/failed sessions."""
    with get_db_cursor(commit=False) as (conn, cur):
        if department:
            cur.execute(
                """SELECT * FROM dept_work_sessions
                   WHERE status IN ('completed', 'failed') AND department = %s
                   ORDER BY ended_at DESC LIMIT %s""",
                (department, limit),
            )
        else:
            cur.execute(
                """SELECT * FROM dept_work_sessions
                   WHERE status IN ('completed', 'failed')
                   ORDER BY ended_at DESC LIMIT %s""",
                (limit,),
            )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Department Metrics Computation
# ---------------------------------------------------------------------------


def compute_department_metrics(period_hours=24):
    """Compute metrics for ALL departments for the given period.

    Called by Agent Loop Job #60 (daily at 2:00 AM, owned by S.P.E.C.T.R.A.).
    Upserts into department_metrics using (department, period_start, period_end).

    #5703: the department list is derived from the live agents table, unioned
    with the static DEPARTMENTS constant (kept as a floor for departments that
    currently have no agents rows). The static-only iteration silently dropped
    News & Media (created 2026-04-14) — and would drop any future department —
    leaving it without a department_metrics row and invisible on the DHQ
    Performance tab.
    """
    computed = 0

    with get_db_cursor(commit=True) as (conn, cur):
        try:
            cur.execute("SELECT DISTINCT department FROM agents WHERE department IS NOT NULL AND department <> ''")
            departments = sorted({r["department"] for r in cur.fetchall()} | set(DEPARTMENTS))
        except Exception as e:
            logger.warning("Department discovery failed, falling back to static list: %s", e)
            conn.rollback()  # clear the aborted txn so the per-dept queries can run
            departments = list(DEPARTMENTS)
        for dept in departments:
            try:
                # --- bridge_jobs metrics (join agents to get department) ---
                cur.execute(
                    """SELECT
                           COUNT(*) FILTER (WHERE bj.status = 'completed') AS jobs_ok,
                           COUNT(*) FILTER (WHERE bj.status = 'failed')    AS jobs_fail,
                           AVG(EXTRACT(EPOCH FROM (bj.completed_at - bj.created_at)) * 1000)
                               FILTER (WHERE bj.completed_at IS NOT NULL)  AS avg_ms
                       FROM bridge_jobs bj
                       JOIN agents a ON a.name = bj.agent_name OR a.display_name = bj.agent_name
                       WHERE a.department = %s
                         AND bj.created_at >= NOW() - INTERVAL '%s hours'""",
                    (dept, period_hours),
                )
                job_row = cur.fetchone()
                jobs_completed = (job_row["jobs_ok"] or 0) if job_row else 0
                jobs_failed = (job_row["jobs_fail"] or 0) if job_row else 0
                avg_response_ms = int(job_row["avg_ms"] or 0) if job_row else 0

                # --- dept_work_sessions completed in period ---
                cur.execute(
                    """SELECT COUNT(*) AS cnt FROM dept_work_sessions
                       WHERE department = %s AND status = 'completed'
                         AND ended_at >= NOW() - INTERVAL '%s hours'""",
                    (dept, period_hours),
                )
                sess_row = cur.fetchone()
                sessions_completed = (sess_row["cnt"] or 0) if sess_row else 0

                # --- C.R.E.E.D. score from governance_audit_log ---
                cur.execute(
                    """SELECT
                           COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE outcome = 'approved') AS approved
                       FROM governance_audit_log
                       WHERE event_category = 'creed_gate'
                         AND timestamp >= NOW() - INTERVAL '%s hours'
                         AND agent_id IN (
                             SELECT id FROM agents WHERE department = %s
                         )""",
                    (period_hours, dept),
                )
                creed_row = cur.fetchone()
                creed_total = (creed_row["total"] or 0) if creed_row else 0
                creed_approved = (creed_row["approved"] or 0) if creed_row else 0
                creed_score = round(creed_approved / creed_total * 100, 1) if creed_total > 0 else 100.0

                # --- Upsert ---
                cur.execute(
                    """INSERT INTO department_metrics
                           (department, period_start, period_end,
                            jobs_completed, jobs_failed, avg_response_ms,
                            tokens_used, sessions_completed, kpis,
                            creed_score, computed_at)
                       VALUES (
                           %s,
                           NOW() - INTERVAL '%s hours', NOW(),
                           %s, %s, %s,
                           0, %s, '{}'::jsonb,
                           %s, NOW()
                       )
                       ON CONFLICT (department, period_start, period_end)
                       DO UPDATE SET
                           jobs_completed = EXCLUDED.jobs_completed,
                           jobs_failed = EXCLUDED.jobs_failed,
                           avg_response_ms = EXCLUDED.avg_response_ms,
                           tokens_used = EXCLUDED.tokens_used,
                           sessions_completed = EXCLUDED.sessions_completed,
                           creed_score = EXCLUDED.creed_score,
                           computed_at = NOW()""",
                    (dept, period_hours, jobs_completed, jobs_failed, avg_response_ms, sessions_completed, creed_score),
                )
                computed += 1

            except Exception as e:
                logger.warning("Failed to compute metrics for %s: %s", dept, e)

    logger.info("Department metrics computed for %d/%d departments", computed, len(departments))
    return {"departments_computed": computed, "period_hours": period_hours}
