"""Single writer for the cockpit Work pane (#6679, Phase 4b) — unified_tasks / unified_projects.

Module-level functions, get_db_cursor context-managed, RealDictCursor rows, no Flask.
Notes live on the task (metadata->'notes'); the session-scoped work_notes table is
deliberately not used. Delegation stamps the SAME row so the agent-loop
delegate_task_worker (delegation_source IS NOT NULL AND status='pending') claims it.
The MCP handlers (mcp_server/tools/project_tools.py) and Dev HQ keep their own SQL for
now — converging them onto this module is a filed follow-up, not this slice.
"""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import Json

from database import get_db_cursor

TASK_STATUSES = ("pending", "in_progress", "blocked", "completed", "cancelled")
OPEN_STATUSES = ("pending", "in_progress", "blocked")
TASK_TYPES = ("implementation", "bugfix", "research", "testing", "review", "documentation")
PROJECT_STATUSES = ("active", "planning", "on_hold", "completed", "cancelled")
PROJECT_DEFAULT_STATUSES = ("active", "planning", "on_hold")
NOTE_CAP = 50
NOTE_MAX_CHARS = 2000
MAX_LIMIT = 200


def clamp_page(limit, offset):
    try:
        limit = 50 if limit is None else int(limit)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = 0 if offset is None else int(offset)
    except (TypeError, ValueError):
        offset = 0
    return max(1, min(MAX_LIMIT, limit)), max(0, offset)


def _csv(value, allowed, label):
    if not value:
        return None
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    for p in parts:
        if p not in allowed:
            raise ValueError(f"unknown {label} {p!r}; allowed: {', '.join(allowed)}")
    return parts or None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def capabilities():
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

    return sorted(CAPABILITY_DEPARTMENT_MAP.keys())


# ---- reads -----------------------------------------------------------------------
def list_projects(status=None, limit=50, offset=0):
    limit, offset = clamp_page(limit, offset)
    statuses = _csv(status, PROJECT_STATUSES, "project status") or list(PROJECT_DEFAULT_STATUSES)
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM unified_projects WHERE status = ANY(%s)", (statuses,))
        total = cur.fetchone()["n"]
        cur.execute(
            """SELECT p.id, p.name, p.slug, p.status, p.priority, p.project_type, p.target_date,
                      COUNT(t.id) FILTER (WHERE t.status IN ('pending', 'in_progress', 'blocked')) AS open_tasks,
                      COUNT(t.id) AS total_tasks
                 FROM unified_projects p
                 LEFT JOIN unified_tasks t ON t.project_id = p.id
                WHERE p.status = ANY(%s)
                GROUP BY p.id
                ORDER BY p.priority DESC NULLS LAST, p.name
                LIMIT %s OFFSET %s""",
            (statuses, limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return rows, total


def list_tasks(q=None, project_id=None, status=None, min_priority=None, limit=50, offset=0):
    limit, offset = clamp_page(limit, offset)
    # status ALWAYS defaults to OPEN_STATUSES when not explicitly given — a q=
    # search never widens scope past it; the chips (an explicit status=) are
    # the only way to search closed statuses (spec §2.2).
    statuses = _csv(status, TASK_STATUSES, "status") or list(OPEN_STATUSES)
    where = ["t.status = ANY(%s)"]
    params: list = [statuses]
    if project_id not in (None, ""):
        where.append("t.project_id = %s")
        params.append(int(project_id))
    if q and str(q).strip():
        like = f"%{str(q).strip()}%"
        where.append("(t.title ILIKE %s OR t.description ILIKE %s)")
        params += [like, like]
    if min_priority not in (None, ""):
        where.append("t.priority >= %s")
        params.append(int(min_priority))
    sql_where = " AND ".join(where) if where else "TRUE"
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) AS n FROM unified_tasks t WHERE {sql_where}", params)
        total = cur.fetchone()["n"]
        cur.execute(
            f"""SELECT t.id, t.project_id, p.name AS project_name, t.title, t.status, t.priority, t.task_type,
                       t.assigned_agent_id, a.name AS agent_name, t.delegation_source, t.due_date,
                       t.created_at, t.updated_at
                  FROM unified_tasks t
                  LEFT JOIN unified_projects p ON p.id = t.project_id
                  LEFT JOIN agents a ON a.id = t.assigned_agent_id
                 WHERE {sql_where}
                 ORDER BY t.priority DESC NULLS LAST, t.created_at DESC
                 LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT status, COUNT(*) AS n FROM unified_tasks WHERE status = ANY(%s) GROUP BY status",
            (list(TASK_STATUSES),),
        )
        status_facet = {r["status"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT id, name FROM unified_projects WHERE status = ANY(%s) ORDER BY name",
            (list(PROJECT_DEFAULT_STATUSES),),
        )
        projects_facet = {str(r["id"]): r["name"] for r in cur.fetchall()}
    return rows, total, {"status": status_facet, "projects": projects_facet, "capabilities": capabilities()}


def get_task(task_id) -> Optional[dict]:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT t.*, p.name AS project_name, a.name AS agent_name
                 FROM unified_tasks t
                 LEFT JOIN unified_projects p ON p.id = t.project_id
                 LEFT JOIN agents a ON a.id = t.assigned_agent_id
                WHERE t.id = %s""",
            (int(task_id),),
        )
        row = cur.fetchone()
    if not row:
        return None
    task = dict(row)
    notes = list((task.get("metadata") or {}).get("notes") or [])
    task["notes"] = notes[-10:][::-1]
    return task


# ---- writes ----------------------------------------------------------------------
def _priority(value) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError):
        raise ValueError("priority must be an integer 1–10")
    if not 1 <= p <= 10:
        raise ValueError("priority must be an integer 1–10")
    return p


