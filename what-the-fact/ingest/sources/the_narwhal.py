"""The Narwhal RSS fetcher — Canadian investigative journalism."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "the_narwhal"
SOURCE_NAME = "The Narwhal"
SOURCE_URL = "https://thenarwhal.ca"
RSS_URL = "https://thenarwhal.ca/feed/"
BIAS_LEAN = "center-left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
