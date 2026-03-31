"""News service — multi-source news fetch with VADER sentiment scoring."""

import os
import logging
from datetime import datetime, timedelta

import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from db import get_db

logger = logging.getLogger(__name__)

_vader = SentimentIntensityAnalyzer()

ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")
ALPHAVANTAGE_NEWS_ENABLED = os.environ.get("ALPHAVANTAGE_NEWS_ENABLED", "true").lower() in ("true", "1")
NEWS_MAX_AGE_MINUTES = int(os.environ.get("NEWS_MAX_AGE_MINUTES", 30))


def fetch_yfinance_news(ticker):
    """Fetch headlines from yfinance.

    Returns list of dicts: [{headline, url, published_at, source}]
    """
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
        results = []
        for item in news[:20]:
            headline = item.get("title", "")
            if not headline:
                continue
            published = None
            pub_ts = item.get("providerPublishTime")
            if pub_ts:
                try:
                    published = datetime.fromtimestamp(pub_ts).isoformat()
                except (ValueError, TypeError, OSError):
                    pass
            results.append({
                "headline": headline,
                "url": item.get("link", ""),
                "published_at": published,
                "source": "yfinance",
            })
        return results
    except Exception as e:
        logger.warning("yfinance news fetch failed for %s: %s", ticker, e)
        return []


def fetch_alphavantage_news(ticker):
    """Fetch headlines from Alpha Vantage NEWS_SENTIMENT endpoint.

    Returns list of dicts: [{headline, url, published_at, source, av_sentiment}]
    """
    if not ALPHAVANTAGE_API_KEY or not ALPHAVANTAGE_NEWS_ENABLED:
        return []

    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ticker,
                "apikey": ALPHAVANTAGE_API_KEY,
                "limit": 10,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Alpha Vantage news failed for %s: HTTP %d", ticker, resp.status_code)
            return []

        data = resp.json()
        feed = data.get("feed", [])
        results = []
        for item in feed:
            headline = item.get("title", "")
            if not headline:
                continue
            published = item.get("time_published", "")
            if published and len(published) >= 8:
                try:
                    published = datetime.strptime(published[:15], "%Y%m%dT%H%M%S").isoformat()
                except ValueError:
                    published = None

            av_sentiment = None
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper() == ticker.upper():
                    try:
                        av_sentiment = float(ts.get("ticker_sentiment_score", 0))
                    except (ValueError, TypeError):
                        pass
                    break

            results.append({
                "headline": headline,
                "url": item.get("url", ""),
                "published_at": published,
                "source": "alphavantage",
                "av_sentiment": av_sentiment,
            })
        return results
    except Exception as e:
        logger.warning("Alpha Vantage news failed for %s: %s", ticker, e)
        return []


def fetch_all_news(ticker):
    """Combine news from all sources, deduplicate by headline.

    Returns list of dicts with: headline, url, published_at, source
    """
    all_news = []
    seen_headlines = set()

    for item in fetch_yfinance_news(ticker):
        key = item["headline"].lower().strip()
        if key not in seen_headlines:
            seen_headlines.add(key)
            all_news.append(item)

    for item in fetch_alphavantage_news(ticker):
        key = item["headline"].lower().strip()
        if key not in seen_headlines:
            seen_headlines.add(key)
            all_news.append(item)

    return all_news


def score_headlines(headlines):
    """Add VADER sentiment scores to each headline dict.

    Mutates in-place, adds: vader_score, vader_sentiment
    """
    for item in headlines:
        scores = _vader.polarity_scores(item["headline"])
        compound = scores["compound"]
        item["vader_score"] = round(compound, 4)
        if compound >= 0.05:
            item["vader_sentiment"] = "positive"
        elif compound <= -0.05:
            item["vader_sentiment"] = "negative"
        else:
            item["vader_sentiment"] = "neutral"
    return headlines


def store_headlines(ticker, headlines):
    """Upsert scored headlines into news_cache.

    Args:
        ticker: stock ticker
        headlines: list of dicts with headline, url, published_at, source, vader_score, vader_sentiment
    """
    conn = get_db()
    try:
        for item in headlines:
            conn.execute(
                """INSERT INTO news_cache (ticker, source, headline, url, published_at, vader_score, vader_sentiment, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(ticker, headline) DO UPDATE SET
                       vader_score = excluded.vader_score,
                       vader_sentiment = excluded.vader_sentiment,
                       fetched_at = CURRENT_TIMESTAMP""",
                (
                    ticker.upper(),
                    item.get("source", "yfinance"),
                    item["headline"],
                    item.get("url", ""),
                    item.get("published_at"),
                    item.get("vader_score"),
                    item.get("vader_sentiment"),
                ),
            )
        conn.commit()
        logger.debug("Stored %d headlines for %s", len(headlines), ticker)
    finally:
        conn.close()


def get_cached_news(ticker, max_age_minutes=None):
    """Return cached headlines for a ticker, or None if stale.

    Args:
        ticker: stock ticker
        max_age_minutes: staleness threshold (default from env var)

    Returns:
        list of dicts or None if no fresh data
    """
    if max_age_minutes is None:
        max_age_minutes = NEWS_MAX_AGE_MINUTES

    conn = get_db()
    try:
        cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).isoformat()
        rows = conn.execute(
            """SELECT headline, url, source, published_at, vader_score, vader_sentiment,
                      pulse_score, pulse_summary, fetched_at
               FROM news_cache
               WHERE ticker = ? AND fetched_at > ?
               ORDER BY fetched_at DESC LIMIT 30""",
            (ticker.upper(), cutoff),
        ).fetchall()

        if not rows:
            return None

        return [
            {
                "headline": r["headline"],
                "url": r["url"],
                "source": r["source"],
                "published_at": r["published_at"],
                "vader_score": r["vader_score"],
                "vader_sentiment": r["vader_sentiment"],
                "pulse_score": r["pulse_score"],
                "pulse_summary": r["pulse_summary"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def update_pulse_analysis(ticker, headline, pulse_score, pulse_summary):
    """Store Pulse agent deep analysis result for a headline."""
    conn = get_db()
    try:
        conn.execute(
            """UPDATE news_cache SET pulse_score = ?, pulse_summary = ?
               WHERE ticker = ? AND headline = ?""",
            (pulse_score, pulse_summary, ticker.upper(), headline),
        )
        conn.commit()
    finally:
        conn.close()
