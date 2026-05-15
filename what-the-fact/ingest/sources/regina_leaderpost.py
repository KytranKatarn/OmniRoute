"""Regina Leader-Post RSS fetcher — Postmedia, Saskatchewan capital, center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "regina_leaderpost"
SOURCE_NAME = "Regina Leader-Post"
SOURCE_URL = "https://leaderpost.com"
RSS_URL = "https://leaderpost.com/feed"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
