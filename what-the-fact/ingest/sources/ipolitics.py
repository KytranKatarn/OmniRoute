"""iPolitics RSS fetcher — Ottawa parliamentary coverage."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "ipolitics"
SOURCE_NAME = "iPolitics"
SOURCE_URL = "https://ipolitics.ca"
RSS_URL = "https://ipolitics.ca/feed/"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
