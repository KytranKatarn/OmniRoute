"""CBC English top-stories RSS fetcher."""

from datetime import datetime, timezone
import logging
import requests

from .rss_generic import extract_byline

logger = logging.getLogger(__name__)
CBC_URL = "https://www.cbc.ca/cmlink/rss-topstories"
SOURCE_SLUG = "cbc_english"


def fetch_articles() -> list[dict]:
    """Fetch + parse. Returns list of raw article dicts (NOT canonicalized)."""
    import feedparser

    resp = requests.get(CBC_URL, timeout=10, headers={"User-Agent": "WTF-Ingest/0.1"})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    out = []
    for entry in feed.entries:
        pub = None
        if entry.get("published_parsed"):
            pub = datetime(*entry.published_parsed[:6])
        out.append(
            {
                "external_id": entry.get("id") or entry.get("link"),
                "title": entry.get("title", "").strip(),
                "body": entry.get("summary", "").strip(),
                "url": entry.get("link", ""),
                "published_at": pub or datetime.now(timezone.utc).replace(tzinfo=None),
                "author": extract_byline(entry),
            }
        )
    logger.info("cbc_english: fetched %d articles", len(out))
    return out
