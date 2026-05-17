"""Toronto Star fetcher — native RSS discontinued 2026-04-29; falls back to Google News RSS (100 items, verified from US VPS 2026-05-17). Body is Google snippets (~150 chars) — adequate for bias scoring + clustering, marginal for fact-checking."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "toronto_star"
SOURCE_NAME = "Toronto Star"
SOURCE_URL = "https://www.thestar.com"
RSS_URL = "https://news.google.com/rss/search?q=site:thestar.com&hl=en-CA&gl=CA&ceid=CA:en"
BIAS_LEAN = "center-left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
