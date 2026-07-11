"""Thin cockpit->platform attachment extraction proxy (COO Cockpit Slice 2).

Base64-forwards the in-memory bytes to the platform @_require_internal_key extract
endpoint over the internal Docker network (PLATFORM_URL=http://archie_platform:3000
— never a public hostname). Fail-SOFT: any transport/non-200 result returns
{"ok": False, "error": ...} so the chat message still sends without the text.
"""

import base64
import logging
import os

import requests

logger = logging.getLogger(__name__)


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def format_attachment_block(filename, text, ocr_used, chars):
    """The block prepended to the outgoing message so the attachment rides the
    DHQ prompt: '\\n\\n[Attachment: <name> (<chars> chars, ocr=<bool>)]\\n<text>\\n'."""
    return f"\n\n[Attachment: {filename} ({chars} chars, ocr={str(bool(ocr_used)).lower()})]\n{text}\n"


def extract(filename, raw_bytes, mime=None):
    try:
        body = {
            "filename": filename,
            "content_b64": base64.b64encode(raw_bytes).decode(),
            "mime": mime,
        }
        r = requests.post(
            f"{_base()}/api/internal/attachments/extract",
            json=body,
            headers={"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"},
            timeout=30,
        )
        data = r.json() if r.content else {}
        if r.status_code == 200:
            return {"ok": True, **data}
        return {"ok": False, "error": data.get("error") or f"HTTP {r.status_code}"}
    except Exception as exc:  # fail-SOFT
        logger.warning("attachment extract proxy failed: %s", exc)
        return {"ok": False, "error": str(exc)}
