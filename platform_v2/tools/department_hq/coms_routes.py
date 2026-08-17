"""
Department HQ — COMs Tab Routes

A.R.C.H.I.E.'s unified communications center. All Telegram messaging flows
through here — message feed, configuration, migration status.

Decision #441 — LLM Ecosystem Redesign Phase 6
"""

import logging
import os

from flask import jsonify, request
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Known Telegram callers — tracked for migration status.
#
# "module" MUST be the dotted source_module identifier the call site passes to
# telegram_service (what lands in telegram_message_log.source_module) — NOT a
# filename. The old list held filenames ('department_dispatcher.py') which can
# never intersect logged values ('security_network.jobs'), so the meter was
# permanently stuck at 0/9 (#5706). Matching is prefix-tolerant so suffixed
# identifiers like 'department_hq.jobs.token_welfare_monitor' still count.
KNOWN_SENDERS = [
    {
        "module": "department_hq.services.department_dispatcher",
        "location": "tools/department_hq/services/department_dispatcher.py",
        "purpose": "Dispatch advisories, cross-department alerts, cloud escalation",
        "agent": "A.R.C.H.I.E.",
    },
    {
        "module": "telegram_approval",
        "location": "ai_bridge/agent_loop.py (approvals via services/telegram_service.py)",
        "purpose": "Approval requests, escalation buttons, briefings",
        "agent": "A.R.C.H.I.E.",
    },
    {
        "module": "telegram_gateway",
        "location": "ai_bridge/telegram_gateway.py",
        "purpose": "Inbound message handler + bot polling (keep as-is)",
        "agent": "A.R.C.H.I.E.",
    },
    {
        "module": "forge_self_heal",
        "location": "tools/repair_bay/services/forge_self_heal.py",
        "purpose": "Self-healing pipeline alerts",
        "agent": "F.O.R.G.E.",
    },
    {
        "module": "forge_pipeline",
        "location": "tools/repair_bay/services/forge_pipeline.py",
        "purpose": "PR review, scan results",
        "agent": "F.O.R.G.E.",
    },
    {
        "module": "github_routes",
        "location": "tools/repair_bay/github_routes.py",
        "purpose": "GitHub webhook notifications",
        "agent": "F.O.R.G.E.",
    },
    {
        "module": "security_network.jobs",
        "location": "tools/security_network/jobs.py",
        "purpose": "Security scan alerts, compliance failures",
        "agent": "V.I.G.I.L.",
    },
    {
        "module": "compliance_safe_exec",
        "location": "tools/security_network/compliance_safe_exec.py",
        "purpose": "Compliance remediation results",
        "agent": "V.I.G.I.L.",
    },
    {
        "module": "consciousness.jobs",
        "location": "tools/consciousness/jobs.py",
        "purpose": "Analysis completion, embedding progress",
        "agent": "C.O.D.E.X.",
    },
    {
        "module": "qa_service",
        "location": "services/qa_service.py",
        "purpose": "QA test results, P.R.O.B.E. reports",
        "agent": "P.R.O.B.E.",
    },
]


