"""Read/write the precomputed /cross-watch top-entities bundle (migration 075, #6166).

WHY THIS EXISTS. `_crosswatch_top()`'s ranking query — a scan of
shared.entity_mentions (~2.15M rows after the #5799 backfill) joined to
shared.entities per mention — measured 5.47s SOLO on an idle DB (EXPLAIN
ANALYZE, 2026-09-04), roughly 8x the ~670ms it ran at when the in-process
cache in routes.py was written. `_CROSSWATCH_CACHE` there is a plain
in-process dict while wtf-consumer runs `gunicorn --workers 4
--max-requests`, so: 4 workers means 4 independent caches (up to 4 requests
pay full cost per TTL window), and `--max-requests` recycling a worker wipes
its cache, so the 5.47s+ path can recur instead of warming once. Several
concurrent cold workers running the SAME heavy scan against the one hub DB
(which also serves ingest and the rest of WTF) is exactly the shape that
turns a 5.47s solo query into the >25s client timeout measured during the
#6149 regression sweeps. Same family as migration 072 (activity_snapshot).

This module is the shared layer: whichever worker computes first writes the
result; every worker (and every request within the TTL) reads the same row.

⚠️ FAIL-SOFT BY DESIGN, same as activity_snapshot.py. A snapshot is an
optimisation, never a dependency: if the table is missing, unreadable, or
holds junk, the caller falls back to computing inline (today's behaviour)
rather than serving an error. Reads return None and writes swallow.
"""

from __future__ import annotations

import json
import logging
import os
import socket

from sqlalchemy import text

log = logging.getLogger(__name__)

# How stale a snapshot may be before a reader gives up on it and computes
# inline. Matches the TTL the in-process cache used before this fix
# (cross-product membership changes slowly).
MAX_AGE_S = int(os.environ.get("WTF_CROSS_WATCH_SNAPSHOT_MAX_AGE", "300"))


def read_snapshot(conn, max_age_s: int | None = None) -> list | None:
    """Return the cached entity list if a snapshot exists and is fresh; else None.

    Freshness is evaluated IN SQL (`NOW() - computed_at`), not against the
    reader's clock: the writer and reader are different processes/containers,
    and comparing a local clock to a DB timestamp is how a snapshot silently
    reads as eternally fresh or eternally stale after a drift.
    """
    limit = MAX_AGE_S if max_age_s is None else max_age_s
    try:
        row = conn.execute(
            text(
                """
                SELECT bundle, computed_at,
                       EXTRACT(EPOCH FROM (NOW() - computed_at)) AS age_s
                FROM wtf.cross_watch_snapshot
                WHERE id = 1
                """
            )
        ).mappings().first()
    except Exception as exc:
        # Most likely the table does not exist yet (migration not applied).
        # That is a normal state on first deploy, not an error worth raising.
        log.info("cross-watch snapshot unreadable, computing inline: %s", exc)
        return None

    if not row or row["bundle"] is None:
        return None
    if float(row["age_s"] or 0) > limit:
        log.info(
            "cross-watch snapshot is %.0fs old (limit %ss) — computing inline",
            float(row["age_s"] or 0), limit,
        )
        return None

    bundle = row["bundle"]
    if isinstance(bundle, str):  # driver returned raw json
        try:
            bundle = json.loads(bundle)
        except ValueError:
            return None
    if not isinstance(bundle, list):
        log.warning("cross-watch snapshot present but malformed — computing inline")
        return None
    return bundle


def write_snapshot(conn, data: list, duration_ms: int | None = None) -> bool:
    """Upsert the single snapshot row. Returns True on success, never raises."""
    try:
        conn.execute(
            text(
                """
                INSERT INTO wtf.cross_watch_snapshot (id, bundle, computed_at,
                                                       duration_ms, computed_by)
                VALUES (1, CAST(:b AS jsonb), NOW(), :d, :who)
                ON CONFLICT (id) DO UPDATE
                   SET bundle      = EXCLUDED.bundle,
                       computed_at = EXCLUDED.computed_at,
                       duration_ms = EXCLUDED.duration_ms,
                       computed_by = EXCLUDED.computed_by
                """
            ),
            {
                "b": json.dumps(data, default=str),
                "d": duration_ms,
                "who": socket.gethostname()[:64],
            },
        )
        return True
    except Exception as exc:
        log.warning("cross-watch snapshot write failed (page unaffected): %s", exc)
        return False
