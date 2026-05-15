"""SaltWire Network RSS fetcher — Atlantic Canada regional news (Chronicle Herald, Cape Breton Post, etc.), center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "saltwire_news"
SOURCE_NAME = "SaltWire Network"
SOURCE_URL = "https://www.saltwire.com"
RSS_URL = "https://www.saltwire.com/rss/news"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
