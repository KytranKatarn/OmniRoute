"""Calgary Herald RSS fetcher — Postmedia, Alberta's largest daily, center-right."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "calgary_herald"
SOURCE_NAME = "Calgary Herald"
SOURCE_URL = "https://calgaryherald.com"
RSS_URL = "https://calgaryherald.com/feed"
BIAS_LEAN = "center-right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
