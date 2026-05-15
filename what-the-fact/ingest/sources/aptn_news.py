"""APTN National News RSS fetcher — Indigenous public broadcaster, center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "aptn_news"
SOURCE_NAME = "APTN National News"
SOURCE_URL = "https://www.aptnnews.ca"
RSS_URL = "https://www.aptnnews.ca/feed/"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
