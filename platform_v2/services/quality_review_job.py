"""Quality Review Job — periodic LLM scoring of knowledge base entries.

Agent Loop Job: runs every 2 hours, scoring entries one at a time through the
DHQ dispatch fleet (services.quality_scoring_service.score_entry → cluster
queue-and-wait). A single failure increments a per-entry attempt counter and
moves on; an entry is only marked 'error' after MAX_SCORE_ATTEMPTS genuine
failures spread across runs (task #4553), so a transient busy-cluster blip
never permanently kills an entry.

Import:
    from services.quality_review_job import run_quality_review
"""

import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)

# How many entries to score per job run
ENTRIES_PER_RUN = 50
# Max seconds per job run (don't hog the fleet forever)
MAX_RUN_SECONDS = 600
# Mark an entry 'error' only after this many genuine scoring failures (one
# attempt per entry per run), so a transient cluster blip doesn't permanently
# kill it (task #4553).
MAX_SCORE_ATTEMPTS = 3

# Stop enqueueing when this many quality_scorer rows are already sitting in the
# queue UNCLAIMED. Tunable live via platform_settings 'quality:review:max_queued'.
MAX_QUEUED_BACKLOG = 25
BACKLOG_SETTING_KEY = "quality:review:max_queued"


def queued_backlog() -> int:
    """How many quality_scorer rows are queued and were never claimed.

    ⚠️ NOT `welfare_governance_service.in_flight_over_cap`, which is the existing
    backpressure helper for the WTF backlogs. That one counts **bridge_jobs**,
    and this producer does not go through bridge_jobs at all — it enqueues
    straight into dispatch_pending_queue via queued_dispatch_text. Wiring it here
    would have read 0 forever and throttled nothing, while looking correct.

    `claimed_at IS NULL` is the load-bearing half: a row a worker has picked up is
    real in-flight work and must not count against the producer. Only rows nobody
    has taken are backlog.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """SELECT count(*) AS n
                     FROM dispatch_pending_queue
                    WHERE module_id = 'quality_scorer'
                      AND status = 'queued'
                      AND claimed_at IS NULL"""
            )
            row = cur.fetchone()
        return int((row or {}).get("n") or 0)
    except Exception as exc:  # noqa: BLE001
        # Fail OPEN: an unreadable count must not silently stop scoring. A stuck
        # producer is visible; a producer that quietly stopped is not.
        logger.warning("quality review: backlog probe failed (%s) — not throttling", exc)
        return 0


def max_queued_backlog() -> int:
    """Cap, tunable without a deploy. Fail-safe to the default, never to 0.

    A 0 would stop the job entirely on the first iteration, which reads exactly
    like the job being broken — the same shape as the TTL-of-0 trap in
    dispatch_queue_reaper.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = %s",
                (BACKLOG_SETTING_KEY,),
            )
            row = cur.fetchone()
        if row and (row.get("value") not in (None, "")):
            val = int(float(row["value"]))
            if val > 0:
                return val
            logger.warning(
                "%s is %s (<=0) — refusing to disable scoring; using default %d",
                BACKLOG_SETTING_KEY,
                val,
                MAX_QUEUED_BACKLOG,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("quality review: cap lookup failed (%s) — using default", exc)
    return MAX_QUEUED_BACKLOG


def _record_failure(get_db_cursor, entry_id: int) -> str:
    """Count a scoring failure for an entry; mark 'error' only after
    MAX_SCORE_ATTEMPTS attempts, else leave it 'pending' to retry on a later
    run. Returns the resulting review_status.

    Fixes the old behavior where a single transient failure permanently marked
    the entry 'error' and it was never retried (task #4553).
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE knowledge_base
                   SET memory_metadata = COALESCE(memory_metadata, '{}'::jsonb)
                           || jsonb_build_object(
                               'score_attempts',
                               COALESCE((memory_metadata->>'score_attempts')::int, 0) + 1
                           ),
                       review_status = CASE
                           WHEN COALESCE((memory_metadata->>'score_attempts')::int, 0) + 1 >= %s
                           THEN 'error' ELSE review_status END,
                       quality_scored_at = CASE
                           WHEN COALESCE((memory_metadata->>'score_attempts')::int, 0) + 1 >= %s
                           THEN NOW() ELSE quality_scored_at END
                   WHERE id = %s
                   RETURNING review_status""",
                (MAX_SCORE_ATTEMPTS, MAX_SCORE_ATTEMPTS, entry_id),
            )
            row = cur.fetchone()
            if row:
                return row["review_status"] if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return "pending"


