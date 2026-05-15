"""Edmonton Journal RSS fetcher — Postmedia, Alberta capital daily, center-right."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "edmonton_journal"
SOURCE_NAME = "Edmonton Journal"
SOURCE_URL = "https://edmontonjournal.com"
RSS_URL = "https://edmontonjournal.com/feed"
BIAS_LEAN = "center-right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
