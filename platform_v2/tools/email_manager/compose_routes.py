"""Email HQ — Compose/Send: outbound email via Stalwart SMTP."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database import get_db_cursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

_SMTP_HOST = "192.168.1.200"
_SMTP_PORT = 587  # STARTTLS submission


def register_compose_routes(bp, admin_required):

    @bp.route("/api/email/compose/mailboxes", methods=["GET"])
    @login_required
    @admin_required
    def email_compose_mailboxes():
        """List provisioned mailboxes available as From addresses."""
        with get_db_cursor() as (conn, cur):
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
        """Send an email from a provisioned mailbox via Stalwart SMTP."""
        data = request.get_json() or {}
        from_address = (data.get("from_address") or "").strip()
        to_address = (data.get("to_address") or "").strip()
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()

        if not from_address or not to_address or not subject:
            return jsonify({"error": "from_address, to_address and subject are required"}), 400

        # Resolve credentials for the From mailbox
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT imap_password FROM email_mailboxes
                   WHERE address = %s AND provisioned = TRUE AND active = TRUE""",
                (from_address,),
            )
            row = cur.fetchone()

        if not row or not row["imap_password"]:
            return jsonify({"error": "Mailbox not provisioned or missing SMTP credentials"}), 400

        username = from_address.split("@")[0]
        password = row["imap_password"]

        # Build message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = to_address
        if body:
            msg.attach(MIMEText(body, "plain"))

        # Send via Stalwart SMTP (port 587 STARTTLS)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.login(username, password)
                smtp.sendmail(from_address, [to_address], msg.as_string())
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("SMTP auth failed for %s: %s", from_address, exc)
            return jsonify({"error": "SMTP authentication failed — check mailbox credentials"}), 500
        except smtplib.SMTPRecipientsRefused as exc:
            logger.error("Recipient refused %s: %s", to_address, exc)
            return jsonify({"error": f"Recipient refused: {to_address}"}), 400
        except Exception as exc:
            logger.error("SMTP send error for %s → %s: %s", from_address, to_address, exc)
            return jsonify({"error": f"Send failed: {exc}"}), 500

        # Log to email_activity_log (direction='sent')
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO email_activity_log
                       (mailbox_address, direction, from_address, to_address, subject)
                   VALUES (%s, 'sent', %s, %s, %s)""",
                (from_address, from_address, to_address, subject),
            )

        logger.info("Email sent: %s → %s  subject=%r", from_address, to_address, subject)
        return jsonify({"success": True})
