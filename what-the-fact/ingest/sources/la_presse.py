"""La Presse fetcher — native RSS discontinued 2026-04-29; falls back to Google News RSS scoped to lapresse.ca (44 items, verified from US VPS 2026-05-17). Body is Google snippets (~150 chars) — adequate for bias scoring + clustering, marginal for fact-checking."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "la_presse"
SOURCE_NAME = "La Presse"
SOURCE_URL = "https://www.lapresse.ca"
RSS_URL = "https://news.google.com/rss/search?q=site:lapresse.ca&hl=en-CA&gl=CA&ceid=CA:en"
BIAS_LEAN = "center-left"
LANGUAGE = "fr"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
