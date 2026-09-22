"""One merge at a time, visible on the UI (owner directive, 2026-09-22).

There was no merge lock of any kind. `pending_push_service.is_freeze_active()` is a stub
that always returns False, so nothing serialised merges and nothing told the owner one was
running. A merge runs merge_pr -> GitHub -> branch delete -> sync_closed_prs -> approval
reconciliation; two of those interleaving is how the "already merged / CANCELLED" confusion
appeared, where an approval row was retired 2s after a merge and read as a failure.

THREE PROPERTIES, each chosen against a specific failure:

⚠️ DB-BACKED, NOT IN-PROCESS. archie_platform runs `--workers 4` and archie_scheduler is a
separate process, so a module-level flag would guard one worker and wave the rest through
(KB #282671). platform_settings is the cross-process store already used for runtime config.

⚠️ TTL-EXPIRING. A lock that can WEDGE is worse than no lock: it would block every merge on
the platform indefinitely. The backup lock (`/backups/.backup_lock`) releases only on PROOF
the owner is dead because a backup is long; a merge is short, so here an old lock means a
crash, not a long job, and expiry is the safe direction.

⚠️ FAIL-OPEN. If the store cannot be read we ALLOW the merge. The real gates are the verdict,
governance and dependency checks in merge_pr; this lock is an improvement over nothing, not
a safety-critical gate. Failing closed would let a DB blip block every merge — strictly worse
than the status quo it replaces.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

LOCK_KEY = "repair_bay:merge_lock"
# A squash merge plus branch delete is seconds. Five minutes is generous enough that a
# healthy merge never trips it, and short enough that a crash does not strand the queue.
LOCK_TTL_SECONDS = 300


def _now() -> float:
    """Indirected so a test can advance the clock without sleeping."""
    return time.time()


def _read() -> Optional[str]:
    from database import get_db_cursor

    with get_db_cursor() as (_conn, cur):
        cur.execute("SELECT value FROM platform_settings WHERE key = %s", (LOCK_KEY,))
        row = cur.fetchone()
    if not row:
        return None
    return row["value"] if isinstance(row, dict) else row[0]


def _write(payload: Optional[str]) -> None:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_conn, cur):
        if payload is None:
            cur.execute("DELETE FROM platform_settings WHERE key = %s", (LOCK_KEY,))
            return
        cur.execute(
            """
            INSERT INTO platform_settings (key, value)
                 VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (LOCK_KEY, payload),
        )


def _current_unsafe() -> Optional[dict]:
    """The live holder, or None. Raises if the store cannot be read — callers decide."""
    raw = _read()
    if not raw:
        return None
    try:
        held = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(held, dict):
        return None
    started = float(held.get("started_at") or 0)
    if _now() - started >= LOCK_TTL_SECONDS:
        # Expired: a merge does not take this long, so the holder crashed.
        logger.info("merge_lock: discarding stale lock for #%s", held.get("pr"))
        return None
    return held


def current() -> Optional[dict]:
    """The merge in flight, or None. Never raises — an unreadable store reads as free."""
    try:
        return _current_unsafe()
    except Exception as exc:  # noqa: BLE001
        logger.debug("merge_lock.current failed (treating as free): %s", exc)
        return None


def acquire(pr: int, repo: str = None, by: str = "") -> Tuple[bool, Optional[str]]:
    """Take the merge lock. ``(True, None)`` on success, ``(False, reason)`` when held.

    Re-entrant for the SAME pr: a retry of one merge must not deadlock against its own lock.
    """
    try:
        held = _current_unsafe()
        if held and int(held.get("pr") or 0) != int(pr):
            age = int(_now() - float(held.get("started_at") or 0))
            return False, (
                f"a merge of #{held.get('pr')} is already in progress " f"(started {age}s ago) — please stand by"
            )
        _write(json.dumps({"pr": int(pr), "repo": repo, "started_at": _now(), "by": by or "unknown"}))
        return True, None
    except Exception as exc:  # noqa: BLE001 - see FAIL-OPEN in the module docstring
        logger.warning("merge_lock.acquire failed (allowing merge): %s", exc)
        return True, None


def release(pr: Optional[int], force: bool = False) -> None:
    """Release the lock. A stray release must never free ANOTHER pr's lock."""
    try:
        if force:
            _write(None)
            return
        held = _current_unsafe()
        if not held:
            return
        if int(held.get("pr") or 0) == int(pr or 0):
            _write(None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("merge_lock.release failed: %s", exc)
