"""Sovereign attachment text extraction (COO Cockpit Slice 2).

Decode uploaded bytes to a temp file, run the existing extract_text_from_file
(PDF / docx / text / image-OCR), cap the returned text, and always clean up the
temp file. Fail-SOFT: a genuinely unreadable file yields text="" + an error note
so the cockpit chat message can still send without the attachment context.
"""

import logging
import os
import tempfile

from services.chronicle_attachment_service import extract_text_from_file

logger = logging.getLogger(__name__)

ATTACHMENT_TEXT_CAP = 20000  # max chars of extracted text returned to the model


def extract_payload(filename, raw_bytes, mime=None):
    """(filename, bytes, mime) -> {text, chars, ocr_used, truncated[, error]}."""
    suffix = os.path.splitext(filename or "")[1][:10]  # preserve ext so _kind() classifies
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw_bytes)
        text, ocr_used = extract_text_from_file(tmp_path, mime)
        text = text or ""
        truncated = len(text) > ATTACHMENT_TEXT_CAP
        if truncated:
            logger.info("attachment %s truncated %d -> %d chars", filename, len(text), ATTACHMENT_TEXT_CAP)
            text = text[:ATTACHMENT_TEXT_CAP]
        return {"text": text, "chars": len(text), "ocr_used": bool(ocr_used), "truncated": truncated}
    except Exception as exc:  # fail-soft — the chat message still sends without the text
        logger.warning("attachment extract failed for %s: %s", filename, exc)
        return {"text": "", "chars": 0, "ocr_used": False, "truncated": False, "error": str(exc)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
