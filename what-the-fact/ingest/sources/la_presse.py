"""La Presse RSS fetcher — major French-language Canadian daily."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "la_presse"
SOURCE_NAME = "La Presse"
SOURCE_URL = "https://www.lapresse.ca"
RSS_URL = "https://www.lapresse.ca/arc/outboundfeeds/rss/"
BIAS_LEAN = "center-left"
LANGUAGE = "fr"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
