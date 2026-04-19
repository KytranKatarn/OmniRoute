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

from services.agent_service import match_capability, get_agent_cache, get_welfare_cache
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
# Capability → Department mapping
# ---------------------------------------------------------------------------

CAPABILITY_DEPARTMENT_MAP = {
    "code": "Engineering & Technology",
    "code_review": "Engineering & Technology",
    "debug": "Engineering & Technology",
    "general": "Engineering & Technology",
    "classify": "Analytics & Intelligence",
    "analyze": "Analytics & Intelligence",
    "knowledge_analysis": "Analytics & Intelligence",
    "summarize": "Documentation & Knowledge",
    "translate": "Documentation & Knowledge",
    "embedding": "Documentation & Knowledge",
    "creative": "Creative & Design",
    "image": "Creative & Design",
    "image_generation": "Creative & Design",
    "visual_design": "Creative & Design",
    # Vision / multimodal analysis belongs with the creative agents who own
    # the image model. Pixel's capabilities.primary now includes "vision"
    # and "ux_scoring" so agent selection resolves to him within the dept.
    "vision": "Creative & Design",
    "multimodal": "Creative & Design",
    "ux_scoring": "Creative & Design",
    "security": "Security & Compliance",
    "compliance": "Security & Compliance",
    "support": "Customer Success & Support",
    "research": "Research & Development",
}


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

    @property
    def model_service(self) -> ModelService:
        """Public access to model service for callers that need to register jobs."""
        return self._model_service

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

    # ------------------------------------------------------------------
    # Scoring & Selection (Phase 2)
    # ------------------------------------------------------------------

    def _refresh_caches(self) -> None:
        """Refresh agent and welfare caches if stale (>30s)."""
        import time as _time

        now = _time.time()
        if not hasattr(self, "_cache_time") or (now - self._cache_time) > 30:
            self._agent_cache = get_agent_cache()
            self._welfare_cache = get_welfare_cache()
            self._cache_time = now

    def score_agent(
        self,
        agent_name: str,
        agent_info: Dict,
        capability: str,
        department: str,
        recommended_tier: Optional[str] = None,
    ) -> tuple:
        """Score an agent for capability dispatch. Returns (score, block_reason_or_None).

        Scoring factors:
        - Status/shift must be active (hard block if not)
        - Budget utilization (hard block at 95%+)
        - Welfare: stress penalty, energy bonus
        - Specialization: skill match bonus
        - Department match bonus
        """
        agent_id = agent_info.get("id")

        if agent_info.get("status") != "active":
            return (
                0.0,
                f"{agent_name} is {agent_info.get('status')} (not available)",
            )

        shift = agent_info.get("shift_state", "active")
        if shift not in ("active", "winding_down"):
            return (0.0, f"{agent_name} shift_state={shift}")

        self._refresh_caches()
        welfare = self._welfare_cache.get(agent_id, {})
        budget = welfare.get("budget", {})
        util_pct = budget.get("utilization_pct", 0.0)
        if util_pct >= 0.95:
            return (0.0, f"{agent_name} budget exhausted ({util_pct:.0%})")

        score = 1.0
        stress = welfare.get("stress", 0.0)
        energy = welfare.get("energy", 0.5)
        score += (1.0 - stress) * 0.3
        score += energy * 0.2
        score -= util_pct * 0.5

        if shift == "winding_down":
            score -= 0.3

        skills = agent_info.get("skills", {})
        if capability in skills:
            proficiency = skills[capability]
            score += proficiency * 0.2
        elif capability:
            # Agent lacks the requested skill entirely.  Apply a hard penalty
            # so unskilled directors (dept +0.2, director +0.3) cannot beat a
            # barracked specialist — this forces wake-on-demand to trigger when
            # every active candidate is unskilled (#2166, 2026-04-19).
            score -= 1.0

        # Competency adjustment — reward/penalize based on tested capability (#2179)
        if capability:
            competency_scores = agent_info.get("competency_scores") or {}
            comp_score = competency_scores.get(capability)
            if comp_score is not None:
                if comp_score >= 0.7:
                    score += 0.2
                elif comp_score < 0.5:
                    score -= 0.2
                # else: 0.5 <= score < 0.7 is passable, no adjustment

        if agent_info.get("department") == department:
            score += 0.2

        if agent_info.get("is_department_ai"):
            score += 0.3

        if recommended_tier:
            agent_model = agent_info.get("model", "")
            try:
                from tools.department_hq.services.smart_router import get_router

                router = get_router()
                configs = router._get_model_configs()
                tier_config = configs.get(recommended_tier)
                if tier_config and (
                    agent_model == tier_config.model_name
                    or agent_model.startswith(tier_config.model_name.split(":")[0])
                ):
                    score += 1.0
            except Exception:
                pass

        return (max(score, 0.01), None)

    def resolve_department(self, capability: str) -> str:
        """Map a capability to its home department."""
        return CAPABILITY_DEPARTMENT_MAP.get(capability, "Engineering & Technology")

    def select_agent(
        self,
        capability: str,
        department: str,
        recommended_tier: Optional[str] = None,
    ) -> Optional[Dict]:
        """Select the best agent for a capability within a department.

        If every active/winding_down candidate is blocked (budget, stress,
        reserved), fall back to a barracked specialist in the same
        department with proficiency >= 3 on the requested skill and wake
        them via shift-state transition before returning. This keeps the
        home-department dispatch path preferred over cross-department
        escalation whenever a qualified specialist exists on the bench.
        """
        self._refresh_caches()

        candidates = []
        for name, info in self._agent_cache.items():
            if info.get("department") != department:
                continue
            score, block_reason = self.score_agent(
                name, info, capability, department, recommended_tier=recommended_tier
            )
            if score > 0 and block_reason is None:
                with self._lock:
                    if info["id"] in self._reserved_agents:
                        continue
                candidates.append((score, name, info))

        if not candidates:
            # Every active candidate blocked/reserved/no-skill-match. Try
            # to wake a barracked specialist before escalating cross-dept.
            woken = self._wake_barracked_specialist(capability, department)
            if woken:
                return woken
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_name, best_info = candidates[0]
        logger.info(
            "coordinator: selected %s (score=%.2f) for %s in %s",
            best_name,
            best_score,
            capability,
            department,
        )
        return best_info

    def _wake_barracked_specialist(
        self,
        capability: str,
        department: str,
        min_proficiency: int = 3,
    ) -> Optional[Dict]:
        """Wake the best barracked specialist in this department for capability.

        Queries agent_skills for a barracked agent with proficiency_level
        >= min_proficiency on the requested skill, activates them via
        agent_service.transition_shift_state, logs a governance event,
        and returns a cache-shaped dict ready for dispatch.
        """
        from db import get_db

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT a.id, a.name, a.display_name, a.model, s.proficiency_level
                FROM agents a
                JOIN agent_skills s ON s.agent_id = a.id
                WHERE a.department = %s
                  AND a.shift_state = 'barracked'
                  AND a.status = 'active'
                  AND s.skill_name = %s
                  AND s.proficiency_level >= %s
                ORDER BY s.proficiency_level DESC, a.last_used ASC NULLS FIRST
                LIMIT 1
                """,
                (department, capability, min_proficiency),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as exc:
            logger.warning("wake_on_demand: lookup failed — %s", exc)
            return None

        if not row:
            return None

        agent_id, agent_name, display_name, model, proficiency = row

        try:
            from services.agent_service import transition_shift_state

            result = transition_shift_state(agent_id, "active", reason="wake_on_demand")
            if not result or not result.get("success"):
                logger.warning(
                    "wake_on_demand: transition_shift_state failed for %s: %s",
                    agent_name,
                    result.get("error") if result else "no result",
                )
                return None
        except Exception as exc:
            logger.warning("wake_on_demand: state transition crashed — %s", exc)
            return None

        logger.info(
            "wake_on_demand: %s (id=%d, Lv%d in %s) woken for %s",
            agent_name,
            agent_id,
            proficiency,
            department,
            capability,
        )

        # Audit trail — K.I.N. sees every on-demand wake
        try:
            from db import get_db as _get_db
            import json as _json

            _conn = _get_db()
            _cur = _conn.cursor()
            _cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, action, outcome, details, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    "agent_welfare",
                    "orchestration",
                    agent_id,
                    "wake_on_demand",
                    "activated",
                    _json.dumps(
                        {
                            "capability": capability,
                            "department": department,
                            "proficiency_level": proficiency,
                            "trigger": "home_dept_saturated",
                        }
                    ),
                ),
            )
            _conn.commit()
            _cur.close()
            _conn.close()
        except Exception as exc:
            logger.debug("wake_on_demand: governance log failed — %s", exc)

        # Force the agent cache to pick up the new shift_state on next refresh.
        self._cache_time = 0

        return {
            "id": agent_id,
            "name": agent_name,
            "display_name": display_name,
            "model": model,
            "department": department,
            "shift_state": "active",
            "status": "active",
            "woken_on_demand": True,
        }

    def find_cross_department_agent(
        self,
        capability: str,
        blocked_department: str,
    ) -> Optional[Dict]:
        """Find an agent in another department that has the requested skill."""
        self._refresh_caches()

        all_departments = set(info.get("department") for info in self._agent_cache.values() if info.get("department"))
        skip = {blocked_department, "Executive Office"}

        for dept in sorted(all_departments - skip):
            for name, info in self._agent_cache.items():
                if info.get("department") != dept:
                    continue
                skills = info.get("skills", {})
                if capability not in skills:
                    continue
                score, block_reason = self.score_agent(name, info, capability, dept)
                if score > 0 and block_reason is None:
                    with self._lock:
                        if info["id"] in self._reserved_agents:
                            continue
                    logger.info(
                        "coordinator: cross-dept fallback %s→%s (%s) for %s",
                        blocked_department,
                        dept,
                        name,
                        capability,
                    )
                    return info
        return None

    # ------------------------------------------------------------------
    # Reservation lifecycle
    # ------------------------------------------------------------------

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
