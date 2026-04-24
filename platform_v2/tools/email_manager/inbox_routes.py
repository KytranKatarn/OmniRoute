"""Email HQ — Inbox tab: message browser from email_activity_log."""

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_inbox_routes(bp, admin_required):

    @bp.route("/api/email/inbox/messages", methods=["GET"])
    @login_required
    @admin_required
    def email_inbox_messages():
        """Recent received messages for a mailbox (from email_activity_log)."""
        address = request.args.get("address", "")
        limit = min(request.args.get("limit", 50, type=int), 500)
        with get_db_cursor() as (conn, cur):
            if address:
                cur.execute(
                    """SELECT id, direction, from_address, to_address, subject,
                              read_at, logged_at, message_id
                       FROM email_activity_log
                       WHERE mailbox_address = %s AND direction = 'received'
                       ORDER BY logged_at DESC LIMIT %s""",
                    (address, limit),
                )
            else:
                cur.execute(
                    """SELECT id, mailbox_address, direction, from_address,
                              to_address, subject, read_at, logged_at, message_id
                       FROM email_activity_log
                       WHERE direction = 'received'
                       ORDER BY logged_at DESC LIMIT %s""",
                    (limit,),
                )
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                for k in ("read_at", "logged_at"):
                    if r.get(k):
                        r[k] = r[k].isoformat()
        return jsonify({"messages": rows, "mailbox": address})

    @bp.route("/api/email/inbox/mark-read", methods=["POST"])
    @login_required
    @admin_required
    def email_mark_read():
        """Mark a message as read."""
        data = request.get_json() or {}
        msg_id = data.get("id")
        if not msg_id:
            return jsonify({"error": "id required"}), 400
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE email_activity_log SET read_at=NOW() WHERE id=%s", (msg_id,))
        return jsonify({"success": True})
