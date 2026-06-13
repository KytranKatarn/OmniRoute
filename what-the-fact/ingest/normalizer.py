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
    # Strip RSS syndication footers (Postmedia/Quebecor/etc.)
    body = re.sub(
        r"The post .{1,200} appeared first on [^.]{1,80}\.?\s*$",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip()
    # Strip leading pull-quote snippet that is the entire body (e.g. "Quote text")
    if body and body.startswith('"') and len(body) < 300 and body.count('"') <= 2:
        body = ""
    title = (raw.get("title") or "").strip()[:1024]
    author = (raw.get("author") or "").strip() or None
    return {
        "external_id": raw["external_id"][:512],
        "title": title,
        "body": body,
        "url": raw["url"][:1024],
        "published_at": raw["published_at"],
        "author": author,
    }
