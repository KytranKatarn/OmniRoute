"""Sentiment service — VADER-based aggregation from news_cache.

Preserves the same interface the W.A.T.C.H. pipeline uses:
    - fetch_and_score_news(ticker) -> list of scored items
    - get_sentiment_summary(ticker) -> aggregated summary dict
"""

import logging
from datetime import datetime, timedelta

from db import get_db
from services.news_service import (
    fetch_all_news,
    score_headlines,
    store_headlines,
    get_cached_news,
    NEWS_MAX_AGE_MINUTES,
)

logger = logging.getLogger(__name__)


def fetch_and_score_news(ticker, limit=20):
    """Fetch news for ticker, score with VADER, store in cache.

    Returns list of dicts: [{headline, url, source, vader_score, vader_sentiment, published_at}]
    """
    # Check cache first
    cached = get_cached_news(ticker)
    if cached:
        logger.debug("Using cached news for %s (%d items)", ticker, len(cached))
        return cached[:limit]

    # Fetch fresh from all sources
    headlines = fetch_all_news(ticker)
    if not headlines:
        logger.info("No news found for %s", ticker)
        return []

    # VADER score
    scored = score_headlines(headlines)

    # Store in cache
    store_headlines(ticker, scored)

    return scored[:limit]


def get_sentiment_summary(ticker, days=7):
    """Aggregate sentiment from news_cache for a ticker.

    Returns dict with: ticker, avg_score, positive_count, negative_count,
    neutral_count, total, sentiment (overall label), headlines (top 10)
    """
    conn = get_db()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT headline, source, vader_score, vader_sentiment, url, published_at
               FROM news_cache
               WHERE ticker = ? AND fetched_at > ?
               ORDER BY fetched_at DESC""",
            (ticker.upper(), cutoff),
        ).fetchall()

        if not rows:
            return {
                "ticker": ticker,
                "avg_score": 0.0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total": 0,
                "sentiment": "neutral",
                "headlines": [],
            }

        scores = [r["vader_score"] for r in rows if r["vader_score"] is not None]
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

        positive = sum(1 for r in rows if r["vader_sentiment"] == "positive")
        negative = sum(1 for r in rows if r["vader_sentiment"] == "negative")
        neutral = sum(1 for r in rows if r["vader_sentiment"] == "neutral")

        if avg_score >= 0.05:
            overall = "positive"
        elif avg_score <= -0.05:
            overall = "negative"
        else:
            overall = "neutral"

        headlines = [
            {
                "headline": r["headline"],
                "source": r["source"],
                "score": r["vader_score"],
                "url": r["url"],
                "date": r["published_at"],
            }
            for r in rows[:10]
        ]

        return {
            "ticker": ticker,
            "avg_score": avg_score,
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "total": len(rows),
            "sentiment": overall,
            "headlines": headlines,
        }
    finally:
        conn.close()
