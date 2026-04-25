"""Globe and Mail RSS fetcher."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "globe_mail"
SOURCE_NAME = "The Globe and Mail"
SOURCE_URL = "https://www.theglobeandmail.com"
RSS_URL = "https://www.theglobeandmail.com/arc/outboundfeeds/rss/"
BIAS_LEAN = "center"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
