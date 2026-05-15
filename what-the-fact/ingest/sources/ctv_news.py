"""CTV News fetcher — native RSS discontinued 2026-04-29; falls back to Google News RSS."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "ctv_news"
SOURCE_NAME = "CTV News"
SOURCE_URL = "https://www.ctvnews.ca"
RSS_URL = "https://news.google.com/rss/search?q=site:ctvnews.ca&hl=en-CA&gl=CA&ceid=CA:en"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
