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


class MailboxSyncError(Exception):
    """A single mailbox could not be synced due to an IMAP auth, connection, or
    unexpected error — distinct from 'connected OK, 0 new messages'.

    Carries ``category`` ('auth' | 'connection' | 'unknown') and the mailbox
    ``address`` so the job runner can aggregate failures and tell an outage apart
    from a one-off bad-credential mailbox."""

    def __init__(self, address: str, category: str, original: BaseException):
        self.address = address
        self.category = category
        self.original = original
        super().__init__(f"{category} error for {address}: {original}")


class EmailSyncOutageError(Exception):
    """Raised by run_email_imap_sync when EVERY provisioned mailbox failed — i.e.
    a real Stalwart/IMAP outage. Raising (rather than returning a dict) is what
    flips job_service.run_job to record status='error' in autonomy_loop_log, so an
    outage can never again be silently reported as 'success, 0 new messages'."""


def _strip_nul(value):
    """PostgreSQL text columns cannot store NUL (0x00) — psycopg2 raises
    'A string literal cannot contain NUL (0x00) characters' on INSERT. Strip it
    from any string (common in spam / bounce-back / DSN messages) so a single bad
    message never aborts the mailbox sync. Non-strings pass through unchanged."""
    return value.replace("\x00", "") if isinstance(value, str) else value


def get_synced_uids(cur, mailbox_id: int, folder: str = "INBOX") -> Set[int]:
    """Return imap_uid values already stored for this mailbox+folder.

    IMAP UIDs are per-folder, so the skip-set MUST be scoped to the folder — INBOX
    UID 5 is a different message than Junk UID 5 (#4519). Without the folder filter,
    syncing Junk would wrongly skip every UID already seen in INBOX."""
    cur.execute(
        "SELECT imap_uid FROM email_messages " "WHERE mailbox_id = %s AND folder = %s AND imap_uid IS NOT NULL",
        (mailbox_id, folder),
    )
    return {row["imap_uid"] for row in cur.fetchall()}


