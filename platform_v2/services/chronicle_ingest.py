"""Chronicle ingest seam (slice 04) — source-agnostic email/attachment ingestion.

A source adapter (Gmail, LinkedIn, chat export, ...) maps its content to a list of
normalized `items` and calls `ingest_source()`. That upserts a per-source import
(reused for live sources re-ingested incrementally, fresh for one-shot uploads) plus
`mailbox_emails` rows, idempotently by (import_id, message_id) via an in-code existing-id
check, and sets the import to 'extracted' so the existing DHQ enrich/story workers pick
it up. Attachment FILES are downloaded by the source adapter, which then calls
`upsert_attachment()` to register each on-disk file for the Slice-03 extraction engine.
No LLM / DHQ here — pure DB writes.

Idempotency is in application code (not a DB unique index): a schema-wide
UNIQUE(import_id, message_id) would collide with pre-existing duplicate rows in a legacy
PST import, and deleting the owner's archived data is out of scope. The live ingest worker
is single + sequential + resumable, so an in-code existing-id skip is sufficient.
"""

import logging

logger = logging.getLogger(__name__)

# Sources re-ingested incrementally (ONE persistent import), vs one-shot uploads (fresh each time).
_LIVE_SOURCE_KINDS = {"gmail", "linkedin"}


def _email_values(import_id, item):
    """Map a normalized source item -> the mailbox_emails INSERT value tuple (pure).

    item keys (all optional except message_id for dedup): message_id, folder, from_addr,
    to_addrs, cc_addrs, in_reply_to, sent_at, subject, body_text, body_html,
    has_attachments, attachments (list — presence implies has_attachments).
    """
    atts = item.get("attachments") or []
    return (
        import_id,
        item.get("message_id"),
        item.get("folder"),
        item.get("from_addr"),
        item.get("to_addrs"),
        item.get("cc_addrs"),
        item.get("in_reply_to"),
        item.get("sent_at"),
        item.get("subject"),
        item.get("body_text"),
        item.get("body_html"),
        bool(item.get("has_attachments") or atts),
    )


def _scalar(row):
    if row is None:
        return None
    return row["id"] if isinstance(row, dict) else row[0]


def _find_or_create_import(cur, source_kind, source_account_id, owner_id, is_live, title):
    """Reuse the one live import for (source_kind, source_account_id, owner_id); else create fresh.
    Always leaves the import at status='extracted' so enrich re-triggers for any new emails."""
    if is_live:
        cur.execute(
            "SELECT id FROM mailbox_imports WHERE source_kind=%s AND source_account_id=%s "
            "AND owner_id IS NOT DISTINCT FROM %s AND is_live_source=TRUE ORDER BY id LIMIT 1",
            (source_kind, source_account_id, owner_id),
        )
        existing = _scalar(cur.fetchone())
        if existing is not None:
            cur.execute("UPDATE mailbox_imports SET status='extracted' WHERE id=%s", (existing,))
            return existing
    cur.execute(
        "INSERT INTO mailbox_imports (owner_id, filename, stored_path, status, email_count, "
        "source_kind, source_account_id, is_live_source) "
        "VALUES (%s,%s,%s,'extracted',0,%s,%s,%s) RETURNING id",
        (
            owner_id,
            title or f"{source_kind}: {source_account_id}",
            source_kind,
            source_kind,
            source_account_id,
            bool(is_live),
        ),
    )
    return _scalar(cur.fetchone())


def ingest_source(source_kind, source_account_id, items, owner_id=None, is_live=None, title=None):
    """Upsert a per-source import + email rows. Idempotent by (import_id, message_id) in code.

    Sets the import to status='extracted' (triggers the existing enrich worker). Returns
    {import_id, inserted, skipped}. `is_live` defaults to (source_kind in gmail/linkedin).
    Items with a message_id already present in the import (or repeated within this batch) are
    skipped; items with no message_id always insert (preserves chat-import behavior)."""
    from database import get_db_cursor

    if is_live is None:
        is_live = source_kind in _LIVE_SOURCE_KINDS

    inserted = skipped = 0
    with get_db_cursor(commit=True) as (conn, cur):
        import_id = _find_or_create_import(cur, source_kind, source_account_id, owner_id, is_live, title)
        # Pre-load existing message_ids for this import so re-ingestion is idempotent.
        cur.execute(
            "SELECT message_id FROM mailbox_emails WHERE import_id=%s AND message_id IS NOT NULL",
            (import_id,),
        )
        seen = {(r["message_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}

        for item in items or []:
            mid = item.get("message_id")
            if mid and mid in seen:
                skipped += 1
                continue
            cur.execute(
                "INSERT INTO mailbox_emails (import_id, message_id, folder, from_addr, to_addrs, "
                "cc_addrs, in_reply_to, sent_at, subject, body_text, body_html, has_attachments) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                _email_values(import_id, item),
            )
            inserted += 1
            if mid:
                seen.add(mid)  # guard against duplicate message_ids within the same batch

        cur.execute(
            "UPDATE mailbox_imports SET email_count="
            "(SELECT count(*) FROM mailbox_emails WHERE import_id=%s) WHERE id=%s",
            (import_id, import_id),
        )
    return {"import_id": import_id, "inserted": inserted, "skipped": skipped}


def upsert_attachment(email_id, filename, mime_type, size_bytes, sha256, stored_path):
    """Register a downloaded attachment file (status 'new') for the Slice-03 extraction engine.
    Idempotent by (email_id, sha256) via the existing UNIQUE index (migration 453).
    Returns (attachment_id, created: bool)."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO mailbox_attachments (email_id, filename, mime_type, size_bytes, sha256, "
            "stored_path, extract_status) VALUES (%s,%s,%s,%s,%s,%s,'new') "
            "ON CONFLICT (email_id, sha256) DO NOTHING RETURNING id",
            (email_id, filename, mime_type, size_bytes, sha256, stored_path),
        )
        new_id = _scalar(cur.fetchone())
        if new_id is not None:
            return (new_id, True)
        cur.execute(
            "SELECT id FROM mailbox_attachments WHERE email_id=%s AND sha256=%s",
            (email_id, sha256),
        )
        return (_scalar(cur.fetchone()), False)
