"""Project service — shared queries for unified_projects/tasks/decisions tables.

Owner: Dev HQ module (10+ CRUD endpoints)
Consumers: Consciousness (6 read-only queries — dashboard, integration health)

Import:
    from services.project_service import get_project_stats, get_recent_activity
"""

import logging

from psycopg2.extras import RealDictCursor
from database import get_db_connection

logger = logging.getLogger(__name__)


def get_project_stats():
    """Count active and completed projects.
    Returns: {"active": int, "completed": int}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'active') as active,
                    count(*) FILTER (WHERE status = 'completed') as completed
                FROM unified_projects
            """
            )
            row = cur.fetchone()
            return {
                "active": row["active"] if row else 0,
                "completed": row["completed"] if row else 0,
            }
        finally:
            cur.close()


def get_task_stats():
    """Count in_progress, completed, and total tasks.
    Returns: {"in_progress": int, "done": int, "total": int}
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                SELECT
                    count(*) FILTER (WHERE status = 'in_progress') as in_progress,
                    count(*) FILTER (WHERE status = 'completed') as done,
                    count(*) as total
                FROM unified_tasks
            """
            )
            row = cur.fetchone()
            return {
                "in_progress": row["in_progress"] if row else 0,
                "done": row["done"] if row else 0,
                "total": row["total"] if row else 0,
            }
        finally:
            cur.close()


def get_active_project_count():
    """Return count of active projects (for health checks)."""
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT count(*) as cnt FROM unified_projects WHERE status = 'active'")
            row = cur.fetchone()
            return row["cnt"] if row else 0
        finally:
            cur.close()


def get_recent_projects(limit=5):
    """Return most recent projects, ordered by created_at DESC.
    Returns: list of dicts with id, name, status, priority, created_at
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT id, name, status, priority, created_at
                FROM unified_projects ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()


def get_recent_decisions(limit=5):
    """Return most recent architectural decisions.
    Returns: list of dicts with title, decision, context, created_at
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """SELECT title, decision, context, created_at
                FROM project_decisions ORDER BY created_at DESC LIMIT %s""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()


def get_recent_activity(limit=15):
    """Blended activity feed: knowledge + bridge + completed tasks.
    Returns: list of dicts with source, description, created_at, icon
    """
    with get_db_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                (SELECT 'knowledge' as source,
                        COALESCE(NULLIF(title, ''), 'Untitled entry') as description,
                        created_at, 'book-open' as icon
                 FROM knowledge_base
                 WHERE knowledge_type != 'archie_v1'
                 ORDER BY created_at DESC LIMIT 5)
                UNION ALL
                (SELECT 'bridge' as source,
                        COALESCE(NULLIF(task_description, ''),
                                 'Bridge task #' || id) as description,
                        created_at, 'radio' as icon
                 FROM task_execution_log
                 ORDER BY created_at DESC LIMIT 5)
                UNION ALL
                (SELECT 'project' as source,
                        COALESCE(NULLIF(title, ''), 'Completed task') as description,
                        created_at, 'folder-kanban' as icon
                 FROM unified_tasks
                 WHERE status = 'completed'
                 ORDER BY created_at DESC LIMIT 5)
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        finally:
            cur.close()
