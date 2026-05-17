"""Winnipeg Free Press RSS fetcher — Manitoba's largest daily, center."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "winnipeg_free_press"
SOURCE_NAME = "Winnipeg Free Press"
SOURCE_URL = "https://www.winnipegfreepress.com"
RSS_URL = "https://www.winnipegfreepress.com/rss/"  # 2026-05-17: /rss/breakingnews returns HTML, /rss/ returns RSS (10 items, verified from US VPS)
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
