"""Canonicalize raw source-specific article dicts into a unified shape."""
import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")


def canonicalize(raw: dict) -> dict:
    if not raw.get("external_id"):
        raise ValueError("external_id required")
    if not raw.get("url"):
        raise ValueError("url required")
    body = unescape(_TAG_RE.sub("", raw.get("body") or "")).strip()
    body = re.sub(r"\s+", " ", body)
    title = (raw.get("title") or "").strip()[:1024]
    return {
        "external_id": raw["external_id"][:512],
        "title":       title,
        "body":        body,
        "url":         raw["url"][:1024],
        "published_at": raw["published_at"],
    }
