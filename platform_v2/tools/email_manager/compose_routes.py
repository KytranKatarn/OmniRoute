"""Email HQ — Compose/Send: outbound email via Stalwart SMTP."""

from __future__ import annotations

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids

logger = logging.getLogger(__name__)


def register_compose_routes(bp, admin_required):

    @bp.route("/api/email/compose/mailboxes", methods=["GET"])
    @login_required
    @admin_required
    def email_compose_mailboxes():
        """List provisioned mailboxes available as From addresses.

        COLLABORATOR callers only see their own department's mailboxes.
        """
        visible = get_visible_mailbox_ids(current_user)
        with get_db_cursor() as (conn, cur):
            if visible is not None:
                cur.execute(
                    """SELECT address, display_name, mailbox_type
                       FROM email_mailboxes
                       WHERE provisioned = TRUE AND active = TRUE
                         AND imap_password IS NOT NULL
                         AND id = ANY(%s)
                       ORDER BY mailbox_type, address""",
                    (visible,),
                )
            else:
                cur.execute(
                    """SELECT address, display_name, mailbox_type
                       FROM email_mailboxes
                       WHERE provisioned = TRUE AND active = TRUE
                         AND imap_password IS NOT NULL
                       ORDER BY mailbox_type, address"""
                )
            rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"mailboxes": rows})

    @bp.route("/api/email/compose/send", methods=["POST"])
    @login_required
    @admin_required
    def email_compose_send():
        """Send an email from a provisioned mailbox via Stalwart SMTP.

        COLLABORATOR callers may only send FROM a mailbox in their visible set.
        Attempting to send from another department's mailbox returns 403.
        """
        data = request.get_json() or {}
        from_address = (data.get("from_address") or "").strip()
        to_address = (data.get("to_address") or "").strip()
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()

        if not from_address or not to_address or not subject:
            return (
                jsonify({"error": "from_address, to_address and subject are required"}),
                400,
            )

        # Enforce COLLABORATOR scope: may only send FROM a mailbox in their visible set.
        visible = get_visible_mailbox_ids(current_user)
        if visible is not None:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT 1 FROM email_mailboxes
                       WHERE address = %s AND provisioned = TRUE AND active = TRUE
                         AND id = ANY(%s)""",
                    (from_address, visible),
                )
                allowed = cur.fetchone()
            if not allowed:
                return jsonify({"error": "Mailbox not in your accessible set"}), 403

        # Send via the shared Stalwart helper (also used by the Telegram approve-to-send executor).
        from .send_service import send_email_via_stalwart

        result = send_email_via_stalwart(from_address, to_address, subject, body)
        if not result.get("success"):
            err = result.get("error", "Send failed")
            client_error = any(s in err for s in ("required", "Recipient refused", "not provisioned"))
            return jsonify({"error": err}), (400 if client_error else 500)

        return jsonify({"success": True})
