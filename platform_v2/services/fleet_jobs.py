"""fleet_jobs.py — Job registrations for Fleet/Operations.

Registers fleet health monitoring jobs with job_service.
"""

import logging

logger = logging.getLogger(__name__)


def register_fleet_jobs(job_service):
    """Register fleet monitoring jobs.

    Future: move implementations from agent_loop.py here.
    """
    logger.info(
        "[FleetJobs] Fleet owns these agent_loop jobs: "
        "agent_fleet_health, agent_mesh_health, agent_model_state_save, "
        "agent_standalone_health, agent_ollama_model_health, fleet_ssl_renewal, "
        "agent_health_probe"
    )
