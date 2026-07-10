"""Chronicle attachment extraction engine (slice 03) — file on disk -> text.

Source-agnostic: source adapters download the file + insert a mailbox_attachments
row (state 'new'); this drains those rows, extracts text by type (PDF via PyPDF2,
docx via python-docx, plain by read, images via tesseract OCR), and stores the
result. CPU work only — no LLM / DHQ dispatch. Resumable via extract_status;
each row is independent so a failure never blocks the batch.
"""

import logging
import os

logger = logging.getLogger(__name__)

_TEXT_EXT = {".txt", ".md", ".csv", ".log", ".json", ".eml", ".html", ".htm"}
_DOCX_EXT = {".docx"}
_PDF_EXT = {".pdf"}
_IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"}


def _kind(path: str, mime_type):
    """Classify -> 'pdf'|'docx'|'text'|'image'|'other' by mime first, then extension."""
    mt = (mime_type or "").lower()
    if "pdf" in mt:
        return "pdf"
    if "wordprocessingml" in mt or mt == "application/msword":
        return "docx"
    if mt.startswith("text/"):
        return "text"
    if mt.startswith("image/"):
        return "image"
    ext = os.path.splitext(path)[1].lower()
    if ext in _PDF_EXT:
        return "pdf"
    if ext in _DOCX_EXT:
        return "docx"
    if ext in _TEXT_EXT:
        return "text"
    if ext in _IMG_EXT:
        return "image"
    return "other"


def extract_text_from_file(path: str, mime_type=None):
    """Extract text from a file on disk. Returns (text, ocr_used). Raises on a
    genuinely unreadable file so the caller can mark the row 'error'."""
    kind = _kind(path, mime_type)
    if kind == "pdf":
        from PyPDF2 import PdfReader

        reader = PdfReader(path)
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 — one bad page shouldn't kill the doc
                continue
        return ("\n".join(parts).strip(), False)
    if kind == "docx":
        import docx

        doc = docx.Document(path)
        return ("\n".join(p.text for p in doc.paragraphs).strip(), False)
    if kind == "text":
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return (fh.read().strip(), False)
    if kind == "image":
        from tools.family_tree.services.ocr_service import ocr_document

        return ((ocr_document(path, language="eng+fra") or "").strip(), True)
    return ("", False)  # unknown/binary type: no text, not an error


def extract_attachment(attachment_id: int) -> str:
    """Extract one mailbox_attachments row; update extracted_text/ocr_used/status.
    Returns the resulting status ('done'|'error'). Never raises."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT stored_path, mime_type FROM mailbox_attachments WHERE id = %s",
                (attachment_id,),
            )
            row = cur.fetchone()
            if not row:
                return "error"
            stored_path = row["stored_path"] if isinstance(row, dict) else row[0]
            mime_type = row["mime_type"] if isinstance(row, dict) else row[1]
    except Exception as e:  # noqa: BLE001 — a single row's DB failure must never abort the batch
        logger.exception("attachment %s row fetch failed", attachment_id)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE mailbox_attachments SET extract_status='error', error=%s WHERE id=%s",
                    (str(e)[:500], attachment_id),
                )
        except Exception:  # noqa: BLE001 — best-effort; even the error-write must not raise
            logger.exception("attachment %s error-write failed", attachment_id)
        return "error"

    if not stored_path or not os.path.exists(stored_path):
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE mailbox_attachments SET extract_status='error', error=%s WHERE id=%s",
                ("file missing", attachment_id),
            )
        return "error"

    try:
        text, ocr_used = extract_text_from_file(stored_path, mime_type)
    except Exception as e:  # noqa: BLE001
        logger.exception("attachment %s extract failed", attachment_id)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE mailbox_attachments SET extract_status='error', error=%s WHERE id=%s",
                (str(e)[:500], attachment_id),
            )
        return "error"

    # Postgres TEXT columns cannot hold NUL (0x00) bytes, which OCR/PDF extraction routinely
    # emits. Strip them so the row stores as 'done' — otherwise the write below raises, the
    # row stays 'new', and run_attachment_extraction re-selects and re-fails it every cycle
    # (poison-pill spin). The text is still recovered, just without the stray NULs.
    if text and "\x00" in text:
        text = text.replace("\x00", "")

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE mailbox_attachments SET extracted_text=%s, ocr_used=%s, "
                "extract_status='done', error=NULL WHERE id=%s",
                (text, ocr_used, attachment_id),
            )
    except Exception as e:  # noqa: BLE001 — defense-in-depth: a failed store must persist
        # 'error', never leave the row 'new' (which would re-spin it forever).
        logger.exception("attachment %s store failed", attachment_id)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE mailbox_attachments SET extract_status='error', error=%s WHERE id=%s",
                    (str(e)[:500], attachment_id),
                )
        except Exception:  # noqa: BLE001 — best-effort; even the error-write must not raise
            logger.exception("attachment %s error-write failed", attachment_id)
        return "error"
    return "done"


def run_attachment_extraction(limit: int = 50) -> dict:
    """Drain up to `limit` 'new' attachments (with a file on disk). Resumable."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id FROM mailbox_attachments WHERE extract_status='new' "
            "AND stored_path IS NOT NULL ORDER BY id LIMIT %s",
            (limit,),
        )
        ids = [(r["id"] if isinstance(r, dict) else r[0]) for r in cur.fetchall()]

    done = err = 0
    for aid in ids:
        try:
            status = extract_attachment(aid)
        except Exception:  # noqa: BLE001 — backstop: extract_attachment must never raise, but
            # if it somehow does, one row can never abort the rest of the batch.
            logger.exception("attachment %s raised out of extract_attachment", aid)
            err += 1
            continue
        if status == "done":
            done += 1
        else:
            err += 1
    return {"processed": len(ids), "done": done, "error": err}
