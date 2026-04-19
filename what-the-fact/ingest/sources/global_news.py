"""Global News top-stories RSS fetcher."""
from datetime import datetime
import logging
import feedparser
import requests

logger = logging.getLogger(__name__)
GLOBAL_NEWS_URL = "https://globalnews.ca/feed/"
SOURCE_SLUG = "global_news"


def fetch_articles() -> list[dict]:
    """Fetch + parse. Returns list of raw article dicts (NOT canonicalized)."""
    resp = requests.get(GLOBAL_NEWS_URL, timeout=10, headers={"User-Agent": "WTF-Ingest/0.1"})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    out = []
    for entry in feed.entries:
        pub = None
        if entry.get("published_parsed"):
            pub = datetime(*entry.published_parsed[:6])
        out.append({
            "external_id": entry.get("id") or entry.get("link"),
            "title":       entry.get("title", "").strip(),
            "body":        entry.get("summary", "").strip(),
            "url":         entry.get("link", ""),
            "published_at": pub or datetime.utcnow(),
        })
    logger.info("global_news: fetched %d articles", len(out))
    return out
