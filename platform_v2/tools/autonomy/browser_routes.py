"""
Browser Automation Routes — Task CRUD, domain approval, results/screenshots

Registered on the autonomy_bp blueprint.

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from . import autonomy_bp
from .routes import admin_required

logger = logging.getLogger("browser_routes")

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


# ============================================================================
# Browser Tasks
# ============================================================================


@autonomy_bp.route("/api/browser/tasks", methods=["GET"])
@login_required
@admin_required
def get_browser_tasks():
    """Get browser automation tasks."""
    try:
        status = request.args.get("status")
        limit = min(int(request.args.get("limit", 50)), 100)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if status:
            cur.execute(
                """
                SELECT id, name, task_type, url, status, priority, schedule_cron,
                       last_run_at, next_run_at, error_message, created_at
                FROM browser_tasks WHERE status = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (status, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, name, task_type, url, status, priority, schedule_cron,
                       last_run_at, next_run_at, error_message, created_at
                FROM browser_tasks
                ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
        tasks = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()
        return jsonify({"success": True, "tasks": tasks})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/browser/tasks", methods=["POST"])
@login_required
@admin_required
def create_browser_task():
    """Create a new browser automation task."""
    try:
        data = request.json
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO browser_tasks
            (name, task_type, url, instructions, schedule_cron, priority,
             timeout_seconds, created_by, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data.get("name", "Browser Task"),
                data.get("task_type", "screenshot"),
                data["url"],
                data.get("instructions"),
                data.get("schedule_cron"),
                data.get("priority", 5),
                data.get("timeout_seconds", 60),
                current_user.id,
                json.dumps(data.get("metadata", {})),
            ),
        )
        task_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "id": task_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/browser/tasks/<int:task_id>/run", methods=["POST"])
@login_required
@admin_required
def run_browser_task(task_id):
    """Execute a browser task immediately."""
    try:
        from browser_automation import BrowserAutomation

        ba = BrowserAutomation()
        result = ba.execute_task(task_id)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/browser/tasks/<int:task_id>", methods=["DELETE"])
@login_required
@admin_required
def delete_browser_task(task_id):
    """Delete a browser task and its results."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM browser_task_results WHERE task_id = %s", (task_id,))
        cur.execute("DELETE FROM browser_tasks WHERE id = %s", (task_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Task Results
# ============================================================================


@autonomy_bp.route("/api/browser/tasks/<int:task_id>/results", methods=["GET"])
@login_required
@admin_required
def get_task_results(task_id):
    """Get results for a browser task."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT * FROM browser_task_results
            WHERE task_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (task_id,),
        )
        results = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Domain Approval
# ============================================================================


@autonomy_bp.route("/api/browser/domains", methods=["GET"])
@login_required
@admin_required
def get_approved_domains():
    """Get approved browser domains."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT bd.*, u.username as approved_by_name
            FROM browser_approved_domains bd
            LEFT JOIN users u ON bd.approved_by = u.id
            ORDER BY bd.created_at DESC
            """
        )
        domains = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "domains": domains})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/browser/domains", methods=["POST"])
@login_required
@admin_required
def add_approved_domain():
    """Add a domain to the approved list."""
    try:
        data = request.json
        from browser_automation import BrowserAutomation

        ba = BrowserAutomation()
        success = ba.approve_domain(
            domain=data["domain"],
            approved_by=current_user.id,
            notes=data.get("notes", ""),
        )
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/browser/domains/<int:domain_id>", methods=["DELETE"])
@login_required
@admin_required
def remove_approved_domain(domain_id):
    """Remove a domain from the approved list."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("DELETE FROM browser_approved_domains WHERE id = %s AND auto_approved = FALSE", (domain_id,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
