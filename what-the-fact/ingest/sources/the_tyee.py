"""The Tyee RSS fetcher — BC-based independent investigative journalism, left-leaning."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "the_tyee"
SOURCE_NAME = "The Tyee"
SOURCE_URL = "https://thetyee.ca"
RSS_URL = "https://thetyee.ca/rss/feed/"
BIAS_LEAN = "left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
