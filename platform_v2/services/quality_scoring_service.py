"""Quality Scoring Service — LLM-based knowledge entry quality assessment.

Scores knowledge_base entries on relevance, accuracy, actionability, uniqueness.
Used by: knowledge_cards.py (gate new entries), agent_loop (periodic re-scoring).

Import:
    from services.quality_scoring_service import score_entry, batch_score_entries
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Quality thresholds
QUALITY_REJECT = 0.3  # Below this: rejected outright
QUALITY_FLAG = 0.5  # Below this: flagged for review
QUALITY_ACCEPT = 0.5  # At or above: accepted

# Prompt for LLM quality assessment
QUALITY_PROMPT = """You are a knowledge base quality assessor for A.R.C.H.I.E., a software platform management system.

Rate this knowledge entry on 4 dimensions (each 0.0 to 1.0):

1. **Relevance** — Is this useful for platform development, operations, or decision-making? Generic filler scores 0.1. Specific platform knowledge scores 0.9.
2. **Accuracy** — Is the information correct, specific, and current? Vague summaries score 0.2. Precise facts with context score 0.9.
3. **Actionability** — Can someone act on this? "Code exists" scores 0.1. "Use function X in file Y for Z" scores 0.9.
4. **Uniqueness** — Does this add value beyond what's already obvious from reading the code? Restating file names scores 0.1. Explaining non-obvious patterns scores 0.9.

Entry to assess:
---
Type: {knowledge_type}
Title: {title}
Content: {content}
---

Respond with ONLY valid JSON (no markdown, no explanation):
{{"relevance": 0.X, "accuracy": 0.X, "actionability": 0.X, "uniqueness": 0.X, "reason": "one sentence"}}"""


def score_entry(
    entry_id: int,
    title: str,
    content: str,
    knowledge_type: str,
    save_to_db: bool = True,
) -> Optional[Dict[str, Any]]:
    """Score a single knowledge entry using LLM.

    Args:
        entry_id: knowledge_base.id
        title: Entry title
        content: Entry content (will be truncated to 2000 chars)
        knowledge_type: e.g. 'knowledge_card', 'conversation_memory'
        save_to_db: Whether to persist the score to DB

    Returns:
        Dict with quality_score, dimensions, reason, or None on failure.
    """
    from ai_bridge.bridge_dispatcher import get_dispatcher

    content_truncated = (content or "")[:2000]

    prompt = QUALITY_PROMPT.format(
        knowledge_type=knowledge_type,
        title=title or "(no title)",
        content=content_truncated,
    )

    try:
        dispatcher = get_dispatcher()
        result = dispatcher.dispatch_json(
            prompt=prompt,
            capability="classify",
            timeout=60,
        )

        if not result or not isinstance(result, dict):
            logger.warning("Quality scorer: empty or invalid LLM response for entry %d", entry_id)
            return None

        relevance = float(result.get("relevance", 0))
        accuracy = float(result.get("accuracy", 0))
        actionability = float(result.get("actionability", 0))
        uniqueness = float(result.get("uniqueness", 0))
        reason = result.get("reason", "")

        quality_score = round(
            relevance * 0.30 + accuracy * 0.25 + actionability * 0.25 + uniqueness * 0.20,
            2,
        )

        if quality_score < QUALITY_REJECT:
            review_status = "rejected"
        elif quality_score < QUALITY_FLAG:
            review_status = "flagged"
        else:
            review_status = "scored"

        scoring_result = {
            "quality_score": quality_score,
            "review_status": review_status,
            "dimensions": {
                "relevance": relevance,
                "accuracy": accuracy,
                "actionability": actionability,
                "uniqueness": uniqueness,
            },
            "reason": reason,
        }

        if save_to_db:
            _persist_score(entry_id, quality_score, review_status, scoring_result)

        return scoring_result

    except Exception as e:
        logger.error("Quality scorer failed for entry %d: %s", entry_id, e)
        return None


def _persist_score(entry_id: int, quality_score: float, review_status: str, full_result: dict):
    """Save quality score to database."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE knowledge_base
                   SET quality_score = %s,
                       review_status = %s,
                       quality_scored_at = NOW(),
                       memory_metadata = COALESCE(memory_metadata, '{}'::jsonb) || %s::jsonb
                   WHERE id = %s""",
                (
                    quality_score,
                    review_status,
                    json.dumps({"quality_assessment": full_result}),
                    entry_id,
                ),
            )
    except Exception as e:
        logger.error("Failed to persist quality score for entry %d: %s", entry_id, e)


def batch_score_entries(
    batch_size: int = 20,
    target_types: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Score a batch of unscored entries. Returns counts by status.

    Args:
        batch_size: How many entries to score in this batch
        target_types: Optional list of knowledge_types to target

    Returns:
        Dict with counts: {"scored": N, "flagged": N, "rejected": N, "failed": N}
    """
    counts = {"scored": 0, "flagged": 0, "rejected": 0, "failed": 0}

    try:
        with get_db_cursor() as (conn, cur):
            type_filter = ""
            params = []
            if target_types:
                placeholders = ",".join(["%s"] * len(target_types))
                type_filter = f"AND knowledge_type IN ({placeholders})"
                params = list(target_types)
            params.append(batch_size)

            cur.execute(
                f"""SELECT id, title, content, knowledge_type
                    FROM knowledge_base
                    WHERE review_status = 'pending'
                    AND knowledge_type NOT LIKE 'archie_v1%%'
                    {type_filter}
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT %s""",
                params,
            )
            entries = cur.fetchall()
    except Exception as e:
        logger.error("Failed to fetch unscored entries: %s", e)
        return counts

    for entry in entries:
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

    logger.info(
        "Quality scoring batch: %d scored, %d flagged, %d rejected, %d failed",
        counts["scored"],
        counts["flagged"],
        counts["rejected"],
        counts["failed"],
    )
    return counts


def get_quality_stats() -> Dict[str, Any]:
    """Get quality score distribution stats for dashboard."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT
                    review_status,
                    COUNT(*) as cnt,
                    ROUND(AVG(quality_score)::numeric, 2) as avg_score
                FROM knowledge_base
                WHERE knowledge_type NOT LIKE 'archie_v1%%'
                GROUP BY review_status
                ORDER BY cnt DESC
            """
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT COUNT(*) as total,
                    COUNT(quality_score) as scored_count
                FROM knowledge_base
                WHERE knowledge_type NOT LIKE 'archie_v1%%'
            """
            )
            totals = cur.fetchone()

            return {
                "total_entries": totals["total"],
                "scored_entries": totals["scored_count"],
                "coverage": round(totals["scored_count"] / max(totals["total"], 1) * 100, 1),
                "by_status": {
                    r["review_status"]: {"count": r["cnt"], "avg_score": float(r["avg_score"] or 0)} for r in rows
                },
            }
    except Exception as e:
        logger.error("Failed to get quality stats: %s", e)
        return {}
