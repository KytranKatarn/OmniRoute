"""Background position monitor — checks open positions for exit triggers every minute."""

import os
import time
import logging

from db import get_db
from services.position_manager import check_price_exits

logger = logging.getLogger(__name__)

POSITION_CHECK_INTERVAL = int(os.environ.get("MW_POSITION_CHECK_INTERVAL", 60))


def run_position_check():
    """Check all open positions for stop-loss, target, and time expiry exits."""
    conn = get_db()
    try:
        open_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM open_positions WHERE status = 'open'"
        ).fetchone()
        count = open_count["cnt"] if open_count else 0
    finally:
        conn.close()

    if count == 0:
        return  # No positions to monitor

    try:
        closed = check_price_exits()
        if closed:
            logger.info(
                "Position monitor: closed %d positions — %s",
                len(closed),
                ", ".join(f"{c['ticker']} ({c['exit_reason']})" for c in closed),
            )
    except Exception as e:
        logger.error("Position monitor check failed: %s", e)
