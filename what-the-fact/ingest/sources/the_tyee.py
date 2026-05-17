"""The Tyee RSS fetcher — BC-based independent investigative journalism, left-leaning."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "the_tyee"
SOURCE_NAME = "The Tyee"
SOURCE_URL = "https://thetyee.ca"
RSS_URL = "https://news.google.com/rss/search?q=site:thetyee.ca&hl=en-CA&gl=CA&ceid=CA:en"  # 2026-05-17: native /rss/feed/ 404s; falls back to Google News RSS (100 items, verified from US VPS). Body content is Google snippets (~150 chars).
BIAS_LEAN = "left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
