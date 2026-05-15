"""Le Journal de Montréal RSS fetcher — Québecor tabloid, largest French daily, right."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "journal_de_montreal"
SOURCE_NAME = "Le Journal de Montréal"
SOURCE_URL = "https://www.journaldemontreal.com"
RSS_URL = "https://www.journaldemontreal.com/rss/nouvelles"
BIAS_LEAN = "right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
