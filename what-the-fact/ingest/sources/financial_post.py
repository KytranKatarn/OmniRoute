"""Financial Post RSS fetcher — Postmedia business/economy coverage, center-right."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "financial_post"
SOURCE_NAME = "Financial Post"
SOURCE_URL = "https://financialpost.com"
RSS_URL = "https://financialpost.com/feed"
BIAS_LEAN = "center-right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
