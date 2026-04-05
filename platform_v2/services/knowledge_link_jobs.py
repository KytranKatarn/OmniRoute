"""knowledge_link_jobs.py -- Auto-link knowledge to projects job registration.

Registers the auto-linking job with job_service. Called at app startup.
Follows the same pattern as budget_jobs.py.
"""

import logging
from services.knowledge_link_service import auto_link_knowledge, auto_link_bridge_jobs

logger = logging.getLogger(__name__)


def _run_auto_link():
    """Run both knowledge and bridge job auto-linking."""
    kb_stats = auto_link_knowledge()
    bj_stats = auto_link_bridge_jobs(batch_size=100)
    return {
        "knowledge": kb_stats,
        "bridge_jobs": bj_stats,
        "total_linked": kb_stats.get("linked", 0) + bj_stats.get("linked", 0),
    }


def register_knowledge_link_jobs(job_service):
    """Register knowledge auto-linking job with the central job service."""
    job_service.register_job(
        name="auto_link_knowledge_to_projects",
        func=_run_auto_link,
        interval_hours=0.5,
        department="Research & Development",
        description="Auto-link knowledge entries and bridge jobs to projects via embedding similarity (every 30 min)",
    )
    logger.info("[KnowledgeLinkJobs] Registered auto_link_knowledge_to_projects job")
