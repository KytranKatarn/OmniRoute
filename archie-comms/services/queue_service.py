"""Outbound Message Queue — polls DB for messages from archie_platform.

Platform writes to outbound_messages table. This service polls every 5s,
processes pending messages through the voice service, and sends via Telegram.
"""

import json
import logging
import time
import threading

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5


class QueueProcessor:
    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="queue-processor")
        self._thread.start()
        logger.info("Queue processor started (polling every %ds)", POLL_INTERVAL)

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            time.sleep(POLL_INTERVAL)
            try:
                self._process_pending()
            except Exception as e:
                logger.warning("Queue processor error: %s", e)

    def _process_pending(self):
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                SELECT id, category, title, message, source_agent, source_department,
                       source_module, channel, priority
                FROM outbound_messages
                WHERE status = 'pending'
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2 WHEN 'low' THEN 3
                    END,
                    created_at ASC
                LIMIT 10
            """)
            rows = cur.fetchall()

            for row in rows:
                try:
                    from services.telegram_service import send
                    result = send(
                        category=row["category"],
                        title=row["title"],
                        message=row["message"],
                        source_agent=row.get("source_agent"),
                        source_department=row.get("source_department"),
                        source_module=row.get("source_module"),
                    )
                    cur.execute(
                        "UPDATE outbound_messages SET status = 'sent', processed_at = NOW(), result = %s WHERE id = %s",
                        (json.dumps(result), row["id"]),
                    )
                except Exception as e:
                    cur.execute(
                        "UPDATE outbound_messages SET status = 'failed', processed_at = NOW(), result = %s WHERE id = %s",
                        (json.dumps({"error": str(e)}), row["id"]),
                    )
                    logger.warning("Queue: failed to process message %d: %s", row["id"], e)
