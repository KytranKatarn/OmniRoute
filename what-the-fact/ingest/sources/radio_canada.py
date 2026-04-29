"""Radio-Canada RSS fetcher — CBC's French-language public broadcaster."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "radio_canada"
SOURCE_NAME = "Radio-Canada"
SOURCE_URL = "https://ici.radio-canada.ca"
RSS_URL = "https://ici.radio-canada.ca/rss/4159"
BIAS_LEAN = "center-left"
LANGUAGE = "fr"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
