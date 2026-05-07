"""
Backup Restore Service — owned by W.A.R.D.E.N.
Two-stage safe restore: sandbox first (P.R.O.B.E. QA), then production promote.
All restore operations dispatched through Department HQ delegate_task queue.
"""

from __future__ import annotations

import logging
from typing import Any

from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_restore_status(backup_id: int) -> dict[str, Any]:
    """Return current restore session status for a backup, or no_session if none exists."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id FROM backup_log WHERE id = %s", (backup_id,))
        if not cur.fetchone():
            return {"success": False, "error": "backup_not_found"}
        cur.execute(
            "SELECT * FROM module_restore_sessions WHERE backup_id = %s ORDER BY created_at DESC LIMIT 1",
            (backup_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": True, "session": None, "status": "no_session"}
        session = dict(row)
        if session.get("created_at"):
            session["created_at"] = session["created_at"].isoformat()
        if session.get("updated_at"):
            session["updated_at"] = session["updated_at"].isoformat()
        return {"success": True, "session": session, "status": session["status"]}


def initiate_sandbox_restore(backup_id: int, triggered_by: str = "user") -> dict[str, Any]:
    """
    Start a sandbox restore session for the given backup_id.
    Creates a module_restore_sessions row and delegates to W.A.R.D.E.N. via dispatch.
    Returns immediately with session_id (async operation).
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT id, file_path, backup_type FROM backup_log WHERE id = %s", (backup_id,))
        backup = cur.fetchone()
        if not backup:
            return {"success": False, "error": "backup_not_found"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO module_restore_sessions (backup_id, status, triggered_by)
               VALUES (%s, 'pending', %s) RETURNING id""",
            (backup_id, triggered_by),
        )
        session_id = cur.fetchone()["id"]

    # Delegate to W.A.R.D.E.N. via Department HQ
    try:
        from services.delegation_service import delegate_task

        delegate_task(
            capability="restore_sandbox",
            reason=f"Sandbox restore for backup #{backup_id} (session #{session_id})",
            args={"backup_id": backup_id, "session_id": session_id},
            delegation_source="automation",
        )
    except Exception as e:
        logger.warning("Could not delegate restore_sandbox task: %s", e)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE module_restore_sessions SET status='failed', updated_at=NOW() WHERE id=%s",
                (session_id,),
            )
        return {"success": False, "error": f"delegation_failed: {e}"}

    return {"success": True, "session_id": session_id, "status": "pending"}


def promote_to_production(session_id: int, triggered_by: str = "user") -> dict[str, Any]:
    """
    Promote a QA-verified sandbox restore to production.
    Only allowed when session status = 'qa_passed'.
    Delegates to W.A.R.D.E.N. via Department HQ.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, backup_id, status FROM module_restore_sessions WHERE id = %s",
            (session_id,),
        )
        session = cur.fetchone()
        if not session:
            return {"success": False, "error": "session_not_found"}
        if session["status"] != "qa_passed":
            return {
                "success": False,
                "error": f"cannot_promote: session status is '{session['status']}', must be 'qa_passed'",
            }

    try:
        from services.delegation_service import delegate_task

        delegate_task(
            capability="restore_production",
            reason=f"Promote session #{session_id} (backup #{session['backup_id']}) to production",
            args={"session_id": session_id, "backup_id": session["backup_id"]},
            delegation_source="automation",
        )
    except Exception as e:
        return {"success": False, "error": f"delegation_failed: {e}"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE module_restore_sessions SET status='promoting', updated_at=NOW() WHERE id=%s",
            (session_id,),
        )
    return {"success": True, "session_id": session_id, "status": "promoting"}
