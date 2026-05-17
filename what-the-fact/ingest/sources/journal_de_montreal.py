"""Le Journal de Montréal RSS fetcher — Québecor tabloid, largest French daily, right."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "journal_de_montreal"
SOURCE_NAME = "Le Journal de Montréal"
SOURCE_URL = "https://www.journaldemontreal.com"
RSS_URL = "https://www.journaldemontreal.com/actualite/rss.xml"  # 2026-05-17: old /rss/nouvelles 404s, new path is /actualite/rss.xml (24 items, verified from US VPS)
BIAS_LEAN = "right"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