def run_quality_review() -> Dict[str, Any]:
    """Score unscored knowledge entries one at a time through the DHQ fleet.

    Fetches one 'pending' entry (skipping ones already attempted THIS run, so a
    persistent failure spreads its attempts across runs), scores it via the
    cluster, persists, then fetches the next. If one entry fails it records the
    attempt and moves on. Stops after ENTRIES_PER_RUN entries or
    MAX_RUN_SECONDS elapsed.

    Returns:
        Dict with scoring results and stats.
    """
    try:
        from services.quality_scoring_service import (
            score_entry,
            get_quality_stats,
        )
        from database import get_db_cursor
    except ImportError as e:
        logger.error("Cannot import quality_scoring_service: %s", e)
        return {"success": False, "error": str(e)}

    # 'throttled' stays 0 unless backpressure actually fired, so a quiet run is
    # distinguishable from a throttled one in the returned dict.
    counts = {"scored": 0, "flagged": 0, "rejected": 0, "failed": 0, "errored": 0, "throttled": 0}
    attempted_ids: list = []
    start_time = time.time()

    cap = max_queued_backlog()

    for i in range(ENTRIES_PER_RUN):
        # Time guard
        elapsed = time.time() - start_time
        if elapsed > MAX_RUN_SECONDS:
            logger.info("Quality review: time limit reached after %d entries", i)
            break

        # BACKPRESSURE. Each score_entry() blocks up to 240s on the queue and, on
        # timeout, ABANDONS its row and moves straight to the next entry — so a
        # slow cluster turns this loop into a row generator for work nobody will
        # claim. Measured 2026-09-15: 629 quality_scorer rows expired in 24h
        # against 244 completed, i.e. the majority of what this job enqueued was
        # thrown away by the reaper 30 minutes later.
        #
        # The reaper (#3333) BOUNDS that leak; it does not cure it. Its own
        # docstring says the reaped count IS the size of the upstream problem.
        # This is the upstream fix: stop producing what the fleet is not draining.
        backlog = queued_backlog()
        if backlog >= cap:
            counts["throttled"] = backlog
            logger.info(
                "Quality review: %d unclaimed quality_scorer rows already queued "
                "(cap %d) — stopping after %d entries rather than enqueueing work "
                "the reaper will expire",
                backlog,
                cap,
                i,
            )
            break

        # Fetch ONE unscored entry not yet attempted this run
        try:
            with get_db_cursor() as (conn, cur):
                if attempted_ids:
                    cur.execute(
                        """SELECT id, title, content, knowledge_type
                           FROM knowledge_base
                           WHERE review_status = 'pending'
                           AND knowledge_type NOT LIKE 'archie_v1%%'
                           AND id <> ALL(%s)
                           ORDER BY importance_score DESC, created_at DESC
                           LIMIT 1""",
                        (attempted_ids,),
                    )
                else:
                    cur.execute(
                        """SELECT id, title, content, knowledge_type
                           FROM knowledge_base
                           WHERE review_status = 'pending'
                           AND knowledge_type NOT LIKE 'archie_v1%%'
                           ORDER BY importance_score DESC, created_at DESC
                           LIMIT 1"""
                    )
                entry = cur.fetchone()
        except Exception as e:
            logger.error("Quality review: failed to fetch entry: %s", e)
            counts["failed"] += 1
            continue

        if not entry:
            logger.info("Quality review: no more unscored entries")
            break

        attempted_ids.append(entry["id"])

        # Score it through the cluster (queue-and-wait)
        try:
            result = score_entry(
                entry_id=entry["id"],
                title=entry["title"],
                content=entry["content"],
                knowledge_type=entry["knowledge_type"],
                save_to_db=True,
            )
            if result:
                counts[result["review_status"]] += 1
            else:
                counts["failed"] += 1
                if _record_failure(get_db_cursor, entry["id"]) == "error":
                    counts["errored"] += 1
        except Exception as e:
            logger.error("Quality review: entry %d failed: %s", entry["id"], e)
            counts["failed"] += 1
            if _record_failure(get_db_cursor, entry["id"]) == "error":
                counts["errored"] += 1

    elapsed = time.time() - start_time
    total = counts["scored"] + counts["flagged"] + counts["rejected"]
    stats = get_quality_stats()

    logger.info(
        "Quality review: %d scored (%d good, %d flagged, %d rejected, %d failed, %d errored) in %.0fs — coverage: %s%%",
        total,
        counts["scored"],
        counts["flagged"],
        counts["rejected"],
        counts["failed"],
        counts["errored"],
        elapsed,
        stats.get("coverage", "?"),
    )

    if counts.get("throttled"):
        logger.info(
            "Quality review: run ended on backpressure (%d queued, cap %d)",
            counts["throttled"],
            cap,
        )

    return {
        "success": True,
        "counts": counts,
        "elapsed_s": round(elapsed),
        "stats": stats,
        "throttled": bool(counts.get("throttled")),
        "queue_cap": cap,
    }
