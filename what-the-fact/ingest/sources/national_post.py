"""National Post RSS fetcher."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "national_post"
SOURCE_NAME = "National Post"
SOURCE_URL = "https://nationalpost.com"
RSS_URL = "https://nationalpost.com/feed"
BIAS_LEAN = "center-right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
