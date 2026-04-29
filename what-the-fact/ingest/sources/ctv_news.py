"""CTV News RSS fetcher — RSS discontinued as of 2026-04-29, all URLs 404."""

SOURCE_SLUG = "ctv_news"
SOURCE_NAME = "CTV News"
SOURCE_URL = "https://www.ctvnews.ca"
RSS_URL = ""  # RSS feed discontinued
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return []
