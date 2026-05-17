"""BNN Bloomberg Canada RSS fetcher — business/markets/economy, center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "bnn_bloomberg"
SOURCE_NAME = "BNN Bloomberg"
SOURCE_URL = "https://www.bnnbloomberg.ca"
RSS_URL = "https://news.google.com/rss/search?q=site:bnnbloomberg.ca&hl=en-CA&gl=CA&ceid=CA:en"  # 2026-05-17: native /rss 404s post-CTV-merger; falls back to Google News RSS (100 items, verified from US VPS). Body content is Google snippets (~150 chars).
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
