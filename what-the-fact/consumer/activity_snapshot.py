"""Read/write the precomputed /activity stats bundle (migration 072).

WHY THIS EXISTS. /activity measured 10,737ms cold vs ~850ms warm, byte-identical
output. `_ACTIVITY_CACHE` in routes.py is a plain in-process dict while
wtf-consumer runs `gunicorn --workers 4 --max-requests 800`, so there are FOUR
independent caches and a recycled worker starts EMPTY — the 10s path recurs
forever rather than warming once (same family as KB #282671). The cost is ~40
whole-table COUNTs plus a 1,634ms union COUNT, which does not belong on a
visitor's request path.

This module is the shared layer: one process computes, every worker reads.

⚠️ EVERY FUNCTION HERE IS FAIL-SOFT BY DESIGN. A snapshot is an optimisation,
never a dependency: if the table is missing, unreadable, or holds junk, the
caller must fall back to computing inline (today's behaviour) rather than serve
an error. A transparency page failing closed on its own cache would be a worse
outcome than a slow one. That is why reads return None and writes swallow —
this is the one place where quiet failure is correct, and it is bounded to a
cache.
"""

from __future__ import annotations

import json
import logging
import os
import socket

from sqlalchemy import text

log = logging.getLogger(__name__)

# How stale a snapshot may be before a reader gives up on it and computes
# inline. Default 90 min = 3x the 30-minute ingest cycle, so ONE missed refresh
# does not push a visitor onto the 10s path; three consecutive misses mean the
# refresher is genuinely broken and the page should stop trusting it.
MAX_AGE_S = int(os.environ.get("WTF_ACTIVITY_SNAPSHOT_MAX_AGE", "5400"))


def read_snapshot(
    conn,
    max_age_s: int | None = None,
    require_keys: "tuple[str, ...] | None" = None,
) -> tuple[dict, object] | None:
    """Return (bundle, computed_at) if a snapshot exists, is fresh, and carries
    every key in `require_keys`; else None.

    Freshness is evaluated IN SQL (`NOW() - computed_at`), not against the
    reader's clock: the consumer and the refresher are different containers, and
    comparing a local clock to a DB timestamp is how a snapshot silently reads
    as eternally fresh or eternally stale after a drift.

    ⚠️ `require_keys` EXISTS BECAUSE AGE IS NOT THE ONLY WAY A SNAPSHOT GOES
    STALE. A snapshot written by an OLDER BUILD is byte-fresh and structurally
    valid while missing whatever that build did not yet produce — there is no
    version stamp to tell the two apart. That is not hypothetical: PR #3083
    added `agent_throughput` to the bundle, the stored snapshot still held the
    previous 12 keys, and every reader was served the old shape. The panel
    rendered its empty state on the live site for as long as the snapshot stayed
    fresh, while the deployed code, the query and the template were all correct
    and every route returned 200. KB mistake #302073.

    A snapshot missing an expected key is treated as STALE, not as malformed:
    the caller recomputes, the recompute writes the new shape, and the system
    heals itself on the first request instead of waiting for someone to notice.
    """
    limit = MAX_AGE_S if max_age_s is None else max_age_s
    try:
        row = conn.execute(
            text(
                """
                SELECT bundle, computed_at,
                       EXTRACT(EPOCH FROM (NOW() - computed_at)) AS age_s
                FROM wtf.activity_snapshot
                WHERE id = 1
                """
            )
        ).mappings().first()
    except Exception as exc:
        # Most likely the table does not exist yet (migration not applied).
        # That is a normal state on first deploy, not an error worth raising.
        log.info("activity snapshot unreadable, computing inline: %s", exc)
        return None

    if not row or row["bundle"] is None:
        return None
    if float(row["age_s"] or 0) > limit:
        log.info(
            "activity snapshot is %.0fs old (limit %ss) — computing inline",
            float(row["age_s"] or 0), limit,
        )
        return None

    bundle = row["bundle"]
    if isinstance(bundle, str):           # driver returned raw json
        try:
            bundle = json.loads(bundle)
        except ValueError:
            return None
    if not isinstance(bundle, dict) or "stats" not in bundle:
        # Junk beats nothing only if it renders; a bundle missing `stats` would
        # blow up in the template, so refuse it and let the caller compute.
        log.warning("activity snapshot present but malformed — computing inline")
        return None

    # Written by an older build: fresh, well-formed, and short of keys this code
    # now renders. Named individually because "the snapshot looked fine" was the
    # whole difficulty last time — the log line has to say WHICH key is absent.
    if require_keys:
        missing = [k for k in require_keys if k not in bundle]
        if missing:
            log.info(
                "activity snapshot predates this build (missing %s) — computing inline",
                ", ".join(sorted(missing)),
            )
            return None
    return bundle, row["computed_at"]


def write_snapshot(conn, bundle: dict, duration_ms: int | None = None) -> bool:
    """Upsert the single snapshot row. Returns True on success, never raises."""
    try:
        conn.execute(
            text(
                """
                INSERT INTO wtf.activity_snapshot (id, bundle, computed_at,
                                                   duration_ms, computed_by)
                VALUES (1, CAST(:b AS jsonb), NOW(), :d, :who)
                ON CONFLICT (id) DO UPDATE
                   SET bundle      = EXCLUDED.bundle,
                       computed_at = EXCLUDED.computed_at,
                       duration_ms = EXCLUDED.duration_ms,
                       computed_by = EXCLUDED.computed_by
                """
            ),
            # default=str keeps a stray datetime from aborting the write. The
            # bundle was verified all-JSON-native (int/float/list/dict, and
            # `stats` a plain dict of 40 ints), so this is a belt, not the braces.
            {
                "b": json.dumps(bundle, default=str),
                "d": duration_ms,
                "who": socket.gethostname()[:64],
            },
        )
        return True
    except Exception as exc:
        log.warning("activity snapshot write failed (page unaffected): %s", exc)
        return False
