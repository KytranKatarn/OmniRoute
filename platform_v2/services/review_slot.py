"""Cross-PR F.O.R.G.E. review slot (#7322).

``review_attempts.owned_attempt`` stops the SAME PR being reviewed twice. Nothing limited reviews
of DIFFERENT PRs, so two reviews sent code_review legs to Defiant (one inference slot) at once and
queued behind each other: legs of 600-1211s and an ``elapsed_time_limit`` NEEDS REVIEW.

A review now holds a LEASE in ``review_slots`` for its whole life (queued dispatches are awaited
synchronously, so there is no async tail). The elapsed budget starts later, inside
``_obtain_review_summary``, so time spent waiting here never counts against it.

* Stale holders expire two ways: heartbeat older than the TTL (crashed process) and a hard
  max-hold (hung but alive thread). A daemon thread heartbeats the lease because one pass can run
  600-1211s with no other heartbeat point.
* FIFO among waiters via ``pr_reviews.metadata.review_queue`` (also what the PR tab renders).
* FAIL OPEN: if the lease table/DB is unavailable the review runs without a slot. Contention
  returns but is no worse than before; a broken lock must never block every review.
* No DB connection is held while waiting: every store call opens a short-lived cursor.

DB access sits behind ``PgStore`` so the logic is unit-tested with a fake store and clock.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

POLL_SECONDS = 5.0
HEARTBEAT_SECONDS = 30.0
WAITER_FRESH_SECONDS = 30  # a queue marker not refreshed this recently belongs to a dead waiter


class ReviewQueued(RuntimeError):
    """No review slot is free (or the wait ran out). The review row stays ``pending``."""

    def __init__(self, behind_pr=None, behind_repo=None, position=1):
        self.behind_pr, self.behind_repo, self.position = behind_pr, behind_repo, position
        super().__init__(f"queued behind PR #{behind_pr}" if behind_pr else "queued behind another review")


@dataclass(frozen=True)
class Config:
    concurrency: int = 1
    ttl_seconds: int = 180
    max_hold_seconds: int = 2700
    max_wait_seconds: int = 1800


def _bounded(value, default, low, high):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return min(max(n, low), high)


def load_config() -> Config:
    """Read the four tunables from ``platform_settings``; any error -> defaults."""
    keys = {
        "forge:review_concurrency": ("concurrency", 1, 1, 8),
        "forge:review_slot_ttl_seconds": ("ttl_seconds", 180, 30, 3600),
        "forge:review_slot_max_hold_seconds": ("max_hold_seconds", 2700, 300, 14400),
        "forge:review_queue_max_wait_seconds": ("max_wait_seconds", 1800, 0, 14400),
    }
    values = {name: default for name, default, _lo, _hi in keys.values()}
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT key, value FROM platform_settings WHERE key = ANY(%s)", (list(keys),))
            for row in cur.fetchall() or []:
                key = row["key"] if isinstance(row, dict) else row[0]
                val = row["value"] if isinstance(row, dict) else row[1]
                name, default, lo, hi = keys[key]
                values[name] = _bounded(val, default, lo, hi)
    except Exception:
        logger.warning("review_slot: config load failed; using defaults", exc_info=True)
    return Config(**values)


class PgStore:
    """The only place that touches Postgres. Every method opens its own short-lived cursor."""

    def try_acquire(self, slot, repo, pr_number, holder, cfg: Config) -> bool:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                """
                INSERT INTO review_slots (slot, repo, pr_number, holder, acquired_at, heartbeat_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (slot) DO UPDATE
                   SET repo = EXCLUDED.repo, pr_number = EXCLUDED.pr_number, holder = EXCLUDED.holder,
                       acquired_at = NOW(), heartbeat_at = NOW()
                 WHERE review_slots.holder IS NULL
                    OR review_slots.heartbeat_at < NOW() - make_interval(secs => %s)
                    OR review_slots.acquired_at < NOW() - make_interval(secs => %s)
                RETURNING slot
                """,
                (slot, repo, pr_number, holder, cfg.ttl_seconds, cfg.max_hold_seconds),
            )
            return cur.fetchone() is not None

    def heartbeat(self, slot, holder) -> bool:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute("UPDATE review_slots SET heartbeat_at = NOW() WHERE slot = %s AND holder = %s", (slot, holder))
            return cur.rowcount > 0

    def release(self, slot, holder) -> None:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute("UPDATE review_slots SET holder = NULL WHERE slot = %s AND holder = %s", (slot, holder))

    def current_holder(self, cfg: Config):
        """The oldest live lease as ``(repo, pr_number)``, or None."""
        from database import get_db_cursor

        with get_db_cursor() as (_c, cur):
            cur.execute(
                """
                SELECT repo, pr_number FROM review_slots
                 WHERE holder IS NOT NULL
                   AND heartbeat_at >= NOW() - make_interval(secs => %s)
                   AND acquired_at >= NOW() - make_interval(secs => %s)
                 ORDER BY acquired_at LIMIT 1
                """,
                (cfg.ttl_seconds, cfg.max_hold_seconds),
            )
            row = cur.fetchone()
        if not row:
            return None
        return (row["repo"], row["pr_number"]) if isinstance(row, dict) else (row[0], row[1])

    def mark_waiting(self, repo, pr_number, since_iso, behind) -> None:
        """Stamp/refresh this PR's queue marker; the PR tab reads it. ``since`` is the FIFO ticket."""
        from database import get_db_cursor
        from psycopg2.extras import Json

        marker = {
            "since": since_iso,
            "behind_pr": behind[1] if behind else None,
            "behind_repo": behind[0] if behind else None,
        }
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                "UPDATE pr_reviews SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{review_queue}', "
                "%s::jsonb || jsonb_build_object('seen_at', NOW()), true) WHERE repo = %s AND pr_number = %s",
                (Json(marker), repo, pr_number),
            )

    def clear_waiting(self, repo, pr_number) -> None:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                "UPDATE pr_reviews SET metadata = metadata - 'review_queue' "
                "WHERE repo = %s AND pr_number = %s AND metadata ? 'review_queue'",
                (repo, pr_number),
            )

    def older_waiters(self, repo, pr_number, since_iso) -> int:
        """Live waiters (other PRs) whose ticket is older than ``since_iso``."""
        from database import get_db_cursor

        with get_db_cursor() as (_c, cur):
            cur.execute(
                """
                SELECT count(*) AS n FROM pr_reviews
                 WHERE metadata ? 'review_queue'
                   AND NOT (repo = %s AND pr_number = %s)
                   AND (metadata->'review_queue'->>'since')::timestamptz < %s::timestamptz
                   AND (metadata->'review_queue'->>'seen_at')::timestamptz
                         >= NOW() - make_interval(secs => %s)
                """,
                (repo, pr_number, since_iso, WAITER_FRESH_SECONDS),
            )
            row = cur.fetchone()
        return int(row["n"] if isinstance(row, dict) else row[0])

    def now_iso(self) -> str:
        from database import get_db_cursor

        with get_db_cursor() as (_c, cur):
            cur.execute("SELECT NOW() AS t")
            row = cur.fetchone()
        t = row["t"] if isinstance(row, dict) else row[0]
        return t.isoformat()


