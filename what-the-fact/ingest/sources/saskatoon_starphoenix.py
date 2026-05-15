"""Saskatoon StarPhoenix RSS fetcher — Postmedia, Saskatchewan, center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "saskatoon_starphoenix"
SOURCE_NAME = "Saskatoon StarPhoenix"
SOURCE_URL = "https://thestarphoenix.com"
RSS_URL = "https://thestarphoenix.com/feed"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
