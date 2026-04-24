"""Email HQ — IMAP sync job.

Polls each provisioned mailbox (that has an imap_password) via IMAP and
writes new messages to email_activity_log. Runs every 5 minutes via JobService.

Stalwart IMAP: 192.168.1.200:993 (SSL) or 192.168.1.200:143 (STARTTLS).
Username = local part of address, password = stored imap_password.
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import ssl
from email.header import decode_header as _decode_header

logger = logging.getLogger(__name__)

_IMAP_HOST = "192.168.1.200"
_IMAP_PORT = 993


def _decode_str(value) -> str:
    if not value:
        return ""
    parts = []
    for fragment, charset in _decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts)


def _sync_mailbox(address: str, password: str) -> int:
    """Fetch unseen messages for one mailbox. Returns count of new rows inserted."""
    from database import get_db_cursor

    username = address.split("@")[0]
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, ssl_context=ctx) as imap:
            imap.login(username, password)
            imap.select("INBOX", readonly=True)
            _, data = imap.search(None, "UNSEEN")
            uids = data[0].split() if data[0] else []

            inserted = 0
            for uid in uids:
                _, msg_data = imap.fetch(uid, "(RFC822)")
                raw = msg_data[0][1] if msg_data and msg_data[0] else None
                if not raw:
                    continue
                msg = email_lib.message_from_bytes(raw)
                message_id = (msg.get("Message-ID") or "").strip()
                subject = _decode_str(msg.get("Subject", ""))
                from_addr = _decode_str(msg.get("From", ""))
                to_addr = _decode_str(msg.get("To", ""))

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO email_activity_log
                           (mailbox_address, direction, from_address, to_address,
                            subject, message_id, size_bytes)
                           VALUES (%s, 'received', %s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""",
                        (address, from_addr, to_addr, subject, message_id or None, len(raw)),
                    )
                    if cur.rowcount:
                        inserted += 1
            return inserted
    except imaplib.IMAP4.error as exc:
        logger.warning("IMAP auth/protocol error for %s: %s", address, exc)
        return 0
    except OSError as exc:
        logger.warning("IMAP connection error for %s: %s", address, exc)
        return 0
    except Exception as exc:
        logger.error("IMAP sync error for %s: %s", address, exc, exc_info=True)
        return 0


def run_email_imap_sync() -> dict:
    """Job entry point: sync all provisioned mailboxes with a stored password."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT address, imap_password FROM email_mailboxes "
            "WHERE provisioned = TRUE AND active = TRUE AND imap_password IS NOT NULL"
        )
        mailboxes = cur.fetchall()

    total_new = 0
    errors = 0
    for row in mailboxes:
        try:
            total_new += _sync_mailbox(row["address"], row["imap_password"])
        except Exception as exc:
            logger.error("Unhandled error syncing %s: %s", row["address"], exc)
            errors += 1

    logger.info("[email_imap_sync] Synced %d mailboxes — %d new messages, %d errors", len(mailboxes), total_new, errors)
    return {"mailboxes": len(mailboxes), "new_messages": total_new, "errors": errors}


def register_email_sync_jobs(job_service) -> None:
    """Register Email HQ sync jobs with the JobService."""
    try:
        job_service.register_job(
            name="email_imap_sync",
            func=run_email_imap_sync,
            interval_hours=1 / 12,  # every 5 minutes
            department="Documentation & Knowledge",
            description="Poll IMAP for all provisioned agent/business mailboxes and log new messages",
        )
        logger.info("[email_imap_sync] Registered")
    except Exception as exc:
        logger.error("[email_imap_sync] Failed to register: %s", exc)
