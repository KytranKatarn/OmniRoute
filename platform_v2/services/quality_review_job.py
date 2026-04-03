"""Quality Review Job — periodic LLM scoring of knowledge base entries.

Agent Loop Job: runs every 2 hours, scores 25 unscored entries per batch.

Import:
    from services.quality_review_job import run_quality_review
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def run_quality_review() -> Dict[str, Any]:
    """Score unscored knowledge entries in priority order.

    Returns:
        Dict with scoring results and stats.
    """
    try:
        from services.quality_scoring_service import batch_score_entries, get_quality_stats
    except ImportError as e:
        logger.error("Cannot import quality_scoring_service: %s", e)
        return {"success": False, "error": str(e)}

    results: Dict[str, Any] = {"success": True, "batches": []}

    batch1 = batch_score_entries(batch_size=25)
    results["batches"].append({"phase": "general", **batch1})

    stats = get_quality_stats()
    results["stats"] = stats

    total = sum(b.get("scored", 0) + b.get("flagged", 0) + b.get("rejected", 0) for b in results["batches"])
    logger.info(
        "Quality review complete: %d entries scored, coverage: %s%%",
        total,
        stats.get("coverage", "?"),
    )

    return results
