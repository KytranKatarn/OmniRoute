"""MIME parsing utilities for Email HQ full-body sync."""

from __future__ import annotations

import email.header
import email.message
import email.utils
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 200


def decode_header_value(value: str) -> str:
    """RFC2047-decode an email header value (Subject, From, etc.)."""
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
        decoded = []
        for chunk, charset in parts:
            if isinstance(chunk, bytes):
                decoded.append(chunk.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(chunk)
        return "".join(decoded)
    except Exception:
        return str(value)


def parse_received_at(msg: email.message.Message) -> datetime:
    """Extract the Date header as a UTC-aware datetime. Falls back to now()."""
    date_str = msg.get("Date", "")
    if date_str:
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def extract_body_parts(msg: email.message.Message) -> dict:
    """Walk a parsed email.message.Message and extract body parts.

    Returns:
        {
            "html": str | None,
            "text": str | None,
            "preview": str,
            "attachments": list[{"filename": str, "content_type": str, "size": int}],
        }
    """
    html_body: str | None = None
    text_body: str | None = None
    attachments: list[dict] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition() or ""

            if disposition == "attachment" or (part.get_filename() and content_type not in ("text/plain", "text/html")):
                attachments.append(
                    {
                        "filename": decode_header_value(part.get_filename() or "attachment"),
                        "content_type": content_type,
                        "size": len(part.get_payload(decode=True) or b""),
                    }
                )
                continue

            if content_type == "text/html" and html_body is None:
                html_body = _decode_part(part)
            elif content_type == "text/plain" and text_body is None:
                text_body = _decode_part(part)
    else:
        content_type = msg.get_content_type()
        if content_type == "text/html":
            html_body = _decode_part(msg)
        else:
            text_body = _decode_part(msg)

    preview = _make_preview(text_body or html_body or "")
    return {
        "html": html_body,
        "text": text_body,
        "preview": preview,
        "attachments": attachments,
    }


def _decode_part(part: email.message.Message) -> str:
    """Decode a single message part to a unicode string."""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, Exception):
        return payload.decode("utf-8", errors="replace")


def _make_preview(text: str) -> str:
    """Strip HTML tags if present and return first _PREVIEW_LEN chars."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:_PREVIEW_LEN]