def _heartbeat_loop(store, slot, holder, stop: threading.Event, interval: float):
    while not stop.wait(interval):
        try:
            if not store.heartbeat(slot, holder):
                logger.warning("review_slot: lease on slot %s was taken over; heartbeat stopping", slot)
                return
        except Exception:
            logger.warning("review_slot: heartbeat failed (will retry)", exc_info=True)


@contextmanager
def review_slot(
    repo: str,
    pr_number: int,
    *,
    wait: bool = True,
    max_wait: Optional[float] = None,
    store=None,
    config: Optional[Config] = None,
    clock=time.monotonic,
    sleep=time.sleep,
    poll_seconds: float = POLL_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
):
    """Hold one review slot for the duration of the ``with`` block.

    ``wait=False`` raises :class:`ReviewQueued` at once when no slot is free (the scheduler sidecar
    uses this so it never blocks). ``wait=True`` polls until a slot frees or ``max_wait`` runs out.
    Yields the slot number, or ``None`` when the lease table is unavailable (fail open).
    """
    holder = uuid.uuid4().hex
    slot = None
    registered = False
    store = store or PgStore()
    try:
        cfg = config or load_config()
        deadline = clock() + (cfg.max_wait_seconds if max_wait is None else max_wait)
        ticket = None
        while True:
            if ticket is None:
                ticket = store.now_iso()
            # FIFO: a live waiter with an older ticket goes first (a non-waiting caller has no ticket
            # of its own, so it yields to every live waiter).
            older = store.older_waiters(repo, pr_number, ticket if wait else "infinity")
            if not older:
                for candidate in range(cfg.concurrency):
                    if store.try_acquire(candidate, repo, pr_number, holder, cfg):
                        slot = candidate
                        break
            if slot is not None:
                break
            behind = store.current_holder(cfg)
            if not wait or clock() >= deadline:
                raise ReviewQueued(behind[1] if behind else None, behind[0] if behind else None, older + 1)
            store.mark_waiting(repo, pr_number, ticket, behind)
            registered = True
            sleep(poll_seconds)
    except ReviewQueued:
        raise
    except Exception:
        logger.warning("review_slot: unavailable, running the review WITHOUT a slot (fail open)", exc_info=True)
        slot = None
    finally:
        if registered:
            try:
                store.clear_waiting(repo, pr_number)
            except Exception:
                logger.warning("review_slot: could not clear queue marker", exc_info=True)

    stop = threading.Event()
    beat = None
    if slot is not None:
        beat = threading.Thread(
            target=_heartbeat_loop,
            args=(store, slot, holder, stop, heartbeat_seconds),
            name=f"review-slot-heartbeat-{pr_number}",
            daemon=True,
        )
        beat.start()
    try:
        yield slot
    finally:
        stop.set()
        if slot is not None:
            try:
                store.release(slot, holder)
            except Exception:
                logger.warning("review_slot: release failed; lease will expire by TTL", exc_info=True)
