"""Toronto Star RSS fetcher — returns HTML (200) not XML as of 2026-04-29, effectively no feed."""

SOURCE_SLUG = "toronto_star"
SOURCE_NAME = "Toronto Star"
SOURCE_URL = "https://www.thestar.com"
RSS_URL = ""  # Returns HTML not RSS — feed discontinued
BIAS_LEAN = "center-left"


def fetch_articles() -> list[dict]:
    return []
