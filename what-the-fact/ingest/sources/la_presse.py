"""La Presse RSS fetcher — major French-language Canadian daily.

La Presse discontinued their public RSS feed (all URLs return 404 as of 2026-04-29).
Returning empty list until an alternative feed or scrape method is available.
"""

SOURCE_SLUG = "la_presse"
SOURCE_NAME = "La Presse"
SOURCE_URL = "https://www.lapresse.ca"
RSS_URL = ""  # RSS feed discontinued — see module docstring
BIAS_LEAN = "center-left"
LANGUAGE = "fr"


def fetch_articles() -> list[dict]:
    return []
