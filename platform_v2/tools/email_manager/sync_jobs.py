"""Email HQ — IMAP sync job.

Full RFC822 body sync: polls each provisioned mailbox via IMAP4_SSL,
writes complete messages (headers + body_html + body_text + preview)
into email_messages.

Stalwart IMAP: 192.168.1.200:993 (SSL)
Username = local part of address, password = stored imap_password.
"""

from __future__ import annotations

import email as email_lib
import imaplib
import logging
import ssl
from typing import Set

from .email_parser import decode_header_value, extract_body_parts, parse_received_at

logger = logging.getLogger(__name__)

_IMAP_HOST = "stalwart_mail"  # direct container-to-container via archie_network
_IMAP_PORT = 993
_BATCH_SIZE = 50  # max new messages fetched per cycle per mailbox


def get_synced_uids(cur, mailbox_id: int) -> Set[int]:
    """Return imap_uid values already stored for this mailbox."""
    cur.execute(
        "SELECT imap_uid FROM email_messages WHERE mailbox_id = %s AND imap_uid IS NOT NULL",
        (mailbox_id,),
    )
    return {row["imap_uid"] for row in cur.fetchall()}


def insert_email_message(cur, mailbox_id: int, imap_uid: int, msg, raw: bytes) -> bool:
    """Parse msg and insert one row into email_messages. Returns True if inserted."""
    from .thread_service import resolve_thread

    message_id = (msg.get("Message-ID") or "").strip() or f"<local.{mailbox_id}.{imap_uid}@archie>"
    subject = decode_header_value(msg.get("Subject", ""))
    from_addr = decode_header_value(msg.get("From", ""))
    to_addr = decode_header_value(msg.get("To", ""))
    cc_addr = decode_header_value(msg.get("Cc", "")) or None
    in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
    references = (msg.get("References") or "").strip() or None
    received_at = parse_received_at(msg)

    parts = extract_body_parts(msg)
    attachments = parts["attachments"]

    thread_id = resolve_thread(cur, mailbox_id, in_reply_to, references, subject, received_at)

    cur.execute(
        """INSERT INTO email_messages
           (mailbox_id, imap_uid, message_id, from_address, to_address, cc_address,
            subject, received_at, body_html, body_text, body_preview,
            has_attachments, attachment_count, size_bytes,
            in_reply_to, references_header, thread_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (
            mailbox_id,
            imap_uid,
            message_id,
            from_addr,
            to_addr,
            cc_addr,
            subject,
            received_at,
            parts["html"],
            parts["text"],
            parts["preview"],
            bool(attachments),
            len(attachments),
            len(raw),
            in_reply_to,
            references,
            thread_id,
        ),
    )
    return bool(cur.rowcount)


def sync_single_mailbox_full(mailbox_id: int, address: str, password: str) -> int:
    """Sync one mailbox: fetch new UIDs, write full bodies to email_messages.

    Returns count of newly inserted messages.
    """
    from database import get_db_cursor

    username = address.split("@")[0]
    ctx = ssl.create_default_context()
    ctx.check_hostname = (
        False  # Docker-internal hostname (stalwart_mail) doesn't match cert CN (mail.kytranempowerment.com)
    )
    ctx.verify_mode = ssl.CERT_REQUIRED  # Stalwart has a valid Let's Encrypt cert — enforce chain validation

    try:
        with imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, ssl_context=ctx) as imap:
            imap.login(username, password)
            imap.select("INBOX", readonly=True)
            _, data = imap.search(None, "ALL")
            all_uids = [int(u) for u in (data[0].split() if data[0] else [])]

            with get_db_cursor() as (conn, cur):
                already_synced = get_synced_uids(cur, mailbox_id)

            new_uids = [u for u in all_uids if u not in already_synced][-_BATCH_SIZE:]
            if not new_uids:
                return 0

            inserted = 0
            for uid in new_uids:
                _, msg_data = imap.fetch(str(uid).encode(), "(RFC822)")
                raw = msg_data[0][1] if msg_data and msg_data[0] else None
                if not raw:
                    continue
                msg = email_lib.message_from_bytes(raw)
                with get_db_cursor(commit=True) as (conn, cur):
                    new_id = None
                    if insert_email_message(cur, mailbox_id, uid, msg, raw):
                        inserted += 1
                        cur.execute(
                            "SELECT id FROM email_messages WHERE mailbox_id=%s AND imap_uid=%s",
                            (mailbox_id, uid),
                        )
                        row = cur.fetchone()
                        if row:
                            new_id = row["id"]
                if new_id:
                    from .rules_service import apply_rules
                    from .triage_service import triage_message_async

                    rule_result = apply_rules(
                        new_id,
                        mailbox_id,
                        {
                            "from_address": msg.get("From", ""),
                            "subject": msg.get("Subject", ""),
                            "to_address": msg.get("To", ""),
                            "body_preview": "",
                        },
                    )
                    if rule_result.get("action_type") != "skip_triage":
                        triage_message_async(new_id)

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
            "SELECT id, address, imap_password FROM email_mailboxes "
            "WHERE provisioned = TRUE AND active = TRUE AND imap_password IS NOT NULL"
        )
        mailboxes = cur.fetchall()

    total_new = 0
    errors = 0
    for row in mailboxes:
        try:
            total_new += sync_single_mailbox_full(row["id"], row["address"], row["imap_password"])
        except Exception as exc:
            logger.error("Unhandled error syncing %s: %s", row["address"], exc)
            errors += 1

    logger.info(
        "[email_imap_sync] Synced %d mailboxes — %d new messages, %d errors",
        len(mailboxes),
        total_new,
        errors,
    )

    # C.R.E.E.D. privacy event — PIPEDA: safeguards + limiting use
    try:
        from services.creed_privacy_logger import log_email_sync

        log_email_sync(
            mailboxes_synced=len(mailboxes),
            new_messages=total_new,
            errors=errors,
        )
    except Exception as _pe:
        logger.debug("[email_imap_sync] C.R.E.E.D. privacy log skipped: %s", _pe)

    return {"mailboxes": len(mailboxes), "new_messages": total_new, "errors": errors}


def register_email_sync_jobs(job_service) -> None:
    """Register Email HQ sync jobs with the JobService."""
    try:
        job_service.register_job(
            name="email_imap_sync",
            func=run_email_imap_sync,
            interval_hours=1 / 12,  # every 5 minutes
            department="Documentation & Knowledge",
            description="Poll IMAP for all provisioned mailboxes and sync full message bodies",
        )
        logger.info("[email_imap_sync] Registered")
    except Exception as exc:
        logger.error("[email_imap_sync] Failed to register: %s", exc)
