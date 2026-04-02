"""
Department Coordinator — admission control and agent reservation.

Coordinates agent scheduling across departments:
  - Picks the best available agent for a capability
  - Ensures the agent's model is loaded before assigning
  - Tracks reservations to avoid double-booking
  - Queues requests when no capacity is available
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from services.agent_service import match_capability
from services.model_service import ModelService, get_model_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Assignment:
    """Result of a request_agent call."""

    agent_id: Optional[int] = None
    agent_name: str = ""
    model: str = ""
    host: str = "192.168.1.200"
    department: str = ""
    queued: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class DepartmentCoordinator:
    """Admission controller for agent assignments.

    Thread-safe: uses a lock around the reserved-agents set so concurrent
    Flask threads cannot assign the same agent twice.
    """

    def __init__(self, model_service: Optional[ModelService] = None) -> None:
        self._model_service: ModelService = model_service or get_model_service()
        self._reserved_agents: Set[int] = set()
        self._lock = threading.Lock()
        # job_id → agent_id, for cleanup on release
        self._job_map: Dict[int, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_agent(
        self,
        capability: str,
        module_source: str = "",
        priority: str = "normal",
    ) -> Assignment:
        """Find and reserve an agent that matches *capability*.

        Steps:
        1. match_capability → ranked candidate list
        2. Skip reserved agents
        3. For each remaining candidate, ensure_ready the model
        4. First success → reserve and return Assignment
        5. If none succeed → return queued Assignment
        """
        candidates: List[Dict] = match_capability(capability)

        if not candidates:
            logger.warning("department_coordinator: no agent found for capability=%s", capability)
            return Assignment(
                queued=True,
                reason=f"no agent available for capability '{capability}'",
            )

        for candidate in candidates:
            agent_id: int = candidate["id"]
            model: str = candidate.get("model", "")

            with self._lock:
                if agent_id in self._reserved_agents:
                    logger.debug("department_coordinator: agent %s is reserved, skipping", agent_id)
                    continue

            # Check model capacity outside lock (potentially slow Ollama call)
            needed_gb = 8.0
            if not self._model_service.ensure_ready(model, needed_gb):
                logger.debug(
                    "department_coordinator: ensure_ready failed for model=%s agent=%s",
                    model,
                    agent_id,
                )
                continue

            # Claim the agent
            with self._lock:
                # Double-check — another thread may have grabbed it while we
                # were waiting for ensure_ready
                if agent_id in self._reserved_agents:
                    continue
                self._reserved_agents.add(agent_id)

            self._model_service.register_job(model, agent_id)

            logger.info(
                "department_coordinator: assigned agent %s (%s) model=%s src=%s",
                agent_id,
                candidate.get("display_name", ""),
                model,
                module_source,
            )

            return Assignment(
                agent_id=agent_id,
                agent_name=candidate.get("display_name", candidate.get("name", "")),
                model=model,
                host="192.168.1.200",
                department=candidate.get("department", ""),
                queued=False,
                reason="",
            )

        # All candidates exhausted
        logger.warning(
            "department_coordinator: all %d candidates for '%s' are busy or have no capacity",
            len(candidates),
            capability,
        )
        return Assignment(
            queued=True,
            reason=f"all agents for capability '{capability}' are busy or have insufficient capacity",
        )

    def release_agent(self, agent_id: int, job_id: Optional[int] = None) -> None:
        """Release an agent reservation so it can accept new work."""
        with self._lock:
            self._reserved_agents.discard(agent_id)
            if job_id is not None:
                self._job_map.pop(job_id, None)

        logger.debug("department_coordinator: released agent %s", agent_id)

    def get_status(self) -> Dict:
        """Return a snapshot of coordinator state for monitoring endpoints."""
        with self._lock:
            reserved = list(self._reserved_agents)

        return {
            "reserved_agents": reserved,
            "loaded_models": self._model_service.check_loaded_models(),
            "available_ram_gb": self._model_service.get_available_ram(),
            "active_jobs": len(reserved),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_coordinator: Optional[DepartmentCoordinator] = None
_coordinator_lock = threading.Lock()


def get_coordinator() -> DepartmentCoordinator:
    """Return the global DepartmentCoordinator singleton."""
    global _coordinator
    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                _coordinator = DepartmentCoordinator()
    return _coordinator
