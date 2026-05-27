"""Email HQ — Inbox tab: message browser from email_activity_log."""

import logging

from database import get_db_cursor
from flask import abort, jsonify, request
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

logger = logging.getLogger(__name__)


def register_inbox_routes(bp, admin_required):

    @bp.route("/api/email/inbox/messages", methods=["GET"])
    @login_required
    @admin_required
    def email_inbox_messages():
        """Recent received messages for a mailbox (from email_activity_log).

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
                # Scope guard: COLLABORATOR may only request their own mailboxes.
                if visible is not None:
                    cur.execute(
                        "SELECT id FROM email_mailboxes WHERE address = %s AND id = ANY(%s)",
                        (address, visible),
                    )
                    if not cur.fetchone():
                        abort(403)
                cur.execute(
                    """SELECT id, direction, from_address, to_address, subject,
                              read_at, logged_at, message_id
                       FROM email_activity_log
                       WHERE mailbox_address = %s AND direction = 'received'
                       ORDER BY logged_at DESC LIMIT %s""",
                    (address, limit),
                )
            elif visible is not None:
                cur.execute(
                    """SELECT al.id, al.mailbox_address, al.direction, al.from_address,
                              al.to_address, al.subject, al.read_at, al.logged_at, al.message_id
                       FROM email_activity_log al
                       JOIN email_mailboxes m ON m.address = al.mailbox_address
                       WHERE al.direction = 'received' AND m.id = ANY(%s)
                       ORDER BY al.logged_at DESC LIMIT %s""",
                    (visible, limit),
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
        """Mark a message as read.

        COLLABORATOR callers can only mark messages in their visible mailboxes;
        the UPDATE is scoped via a subquery so cross-dept IDs are silently ignored.
        """
        data = request.get_json() or {}
        msg_id = data.get("id")
        if not msg_id:
            return jsonify({"error": "id required"}), 400
        visible = get_visible_mailbox_ids(current_user)
        with get_db_cursor(commit=True) as (conn, cur):
            if visible is not None:
                cur.execute(
                    """UPDATE email_activity_log SET read_at = NOW()
                       WHERE id = %s
                         AND mailbox_address IN (
                             SELECT address FROM email_mailboxes WHERE id = ANY(%s)
                         )""",
                    (msg_id, visible),
                )
            else:
                cur.execute(
                    "UPDATE email_activity_log SET read_at = NOW() WHERE id = %s",
                    (msg_id,),
                )
        return jsonify({"success": True})
