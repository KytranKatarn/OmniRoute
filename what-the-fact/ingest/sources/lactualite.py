"""L'actualité RSS fetcher — French-language news magazine, center-left."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "lactualite"
SOURCE_NAME = "L'actualité"
SOURCE_URL = "https://lactualite.com"
RSS_URL = "https://lactualite.com/feed/"
BIAS_LEAN = "center-left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
