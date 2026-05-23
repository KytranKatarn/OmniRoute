"""Cross-Watch alert generator — APScheduler job, runs every 15 minutes.

Matches recent cross_watch_signals to user_follows and inserts
cross_watch_alerts rows (one per user per signal, deduped via UNIQUE constraint).
"""

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

_SIGNAL_TYPE_LABELS = {
    "new_tender": "new tender",
    "lobbying_activity": "lobbying activity",
    "bill_passed": "bill passed",
    "news_coverage": "news coverage",
    "market_movement": "market movement",
    "legal_ruling": "legal ruling",
}

_SOURCE_LABELS = {
    "gov_watch": "Gov Watch",
    "civic_watch": "Civic Watch",
    "legal_watch": "Legal Watch",
    "market_watch": "Market Watch",
    "wtf": "What The Fact",
}


def generate_cross_watch_alerts() -> None:
    """Match signals from the last 20 minutes to user follows and create alerts."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            # Fetch recent signals (20-min window with 5-min overlap buffer)
            cur.execute(
                """
                SELECT s.id AS signal_id, s.entity_id, s.signal_type,
                       s.source_product, s.headline, s.url
                FROM shared.cross_watch_signals s
                WHERE s.created_at >= NOW() - INTERVAL '20 minutes'
                ORDER BY s.created_at DESC
                """
            )
            signals = cur.fetchall()

            if not signals:
                return

            generated = 0
            for sig in signals:
                # Find all users following this entity
                cur.execute(
                    "SELECT user_id FROM shared.user_follows WHERE entity_id = %s",
                    (sig["entity_id"],),
                )
                followers = cur.fetchall()

                if not followers:
                    continue

                # Build human-readable message
                type_label = _SIGNAL_TYPE_LABELS.get(sig["signal_type"], sig["signal_type"])
                source_label = _SOURCE_LABELS.get(sig["source_product"], sig["source_product"])
                headline_short = (sig["headline"] or "")[:120]
                message = f"{source_label} — {type_label}: {headline_short}"

                for follower in followers:
                    cur.execute(
                        """
                        INSERT INTO shared.cross_watch_alerts
                            (user_id, entity_id, signal_id, message, url)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (user_id, signal_id) DO NOTHING
                        """,
                        (
                            follower["user_id"],
                            sig["entity_id"],
                            sig["signal_id"],
                            message,
                            sig["url"],
                        ),
                    )
                    if cur.rowcount:
                        generated += 1

        if generated:
            logger.info(
                "[cross_watch] alert_generator: created %d alerts from %d signals",
                generated,
                len(signals),
            )

    except Exception as e:
        logger.error("[cross_watch] alert_generator failed: %s", e)
