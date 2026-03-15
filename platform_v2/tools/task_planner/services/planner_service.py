"""
Task Planner Service — CRUD, stats, AI prioritization, and Google Calendar scheduling.
"""

import logging
from datetime import datetime, timedelta

import psycopg2.extras

from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_tasks(user_id, status=None, category=None):
    """Return tasks for a user with optional status/category filters."""
    query = "SELECT * FROM planner_tasks WHERE user_id = %s"
    params = [user_id]
    if status:
        query += " AND status = %s"
        params.append(status)
    if category:
        query += " AND category = %s"
        params.append(category)
    query += " ORDER BY sort_order ASC, created_at DESC"
    with get_db_cursor() as (conn, cur):
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def create_task(user_id, title, description=None, priority=5, category=None, due_date=None, tags=None):
    """Insert a new planner task."""
    import json

    tags_val = psycopg2.extras.Json(tags or [])
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO planner_tasks (user_id, title, description, priority, category, due_date, tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, title, description, priority, category, due_date, tags_val),
        )
        return dict(cur.fetchone())


def update_task(task_id, user_id, updates):
    """Update allowed fields on a task. Only touches provided keys."""
    allowed = {"title", "description", "status", "priority", "category", "due_date", "tags", "sort_order"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return None

    # Wrap JSONB fields
    if "tags" in fields:
        fields["tags"] = psycopg2.extras.Json(fields["tags"])

    set_clause = ", ".join(f"{k} = %s" for k in fields)
    set_clause += ", updated_at = NOW()"
    if updates.get("status") == "done":
        set_clause += ", completed_at = NOW()"

    params = list(fields.values()) + [task_id, user_id]
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE planner_tasks SET {set_clause} WHERE id = %s AND user_id = %s RETURNING *",
            params,
        )
        row = cur.fetchone()
        return dict(row) if row else None


def delete_task(task_id, user_id):
    """Delete a task, enforcing ownership."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM planner_tasks WHERE id = %s AND user_id = %s RETURNING id",
            (task_id, user_id),
        )
        return cur.fetchone() is not None


def move_task(task_id, user_id, new_status, sort_order=0):
    """Update status + sort_order for kanban drag-and-drop."""
    completed_at_clause = ", completed_at = NOW()" if new_status == "done" else ", completed_at = NULL"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"""UPDATE planner_tasks
                SET status = %s, sort_order = %s, updated_at = NOW(){completed_at_clause}
                WHERE id = %s AND user_id = %s
                RETURNING *""",
            (new_status, sort_order, task_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_boards(user_id):
    """Return all kanban boards for a user."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM planner_boards WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
        return [dict(r) for r in cur.fetchall()]


def create_board(user_id, name, columns=None):
    """Insert a new board."""
    cols = psycopg2.extras.Json(columns or ["todo", "in_progress", "done"])
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO planner_boards (user_id, name, columns) VALUES (%s, %s, %s) RETURNING *",
            (user_id, name, cols),
        )
        return dict(cur.fetchone())


def get_stats(user_id):
    """Return counts by status, overdue count, and completed-this-week count."""
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT status, COUNT(*) AS cnt FROM planner_tasks WHERE user_id = %s GROUP BY status",
            (user_id,),
        )
        by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM planner_tasks WHERE user_id = %s AND due_date < NOW() AND status != 'done'",
            (user_id,),
        )
        overdue = cur.fetchone()["cnt"]

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM planner_tasks WHERE user_id = %s AND completed_at >= %s",
            (user_id, week_start),
        )
        completed_this_week = cur.fetchone()["cnt"]

    total = sum(by_status.values())
    done = by_status.get("done", 0)
    completion_rate = round((done / total * 100) if total else 0, 1)

    return {
        "by_status": by_status,
        "total": total,
        "overdue": overdue,
        "completed_this_week": completed_this_week,
        "completion_rate": completion_rate,
    }


def schedule_task(user_id, task_id):
    """Create a Google Calendar event for the task's due_date (if set)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM planner_tasks WHERE id = %s AND user_id = %s",
            (task_id, user_id),
        )
        task = cur.fetchone()
    if not task:
        return {"error": "Task not found"}
    if not task["due_date"]:
        return {"error": "Task has no due_date — set one before scheduling"}

    # Find the user's first linked Google account
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM google_accounts WHERE owner_type = 'user' AND owner_id = %s LIMIT 1",
            (user_id,),
        )
        acct = cur.fetchone()
    if not acct:
        return {"error": "No Google account linked. Connect one in Google Work Suite."}

    try:
        from platform_v2.tools.google_work_suite.services.calendar_service import create_event

        due = task["due_date"]
        start_iso = due.isoformat()
        end_iso = (due + timedelta(hours=1)).isoformat()
        event = create_event(
            account_id=acct["id"],
            summary=task["title"],
            start=start_iso,
            end=end_iso,
            description=task["description"] or "",
        )
        return {"success": True, "event": event}
    except Exception as exc:
        logger.error("schedule_task failed: %s", exc)
        return {"error": str(exc)}


def ai_prioritize(user_id):
    """Ask the Bridge to suggest a priority ordering for the user's open tasks."""
    tasks = get_tasks(user_id, status=None)
    open_tasks = [t for t in tasks if t["status"] != "done"]
    if not open_tasks:
        return {"error": "No open tasks to prioritize"}

    task_list_text = "\n".join(
        f"- ID {t['id']}: {t['title']} (priority={t['priority']}, due={t['due_date']})" for t in open_tasks
    )
    prompt = (
        "You are a productivity assistant. Re-order these tasks by urgency and importance. "
        "Return ONLY a JSON array of task IDs in recommended order, highest priority first.\n\n"
        f"Tasks:\n{task_list_text}"
    )

    try:
        from ai_bridge.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        result = dispatcher.dispatch_request(
            prompt=prompt,
            station="OPERATIONS",
            task_type="task_prioritization",
            preferred_model="mistral:7b",
        )
        response_text = result.get("response", "") if isinstance(result, dict) else str(result)

        import json
        import re

        match = re.search(r"\[[\d,\s]+\]", response_text)
        ordered_ids = json.loads(match.group()) if match else []
        return {"success": True, "ordered_ids": ordered_ids, "raw": response_text}
    except Exception as exc:
        logger.error("ai_prioritize failed: %s", exc)
        return {"error": str(exc)}
