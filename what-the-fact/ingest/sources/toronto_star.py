"""Toronto Star RSS fetcher."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "toronto_star"
SOURCE_NAME = "Toronto Star"
SOURCE_URL = "https://www.thestar.com"
RSS_URL = "https://www.thestar.com/content/thestar/feed.rss"
BIAS_LEAN = "center-left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
