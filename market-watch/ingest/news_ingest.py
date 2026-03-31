"""Background news ingest — fetches and scores headlines for all watchlist tickers."""

import os
import time
import logging

from db import get_db
from services.news_service import fetch_all_news, score_headlines, store_headlines

logger = logging.getLogger(__name__)

NEWS_INGEST_INTERVAL = int(os.environ.get("NEWS_INGEST_INTERVAL", 900))


def run_news_ingest():
    """Fetch and score news for all watchlist tickers."""
    start = time.time()
    conn = get_db()
    try:
        tickers = conn.execute("SELECT ticker FROM watchlist").fetchall()
    finally:
        conn.close()

    if not tickers:
        logger.debug("News ingest: no tickers in watchlist")
        return

    count, errors = 0, 0
    for row in tickers:
        ticker = row["ticker"]
        try:
            headlines = fetch_all_news(ticker)
            if headlines:
                scored = score_headlines(headlines)
                store_headlines(ticker, scored)
                count += len(scored)
            time.sleep(1)  # Rate limit between tickers
        except Exception as e:
            logger.error("News ingest failed for %s: %s", ticker, e)
            errors += 1

    duration_ms = int((time.time() - start) * 1000)

    # Log to ingest_log
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO ingest_log (source, status, records_count, error_message, duration_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "news",
                "success" if errors == 0 else "failure",
                count,
                f"{errors} errors" if errors > 0 else None,
                duration_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("News ingest: %d headlines for %d tickers in %dms (%d errors)",
                count, len(tickers), duration_ms, errors)
