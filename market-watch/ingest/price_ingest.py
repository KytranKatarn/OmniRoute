"""Background price data ingestion for watchlist tickers."""

import time
import logging
from db import get_db
from services.market_data import get_quote

logger = logging.getLogger(__name__)


def run_price_ingest():
    """Refresh quotes for all watchlist tickers."""
    start = time.time()
    conn = get_db()
    tickers = conn.execute("SELECT ticker FROM watchlist").fetchall()
    conn.close()

    if not tickers:
        return

    count = 0
    errors = 0
    for row in tickers:
        try:
            get_quote(row["ticker"])
            count += 1
            time.sleep(0.5)  # Rate limit
        except Exception as e:
            logger.error("Ingest failed for %s: %s", row["ticker"], e)
            errors += 1

    duration_ms = int((time.time() - start) * 1000)

    conn = get_db()
    conn.execute(
        "INSERT INTO ingest_log (source, status, records_count, error_message, duration_ms) VALUES (?, ?, ?, ?, ?)",
        ("price_refresh", "success" if errors == 0 else "failure", count, f"{errors} errors" if errors else None, duration_ms),
    )
    conn.commit()
    conn.close()
    logger.info("Price ingest: %d tickers refreshed in %dms (%d errors)", count, duration_ms, errors)
