"""
Department HQ — Approvals Routes
=================================
Consolidated view of pending Tier-2 approvals with web approve/deny buttons.
Mirrors the Telegram approval flow so agents can be approved via either channel.
"""

import logging

from flask import jsonify, request
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def register_approvals_routes(bp, admin_required_decorator):
    """Register all approvals endpoints on the department_hq blueprint."""

    @bp.route("/api/approvals/pending", methods=["GET"])
    @login_required
    @admin_required_decorator
    def approvals_pending():
        """List all pending Tier-2 approvals with enriched metadata."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, action_type, action_data, tier, priority,
                              requested_by, reason, created_at, expires_at
                       FROM autonomy_approval_queue
                       WHERE status = 'pending' AND tier >= 2
                       ORDER BY priority ASC, created_at ASC"""
                )
                rows = [dict(r) for r in cur.fetchall()]

            approvals = []
            for r in rows:
                # Serialize timestamps
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
                if r.get("expires_at"):
                    r["expires_at"] = r["expires_at"].isoformat()
                # Classify by type for UI grouping
                at = r.get("action_type", "")
                if at.startswith("compliance_fix_"):
                    r["category"] = "compliance_fix"
                    r["display_name"] = "Compliance Fix"
                elif at == "cloud_throughput_escalation":
                    r["category"] = "cloud_escalation"
                    r["display_name"] = "Cloud Model Escalation"
                elif at == "create_agent":
                    r["category"] = "agent_creation"
                    r["display_name"] = "Create New Agent"
                else:
                    r["category"] = "other"
                    r["display_name"] = at
                approvals.append(r)

            return jsonify({"success": True, "approvals": approvals, "count": len(approvals)})
        except Exception as exc:
            logger.error("approvals_pending error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/approvals/<int:approval_id>/approve", methods=["POST"])
    @login_required
    @admin_required_decorator
    def approvals_approve(approval_id):
        """Approve a pending approval via web UI (mirrors Telegram approve)."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'approved', approved_by = %s,
                           approved_at = NOW(), updated_at = NOW()
                       WHERE id = %s AND status = 'pending'
                       RETURNING action_type, id""",
                    (current_user.id, approval_id),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404

            logger.info(
                "Approval #%s (%s) approved via web by user %s",
                approval_id,
                row.get("action_type") if isinstance(row, dict) else row[0],
                current_user.id,
            )
            return jsonify(
                {
                    "success": True,
                    "approval_id": approval_id,
                    "action_type": row.get("action_type") if isinstance(row, dict) else row[0],
                    "note": "Approved. Agent loop will execute shortly.",
                }
            )
        except Exception as exc:
            logger.error("approvals_approve error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/approvals/<int:approval_id>/deny", methods=["POST"])
    @login_required
    @admin_required_decorator
    def approvals_deny(approval_id):
        """Deny a pending approval via web UI (mirrors Telegram deny)."""
        try:
            from database import get_db_cursor

            data = request.get_json(silent=True) or {}
            reason = data.get("reason", "Denied via web UI")

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE autonomy_approval_queue
                       SET status = 'rejected', approved_by = %s,
                           approved_at = NOW(), rejected_reason = %s,
                           updated_at = NOW()
                       WHERE id = %s AND status = 'pending'
                       RETURNING action_type""",
                    (current_user.id, reason, approval_id),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Not found or already processed"}), 404

            return jsonify({"success": True, "approval_id": approval_id})
        except Exception as exc:
            logger.error("approvals_deny error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/approvals/history", methods=["GET"])
    @login_required
    @admin_required_decorator
    def approvals_history():
        """Recent approval history (approved/rejected/executed/expired)."""
        try:
            from database import get_db_cursor

            limit = min(request.args.get("limit", 50, type=int), 200)
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, action_type, status, approved_at,
                              approved_by, rejected_reason, executed_at,
                              created_at, tier
                       FROM autonomy_approval_queue
                       WHERE status != 'pending'
                       ORDER BY updated_at DESC LIMIT %s""",
                    (limit,),
                )
                rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                for k in ["approved_at", "executed_at", "created_at"]:
                    if r.get(k):
                        r[k] = r[k].isoformat()
            return jsonify({"success": True, "history": rows})
        except Exception as exc:
            logger.error("approvals_history error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
