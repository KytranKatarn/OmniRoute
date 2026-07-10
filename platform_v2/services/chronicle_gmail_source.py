"""Chronicle Gmail full-content source (slice 05) — bodies only.

Pulls a Gmail account's messages at format=full and lands their full bodies into
Chronicle via chronicle_ingest.ingest_source (source_kind='gmail'). Resumable: skips
message_ids already present in the account's Chronicle import. Bounded by `limit`,
per-message error-isolated (one bad message never aborts the run). Attachment download
and scheduled backfill are separate later slices; this worker is invoked manually for a
bounded live verification run.
"""

import logging
from email.utils import parsedate_to_datetime

from tools.google_work_suite.services import gmail_service
from services.chronicle_ingest import ingest_source

logger = logging.getLogger(__name__)


def _owner_id_for_account(account_id):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT owner_id FROM google_accounts WHERE id=%s", (account_id,))
        row = cur.fetchone()
    if not row:
        return None
    return row["owner_id"] if isinstance(row, dict) else row[0]


def _seen_message_ids(account_id):
    """message_ids already ingested into the account's live gmail Chronicle import."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT e.message_id FROM mailbox_emails e JOIN mailbox_imports i ON e.import_id=i.id "
            "WHERE i.source_kind='gmail' AND i.source_account_id=%s AND e.message_id IS NOT NULL",
            (account_id,),
        )
        return {(r["message_id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()}


def _parse_date(raw):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:  # noqa: BLE001 — malformed date must never break ingestion
        return None


def _to_item(gmail_id, em):
    """Map a get_email dict -> an ingest_source item (pure)."""
    recips = em.get("recipients")
    if isinstance(recips, (list, tuple)):
        to_addrs = ", ".join(str(r) for r in recips if r)
    else:
        to_addrs = recips or None
    return {
        "message_id": gmail_id,
        "from_addr": em.get("sender"),
        "to_addrs": to_addrs,
        "subject": em.get("subject"),
        "body_text": em.get("body_plain") or "",
        "body_html": em.get("body_html") or "",
        "sent_at": _parse_date(em.get("date")),
        "has_attachments": bool(em.get("attachments")),
    }


def _candidate_ids(account_id, seen, limit):
    """Enumerate up to `limit` message ids not already in Chronicle (newest first)."""
    candidates = []
    page_token = None
    # cap the enumeration pages so a huge mailbox can't loop unbounded for a small limit
    for _ in range(40):
        msgs, page_token = gmail_service.list_all_message_ids(account_id, page_token=page_token, max_per_page=500)
        for m in msgs or []:
            gid = m["id"] if isinstance(m, dict) else m
            if gid and gid not in seen:
                candidates.append(gid)
                if len(candidates) >= limit:
                    return candidates
        if not page_token or not msgs:
            break
    return candidates


def run_gmail_ingest(account_id, limit=50):
    """Fetch up to `limit` not-yet-ingested Gmail messages (format=full) and land their full
    bodies into Chronicle. Returns a summary dict. Per-message errors are counted, not raised."""
    owner_id = _owner_id_for_account(account_id)
    seen = _seen_message_ids(account_id)
    candidates = _candidate_ids(account_id, seen, limit)

    items = []
    errors = 0
    for gid in candidates:
        try:
            em = gmail_service.get_email(account_id, gid)
            items.append(_to_item(gid, em))
        except Exception:  # noqa: BLE001 — one bad fetch must not abort the run
            errors += 1
            logger.exception("chronicle gmail fetch failed acct=%s msg=%s", account_id, gid)

    if items:
        res = ingest_source("gmail", account_id, items, owner_id=owner_id, is_live=True)
    else:
        res = {"import_id": None, "inserted": 0, "skipped": 0}

    return {
        "account_id": account_id,
        "candidates": len(candidates),
        "fetched": len(items),
        "errors": errors,
        "import_id": res.get("import_id"),
        "inserted": res.get("inserted", 0),
        "skipped": res.get("skipped", 0),
    }
