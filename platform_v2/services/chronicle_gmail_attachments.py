"""Chronicle Gmail attachment download (slice 06).

For messages already ingested into a Chronicle gmail import (mailbox_emails with
has_attachments=true and no attachment rows yet), download each attachment file via the
Gmail API, save it under /mnt/data2/mailbox_story/<import_id>/att/<email_id>/<filename>,
and register it via chronicle_ingest.upsert_attachment (state 'new') so the Slice-03
extraction engine text/OCRs it. Resumable (skips emails that already have attachment rows),
bounded by `limit`, per-attachment error-isolated. No scheduler / DHQ / LLM here.
"""

import base64
import hashlib
import logging
import os

from tools.google_work_suite.services import gmail_service
from tools.google_work_suite.services.google_api_service import get_gmail_client
from services.chronicle_ingest import upsert_attachment

logger = logging.getLogger(__name__)

STORAGE_ROOT = "/mnt/data2/mailbox_story"  # tests monkeypatch this


def _scalar(row):
    if row is None:
        return None
    return row["id"] if isinstance(row, dict) else row[0]


def _account_for_import(import_id):
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT source_account_id FROM mailbox_imports WHERE id=%s", (import_id,))
        row = cur.fetchone()
    if not row:
        return None
    return row["source_account_id"] if isinstance(row, dict) else row[0]


def _candidate_emails(import_id, limit):
    """(email_id, message_id) for emails in this import that have attachments but no rows yet."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT e.id, e.message_id FROM mailbox_emails e WHERE e.import_id=%s "
            "AND e.has_attachments=TRUE AND e.message_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM mailbox_attachments a WHERE a.email_id=e.id) "
            "ORDER BY e.id LIMIT %s",
            (import_id, limit),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append((r["id"], r["message_id"]))
        else:
            out.append((r[0], r[1]))
    return out


def _get_attachment_bytes(account_id, gmail_id, attachment_id):
    service = get_gmail_client(account_id)
    res = service.users().messages().attachments().get(userId="me", messageId=gmail_id, id=attachment_id).execute()
    return base64.urlsafe_b64decode(res["data"])


def _safe_name(filename):
    base = os.path.basename(filename or "").strip()
    base = base.replace("/", "_").replace("\\", "_")
    return base or "attachment"


def run_attachment_download(import_id, limit=50):
    """Download + register attachments for up to `limit` not-yet-processed emails in a Chronicle
    gmail import. Returns a summary dict. Per-attachment errors are counted, not raised."""
    account_id = _account_for_import(import_id)
    if account_id is None:
        return {"import_id": import_id, "emails_processed": 0, "attachments_saved": 0, "errors": 0}

    emails = _candidate_emails(import_id, limit)
    saved = errors = 0
    for email_id, gmail_id in emails:
        try:
            atts = gmail_service.get_email(account_id, gmail_id).get("attachments") or []
        except Exception:  # noqa: BLE001 — one bad message must not abort the run
            errors += 1
            logger.exception("chronicle att: get_email failed import=%s email=%s", import_id, email_id)
            continue
        dest_dir = os.path.join(STORAGE_ROOT, str(import_id), "att", str(email_id))
        for att in atts:
            att_id = att.get("attachmentId")
            if not att_id:
                continue
            try:
                data = _get_attachment_bytes(account_id, gmail_id, att_id)
                os.makedirs(dest_dir, exist_ok=True)
                fname = _safe_name(att.get("filename"))
                path = os.path.join(dest_dir, fname)
                with open(path, "wb") as fh:
                    fh.write(data)
                sha = hashlib.sha256(data).hexdigest()
                upsert_attachment(email_id, fname, att.get("mimeType"), len(data), sha, path)
                saved += 1
            except Exception:  # noqa: BLE001 — one bad attachment must not abort the run
                errors += 1
                logger.exception(
                    "chronicle att: download failed import=%s email=%s att=%s",
                    import_id,
                    email_id,
                    att_id,
                )
    return {
        "import_id": import_id,
        "emails_processed": len(emails),
        "attachments_saved": saved,
        "errors": errors,
    }
