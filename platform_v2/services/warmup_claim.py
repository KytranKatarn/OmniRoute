"""Run the startup model warm-up once per cluster start, not once per process (#7328).

``app._warmup_ollama_models`` runs at import in every gunicorn worker of ``archie_platform``
(--workers 4) and in ``archie_scheduler``. Every warm-up log line therefore appeared 4-5 times and
each copy made the same load/refusal calls against one Ollama.

A short DB-backed claim lets exactly one process warm up. It must be DB-backed: an in-memory guard
only holds inside one worker (KB #282671; same reason ``warmboot:wtf_backlog`` keeps its TTL in
``platform_settings``).

* TTL, not a permanent lock: a claimer that dies mid-warm-up must not suppress warm-up forever. The
  default (120s) comfortably covers the ~10s in which the four workers + scheduler import, but a
  restart a few minutes later warms up again.
* FAIL OPEN: any DB error means "go ahead and warm up" - exactly the old behaviour.
"""

from __future__ import annotations

import logging
import os
import socket
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CLAIM_KEY = "warmup:claim"
TTL_KEY = "warmup:claim_ttl_seconds"
DEFAULT_TTL_SECONDS = 120
_TTL_MIN, _TTL_MAX = 30, 1800


def _bounded_ttl(value) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_TTL_SECONDS
    return min(max(n, _TTL_MIN), _TTL_MAX)


def _claim_in_db(holder: str) -> bool:
    """Atomically take the claim if it is absent or older than the TTL. True = we own it."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("SELECT value FROM platform_settings WHERE key = %s", (TTL_KEY,))
        row = cur.fetchone()
        ttl = _bounded_ttl((row["value"] if isinstance(row, dict) else row[0]) if row else None)
        cur.execute(
            """
            INSERT INTO platform_settings (key, value, value_type, description, updated_at)
            VALUES (%s, %s, 'string', 'Startup warm-up claim: one process warms up per cluster start (#7328)', NOW())
            ON CONFLICT (key) DO UPDATE
               SET value = EXCLUDED.value, updated_at = NOW()
             WHERE platform_settings.updated_at < NOW() - make_interval(secs => %s)
            RETURNING key
            """,
            (CLAIM_KEY, holder, ttl),
        )
        return cur.fetchone() is not None


def claim_warmup(*, claim: Optional[Callable[[str], bool]] = None, holder: Optional[str] = None) -> bool:
    """True if THIS process should run the warm-up. Never raises."""
    holder = holder or f"{socket.gethostname()}:{os.getpid()}"
    try:
        won = (claim or _claim_in_db)(holder)
    except Exception:
        logger.warning("warmup claim unavailable; warming up anyway (fail open)", exc_info=True)
        return True
    if not won:
        logger.info("Ollama warmup: already claimed by another process in the last TTL; skipping (#7328)")
    return won
