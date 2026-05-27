"""Email HQ — Sent tab: outbound email log."""

import logging

from database import get_db_cursor
from flask import abort, jsonify, request
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

logger = logging.getLogger(__name__)


def register_sent_routes(bp, admin_required):

    @bp.route("/api/email/sent/messages", methods=["GET"])
    @login_required
    @admin_required
    def email_sent_messages():
        """Sent messages for a mailbox or all mailboxes.

        When an address filter is supplied and the caller is a COLLABORATOR,
        the address must belong to a visible mailbox — otherwise 403.
        When no address filter is supplied, results are scoped to the caller's
        visible mailboxes automatically.
        """
        address = request.args.get("address", "")
        limit = min(request.args.get("limit", 50, type=int), 500)
        visible = get_visible_mailbox_ids(current_user)

        with get_db_cursor() as (conn, cur):
            if address:
                if visible is not None:
                    cur.execute(
                        "SELECT id FROM email_mailboxes WHERE address = %s AND id = ANY(%s)",
                        (address, visible),
                    )
                    if not cur.fetchone():
                        abort(403)
                cur.execute(
                    """SELECT id, from_address, to_address, subject, logged_at, message_id
                       FROM email_activity_log
                       WHERE mailbox_address = %s AND direction = 'sent'
                       ORDER BY logged_at DESC LIMIT %s""",
                    (address, limit),
                )
            elif visible is not None:
                cur.execute(
                    """SELECT al.id, al.mailbox_address, al.from_address, al.to_address,
                              al.subject, al.logged_at, m.display_name AS mailbox_display
                       FROM email_activity_log al
                       JOIN email_mailboxes m ON m.address = al.mailbox_address
                       WHERE al.direction = 'sent' AND m.id = ANY(%s)
                       ORDER BY al.logged_at DESC LIMIT %s""",
                    (visible, limit),
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
