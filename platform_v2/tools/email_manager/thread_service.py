"""Email HQ — Phase 7 threading service.

Thread resolution on IMAP sync:
  1. Check In-Reply-To header against existing message_ids in same mailbox
  2. Check References header (space-separated) for any known message_id
  3. No match → create new email_thread row
  4. Match → inherit existing thread_id and update its stats
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_RE_PREFIX = re.compile(r"^(Re|Fwd|FW|RE|FWD|AW|Antwort):\s*", re.IGNORECASE)


def _clean_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes for canonical thread subject."""
    s = subject or ""
    for _ in range(10):
        new = _RE_PREFIX.sub("", s).strip()
        if new == s:
            break
        s = new
    return s


def resolve_thread(
    cur, mailbox_id: int, in_reply_to: str | None, references: str | None, subject: str, received_at
) -> int:
    """Find or create a thread for this message. Returns thread_id.

    Must be called inside a DB transaction (caller commits).
    """
    # Build candidate parent message IDs from In-Reply-To + References
    candidates: list[str] = []
    if in_reply_to and in_reply_to.strip():
        candidates.append(in_reply_to.strip())
    if references:
        candidates.extend(r.strip() for r in references.split() if r.strip())

    # Search for an existing thread via any candidate message_id
    for cand_id in candidates:
        cur.execute(
            "SELECT thread_id FROM email_messages WHERE message_id = %s AND mailbox_id = %s AND thread_id IS NOT NULL",
            (cand_id, mailbox_id),
        )
        row = cur.fetchone()
        if row and row["thread_id"]:
            thread_id = row["thread_id"]
            # Update thread stats
            cur.execute(
                """UPDATE email_threads
                   SET message_count = message_count + 1,
                       last_message_at = GREATEST(last_message_at, %s)
                   WHERE id = %s""",
                (received_at, thread_id),
            )
            logger.debug("[threading] msg joined thread #%d via %s", thread_id, cand_id)
            return thread_id

    # No match — create a new thread
    clean_subj = _clean_subject(subject)
    cur.execute(
        "INSERT INTO email_threads (mailbox_id, subject, last_message_at) VALUES (%s, %s, %s) RETURNING id",
        (mailbox_id, clean_subj or subject, received_at),
    )
    thread_id = cur.fetchone()["id"]
    logger.debug("[threading] new thread #%d subject=%s", thread_id, clean_subj)
    return thread_id
