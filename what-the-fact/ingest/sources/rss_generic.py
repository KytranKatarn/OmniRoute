"""Generic RSS fetcher used by all WTF source modules."""
from datetime import datetime
import logging

import feedparser
import requests

logger = logging.getLogger(__name__)


def fetch_rss(rss_url: str, source_slug: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns raw article dicts (not canonicalized)."""
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
                "published_at": pub or datetime.utcnow(),
            }
        )
    logger.info("%s: fetched %d articles", source_slug, len(out))
    return out
