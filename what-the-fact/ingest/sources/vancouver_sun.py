"""Vancouver Sun RSS fetcher — Postmedia, BC's largest English daily."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "vancouver_sun"
SOURCE_NAME = "Vancouver Sun"
SOURCE_URL = "https://vancouversun.com"
RSS_URL = "https://vancouversun.com/feed"
BIAS_LEAN = "center-right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
