"""Alert evaluation engine."""

import logging
from db import get_db
from services.market_data import get_quote

logger = logging.getLogger(__name__)


def check_alerts():
    """Evaluate all untriggered alerts against current prices."""
    conn = get_db()
    alerts = conn.execute("SELECT * FROM alerts WHERE triggered = 0").fetchall()

    triggered = []
    for alert in alerts:
        quote = get_quote(alert["ticker"])
        price = quote.get("price", 0)
        if not price:
            continue

        fire = False
        if alert["alert_type"] == "price_above" and price >= alert["threshold"]:
            fire = True
        elif alert["alert_type"] == "price_below" and price <= alert["threshold"]:
            fire = True
        elif alert["alert_type"] == "volume":
            volume = quote.get("volume", 0)
            if volume >= alert["threshold"]:
                fire = True

        if fire:
            conn.execute(
                "UPDATE alerts SET triggered = 1, triggered_at = CURRENT_TIMESTAMP WHERE id = ?",
                (alert["id"],),
            )
            triggered.append(dict(alert))

    conn.commit()
    conn.close()
    return triggered
