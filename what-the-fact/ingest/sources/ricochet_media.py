"""Ricochet Media RSS fetcher — progressive Canadian news, left."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "ricochet_media"
SOURCE_NAME = "Ricochet Media"
SOURCE_URL = "https://ricochet.media"
RSS_URL = "https://ricochet.media/feed/"
BIAS_LEAN = "left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
