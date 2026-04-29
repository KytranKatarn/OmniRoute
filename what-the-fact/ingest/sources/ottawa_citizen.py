"""Ottawa Citizen RSS fetcher — Postmedia, Ottawa/federal politics focus."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "ottawa_citizen"
SOURCE_NAME = "Ottawa Citizen"
SOURCE_URL = "https://ottawacitizen.com"
RSS_URL = "https://ottawacitizen.com/feed"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
