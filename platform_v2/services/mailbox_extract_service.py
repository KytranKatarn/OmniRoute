"""mailbox_extract_service.py — Mailbox Story Extractor extraction engine (Phase 1).

readpst (libpst/pst-utils) converts a .pst into one .eml per message under a folder tree;
we parse each .eml (stdlib `email`) into a mailbox_emails row. PRIVACY: everything is local —
readpst is a local binary, files stay on local disk, no network. Enrichment (Phase 2) runs
on local-only fleet LLMs.

Usage (from the upload route's background job):
    n = extract_pst(import_id, '/mnt/data2/mailbox_story/<id>/source.pst',
                    '/mnt/data2/mailbox_story/<id>/eml')
"""

import email
import logging
import os
import subprocess
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from database import get_db_cursor

logger = logging.getLogger(__name__)

_BODY_CAP = 100_000  # chars of plain-text body stored per email
_READPST_TIMEOUT = 3600  # a big PST can take a while; bounded


def _addrs(msg, field):
    """Comma-joined email addresses for a header (From/To/Cc), or None."""
    vals = msg.get_all(field, [])
    addrs = [a for _, a in getaddresses(vals) if a]
    return ", ".join(addrs) or None


def _body_text(msg):
    """Best-effort plain-text body. Prefers text/plain parts; never raises."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(
                    part.get("Content-Disposition", "")
                ):
                    try:
                        return part.get_content()
                    except Exception:
                        raw = part.get_payload(decode=True) or b""
                        return raw.decode("utf-8", "replace")
            return ""
        try:
            return msg.get_content()
        except Exception:
            raw = msg.get_payload(decode=True) or b""
            return raw.decode("utf-8", "replace")
    except Exception:
        return ""


def _has_attachments(msg):
    try:
        return any("attachment" in str(p.get("Content-Disposition", "")) for p in msg.walk())
    except Exception:
        return False


def parse_eml(path, folder):
    """Parse one .eml file -> dict of mailbox_emails columns. Never raises on bad headers."""
    with open(path, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=policy.default)
    sent = None
    if msg.get("Date"):
        try:
            sent = parsedate_to_datetime(msg.get("Date"))
        except Exception:
            sent = None
    return {
        "folder": folder,
        "message_id": (msg.get("Message-ID") or None),
        "in_reply_to": (msg.get("In-Reply-To") or None),
        "from_addr": _addrs(msg, "From"),
        "to_addrs": _addrs(msg, "To"),
        "cc_addrs": _addrs(msg, "Cc"),
        "sent_at": sent,
        "subject": (msg.get("Subject") or None),
        "body_text": (_body_text(msg) or "")[:_BODY_CAP],
        "has_attachments": _has_attachments(msg),
    }


def _mark_error(import_id, message):
    """Flip an import to 'error' with a bounded message. Never raises (best-effort)."""
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                "UPDATE mailbox_imports SET status='error', error=%s WHERE id=%s",
                ((message or "extraction failed")[:1000], import_id),
            )
    except Exception:
        logger.exception("could not mark import %s as error", import_id)


def extract_pst(import_id, pst_path, out_dir):
    """Run readpst on `pst_path`, parse every .eml into mailbox_emails, update the import row.
    Returns the number of emails ingested. Marks the import 'error' on ANY failure
    (readpst timeout / spawn failure / non-zero exit / a DB error during the walk) so a
    caller never has to depend on its own exception handling to avoid a stuck 'extracting'."""
    os.makedirs(out_dir, exist_ok=True)
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("UPDATE mailbox_imports SET status='extracting' WHERE id=%s", (import_id,))

    # -e = one .eml per message; -D = include deleted; -o = output dir. Local binary, no network.
    try:
        proc = subprocess.run(
            ["readpst", "-e", "-D", "-o", out_dir, pst_path],
            capture_output=True,
            text=True,
            timeout=_READPST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.error("readpst timed out after %ss for import %s", _READPST_TIMEOUT, import_id)
        _mark_error(import_id, f"readpst timed out after {_READPST_TIMEOUT}s")
        return 0
    except Exception as exc:  # FileNotFoundError (readpst missing), OSError, etc.
        logger.exception("readpst could not run for import %s", import_id)
        _mark_error(import_id, f"readpst failed to start: {exc}")
        return 0
    if proc.returncode != 0:
        logger.error("readpst failed (%s): %s", proc.returncode, (proc.stderr or "")[:500])
        _mark_error(import_id, proc.stderr or "readpst failed")
        return 0

    count = 0
    try:
        with get_db_cursor(commit=True) as (_conn, cur):
            for root, _dirs, files in os.walk(out_dir):
                folder = os.path.relpath(root, out_dir)
                for fn in files:
                    if not fn.lower().endswith(".eml"):
                        continue
                    try:
                        rec = parse_eml(os.path.join(root, fn), folder if folder != "." else "")
                    except Exception as exc:
                        logger.warning("parse failed for %s: %s", fn, exc)
                        continue
                    rec["i"] = import_id
                    cur.execute(
                        """
                        INSERT INTO mailbox_emails
                            (import_id, folder, message_id, in_reply_to, from_addr, to_addrs,
                             cc_addrs, sent_at, subject, body_text, has_attachments)
                        VALUES (%(i)s, %(folder)s, %(message_id)s, %(in_reply_to)s, %(from_addr)s,
                                %(to_addrs)s, %(cc_addrs)s, %(sent_at)s, %(subject)s, %(body_text)s,
                                %(has_attachments)s)
                    """,
                        rec,
                    )
                    count += 1
            cur.execute(
                "UPDATE mailbox_imports SET status='extracted', email_count=%s WHERE id=%s",
                (count, import_id),
            )
    except Exception as exc:  # DB error / disk error during the walk — don't leave it 'extracting'
        logger.exception("mailbox import %s failed during email ingest", import_id)
        _mark_error(import_id, f"ingest failed after {count} emails: {exc}")
        return 0
    logger.info("mailbox import %s: extracted %d emails", import_id, count)
    return count
