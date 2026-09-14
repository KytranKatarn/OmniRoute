"""Reaper for orphaned `dispatch_pending_queue` rows.

WHY THIS EXISTS
---------------
`dispatch_awaiting_queue` promises, in its own docstring:

    "None NEVER means 'the work was lost': a timed-out poll leaves the queue row
     for the worker to finish and log."

That contract is correct in intent and was FALSE in practice. Measured live
2026-09-14 on `dispatch_pending_queue`:

    module            queued  expires_at NULL  older than the 240s poll  ever claimed
    quality_scorer      534        534                   533                   0
    wtf_hub_quick       308        308                   308                   0
    wtf_hub             104        104                   102                   0

**Zero rows anywhere carried a TTL. Zero had ever been claimed.** 953 of 957 were
older than the poll timeout their caller had already given up on — the oldest by
137 minutes. So the rows were not "left for the worker to finish"; they were left
forever, and nothing reaped them because nothing set an expiry.

The cost was not just disk. Queue depth is what the starved-lane monitor pages on,
so ~950 dead rows made a healthy fleet look starved, and the one genuinely
interesting signal (`qwen25-classify`, a hub-only model with no spill valve) was
buried in noise from two producer bursts.

WHAT THIS DOES *NOT* DO
-----------------------
It does not restore the lost work, and it deliberately does not expire anything a
worker could still legitimately claim. The contract above stays intact: the TTL is
generous (default 30 min, ~7x the 240s poll) and a row that was EVER claimed is
never touched, however old. This bounds a leak; it is not a cancellation policy.

⚠️ The real repair is upstream — a caller that abandons a row should say so. Until
that lands this is a sweeper, and the `reaped` counter it returns is the size of
the upstream problem. A rising count means MORE work is being abandoned, not that
the reaper is working harder.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Generous on purpose: ~7x the 240s default poll_timeout_s. A row younger than this
# may still be claimed by model_dispatch_worker, and expiring it WOULD lose work.
DEFAULT_TTL_MINUTES = 30
TTL_SETTING_KEY = "dispatch:queue_ttl_minutes"

# Bound each sweep so a pathological backlog cannot hold a transaction open. A
# truncated sweep is LOGGED, never silent — an unreported cap reads as "all clear".
MAX_SWEEP = 2000


def get_ttl_minutes() -> int:
    """TTL in minutes, tunable via platform_settings without a deploy.

    Fail-safe: any unreadable/invalid value falls back to the default rather than
    to 0, because a 0 would expire live work on the next sweep.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (TTL_SETTING_KEY,))
            row = cur.fetchone()
        if row and row.get("value") not in (None, ""):
            val = int(float(row["value"]))
            if val > 0:
                return val
            logger.warning(
                "%s is %s (<=0) — refusing to expire live work; using default %d",
                TTL_SETTING_KEY,
                val,
                DEFAULT_TTL_MINUTES,
            )
    except Exception as exc:  # noqa: BLE001 - never let a settings read break the sweep
        logger.warning("dispatch_queue_reaper: TTL lookup failed (%s) — using default", exc)
    return DEFAULT_TTL_MINUTES


def reap_orphaned_queue_rows(dry_run: bool = True) -> Dict[str, Any]:
    """Expire queued rows no caller is waiting on and no worker ever claimed.

    A row is orphaned when ALL of these hold:
      * ``status = 'queued'``            — not running, not already terminal
      * ``claimed_at IS NULL``           — no worker ever picked it up
      * past its TTL                     — by ``expires_at`` when set, else by age

    ``dry_run=True`` (the DEFAULT) only counts. The caller must ask for the write,
    so an accidental import can never mutate the queue.

    Returns ``{ok, dry_run, ttl_minutes, reaped, truncated, by_module}``.
    Fail-safe: on any error returns ``ok=False`` having written nothing.
    """
    ttl = get_ttl_minutes()
    out: Dict[str, Any] = {
        "ok": False,
        "dry_run": dry_run,
        "ttl_minutes": ttl,
        "reaped": 0,
        "truncated": False,
        "by_module": {},
    }

    # expires_at wins when present; age is the fallback for legacy rows written
    # before the enqueue sites set a TTL (every row in the table on 2026-09-14).
    where = """
        status = 'queued'
        AND claimed_at IS NULL
        AND (
            (expires_at IS NOT NULL AND expires_at < now())
            OR (expires_at IS NULL AND queued_at < now() - (%s * interval '1 minute'))
        )
    """

    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                f"SELECT module_id, count(*) n FROM dispatch_pending_queue WHERE {where} GROUP BY 1",
                (ttl,),
            )
            out["by_module"] = {r["module_id"]: r["n"] for r in cur.fetchall()}
        total = sum(out["by_module"].values())

        if dry_run:
            out.update(ok=True, reaped=total, truncated=total > MAX_SWEEP)
            return out

        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                f"""
                UPDATE dispatch_pending_queue
                   SET status = 'expired',
                       completed_at = now(),
                       error = COALESCE(error, '')
                               || 'orphaned: caller abandoned after its poll timeout; '
                               || 'never claimed by a worker. Reaped by dispatch_queue_reaper.'
                 WHERE id IN (
                     SELECT id FROM dispatch_pending_queue
                      WHERE {where}
                      ORDER BY queued_at
                      LIMIT {MAX_SWEEP}
                 )
                """,
                (ttl,),
            )
            out["reaped"] = cur.rowcount or 0

        out["truncated"] = total > MAX_SWEEP
        if out["truncated"]:
            logger.warning(
                "dispatch_queue_reaper: swept %d of %d orphans (MAX_SWEEP=%d) — "
                "more remain, next cycle will continue",
                out["reaped"],
                total,
                MAX_SWEEP,
            )
        if out["reaped"]:
            logger.info(
                "dispatch_queue_reaper: expired %d orphaned rows (ttl=%dm) by module: %s",
                out["reaped"],
                ttl,
                out["by_module"],
            )
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001 - a reaper must never break the scheduler
        logger.error("dispatch_queue_reaper failed: %s", exc, exc_info=True)
        out["error"] = str(exc)
    return out
