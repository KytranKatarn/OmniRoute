"""News API routes — public headlines + authenticated per-ticker news."""

from flask import Blueprint, jsonify, request

from db import get_db
from auth import tier_required

news_bp = Blueprint("news", __name__)


@news_bp.route("/api/news/<ticker>")
@tier_required("viewer")
def get_ticker_news(ticker):
    """Return recent headlines + sentiment for a specific ticker."""
    ticker = ticker.upper()
    conn = get_db()
    try:
        limit = request.args.get("limit", 30, type=int)
        rows = conn.execute(
            """SELECT headline, url, source, published_at, vader_score, vader_sentiment,
                      pulse_score, pulse_summary, fetched_at
               FROM news_cache
               WHERE ticker = ?
               ORDER BY fetched_at DESC LIMIT ?""",
            (ticker, limit),
        ).fetchall()

        # Aggregate sentiment
        scores = [r["vader_score"] for r in rows if r["vader_score"] is not None]
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

        return jsonify({
            "success": True,
            "ticker": ticker,
            "avg_sentiment": avg_score,
            "total_headlines": len(rows),
            "headlines": [
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
            ],
        })
    finally:
        conn.close()


@news_bp.route("/api/public/news")
def get_public_news():
    """Return latest headlines across all watchlist tickers (public)."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT ticker, headline, url, source, published_at, vader_score, vader_sentiment, fetched_at
               FROM news_cache
               ORDER BY fetched_at DESC LIMIT 20"""
        ).fetchall()

        return jsonify({
            "success": True,
            "total": len(rows),
            "headlines": [
                {
                    "ticker": r["ticker"],
                    "headline": r["headline"],
                    "url": r["url"],
                    "source": r["source"],
                    "published_at": r["published_at"],
                    "vader_score": r["vader_score"],
                    "vader_sentiment": r["vader_sentiment"],
                }
                for r in rows
            ],
        })
    finally:
        conn.close()
