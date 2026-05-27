"""Email SSE manager — DB-polling cross-process event bus (T3279).

Architecture note: archie_platform runs gunicorn --workers 4, so in-process
Queue objects cannot bridge IDLE workers (archie_scheduler) to SSE clients
(archie_platform).  Instead, idle_worker.py INSERTs into email_push_events
and generate_stream() polls that table every 3 s.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 3  # seconds between DB polls
_HEARTBEAT_INTERVAL = 30  # seconds between SSE heartbeat comments
_CLEANUP_EVERY = 120  # seconds between old-event cleanup runs


class EmailSSEManager:
    """Stateless façade — all event state lives in the email_push_events DB table."""

    def generate_stream(self, mailbox_ids: list[int] | None):
        """Yield SSE-formatted strings until the client disconnects.

        Args:
            mailbox_ids: None = admin (unrestricted). list[int] = COLLABORATOR
                         (dept-scoped; only events for those mailboxes emitted).

        Yields:
            'data: {"type":"newMail","mailbox_id":<N>,"count":<M>}\\n\\n'
            ': heartbeat\\n\\n'  (every 30 s, keeps proxies alive)
        """
        from database import get_db_cursor  # noqa: PLC0415 — avoid circular at module load

        # Anchor at current max id so we don't replay events from before connect.
        last_id: int = 0
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM email_push_events")
                row = cur.fetchone()
                last_id = int(row[0]) if row else 0
        except Exception as exc:
            logger.debug("[SSE] Could not read initial max event id: %s", exc)

        elapsed_heartbeat = 0
        elapsed_cleanup = 0

        while True:
            time.sleep(_POLL_INTERVAL)
            elapsed_heartbeat += _POLL_INTERVAL
            elapsed_cleanup += _POLL_INTERVAL

            # --- poll for new events ---
            try:
                with get_db_cursor() as (conn, cur):
                    if mailbox_ids is None:
                        cur.execute(
                            "SELECT id, mailbox_id, count FROM email_push_events " "WHERE id > %s ORDER BY id",
                            (last_id,),
                        )
                    else:
                        cur.execute(
                            "SELECT id, mailbox_id, count FROM email_push_events "
                            "WHERE id > %s AND mailbox_id = ANY(%s) ORDER BY id",
                            (last_id, mailbox_ids),
                        )
                    rows = cur.fetchall()
                for row in rows:
                    eid, mid, cnt = row["id"], row["mailbox_id"], row["count"]
                    if eid > last_id:
                        last_id = eid
                    yield f'data: {{"type":"newMail","mailbox_id":{mid},"count":{cnt}}}\n\n'
            except Exception as exc:
                logger.debug("[SSE] DB poll error: %s", exc)

            # --- heartbeat ---
            if elapsed_heartbeat >= _HEARTBEAT_INTERVAL:
                yield ": heartbeat\n\n"
                elapsed_heartbeat = 0

            # --- periodic cleanup: delete events older than 10 min ---
            if elapsed_cleanup >= _CLEANUP_EVERY:
                elapsed_cleanup = 0
                try:
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute("DELETE FROM email_push_events " "WHERE created_at < NOW() - INTERVAL '10 minutes'")
                except Exception as exc:
                    logger.debug("[SSE] Cleanup error: %s", exc)


_manager: EmailSSEManager | None = None


def get_sse_manager() -> EmailSSEManager:
    global _manager
    if _manager is None:
        _manager = EmailSSEManager()
    return _manager
