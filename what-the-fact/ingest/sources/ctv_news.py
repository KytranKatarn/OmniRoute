"""CTV News RSS fetcher."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "ctv_news"
SOURCE_NAME = "CTV News"
SOURCE_URL = "https://www.ctvnews.ca"
RSS_URL = "https://www.ctvnews.ca/rss/ctvnews-ca-top-stories-1.822066"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
