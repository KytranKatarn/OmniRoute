"""BNN Bloomberg Canada RSS fetcher — business/markets/economy, center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "bnn_bloomberg"
SOURCE_NAME = "BNN Bloomberg"
SOURCE_URL = "https://www.bnnbloomberg.ca"
RSS_URL = "https://www.bnnbloomberg.ca/rss"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
