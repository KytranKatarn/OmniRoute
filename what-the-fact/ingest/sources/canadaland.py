"""Canadaland RSS fetcher — independent Canadian media criticism."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "canadaland"
SOURCE_NAME = "Canadaland"
SOURCE_URL = "https://www.canadaland.com"
RSS_URL = "https://www.canadaland.com/feed/"
BIAS_LEAN = "left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
