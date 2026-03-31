"""News sentiment scoring per ticker."""

import logging
from datetime import datetime, timedelta

import yfinance as yf

from db import get_db

POSITIVE_WORDS = {
    "surge", "soar", "beat", "upgrade", "bullish", "record", "growth",
    "profit", "gain", "rally", "boom", "strong", "outperform", "buy",
    "breakout", "dividend", "innovation", "partnership", "expansion",
}

NEGATIVE_WORDS = {
    "crash", "plunge", "miss", "downgrade", "bearish", "loss", "decline",
    "sell", "warning", "layoff", "debt", "lawsuit", "investigation",
    "recall", "bankruptcy", "fraud", "cut", "weak", "underperform",
}


def _keyword_score(text):
    """Score a headline -1 to 1 based on keyword counts."""
    words = text.lower().split()
    pos = sum(1 for w in words if w.strip(".,!?") in POSITIVE_WORDS)
    neg = sum(1 for w in words if w.strip(".,!?") in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _store_score(ticker, source, headline, score, url):
    """Store a sentiment score in the DB."""
    try:
        db = get_db()
        db.execute(
            """INSERT OR IGNORE INTO sentiment_scores
               (ticker, source, headline, score, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticker, source, headline, score, url, datetime.utcnow().isoformat()),
        )
        db.commit()
    except Exception as e:
        logging.debug("sentiment _store_score error: %s", e)


def fetch_and_score_news(ticker, limit=20):
    """Fetch recent news for ticker, score each headline, store and return results."""
    results = []
    try:
        news_items = yf.Ticker(ticker).news or []
        for item in news_items[:limit]:
            headline = item.get("title", "")
            source = item.get("publisher", "")
            url = item.get("link", "")
            published = item.get("providerPublishTime", 0)
            score = _keyword_score(headline)
            _store_score(ticker, source, headline, score, url)
            results.append(
                {
                    "headline": headline,
                    "source": source,
                    "score": score,
                    "url": url,
                    "published": datetime.utcfromtimestamp(published).isoformat()
                    if published
                    else None,
                }
            )
    except Exception as e:
        logging.debug("fetch_and_score_news error for %s: %s", ticker, e)
    return results


def get_sentiment_summary(ticker, days=7):
    """Return sentiment summary for ticker over last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    try:
        db = get_db()
        rows = db.execute(
            """SELECT headline, source, score, url, created_at
               FROM sentiment_scores
               WHERE ticker = ? AND created_at >= ?
               ORDER BY created_at DESC""",
            (ticker, cutoff),
        ).fetchall()

        if not rows:
            fetch_and_score_news(ticker)
            rows = db.execute(
                """SELECT headline, source, score, url, created_at
                   FROM sentiment_scores
                   WHERE ticker = ? AND created_at >= ?
                   ORDER BY created_at DESC""",
                (ticker, cutoff),
            ).fetchall()

        scores = [r["score"] for r in rows]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        positive_count = sum(1 for s in scores if s > 0.1)
        negative_count = sum(1 for s in scores if s < -0.1)
        neutral_count = len(scores) - positive_count - negative_count

        headlines = [
            {
                "headline": r["headline"],
                "source": r["source"],
                "score": r["score"],
                "url": r["url"],
                "date": r["created_at"],
            }
            for r in rows[:10]
        ]

        return {
            "ticker": ticker,
            "avg_score": round(avg_score, 4),
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "total": len(scores),
            "headlines": headlines,
        }
    except Exception as e:
        logging.debug("get_sentiment_summary error for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "avg_score": 0.0,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "total": 0,
            "headlines": [],
        }
