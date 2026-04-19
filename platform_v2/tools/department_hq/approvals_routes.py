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
        """List pending approvals from every source the platform uses.

        Unified over three sources that all share the "waiting for a
        human to approve" semantic:
          - autonomy_approval_queue (Tier-2 agent loop actions)
          - contractor_approval_requests (contractor dispatch cost gate)
          - bridge_jobs with status='pending_approval' (cloud dispatch gate)

        Every row is normalised to the same shape: id, source, category,
        display_name, reason/summary, created_at, agent_name (if any).
        IDs are source-prefixed ("autonomy:123", "bridge:456") so the
        approve/deny endpoints can dispatch to the right table.
        """
        try:
            from database import get_db_cursor

            approvals: list = []

            with get_db_cursor() as (conn, cur):
                # 1. autonomy_approval_queue — Tier-2 agent loop
                cur.execute(
                    """SELECT id, action_type, action_data, tier, priority,
                              requested_by, reason, created_at, expires_at
                       FROM autonomy_approval_queue
                       WHERE status = 'pending' AND tier >= 2
                       ORDER BY priority ASC, created_at ASC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    at = r.get("action_type", "")
                    if at.startswith("compliance_fix_"):
                        category, display = "compliance_fix", "Compliance Fix"
                    elif at == "cloud_throughput_escalation":
                        category, display = "cloud_escalation", "Cloud Model Escalation"
                    elif at == "create_agent":
                        category, display = "agent_creation", "Create New Agent"
                    else:
                        category, display = "other", at
                    approvals.append(
                        {
                            "id": f"autonomy:{r['id']}",
                            "source": "autonomy_approval_queue",
                            "source_id": r["id"],
                            "category": category,
                            "display_name": display,
                            "action_type": at,
                            "tier": r.get("tier"),
                            "priority": r.get("priority"),
                            "reason": r.get("reason"),
                            "requested_by": r.get("requested_by"),
                            "agent_name": None,
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                            "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                        }
                    )

                # 2. contractor_approval_requests — cost-gated contractor dispatch
                cur.execute(
                    """SELECT r.id, r.agent_id, r.task_type, r.task_description,
                              r.module_source, r.estimated_cost, r.estimated_tokens,
                              r.contractor_provider, r.contractor_model,
                              r.priority, r.created_at, r.expires_at,
                              a.name AS agent_name, a.display_name AS agent_display
                       FROM contractor_approval_requests r
                       LEFT JOIN agents a ON a.id = r.agent_id
                       WHERE r.status = 'pending'
                       ORDER BY r.priority ASC NULLS LAST, r.created_at ASC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    approvals.append(
                        {
                            "id": f"contractor:{r['id']}",
                            "source": "contractor_approval_requests",
                            "source_id": r["id"],
                            "category": "contractor_dispatch",
                            "display_name": "Contractor Dispatch",
                            "action_type": r.get("task_type") or "contractor_dispatch",
                            "module_source": r.get("module_source"),
                            "contractor": f"{r.get('contractor_provider') or ''}/{r.get('contractor_model') or ''}".strip(
                                "/"
                            ),
                            "estimated_cost": (
                                float(r["estimated_cost"]) if r.get("estimated_cost") is not None else None
                            ),
                            "estimated_tokens": r.get("estimated_tokens"),
                            "priority": r.get("priority"),
                            "reason": (r.get("task_description") or "")[:300] or None,
                            "agent_name": r.get("agent_display") or r.get("agent_name"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                            "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                        }
                    )

                # 3. bridge_jobs.pending_approval — cloud dispatch gate
                cur.execute(
                    """SELECT id, agent_name, module_source, description, created_at
                       FROM bridge_jobs
                       WHERE status = 'pending_approval'
                       ORDER BY created_at ASC"""
                )
                for r in cur.fetchall():
                    r = dict(r)
                    desc = r.get("description") or ""
                    approvals.append(
                        {
                            "id": f"bridge:{r['id']}",
                            "source": "bridge_jobs",
                            "source_id": r["id"],
                            "category": "cloud_dispatch",
                            "display_name": "Cloud Dispatch",
                            "action_type": "cloud_dispatch",
                            "module_source": r.get("module_source"),
                            "reason": desc[:300] if desc else None,
                            "agent_name": r.get("agent_name"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                        }
                    )

            by_source = {}
            for a in approvals:
                by_source[a["source"]] = by_source.get(a["source"], 0) + 1

            return jsonify(
                {
                    "success": True,
                    "approvals": approvals,
                    "count": len(approvals),
                    "by_source": by_source,
                }
            )
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
