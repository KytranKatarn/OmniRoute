"""Email HQ — shared outbound send helper.

Standalone SMTP send via Stalwart, with NO Flask / current_user dependency, so it
can be called from:
  * the compose route (`compose_routes.email_compose_send`), and
  * the Telegram approve-to-send executor (`draft_proposal_service.execute_email_reply`),
    which runs in the python-telegram-bot async context with no Flask request.

Stalwart connection rule (email-manager.md): use the Docker-internal hostname
`stalwart_mail:587` (STARTTLS) — NEVER the external HTTPS endpoint (hairpin NAT blocks
TLS from containers). The cert CN is mail.kytranempowerment.com so hostname checking is
disabled but the chain + expiry are still enforced (CERT_REQUIRED).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database import get_db_cursor

logger = logging.getLogger(__name__)

_SMTP_HOST = "stalwart_mail"  # Docker-internal hostname (not the LAN/public IP)
_SMTP_PORT = 587  # STARTTLS submission


def send_email_via_stalwart(
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
) -> dict:
    """Send one plaintext email from a provisioned mailbox via Stalwart SMTP.

    Resolves the From mailbox's SMTP password from `email_mailboxes` (plaintext
    `imap_password`, same credential used for IMAP). Logs a `direction='sent'` row to
    `email_activity_log`. Returns {"success": True} or {"success": False, "error": str}.

    `in_reply_to` (the original message's RFC Message-ID) is threaded via the
    In-Reply-To / References headers when supplied.
    """
    from_address = (from_address or "").strip()
    to_address = (to_address or "").strip()
    subject = (subject or "").strip()
    if not from_address or not to_address or not subject:
        return {"success": False, "error": "from_address, to_address and subject are required"}

    # Resolve credentials for the From mailbox.
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT imap_password FROM email_mailboxes
                   WHERE address = %s AND provisioned = TRUE AND active = TRUE""",
                (from_address,),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("[email-send] credential lookup failed for %s: %s", from_address, exc)
        return {"success": False, "error": f"credential lookup failed: {exc}"}

    password = (row or {}).get("imap_password") if isinstance(row, dict) else (row[0] if row else None)
    if not password:
        return {"success": False, "error": "Mailbox not provisioned or missing SMTP credentials"}

    username = from_address.split("@")[0]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.attach(MIMEText(body or "", "plain"))

    ctx = ssl.create_default_context()
    ctx.check_hostname = False  # Docker hostname (stalwart_mail) != cert CN (mail.kytranempowerment.com)
    ctx.verify_mode = ssl.CERT_REQUIRED  # valid Let's Encrypt cert — still enforce chain + expiry

    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.login(username, password)
            smtp.sendmail(from_address, [to_address], msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("[email-send] SMTP auth failed for %s: %s", from_address, exc)
        return {"success": False, "error": "SMTP authentication failed — check mailbox credentials"}
    except smtplib.SMTPRecipientsRefused as exc:
        logger.error("[email-send] recipient refused %s: %s", to_address, exc)
        return {"success": False, "error": f"Recipient refused: {to_address}"}
    except Exception as exc:
        logger.error("[email-send] SMTP send error %s -> %s: %s", from_address, to_address, exc)
        return {"success": False, "error": f"Send failed: {exc}"}

    # Best-effort activity log — a logging failure must not undo a successful send.
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO email_activity_log
                       (mailbox_address, direction, from_address, to_address, subject)
                   VALUES (%s, 'sent', %s, %s, %s)""",
                (from_address, from_address, to_address, subject),
            )
    except Exception as exc:
        logger.warning("[email-send] activity log failed (%s -> %s): %s", from_address, to_address, exc)

    logger.info("[email-send] sent: %s -> %s  subject=%r", from_address, to_address, subject)
    return {"success": True}