def register_coms_routes(bp, admin_required):
    """Register COMs tab API routes on the blueprint."""

    # ── Message Feed ──────────────────────────────────────────────────

    @bp.route("/api/coms/messages")
    @admin_required
    def coms_messages():
        """Message feed — all outbound Telegram messages logged by telegram_service."""
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        category = request.args.get("category")
        source = request.args.get("source_agent")
        status = request.args.get("status")

        with get_db_cursor() as (conn, cur):
            query = "SELECT * FROM telegram_message_log WHERE 1=1"
            params = []

            if category:
                query += " AND category = %s"
                params.append(category)
            if source:
                query += " AND source_agent = %s"
                params.append(source)
            if status:
                query += " AND status = %s"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            messages = []
            for row in cur.fetchall():
                r = dict(row)
                r["created_at"] = str(r["created_at"]) if r["created_at"] else None
                messages.append(r)

            # Total count for pagination
            count_query = "SELECT COUNT(*) AS total FROM telegram_message_log WHERE 1=1"
            count_params = []
            if category:
                count_query += " AND category = %s"
                count_params.append(category)
            if source:
                count_query += " AND source_agent = %s"
                count_params.append(source)
            if status:
                count_query += " AND status = %s"
                count_params.append(status)

            cur.execute(count_query, count_params)
            total = cur.fetchone()["total"]

        return jsonify({"success": True, "messages": messages, "total": total})

    @bp.route("/api/coms/stats")
    @admin_required
    def coms_stats():
        """COMs dashboard stats — message counts, delivery rates, active agents."""
        with get_db_cursor() as (conn, cur):
            # Overall stats
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_messages,
                    COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                    COUNT(*) FILTER (WHERE status = 'throttled') AS throttled,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                    COUNT(DISTINCT source_agent) AS unique_agents,
                    COUNT(DISTINCT category) AS unique_categories
                FROM telegram_message_log
            """
            )
            overall = dict(cur.fetchone())

            # Last 24h breakdown by category
            cur.execute(
                """
                SELECT category,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'sent') AS sent,
                       COUNT(*) FILTER (WHERE status = 'throttled') AS throttled
                FROM telegram_message_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY category
                ORDER BY total DESC
            """
            )
            by_category = [dict(r) for r in cur.fetchall()]

            # Last 24h breakdown by source agent
            cur.execute(
                """
                SELECT source_agent,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status = 'sent') AS sent
                FROM telegram_message_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                  AND source_agent IS NOT NULL
                GROUP BY source_agent
                ORDER BY total DESC
            """
            )
            by_agent = [dict(r) for r in cur.fetchall()]

        return jsonify(
            {
                "success": True,
                "overall": overall,
                "last_24h": {"by_category": by_category, "by_agent": by_agent},
            }
        )

    # ── Configuration ─────────────────────────────────────────────────

    @bp.route("/api/coms/config")
    @admin_required
    def coms_config():
        """Current Telegram configuration and connection health."""
        from services.telegram_service import CATEGORIES, THROTTLE

        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        return jsonify(
            {
                "success": True,
                "config": {
                    "bot_token_set": bool(token),
                    "bot_token_preview": f"...{token[-8:]}" if len(token) > 8 else "(not set)",
                    "chat_id": chat_id or "(not set)",
                    "categories": {
                        name: {
                            "icon": cat["icon"],
                            "label": cat["label"],
                            "priority": cat["priority"],
                            "throttle_seconds": THROTTLE.get(cat["priority"], 300),
                        }
                        for name, cat in CATEGORIES.items()
                    },
                },
            }
        )

    # ── Migration Status ──────────────────────────────────────────────

    @bp.route("/api/coms/migration")
    @admin_required
    def coms_migration():
        """Migration status — which modules route through telegram_service vs direct API."""
        with get_db_cursor() as (conn, cur):
            # Check which source_modules have logged messages (= migrated)
            cur.execute(
                """
                SELECT DISTINCT source_module
                FROM telegram_message_log
                WHERE source_module IS NOT NULL
            """
            )
            migrated_modules = {r["source_module"] for r in cur.fetchall()}

        senders = []
        for sender in KNOWN_SENDERS:
            # Prefix-tolerant: 'department_hq.jobs.token_welfare_monitor'
            # counts for a 'department_hq.jobs' sender entry.
            is_migrated = any(m == sender["module"] or m.startswith(sender["module"] + ".") for m in migrated_modules)
            # telegram_gateway is special — it stays as inbound handler
            if sender["module"] == "telegram_gateway":
                status = "keep"
                note = "Inbound handler — not migrated, stays as-is"
            elif is_migrated:
                status = "migrated"
                note = "Routing through telegram_service"
            else:
                status = "direct"
                note = "Still calling Telegram API directly"

            senders.append(
                {
                    "module": sender["module"],
                    "location": sender["location"],
                    "purpose": sender["purpose"],
                    "agent": sender["agent"],
                    "status": status,
                    "note": note,
                }
            )

        migrated_count = sum(1 for s in senders if s["status"] == "migrated")
        total_migratable = sum(1 for s in senders if s["status"] != "keep")

        return jsonify(
            {
                "success": True,
                "senders": senders,
                "progress": {
                    "migrated": migrated_count,
                    "total": total_migratable,
                    "percentage": round(migrated_count / max(total_migratable, 1) * 100),
                },
            }
        )

    # ── Send Test Message ─────────────────────────────────────────────

    @bp.route("/api/coms/test", methods=["POST"])
    @admin_required
    def coms_test_message():
        """Send a test message through A.R.C.H.I.E.'s voice."""
        from services.telegram_service import send

        data = request.get_json() or {}
        category = data.get("category", "info")
        title = data.get("title", "COMs Test")
        message = data.get("message", "This is a test from the COMs center.")
        source_agent = data.get("source_agent", "A.R.C.H.I.E.")

        result = send(
            category,
            title,
            message,
            source_agent=source_agent,
            source_department="Executive Office",
            source_module="coms_routes",
            force=True,
        )
        return jsonify({"success": result.get("sent", False), "result": result})

    # ── Director Reports Feed ────────────────────────────────────────

    @bp.route("/api/coms/director-reports")
    @admin_required
    def coms_director_reports():
        """Get recent director reports for the COMs tab."""
        hours = request.args.get("hours", 24, type=int)
        limit = request.args.get("limit", 20, type=int)

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, department, director_agent, severity, category,
                              title, summary, escalated, triage_status, triage_action,
                              created_at
                       FROM director_reports
                       WHERE created_at > NOW() - INTERVAL '%s hours'
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (hours, limit),
                )
                reports = cur.fetchall()

            return jsonify({"reports": reports, "count": len(reports)})
        except Exception as e:
            logger.warning("coms_director_reports: %s", e)
            return jsonify({"reports": [], "count": 0, "error": str(e)})

    @bp.route("/api/coms/director-reports/pending")
    @admin_required
    def coms_director_reports_pending():
        """Pending-only triage inbox for COMs Inbox section."""
        limit = request.args.get("limit", 50, type=int)
        from services.director_report_service import get_pending_reports

        reports = get_pending_reports(limit=limit)
        return jsonify({"reports": reports, "count": len(reports)})

    @bp.route("/api/coms/director-reports/<int:report_id>/ack", methods=["POST"])
    @admin_required
    def coms_ack_report(report_id):
        """Manual triage action from COMs Inbox — Kytran override."""
        from services.director_report_service import triage_report

        data = request.get_json() or {}
        action = data.get("action", "suppress")
        if action not in ("resolve", "consolidate", "suppress", "escalate"):
            return jsonify({"error": "Invalid action"}), 400
        ok = triage_report(report_id, action, reason="Manual override by Kytran")
        return jsonify({"success": ok})

    @bp.route("/api/coms/triage-policies")
    @admin_required
    def coms_triage_policies():
        """Return all triage policies for the classification rules viewer."""
        from services.director_report_service import get_policies

        policies = get_policies()
        return jsonify({"policies": policies, "count": len(policies)})

    @bp.route("/api/coms/triage-policies", methods=["POST"])
    @admin_required
    def coms_create_triage_policy():
        """Create a new triage policy."""
        from services.director_report_service import create_policy

        data = request.get_json() or {}
        result = create_policy(
            action=data.get("action", ""),
            reason=data.get("reason", ""),
            severity=data.get("severity") or None,
            category_prefix=data.get("category_prefix") or None,
            director_agent_pattern=data.get("director_agent_pattern") or None,
            priority=int(data.get("priority", 50)),
        )
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result), 201

    @bp.route("/api/coms/triage-policies/<int:policy_id>", methods=["DELETE"])
    @admin_required
    def coms_delete_triage_policy(policy_id):
        """Delete a triage policy."""
        from services.director_report_service import delete_policy

        ok = delete_policy(policy_id)
        if not ok:
            return jsonify({"error": "Delete failed or not found"}), 404
        return jsonify({"success": True})