def _fetch(cur, task_id):
    cur.execute("SELECT * FROM unified_tasks WHERE id = %s", (int(task_id),))
    row = cur.fetchone()
    if not row:
        raise LookupError("task not found")
    return dict(row)


def _append_note(meta: dict, author: str, text: str) -> dict:
    note = {"ts": _now_iso(), "author": author, "text": text}
    notes = list(meta.get("notes") or [])
    notes.append(note)
    meta["notes"] = notes[-NOTE_CAP:]
    return note


def create_task(project_id, title, description="", priority=5, task_type="implementation", requested_by="cockpit"):
    title = (title or "").strip()
    if not 1 <= len(title) <= 500:
        raise ValueError("title must be 1–500 characters")
    priority = _priority(priority)
    if task_type not in TASK_TYPES:
        raise ValueError(f"task_type must be one of {', '.join(TASK_TYPES)}")
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("SELECT id, status FROM unified_projects WHERE id = %s", (int(project_id),))
        project = cur.fetchone()
        if not project:
            raise LookupError("project not found")
        if project["status"] in ("completed", "cancelled"):
            raise ValueError(f"project is {project['status']} — pick an open project")
        cur.execute(
            """INSERT INTO unified_tasks (project_id, title, description, status, priority, task_type, metadata,
                                          created_at, updated_at)
               VALUES (%s, %s, %s, 'pending', %s, %s, %s, NOW(), NOW()) RETURNING id""",
            (int(project_id), title, description or "", priority, task_type, Json({"created_via": requested_by})),
        )
        task_id = cur.fetchone()["id"]
    return get_task(task_id)


def set_status(task_id, status, requested_by="cockpit"):
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of {', '.join(TASK_STATUSES)}")
    with get_db_cursor(commit=True) as (conn, cur):
        row = _fetch(cur, task_id)
        if row.get("delegation_source") and row.get("status") == "in_progress":
            raise ValueError("the fleet worker owns this task while it runs — wait for it to finish")
        cur.execute(
            """UPDATE unified_tasks
                  SET status = %s,
                      updated_at = NOW(),
                      completed_at = CASE WHEN %s = 'completed' THEN NOW() ELSE completed_at END,
                      started_at = CASE WHEN %s = 'in_progress' AND started_at IS NULL THEN NOW() ELSE started_at END
                WHERE id = %s""",
            (status, status, status, int(task_id)),
        )
    return get_task(task_id)


def set_priority(task_id, priority, requested_by="cockpit"):
    priority = _priority(priority)
    with get_db_cursor(commit=True) as (conn, cur):
        _fetch(cur, task_id)
        cur.execute(
            "UPDATE unified_tasks SET priority = %s, updated_at = NOW() WHERE id = %s", (priority, int(task_id))
        )
    return get_task(task_id)


def add_note(task_id, text, author="cockpit"):
    text = (text or "").strip()
    if not text:
        raise ValueError("note text required")
    if len(text) > NOTE_MAX_CHARS:
        raise ValueError(f"note is longer than {NOTE_MAX_CHARS} characters")
    with get_db_cursor(commit=True) as (conn, cur):
        row = _fetch(cur, task_id)
        meta = dict(row.get("metadata") or {})
        note = _append_note(meta, author, text)
        cur.execute(
            "UPDATE unified_tasks SET metadata = %s, updated_at = NOW() WHERE id = %s", (Json(meta), int(task_id))
        )
    return note


def _known_capabilities(cur) -> list:
    known = set(capabilities())
    cur.execute("SELECT DISTINCT skill_name FROM agent_skills WHERE skill_name IS NOT NULL")
    known.update(r["skill_name"] for r in cur.fetchall())
    return sorted(known)


def delegate(task_id, capability, requested_by="cockpit"):
    capability = (capability or "").strip()
    with get_db_cursor(commit=True) as (conn, cur):
        known = _known_capabilities(cur)
        if capability not in known:
            near = difflib.get_close_matches(capability, known, n=3) or known[:3]
            raise ValueError(f"unknown capability {capability!r}; nearest: {', '.join(near)}")
        row = _fetch(cur, task_id)
        if row.get("status") not in ("pending", "blocked"):
            raise ValueError(f"only pending or blocked tasks can be delegated (this one is {row.get('status')})")
        if row.get("delegation_source") and row.get("status") == "pending":
            raise ValueError("this task is already queued for the fleet")
        args = {
            "capability": capability,
            "reason": (row.get("description") or row.get("title") or "")[:2000],
            "args": {"origin_task_id": row["id"], "requested_by": requested_by},
        }
        meta = dict(row.get("metadata") or {})
        _append_note(meta, requested_by, f"delegated to fleet: {capability}")
        cur.execute(
            """UPDATE unified_tasks
                  SET delegation_source = 'cockpit', delegation_args = %s, status = 'pending',
                      metadata = %s, updated_at = NOW()
                WHERE id = %s""",
            (Json(args), Json(meta), int(task_id)),
        )
    return get_task(task_id)
