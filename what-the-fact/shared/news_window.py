"""The /news time window — one closed set, shared by the route and its tests.

Design wtf-news.html has a "Window" filter: All time / 24 hours / 7 days / 30 days.

CLOSED SET, on purpose. The route's page cache (`_NEWS_CACHE`, keyed on every filter) and
its faceted-crawl guards were built around a bounded set of filter values. An open
`?window=<anything>` would mint a new cache key and a new DB query per distinct string, which
is the crawler-amplification the August 2026 incident (a faceted-/news bot fleet wedging all
four workers) is documented in routes.py. So: an unknown value is not an error and not a new
key — it collapses to the default, "all", and renders the unfiltered page.

The hours are an integer from this table and are bound as a SQL parameter; the key the visitor
typed is never interpolated into SQL.
"""
from __future__ import annotations

DEFAULT_WINDOW = "all"

# key -> hours back from now, or None for no time restriction. Order is the UI order.
WINDOWS = {"all": None, "24h": 24, "7d": 7 * 24, "30d": 30 * 24}

# (key, label) in UI order; the labels are the design's.
WINDOW_META = [("all", "All time"), ("24h", "24 hours"), ("7d", "7 days"), ("30d", "30 days")]


def normalize_window(raw) -> str:
    """The query-string value -> a key in WINDOWS. Anything else -> "all"."""
    return raw if isinstance(raw, str) and raw in WINDOWS else DEFAULT_WINDOW


def window_hours(key: str):
    """Hours back for a normalised key, or None when there is no restriction."""
    return WINDOWS[normalize_window(key)]


def query_suffix(key: str) -> str:
    """'&window=7d' for an active window, '' for the default — so a clean /news stays clean
    and every existing URL is byte-identical until a window is actually chosen."""
    key = normalize_window(key)
    return "" if key == DEFAULT_WINDOW else f"&window={key}"
