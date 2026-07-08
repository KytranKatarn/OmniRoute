"""
Media Hub Health Check Job
==========================
Runs probe() on every enabled row in media_hub_services, persists
health_status / health_message / last_health_check.

Designed to be callable from:
- ai_bridge/agent_loop.py (scheduled cron in-platform)
- APScheduler inside a standalone Media Hub container (post-extraction)

Keeping this file under tools/media_hub/ so it lifts cleanly during
Project #273 extraction — no platform-specific glue leaks in.
"""

import logging
from database import get_db_cursor
from .encryption import decrypt_api_key
from .services import get_service_client

logger = logging.getLogger(__name__)


def run_health_checks() -> dict:
    """Probe every enabled media_hub_services row and persist the result.

    Returns a summary dict: {checked, healthy, unhealthy, errors}.
    Safe to call from an APScheduler job; catches per-row exceptions so
    one bad service cannot break the sweep.
    """
    summary = {"checked": 0, "healthy": 0, "unhealthy": 0, "errors": 0}

    with get_db_cursor(cursor_factory=None) as (_conn, cur):
        cur.execute(
            """
            SELECT id, service_type, host, port, use_ssl, api_key_encrypted
            FROM media_hub_services
            WHERE is_enabled = true
            ORDER BY service_type
            """
        )
        rows = cur.fetchall()

    for row in rows:
        service_id, service_type, host, port, use_ssl, enc = row
        summary["checked"] += 1

        try:
            api_key = decrypt_api_key(enc) if enc else None
            client = get_service_client(service_type, host, port, api_key or "", use_ssl)

            if hasattr(client, "probe"):
                is_healthy, message = client.probe()
            else:
                is_healthy = client.test_connection()
                message = "Connection successful" if is_healthy else "Connection failed"
        except Exception as e:
            logger.warning("media_hub health probe failed for %s (id=%s): %s", service_type, service_id, e)
            is_healthy, message = False, f"Probe raised exception: {e.__class__.__name__}: {e}"
            summary["errors"] += 1

        try:
            with get_db_cursor(cursor_factory=None, commit=True) as (_conn, cur):
                cur.execute(
                    """
                    UPDATE media_hub_services SET
                        health_status = %s,
                        health_message = %s,
                        last_health_check = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    ("healthy" if is_healthy else "unhealthy", message, service_id),
                )
        except Exception as e:
            logger.error("media_hub health persist failed for id=%s: %s", service_id, e)
            summary["errors"] += 1
            continue

        if is_healthy:
            summary["healthy"] += 1
        else:
            summary["unhealthy"] += 1

    logger.info(
        "media_hub_health_check: checked=%d healthy=%d unhealthy=%d errors=%d",
        summary["checked"],
        summary["healthy"],
        summary["unhealthy"],
        summary["errors"],
    )
    return summary
