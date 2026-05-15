"""The Conversation Canada RSS fetcher — academic experts writing for general public, center-left."""
from .rss_generic import fetch_rss

SOURCE_SLUG = "the_conversation_canada"
SOURCE_NAME = "The Conversation Canada"
SOURCE_URL = "https://theconversation.com/ca"
RSS_URL = "https://theconversation.com/ca/articles.atom"
BIAS_LEAN = "center-left"


def fetch_articles() -> list[dict]:
    return fetch_rss(RSS_URL, SOURCE_SLUG)
