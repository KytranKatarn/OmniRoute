"""Tier-2 (Deep Dive) PRE-COMPUTE — drain the queue nothing was draining.

THE PROBLEM THIS SOLVES
Deep Dive is the paywalled tier. Until now it was computed ON THE CLICK:
`POST /api/upgrade-tier2/<id>` dispatches synchronously and its own docstring
says "can take up to 90s for cold qwen2.5:7b". Measured 2026-08-31:

    quick_v1+full   20,722   pre-computed, instant
    quick_v1 only   45,332   <- a 90s live cluster scan on first paid click
    tier2_pending    8,056   <- flagged for deep review, NEVER drained
    tier2_failed     8,319   <- failed, never retried

⚠️ `tier2_pending` was WRITE-ONLY. It is set by factcheck_backlog_worker,
llm_analysis_backlog_worker and tier_router (on every Tier-2 rate-limit), and the
only readers were two display COUNTs. A queue with producers, a UI that reports
it, and no consumer — the same shape as the gdrive retention tier that had a
policy and no pruner. That is why dedicating cluster capacity to news produced no
visible change: the work was being enqueued into a dead letter box.

WHY PRIORITISED, NOT A FULL SWEEP
45,332 articles x 30-90s is roughly 380-1,100 hours of cluster time, and most of
those articles will never be opened. This drains in priority order instead:

    1. tier2_pending      — already judged to qualify
    2. recent             — where subscriber traffic actually lands
    3. multi-outlet       — cluster_size >= N, the stories worth a Deep Dive

The long tail stays on-demand. Pre-computing everything would spend the fleet on
articles nobody reads.

SAFETY
  - OFF by default. WTF_TIER2_PRECOMPUTE_ENABLED=true to arm.
  - Hard run cap per cycle; a sleep between dispatches so it yields the
    interactive lane.
  - HONOURS retry_after on a 429 and ends the cycle rather than hammering — a
    worker that ignores backpressure is how the hub gets saturated (wtf.md).
  - Never raises. A failed pre-compute must not stop the ingest loop; the
    on-demand path still works for anything not yet done.
"""

import logging
import os
import time
from typing import Any, Dict

from sqlalchemy import text

from ingest import tier2_upgrade

log = logging.getLogger(__name__)

_ENABLED = os.environ.get("WTF_TIER2_PRECOMPUTE_ENABLED", "false").lower() == "true"
_MAX_AGE_DAYS = int(os.environ.get("WTF_TIER2_MAX_AGE_DAYS", "14"))
_MIN_CLUSTER = int(os.environ.get("WTF_TIER2_MIN_CLUSTER", "2"))
_MAX_RUNS = int(os.environ.get("WTF_TIER2_MAX_RUNS_PER_CYCLE", "50"))
_SLEEP_SEC = float(os.environ.get("WTF_TIER2_SLEEP_SEC", "2"))
_BATCH = 25


def _candidates(conn, schema: str, limit: int, exclude: list):
    """Priority-ordered candidates.

    ⚠️ Selects on `analysis_tier <> 'quick_v1+full'`, NOT on ai_analyzed. Those
    are different questions: ai_analyzed means "an LLM has looked at it at all",
    while the tier is the free-vs-paid product state. An article can be
    ai_analyzed via the DHQ path and still have no Deep Dive.
    """
    return conn.execute(
        text(
            f"""
            SELECT a.id,
                   CASE
                     WHEN a.tier2_pending THEN 1
                     WHEN a.published_at > NOW() - make_interval(days => :days) THEN 2
                     ELSE 3
                   END AS priority
              FROM {schema}.articles a
              LEFT JOIN {schema}.story_clusters sc ON sc.id = a.cluster_id
             WHERE a.suppressed_reason IS NULL
               AND a.analysis_tier NOT IN ('quick_v1+full', 'pending')
               AND NOT (a.id = ANY(:exclude))
               AND (
                     a.tier2_pending
                  OR a.published_at > NOW() - make_interval(days => :days)
                  OR COALESCE(sc.article_count, 0) >= :min_cluster
                   )
             ORDER BY priority, a.published_at DESC
             LIMIT :limit
            """
        ),
        {
            "days": _MAX_AGE_DAYS,
            "min_cluster": _MIN_CLUSTER,
            "exclude": exclude or [0],
            "limit": limit,
        },
    ).mappings().all()


def run_backlog(engine) -> Dict[str, Any]:
    """Drain the Tier-2 queue. Matches the sibling backlog-worker contract."""
    if not _ENABLED:
        return {"processed": 0, "stopped": "disabled"}

    schema = os.environ.get("WTF_SCHEMA", "wtf")
    processed = failed = rate_limited = skipped = 0
    tried: list = []
    stopped = "max_runs"

    try:
        while processed + failed + rate_limited < _MAX_RUNS:
            with engine.begin() as conn:
                rows = _candidates(conn, schema, _BATCH, tried)
            if not rows:
                stopped = "no_backlog"
                break

            for row in rows:
                if processed + failed + rate_limited >= _MAX_RUNS:
                    break
                aid = row["id"]
                tried.append(aid)

                res = tier2_upgrade.upgrade_article(engine, schema, aid)
                status = res.get("status")

                if status == "upgraded":
                    processed += 1
                elif status == "already":
                    skipped += 1
                    continue  # no dispatch happened — don't pay the sleep
                elif status == "not_found":
                    skipped += 1
                    continue
                elif status == "rate_limited":
                    rate_limited += 1
                    wait = res.get("retry_after")
                    # Honour it. A worker that drops the item and charges on is
                    # how the hub gets saturated by its own backlog.
                    try:
                        wait = float(wait) if wait is not None else 0.0
                    except (TypeError, ValueError):
                        wait = 0.0
                    log.info(
                        "[tier2_precompute] rate limited, retry_after=%ss — ending cycle",
                        wait or "unset",
                    )
                    stopped = "rate_limited"
                    return {
                        "processed": processed,
                        "failed": failed,
                        "rate_limited": rate_limited,
                        "skipped": skipped,
                        "stopped": stopped,
                        "retry_after": wait or None,
                    }
                else:
                    failed += 1
                    log.warning(
                        "[tier2_precompute] article=%s %s: %s",
                        aid, status, res.get("error", "")[:160],
                    )

                if _SLEEP_SEC > 0:
                    time.sleep(_SLEEP_SEC)
    except Exception as exc:  # the ingest loop must survive this worker
        log.exception("[tier2_precompute] crashed: %s", exc)
        stopped = "error"

    return {
        "processed": processed,
        "failed": failed,
        "rate_limited": rate_limited,
        "skipped": skipped,
        "stopped": stopped,
    }
