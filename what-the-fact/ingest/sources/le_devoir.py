"""Le Devoir RSS fetcher — independent French-language Quebec daily."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "le_devoir"
SOURCE_NAME = "Le Devoir"
SOURCE_URL = "https://www.ledevoir.com"
RSS_URL = "https://www.ledevoir.com/rss/manchettes.xml"
BIAS_LEAN = "center-left"
LANGUAGE = "fr"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
