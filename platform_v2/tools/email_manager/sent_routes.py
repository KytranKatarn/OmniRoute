"""Email HQ — Sent tab: outbound email log."""

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_sent_routes(bp, admin_required):

    @bp.route("/api/email/sent/messages", methods=["GET"])
    @login_required
    @admin_required
    def email_sent_messages():
        """Sent messages for a mailbox or all mailboxes."""
        address = request.args.get("address", "")
        limit = min(request.args.get("limit", 50, type=int), 500)
        with get_db_cursor() as (conn, cur):
            if address:
                cur.execute(
                    """SELECT id, from_address, to_address, subject, logged_at, message_id
                       FROM email_activity_log
                       WHERE mailbox_address = %s AND direction = 'sent'
                       ORDER BY logged_at DESC LIMIT %s""",
                    (address, limit),
                )
            else:
                cur.execute(
                    """SELECT al.id, al.mailbox_address, al.from_address, al.to_address,
                              al.subject, al.logged_at, m.display_name AS mailbox_display
                       FROM email_activity_log al
                       LEFT JOIN email_mailboxes m ON m.address = al.mailbox_address
                       WHERE al.direction = 'sent'
                       ORDER BY al.logged_at DESC LIMIT %s""",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("logged_at"):
                    r["logged_at"] = r["logged_at"].isoformat()
        return jsonify({"messages": rows})