def insert_email_message(cur, mailbox_id: int, imap_uid: int, msg, raw: bytes, folder: str = "INBOX") -> bool:
    """Parse msg and insert one row into email_messages. Returns True if inserted.

    ``folder`` attributes the message to its source IMAP folder (#4519). Row dedup
    stays keyed on the globally-unique (mailbox_id, message_id), so a message present
    in two folders is stored once (keeping whichever folder synced it first)."""
    from .thread_service import resolve_thread

    message_id = _strip_nul((msg.get("Message-ID") or "").strip()) or f"<local.{mailbox_id}.{imap_uid}@archie>"
    subject = _strip_nul(decode_header_value(msg.get("Subject", "")))
    from_addr = _strip_nul(decode_header_value(msg.get("From", "")))
    to_addr = _strip_nul(decode_header_value(msg.get("To", "")))
    cc_addr = _strip_nul(decode_header_value(msg.get("Cc", ""))) or None
    in_reply_to = _strip_nul((msg.get("In-Reply-To") or "").strip()) or None
    references = _strip_nul((msg.get("References") or "").strip()) or None
    received_at = parse_received_at(msg)

    parts = extract_body_parts(msg)
    parts["html"] = _strip_nul(parts.get("html"))
    parts["text"] = _strip_nul(parts.get("text"))
    parts["preview"] = _strip_nul(parts.get("preview"))
    attachments = parts["attachments"]

    thread_id = resolve_thread(cur, mailbox_id, in_reply_to, references, subject, received_at)

    cur.execute(
        """INSERT INTO email_messages
           (mailbox_id, folder, imap_uid, message_id, from_address, to_address, cc_address,
            subject, received_at, body_html, body_text, body_preview,
            has_attachments, attachment_count, size_bytes,
            in_reply_to, references_header, thread_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING""",
        (
            mailbox_id,
            folder,
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


def _sync_folders() -> list:
    """Ordered, de-duplicated IMAP folders to sync (#4519).

    From platform_settings ``mailhq:sync:folders`` (comma-separated), default
    ``INBOX,Junk Mail``. INBOX is always present and first (it is the only
    triaged/notified folder). Fail-safe to the default on any error. NOTE: Stalwart's
    junk folder is "Junk Mail" (with a space), not "Junk"."""
    raw = "INBOX,Junk Mail"
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'mailhq:sync:folders'")
            row = cur.fetchone()
            if row and row.get("value"):
                raw = row["value"]
    except Exception:
        pass
    out = ["INBOX"]
    for f in raw.split(","):
        f = f.strip()
        if f and f not in out:
            out.append(f)
    return out


def _sync_one_folder(imap, mailbox_id: int, address: str, folder: str) -> int:
    """Sync a single IMAP folder for one mailbox. Returns newly-inserted count (#4519).

    A folder that does not exist on this mailbox (e.g. Junk) is skipped, not fatal.
    Rules/triage + the A.R.C.H.I.E. new-mail advisory run for INBOX ONLY — other
    folders are stored for coverage/search but never triaged or notified (so we never
    draft replies to spam or ping the owner about Junk)."""
    from database import get_db_cursor

    try:
        # IMAP mailbox names containing a space (e.g. Stalwart's "Junk Mail") must be
        # quoted or the server parses only the first word and errors.
        sel_name = '"%s"' % folder if any(c in folder for c in ' "\\') else folder
        status, _sel = imap.select(sel_name, readonly=True)
        if status != "OK":
            logger.info("[email_imap_sync] %s: folder %r not found — skipping", address, folder)
            return 0
    except imaplib.IMAP4.error as exc:
        logger.info("[email_imap_sync] %s: cannot select folder %r (%s) — skipping", address, folder, exc)
        return 0

    _, data = imap.search(None, "ALL")
    all_uids = [int(u) for u in (data[0].split() if data[0] else [])]

    with get_db_cursor() as (conn, cur):
        already_synced = get_synced_uids(cur, mailbox_id, folder)

    new_uids = [u for u in all_uids if u not in already_synced][-_BATCH_SIZE:]
    if not new_uids:
        return 0

    is_inbox = folder.upper() == "INBOX"
    inserted = 0
    new_for_notify = []  # Slice 2 A.R.C.H.I.E. advisory — INBOX only
    for uid in new_uids:
        try:
            _, msg_data = imap.fetch(str(uid).encode(), "(RFC822)")
            raw = msg_data[0][1] if msg_data and msg_data[0] else None
            if not raw:
                continue
            msg = email_lib.message_from_bytes(raw)
            with get_db_cursor(commit=True) as (conn, cur):
                new_id = None
                if insert_email_message(cur, mailbox_id, uid, msg, raw, folder):
                    inserted += 1
                    cur.execute(
                        "SELECT id, received_at FROM email_messages "
                        "WHERE mailbox_id=%s AND folder=%s AND imap_uid=%s",
                        (mailbox_id, folder, uid),
                    )
                    row = cur.fetchone()
                    if row:
                        new_id = row["id"]
                        if is_inbox:
                            new_for_notify.append(
                                {
                                    "from": decode_header_value(msg.get("From", "")),
                                    "subject": decode_header_value(msg.get("Subject", "")),
                                    "received_at": row.get("received_at"),
                                }
                            )
            if new_id and is_inbox:
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
        except Exception as msg_exc:
            # One malformed message must not abort the whole mailbox sync.
            # (A NUL-byte poison-pill at the front of the queue froze ALL
            # sync since 2026-06-11 — now isolated + logged, not fatal.)
            logger.warning("Skipping message uid=%s folder=%s in %s: %s", uid, folder, address, msg_exc)
            continue

    if new_for_notify:
        try:
            from .notify_service import notify_new_mail

            notify_new_mail(mailbox_id, address, new_for_notify)
        except Exception:
            pass  # Slice 2 advisory must never break mail sync

    return inserted


def sync_single_mailbox_full(mailbox_id: int, address: str, password: str) -> int:
    """Sync one mailbox across all configured folders (#4519 — INBOX + Junk + …).

    Returns count of newly inserted messages across folders.
    """
    username = address.split("@")[0]
    ctx = ssl.create_default_context()
    ctx.check_hostname = (
        False  # Docker-internal hostname (stalwart_mail) doesn't match cert CN (mail.kytranempowerment.com)
    )
    ctx.verify_mode = ssl.CERT_REQUIRED  # Stalwart has a valid Let's Encrypt cert — enforce chain validation

    try:
        with imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT, ssl_context=ctx) as imap:
            imap.login(username, password)
            total_inserted = 0
            for folder in _sync_folders():
                total_inserted += _sync_one_folder(imap, mailbox_id, address, folder)
            return total_inserted

    except imaplib.IMAP4.error as exc:
        # Auth/protocol failure for THIS mailbox. Raise (don't return 0) so the
        # job runner can tell a real failure apart from "0 new messages".
        logger.warning("IMAP auth/protocol error for %s: %s", address, exc)
        raise MailboxSyncError(address, "auth", exc) from exc
    except OSError as exc:
        # Connection/socket failure — the signature of a Stalwart outage when it
        # hits every mailbox. Raise so the outage surfaces instead of masking.
        logger.warning("IMAP connection error for %s: %s", address, exc)
        raise MailboxSyncError(address, "connection", exc) from exc
    except Exception as exc:
        logger.error("IMAP sync error for %s: %s", address, exc, exc_info=True)
        raise MailboxSyncError(address, "unknown", exc) from exc


def run_email_imap_sync() -> dict:
    """Job entry point: sync all provisioned mailboxes with a stored password."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, address, imap_password FROM email_mailboxes "
            "WHERE provisioned = TRUE AND active = TRUE AND imap_password IS NOT NULL"
        )
        mailboxes = cur.fetchall()

    total = len(mailboxes)
    total_new = 0
    synced_ok = 0
    by_category: dict[str, int] = {"auth": 0, "connection": 0, "unknown": 0}
    failures: list[tuple[str, str, str]] = []  # (address, category, message)

    ok_ids: list[int] = []
    fail_rows: list[tuple[int, str, str]] = []  # (mailbox_id, category, message)
    for row in mailboxes:
        try:
            total_new += sync_single_mailbox_full(row["id"], row["address"], row["imap_password"])
            synced_ok += 1
            ok_ids.append(row["id"])
        except MailboxSyncError as exc:
            by_category[exc.category] = by_category.get(exc.category, 0) + 1
            failures.append((exc.address, exc.category, str(exc.original)))
            fail_rows.append((row["id"], exc.category, str(exc.original)))
            logger.error("[email_imap_sync] %s sync failed (%s): %s", exc.address, exc.category, exc.original)
        except Exception as exc:
            # Defence in depth: sync_single_mailbox_full now raises MailboxSyncError,
            # but never let an unexpected error type be silently counted as success.
            by_category["unknown"] += 1
            failures.append((row["address"], "unknown", str(exc)))
            fail_rows.append((row["id"], "unknown", str(exc)))
            logger.error("[email_imap_sync] Unhandled error syncing %s: %s", row["address"], exc)

    # #5849: persist per-mailbox sync health so a forked/auth-broken mailbox is
    # VISIBLE in Email HQ instead of rendering identically to a healthy one (the
    # OWNER mailbox failed auth for 9 days unseen — outcomes lived only in these
    # log lines). Success clears the error; failure stamps category + message.
    # One batch write after the loop; NEVER let stamping break the sync itself.
    try:
        with get_db_cursor(commit=True) as (_c2, cur2):
            if ok_ids:
                cur2.execute(
                    "UPDATE email_mailboxes SET last_sync_ok_at = NOW(), "
                    "last_sync_error = NULL, last_sync_error_at = NULL "
                    "WHERE id = ANY(%s)",
                    (ok_ids,),
                )
            for _mb_id, _cat, _msg in fail_rows:
                cur2.execute(
                    "UPDATE email_mailboxes SET last_sync_error = %s, last_sync_error_at = NOW() WHERE id = %s",
                    ((_cat + ": " + _msg)[:300], _mb_id),
                )
    except Exception as _stamp_exc:
        logger.warning("[email_imap_sync] sync-health stamping failed (non-blocking): %s", _stamp_exc)

    errors = len(failures)
    reasons = [f"{n} {cat} error(s)" for cat, n in by_category.items() if n]

    logger.info(
        "[email_imap_sync] %d/%d mailboxes synced — %d new messages, %d errors%s",
        synced_ok,
        total,
        total_new,
        errors,
        (" [" + "; ".join(reasons) + "]") if reasons else "",
    )

    # C.R.E.E.D. privacy event — PIPEDA: safeguards + limiting use
    try:
        from services.creed_privacy_logger import log_email_sync

        log_email_sync(
            mailboxes_synced=synced_ok,
            new_messages=total_new,
            errors=errors,
        )
    except Exception as _pe:
        logger.debug("[email_imap_sync] C.R.E.E.D. privacy log skipped: %s", _pe)

    result = {
        "mailboxes": total,
        "synced": synced_ok,
        "new_messages": total_new,
        "errors": errors,
        "reasons": reasons,
        "failures": [{"address": a, "category": c} for a, c, _ in failures[:10]],
    }

    # OBSERVABILITY: a real outage (EVERY mailbox failed) must never mask as
    # success. Raise so JobService.run_job records status='error' in
    # autonomy_loop_log with the reason — instead of the old false-green where
    # all-mailboxes-return-0 looked identical to "no new mail" (the #1686 follow-up).
    # A partial failure (one bad-credential mailbox) is logged + returned above but
    # does NOT redden the whole 5-minute job.
    if total > 0 and errors == total:
        sample = failures[0][2] if failures else "unknown"
        raise EmailSyncOutageError(
            f"email_imap_sync OUTAGE: all {total} mailbox(es) failed " f"[{'; '.join(reasons)}]; sample: {sample}"
        )

    return result


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

    # Mail HQ Smart Inbox — Slice 3: agent-drafted approve-to-send proposals.
    # Gated OFF by default (platform_settings mailhq:draft:enabled) — the job is a
    # no-op until enabled, so registering it is safe. Isolated try/except so a
    # failure here cannot affect the email sync job above.
    try:
        from .draft_proposal_service import run_mailhq_draft_proposals

        job_service.register_job(
            name="mailhq_draft_proposals",
            func=run_mailhq_draft_proposals,
            interval_hours=1 / 6,  # every 10 minutes
            department="Customer Success & Support",
            description="Draft approve-to-send replies for action-priority owner/business mail (gated)",
        )
        logger.info("[mailhq_draft_proposals] Registered")
    except Exception as exc:
        logger.error("[mailhq_draft_proposals] Failed to register: %s", exc)

    # Collaborator Persona Email Assistant — Slice 1: per-collaborator persona drafts
    # for action-priority human_agent mail (llama3.2:3b). INDEPENDENTLY gated OFF by
    # default (platform_settings mailhq:draft:collaborators) — a no-op until enabled,
    # so registering it is safe and does not touch the owner/business draft job above.
    # Isolated try/except so a failure here cannot affect the jobs above.
    try:
        from .draft_proposal_service import run_mailhq_collaborator_drafts

        job_service.register_job(
            name="mailhq_collaborator_drafts",
            func=run_mailhq_collaborator_drafts,
            interval_hours=1 / 6,  # every 10 minutes
            department="Customer Success & Support",
            description="Draft persona-voiced replies for action-priority collaborator (human_agent) mail (gated)",
        )
        logger.info("[mailhq_collaborator_drafts] Registered")
    except Exception as exc:
        logger.error("[mailhq_collaborator_drafts] Failed to register: %s", exc)

    # Collaborator triage backfill (#4957) — retroactively triages pre-flip
    # human_agent inbox mail so it can become a collaborator-draft candidate the
    # moment the gate flips on. `ai_priority` is only ever set on NEW mail during
    # IMAP sync, so mail that arrived before the flip would otherwise stay
    # untriaged forever. INDEPENDENTLY gated (same flag as the draft job above) +
    # bounded (limit=25/run) — the function itself is a no-op while
    # `mailhq:draft:collaborators` is off, so registering it is safe. Isolated
    # try/except so a failure here cannot affect the jobs above.
    try:
        from .triage_service import backfill_collaborator_triage

        job_service.register_job(
            name="mailhq_collaborator_triage_backfill",
            func=lambda: backfill_collaborator_triage(limit=25),
            interval_hours=1 / 2,  # every 30 minutes
            department="Documentation & Knowledge",
            description="Backfill triage for pre-flip collaborator (human_agent) inbox mail (gated, bounded)",
        )
        logger.info("[mailhq_collaborator_triage_backfill] Registered")
    except Exception as exc:
        logger.error("[mailhq_collaborator_triage_backfill] Failed to register: %s", exc)

    # Mail HQ triage-health alert (task #4518) — flags the silent-failure class where
    # triage stops populating ai_priority (the whole Smart Inbox depends on it).
    try:
        from .triage_service import run_triage_health_check

        job_service.register_job(
            name="mailhq_triage_health",
            func=run_triage_health_check,
            interval_hours=6,
            department="Documentation & Knowledge",
            description="Alert if recent owner/business mail is largely untriaged (triage degraded)",
        )
        logger.info("[mailhq_triage_health] Registered")
    except Exception as exc:
        logger.error("[mailhq_triage_health] Failed to register: %s", exc)
