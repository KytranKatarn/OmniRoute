"""Email HQ routes — unified inbox, assign-to-agent, rules, and stats."""

import logging
from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_hq_routes(bp, admin_required):

    @bp.route("/api/hq/unified-inbox", methods=["GET"])
    @login_required
    def hq_unified_inbox():
        limit = min(int(request.args.get("limit", 50)), 200)
        mailbox_filter = request.args.get("mailbox_id", type=int)
        status_filter = request.args.get("status", "")

        with get_db_cursor() as (_, cur):
            where_clauses = []
            params = []
            if mailbox_filter:
                where_clauses.append("m.id = %s")
                params.append(mailbox_filter)
            if status_filter == "unread":
                where_clauses.append("al.read_at IS NULL")
            elif status_filter == "read":
                where_clauses.append("al.read_at IS NOT NULL")
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            params.append(limit)
            cur.execute(
                f"""
                SELECT al.id, m.id AS mailbox_id, al.direction, al.from_address,
                       al.to_address, al.subject, al.logged_at AS received_at, al.read_at,
                       m.address AS mailbox_address, m.mailbox_type,
                       ea.assigned_agent, ea.status AS assignment_status
                FROM email_activity_log al
                JOIN email_mailboxes m ON m.address = al.mailbox_address
                LEFT JOIN email_assignments ea ON ea.email_id = al.id
                  AND ea.status = 'open'
                {where_sql}
                ORDER BY al.logged_at DESC NULLS LAST
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
        emails = [
            {
                "id": r["id"],
                "mailbox_id": r["mailbox_id"],
                "mailbox_address": r["mailbox_address"],
                "mailbox_type": r["mailbox_type"],
                "direction": r["direction"],
                "from_address": r["from_address"] or "",
                "to_address": r["to_address"] or "",
                "subject": r["subject"] or "(no subject)",
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                "is_read": r["read_at"] is not None,
                "assigned_agent": r["assigned_agent"],
                "assignment_status": r["assignment_status"],
            }
            for r in rows
        ]
        return jsonify({"emails": emails, "count": len(emails)})

    @bp.route("/api/hq/assign", methods=["POST"])
    @login_required
    def hq_assign():
        data = request.get_json(silent=True) or {}
        email_id = data.get("email_id")
        agent_name = str(data.get("agent_name", "")).strip()
        notes = str(data.get("notes", "")).strip()[:500]
        if not email_id or not agent_name:
            return jsonify({"error": "email_id and agent_name required"}), 400
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """
                INSERT INTO email_assignments
                    (email_id, assigned_agent, assigned_by, notes, status)
                VALUES (%s, %s, 'manual', %s, 'open')
                ON CONFLICT DO NOTHING
                """,
                (email_id, agent_name, notes or None),
            )
        logger.info("email_hq.assign: email=%s agent=%s", email_id, agent_name)
        return jsonify({"assigned": True, "email_id": email_id, "agent": agent_name})

    @bp.route("/api/hq/stats", methods=["GET"])
    @login_required
    def hq_stats():
        with get_db_cursor() as (_, cur):
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE logged_at > NOW() - INTERVAL '24h') AS last_24h,
                    COUNT(*) FILTER (WHERE read_at IS NULL
                        AND logged_at > NOW() - INTERVAL '24h') AS unread_24h,
                    COUNT(*) FILTER (WHERE logged_at > NOW() - INTERVAL '24h'
                        AND direction = 'received') AS inbound_24h,
                    COUNT(DISTINCT mailbox_address) AS active_mailboxes
                FROM email_activity_log
                """
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS flagged FROM email_assignments "
                "WHERE status = 'open' AND created_at < NOW() - INTERVAL '24h'"
            )
            flagged_row = cur.fetchone()
        return jsonify(
            {
                "last_24h": int(row["last_24h"] or 0),
                "unread_24h": int(row["unread_24h"] or 0),
                "inbound_24h": int(row["inbound_24h"] or 0),
                "active_mailboxes": int(row["active_mailboxes"] or 0),
                "flagged_unanswered": int(flagged_row["flagged"] or 0),
            }
        )

    @bp.route("/api/hq/rules", methods=["GET"])
    @login_required
    def hq_rules():
        with get_db_cursor() as (_, cur):
            cur.execute(
                "SELECT id, name, condition_field, condition_value, "
                "action, action_value, is_active FROM email_rules ORDER BY id"
            )
            rows = cur.fetchall()
        return jsonify({"rules": [dict(r) for r in rows]})
