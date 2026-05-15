"""PressProgress RSS fetcher — progressive investigative journalism, left."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "press_progress"
SOURCE_NAME = "PressProgress"
SOURCE_URL = "https://pressprogress.ca"
RSS_URL = "https://pressprogress.ca/feed/"
BIAS_LEAN = "left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
