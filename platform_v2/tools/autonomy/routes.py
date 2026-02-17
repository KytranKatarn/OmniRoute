"""
Autonomy Module Routes — Dashboard, Approval Queue, Loop Status, Config API

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import json
import logging
import os
from datetime import datetime
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import current_app, jsonify, render_template, request
from flask_login import current_user, login_required

from rbac import Permission, has_permission

from . import autonomy_bp

logger = logging.getLogger("autonomy")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", "archiepass"),
    )


def admin_required(f):
    """Decorator to require admin access"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permission.ADMIN_ACCESS, current_user):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


# ============================================================================
# Dashboard
# ============================================================================


@autonomy_bp.route("/")
@login_required
@admin_required
def index():
    """Autonomy dashboard"""
    return render_template("tools/autonomy.html")


# ============================================================================
# Agent Loop Status
# ============================================================================


@autonomy_bp.route("/api/status")
@login_required
@admin_required
def get_loop_status():
    """Get agent loop status and recent activity."""
    try:
        # Get agent loop instance
        agent_loop = current_app.config.get("AGENT_LOOP")
        loop_status = agent_loop.get_status() if agent_loop else {"running": False, "jobs": [], "job_count": 0}

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Recent loop cycles (last 24h)
        cur.execute(
            """
            SELECT job_name,
                   COUNT(*) as cycles,
                   SUM(items_processed) as total_processed,
                   SUM(items_failed) as total_failed,
                   AVG(duration_ms)::integer as avg_duration_ms,
                   MAX(created_at) as last_run
            FROM autonomy_loop_log
            WHERE created_at > NOW() - INTERVAL '24 hours'
            GROUP BY job_name
            ORDER BY job_name
            """
        )
        job_stats = [dict(r) for r in cur.fetchall()]

        # Pending approvals count
        cur.execute("SELECT COUNT(*) as count FROM autonomy_approval_queue WHERE status = 'pending'")
        pending_approvals = cur.fetchone()["count"]

        # Recent log entries
        cur.execute(
            """
            SELECT job_name, status, items_processed, items_failed, duration_ms, error_message, created_at
            FROM autonomy_loop_log
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        recent_logs = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "loop": loop_status,
                "job_stats_24h": job_stats,
                "pending_approvals": pending_approvals,
                "recent_logs": recent_logs,
            }
        )
    except Exception as e:
        logger.error(f"Failed to get loop status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/loop/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_loop():
    """Start or stop the agent loop."""
    try:
        agent_loop = current_app.config.get("AGENT_LOOP")
        if not agent_loop:
            return jsonify({"success": False, "error": "Agent loop not initialized"}), 500

        action = request.json.get("action", "toggle")

        if action == "start" or (action == "toggle" and not agent_loop.is_running):
            agent_loop.start()
            return jsonify({"success": True, "running": True, "message": "Agent loop started"})
        elif action == "stop" or (action == "toggle" and agent_loop.is_running):
            agent_loop.stop()
            return jsonify({"success": True, "running": False, "message": "Agent loop stopped"})
        else:
            return jsonify({"success": True, "running": agent_loop.is_running})
    except Exception as e:
        logger.error(f"Failed to toggle loop: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Approval Queue
# ============================================================================


@autonomy_bp.route("/api/approvals")
@login_required
@admin_required
def get_approvals():
    """Get approval queue items."""
    try:
        status_filter = request.args.get("status", "pending")
        limit = min(int(request.args.get("limit", 50)), 100)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if status_filter == "all":
            cur.execute(
                """
                SELECT a.*, u.username as approved_by_name
                FROM autonomy_approval_queue a
                LEFT JOIN users u ON a.approved_by = u.id
                ORDER BY a.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        else:
            cur.execute(
                """
                SELECT a.*, u.username as approved_by_name
                FROM autonomy_approval_queue a
                LEFT JOIN users u ON a.approved_by = u.id
                WHERE a.status = %s
                ORDER BY a.priority ASC, a.created_at ASC
                LIMIT %s
                """,
                (status_filter, limit),
            )
        items = [dict(r) for r in cur.fetchall()]

        # Count by status
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM autonomy_approval_queue
            GROUP BY status
            """
        )
        counts = {r["status"]: r["count"] for r in cur.fetchall()}

        cur.close()
        conn.close()

        return jsonify({"success": True, "items": items, "counts": counts})
    except Exception as e:
        logger.error(f"Failed to get approvals: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/approvals/<int:approval_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_action(approval_id):
    """Approve a pending action."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE autonomy_approval_queue
            SET status = 'approved', approved_by = %s, approved_at = NOW(), updated_at = NOW()
            WHERE id = %s AND status = 'pending'
            RETURNING id, action_type
            """,
            (current_user.id, approval_id),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return jsonify({"success": False, "error": "Item not found or not pending"}), 404

        return jsonify({"success": True, "message": f"Approved: {result['action_type']}"})
    except Exception as e:
        logger.error(f"Failed to approve action: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/approvals/<int:approval_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_action(approval_id):
    """Reject a pending action."""
    try:
        reason = request.json.get("reason", "")
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE autonomy_approval_queue
            SET status = 'rejected', approved_by = %s, rejected_reason = %s, updated_at = NOW()
            WHERE id = %s AND status = 'pending'
            RETURNING id, action_type
            """,
            (current_user.id, reason, approval_id),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return jsonify({"success": False, "error": "Item not found or not pending"}), 404

        return jsonify({"success": True, "message": f"Rejected: {result['action_type']}"})
    except Exception as e:
        logger.error(f"Failed to reject action: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Configuration
# ============================================================================


@autonomy_bp.route("/api/config")
@login_required
@admin_required
def get_config():
    """Get all autonomy configuration."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM autonomy_config ORDER BY config_key")
        configs = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"success": True, "configs": configs})
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@autonomy_bp.route("/api/config/<config_key>", methods=["PUT"])
@login_required
@admin_required
def update_config(config_key):
    """Update a configuration value."""
    try:
        value = request.json.get("value")
        if value is None:
            return jsonify({"success": False, "error": "Missing value"}), 400

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            UPDATE autonomy_config
            SET config_value = %s, updated_by = %s, updated_at = NOW()
            WHERE config_key = %s
            RETURNING config_key
            """,
            (json.dumps(value), current_user.id, config_key),
        )
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return jsonify({"success": False, "error": "Config key not found"}), 404

        return jsonify({"success": True, "message": f"Updated {config_key}"})
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# Loop History
# ============================================================================


@autonomy_bp.route("/api/history")
@login_required
@admin_required
def get_history():
    """Get agent loop execution history."""
    try:
        job_name = request.args.get("job")
        limit = min(int(request.args.get("limit", 100)), 500)
        hours = int(request.args.get("hours", 24))

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if job_name:
            cur.execute(
                """
                SELECT * FROM autonomy_loop_log
                WHERE job_name = %s AND created_at > NOW() - make_interval(hours => %s)
                ORDER BY created_at DESC LIMIT %s
                """,
                (job_name, hours, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM autonomy_loop_log
                WHERE created_at > NOW() - make_interval(hours => %s)
                ORDER BY created_at DESC LIMIT %s
                """,
                (hours, limit),
            )
        logs = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify({"success": True, "logs": logs, "count": len(logs)})
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
