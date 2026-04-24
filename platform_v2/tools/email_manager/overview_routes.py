"""Email HQ — Overview tab: stats cards + activity feed."""

import logging

from database import get_db_cursor
from flask import jsonify
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_overview_routes(bp, admin_required):

    @bp.route("/api/email/overview/stats", methods=["GET"])
    @login_required
    @admin_required
    def email_overview_stats():
        """Stats: unread, sent today, provisioned, not provisioned."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM email_activity_log
                   WHERE direction='received' AND read_at IS NULL)        AS unread,
                  (SELECT COUNT(*) FROM email_activity_log
                   WHERE direction='sent'
                     AND logged_at >= NOW() - INTERVAL '24 hours')        AS sent_today,
                  (SELECT COUNT(*) FROM email_mailboxes
                   WHERE provisioned = TRUE AND active = TRUE)            AS provisioned,
                  (SELECT COUNT(*) FROM email_mailboxes
                   WHERE provisioned = FALSE AND active = TRUE)           AS not_provisioned
                """
            )
            row = cur.fetchone()
        return jsonify(
            {
                "unread": row["unread"],
                "sent_today": row["sent_today"],
                "provisioned": row["provisioned"],
                "not_provisioned": row["not_provisioned"],
            }
        )

    @bp.route("/api/email/overview/feed", methods=["GET"])
    @login_required
    @admin_required
    def email_overview_feed():
        """Last 50 email events across all mailboxes."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT al.id, al.mailbox_address, al.direction,
                       al.from_address, al.to_address, al.subject,
                       al.logged_at,
                       m.display_name AS mailbox_display
                FROM email_activity_log al
                LEFT JOIN email_mailboxes m ON m.address = al.mailbox_address
                ORDER BY al.logged_at DESC
                LIMIT 50
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("logged_at"):
                    r["logged_at"] = r["logged_at"].isoformat()
        return jsonify({"events": rows})
