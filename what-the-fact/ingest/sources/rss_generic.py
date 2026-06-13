"""Generic RSS fetcher used by all WTF source modules."""

from datetime import datetime, timezone
import logging

import requests

logger = logging.getLogger(__name__)


def extract_byline(entry):
    """Best-effort author name from a feedparser entry (or any dict-like).

    Prefers the flat ``author`` string, then the first ``authors[].name``. Returns None
    when absent or blank. Pure + feedparser-free so it can be unit-tested without the
    parser installed (the container ships feedparser; the host test env need not)."""
    author = entry.get("author")
    if author and author.strip():
        return author.strip()
    authors = entry.get("authors") or []
    if authors and isinstance(authors[0], dict):
        name = authors[0].get("name")
        if name and name.strip():
            return name.strip()
    return None


def fetch_rss(rss_url: str, source_slug: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns raw article dicts (not canonicalized)."""
    import feedparser  # lazy: keeps extract_byline importable where feedparser is absent

    resp = requests.get(
        rss_url,
        timeout=15,
        headers={"User-Agent": "WTF-Ingest/1.0 (+https://what-the-fact.com)"},
    )
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    out = []
    for entry in feed.entries:
        pub = None
        if entry.get("published_parsed"):
            pub = datetime(*entry.published_parsed[:6])
        body = entry.get("summary", "")
        if not body and entry.get("content"):
            body = entry.content[0].get("value", "")
        out.append(
            {
                "external_id": entry.get("id") or entry.get("link", ""),
                "title": entry.get("title", "").strip(),
                "body": body.strip(),
                "url": entry.get("link", ""),
                "published_at": pub or datetime.now(timezone.utc).replace(tzinfo=None),
                "author": extract_byline(entry),
            }
        )
    logger.info("%s: fetched %d articles", source_slug, len(out))
    return out
