"""Montreal Gazette RSS fetcher — Postmedia, Quebec's largest English daily."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "montreal_gazette"
SOURCE_NAME = "Montreal Gazette"
SOURCE_URL = "https://montrealgazette.com"
RSS_URL = "https://montrealgazette.com/feed"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
