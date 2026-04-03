"""Quality Review Job — periodic LLM scoring of knowledge base entries.

Agent Loop Job: runs every 2 hours, scores entries one at a time.
Fetches one unscored entry, scores it, commits, repeats.
A single failure skips that entry and moves to the next.

Import:
    from services.quality_review_job import run_quality_review
"""

import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)

# How many entries to score per job run
ENTRIES_PER_RUN = 50
# Max seconds per job run (don't hog the LLM forever)
MAX_RUN_SECONDS = 600


def _mark_error(get_db_cursor, entry_id: int):
    """Mark an entry as 'error' so it's not retried forever."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE knowledge_base
                   SET review_status = 'error', quality_scored_at = NOW()
                   WHERE id = %s""",
                (entry_id,),
            )
    except Exception:
        pass


def run_quality_review() -> Dict[str, Any]:
    """Score unscored knowledge entries one at a time.

    Fetches one entry, scores it, persists, then fetches the next.
    If one entry fails, it logs the error and moves on.
    Stops after ENTRIES_PER_RUN entries or MAX_RUN_SECONDS elapsed.

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

    counts = {"scored": 0, "flagged": 0, "rejected": 0, "failed": 0, "skipped": 0}
    start_time = time.time()

    for i in range(ENTRIES_PER_RUN):
        # Time guard
        elapsed = time.time() - start_time
        if elapsed > MAX_RUN_SECONDS:
            logger.info("Quality review: time limit reached after %d entries", i)
            break

        # Fetch ONE unscored entry
        try:
            with get_db_cursor() as (conn, cur):
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

        # Score it
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
                _mark_error(get_db_cursor, entry["id"])
        except Exception as e:
            logger.error("Quality review: entry %d failed: %s", entry["id"], e)
            counts["failed"] += 1
            _mark_error(get_db_cursor, entry["id"])

    elapsed = time.time() - start_time
    total = counts["scored"] + counts["flagged"] + counts["rejected"]
    stats = get_quality_stats()

    logger.info(
        "Quality review: %d scored (%d good, %d flagged, %d rejected, %d failed) in %.0fs — coverage: %s%%",
        total,
        counts["scored"],
        counts["flagged"],
        counts["rejected"],
        counts["failed"],
        elapsed,
        stats.get("coverage", "?"),
    )

    return {"success": True, "counts": counts, "elapsed_s": round(elapsed), "stats": stats}
