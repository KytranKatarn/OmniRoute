"""consciousness/jobs.py — Job registrations for Consciousness module.

These jobs are currently implemented in agent_loop.py.
This module registers them with job_service under the correct
department for proper tracking and future extraction.

Phase 5 gradual extraction: metadata first, implementation later.
"""

import logging

logger = logging.getLogger(__name__)


def register_consciousness_jobs(job_service):
    """Register consciousness module jobs.

    Note: These are metadata-only registrations. The actual job
    implementations still run via agent_loop.py / APScheduler.
    When we extract implementations, the func= parameter will
    point to the real function.
    """
    # Already registered via agent_loop_bridge — just log for now
    # Future: move implementations here
    logger.info(
        "[ConsciousnessJobs] Consciousness owns these agent_loop jobs: "
        "agent_consciousness_analysis, agent_consciousness_embedding, "
        "agent_skill_sync, agent_github_auto_pull, agent_skill_analyzer, "
        "agent_conversation_consolidation, knowledge_deduplication"
    )
