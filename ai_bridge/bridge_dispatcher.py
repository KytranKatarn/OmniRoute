"""
BridgeDispatcher — Central AI Work Dispatch System
Project #91: Team Management Redesign

Single entry point for all AI work requests. Replaces direct LLM calls
throughout the platform with a centralized dispatch model where ARCHIE
assigns team member agents to modules on demand via Bridge Command.

Design:
- Modules call dispatcher.request_work(capability, prompt, ...)
- Dispatcher finds the right agent for the capability
- Agent's model is used to execute the work
- All executions logged to task_execution_log for HR tracking

Author: A.R.C.H.I.E. Platform
Date: 2026-02-17
"""

import json
import logging
import time
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============================================================================
# CAPABILITY → STATION MAPPING
# Maps what kind of work → which station handles it
# ============================================================================

CAPABILITY_STATION_MAP = {
    # Command station capabilities
    "conversation": "COMMAND",
    "dispatch": "COMMAND",
    "governance": "COMMAND",
    "orchestration": "COMMAND",
    # Analytics station capabilities
    "classify": "ANALYTICS",
    "sentiment": "ANALYTICS",
    "tagging": "ANALYTICS",
    "anomaly_detection": "ANALYTICS",
    "pattern_recognition": "ANALYTICS",
    "embedding": "ANALYTICS",
    "vision": "ANALYTICS",
    # Engineering station capabilities
    "code": "ENGINEERING",
    "code_analysis": "ENGINEERING",
    "code_review": "ENGINEERING",
    "testing": "ENGINEERING",
    "debugging": "ENGINEERING",
    "schema_design": "ENGINEERING",
    "api_design": "ENGINEERING",
    "deployment": "ENGINEERING",
    # Operations station capabilities
    "operations": "OPERATIONS",
    "system_monitoring": "OPERATIONS",
    "backup": "OPERATIONS",
    "health_check": "OPERATIONS",
    "security_analysis": "OPERATIONS",
    "telegram": "OPERATIONS",
    "email": "OPERATIONS",
    "notification": "OPERATIONS",
    "webhook": "OPERATIONS",
    "ha_integration": "OPERATIONS",
    "automation": "OPERATIONS",
    # Creative station capabilities
    "content_writing": "CREATIVE",
    "email_composition": "CREATIVE",
    "chat_styling": "CREATIVE",
    "voice": "CREATIVE",
    "ux_writing": "CREATIVE",
    "social_media": "CREATIVE",
    "image_generation": "CREATIVE",
    "video_generation": "CREATIVE",
    "audio_generation": "CREATIVE",
    "audio_tts": "CREATIVE",
    "audio_music": "CREATIVE",
    "media_editing": "CREATIVE",
    # Research station capabilities
    "knowledge_analysis": "RESEARCH",
    "summarize": "RESEARCH",
    "document_analysis": "RESEARCH",
    "fact_checking": "RESEARCH",
    "semantic_search": "RESEARCH",
    "context_retrieval": "RESEARCH",
    # Analytics station — translation (linguistic processing, Languages tab)
    "translate": "ANALYTICS",
    # Analytics — language detection (classification task)
    "detect_language": "ANALYTICS",
    # Generic fallbacks
    "analysis": "ANALYTICS",
    "general": "COMMAND",
    "json": "ANALYTICS",
}

# Capabilities that require explicit agent skill (no generous 0.3 default).
# If no agent at the mapped station has the skill, cross-station dispatch
# finds an agent elsewhere who does.
CAPABILITY_REQUIRES_SKILL = {
    "translate",  # Needs a capable chat LLM — not a classifier or embedder
}

# Specialized agent selection within stations
# When a station has multiple agents, pick by sub-capability
AGENT_SPECIALIZATION = {
    "COMMAND": {
        "default": "ARCHIE",
        "security_analysis": "Sentinel",
        "compliance": "Sentinel",
        "audit": "Sentinel",
        "governance": "Sentinel",
        "threat_detection": "Sentinel",
    },
    "ENGINEERING": {
        "default": "CodeSmith",
        "schema_design": "Architect",
        "api_design": "Architect",
        "architecture": "Architect",
    },
    "OPERATIONS": {
        "default": "OpsMaster",
        "telegram": "CommRelay",
        "email": "CommRelay",
        "notification": "CommRelay",
        "webhook": "CommRelay",
        "ha_integration": "CommRelay",
    },
    "ANALYTICS": {
        "default": "DataMind",
        "embedding": "Nexus",
        "vision": "Nexus",
        "knowledge_extraction": "Nexus",
    },
    "CREATIVE": {
        "default": "Wordsmith",
    },
    "RESEARCH": {
        "default": "Scholar",
    },
}

# Scoring weights for multi-factor agent selection
SELECTION_WEIGHTS = {
    "skills": 0.35,
    "specialization": 0.25,
    "welfare": 0.20,
    "availability": 0.15,
    "budget": 0.05,
}


@dataclass
class DispatchResult:
    """Result from a dispatched work request."""

    success: bool
    response: str
    agent_name: str
    agent_id: Optional[int]
    model_used: str
    station_code: str
    capability: str
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider: str = "ollama"
    error: Optional[str] = None
    metadata: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "response": self.response,
            "agent_name": self.agent_name,
            "agent_id": self.agent_id,
            "model_used": self.model_used,
            "station_code": self.station_code,
            "capability": self.capability,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "provider": self.provider,
            "error": self.error,
        }


class BridgeDispatcher:
    """
    Central dispatch system for all AI work on the ARCHIE Platform.

    Modules request work by capability. The dispatcher:
    1. Maps capability → station → agent
    2. Uses the agent's assigned model to execute
    3. Logs everything to task_execution_log for HR tracking
    4. Handles fallback/escalation gracefully
    """

    def __init__(self):
        self._agent_cache = {}  # name → {id, model, station_code, ...}
        self._cache_time = 0
        self._cache_ttl = 300  # Refresh cache every 5 minutes
        self._db_getter = None
        # Failure tracking for escalation
        self._failure_tracker = {}  # (agent_id, capability) -> count
        # Welfare cache — shorter TTL for near-real-time welfare awareness
        self._welfare_cache = {}  # agent_id → {stress, energy, mood, resting, budget}
        self._welfare_cache_time = 0
        self._welfare_cache_ttl = 30  # Refresh every 30 seconds
        self._busy_agents = set()  # agent names with running bridge_jobs
        # Module → station cache (bridge_stations.modules lookup)
        self._module_station_cache = {}
        self._module_station_ts = 0

    def _get_db(self):
        """Get database connection."""
        if self._db_getter:
            return self._db_getter()
        try:
            from config import get_db

            self._db_getter = get_db
            return get_db()
        except ImportError:
            import psycopg2

            return psycopg2.connect(
                host=os.getenv("DB_HOST", "192.168.1.200"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=os.getenv("DB_PASSWORD", ""),
            )

    def _refresh_agent_cache(self):
        """Load active agents and their station assignments from DB."""
        now = time.time()
        if self._agent_cache and (now - self._cache_time) < self._cache_ttl:
            return

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT a.id, a.name, a.model, a.default_model_tier,
                       a.system_prompt, a.capabilities, a.temperature,
                       a.max_tokens, a.status,
                       a.first_name, a.last_name, a.title,
                       a.display_name,
                       bs.station_code, bs.default_llm
                FROM agents a
                JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
                JOIN bridge_stations bs ON sa.station_id = bs.id AND bs.is_active = TRUE
                WHERE a.status = 'active'
                ORDER BY sa.priority
            """)
            agents = cur.fetchall()
            cur.close()
            conn.close()

            self._agent_cache = {}
            for agent in agents:
                self._agent_cache[agent["name"]] = {
                    "id": agent["id"],
                    "model": agent["model"],
                    "default_model_tier": agent["default_model_tier"],
                    "system_prompt": agent["system_prompt"],
                    "capabilities": agent["capabilities"] or {},
                    "temperature": float(agent["temperature"] or 0.5),
                    "max_tokens": agent["max_tokens"] or 4096,
                    "station_code": agent["station_code"],
                    "station_llm": agent["default_llm"],
                    "first_name": agent.get("first_name") or "",
                    "last_name": agent.get("last_name") or "",
                    "display_name": agent.get("display_name") or "",
                    "title": agent.get("title") or "",
                    "skills": {},  # populated below
                }

            # Load skills for all cached agents
            try:
                agent_ids = [info["id"] for info in self._agent_cache.values()]
                if agent_ids:
                    conn2 = self._get_db()
                    cur2 = conn2.cursor(cursor_factory=RealDictCursor)
                    cur2.execute(
                        """
                        SELECT agent_id, skill_name, skill_category,
                               proficiency_level
                        FROM agent_skills
                        WHERE agent_id = ANY(%s)
                        ORDER BY agent_id, proficiency_level DESC
                    """,
                        (agent_ids,),
                    )
                    skills_rows = cur2.fetchall()
                    cur2.close()
                    conn2.close()

                    # Build id → skills map
                    skills_by_agent = {}  # agent_id → {skill_name: {category, level}}
                    for row in skills_rows:
                        aid = row["agent_id"]
                        if aid not in skills_by_agent:
                            skills_by_agent[aid] = {}
                        skills_by_agent[aid][row["skill_name"]] = {
                            "category": row["skill_category"] or "general",
                            "level": row["proficiency_level"] or 1,
                        }

                    # Attach to cached entries
                    for name, info in self._agent_cache.items():
                        info["skills"] = skills_by_agent.get(info["id"], {})
            except Exception as skills_err:
                logger.warning(
                    f"[BridgeDispatcher] Skills cache load failed: {skills_err}"
                )

            self._cache_time = now
            logger.info(f"[BridgeDispatcher] Cached {len(self._agent_cache)} agents")
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Cache refresh failed: {e}")

    def _refresh_welfare_cache(self):
        """Load agent welfare state (emotional, rest cycles, budgets) with 30s TTL.

        Populates self._welfare_cache keyed by agent_id with:
        - stress, energy, mood (from agent_emotional_state)
        - resting: bool (from agent_rest_cycles where ended_at IS NULL)
        - rest_type: str or None (type of active rest cycle)
        - budget: dict with task/token usage and limits (from agent_budgets)
        """
        now = time.time()
        if (
            self._welfare_cache
            and (now - self._welfare_cache_time) < self._welfare_cache_ttl
        ):
            return

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Emotional state ---
            cur.execute("""
                SELECT DISTINCT ON (agent_id)
                       agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
                ORDER BY agent_id, timestamp DESC
            """)
            emotional_map = {}
            for r in cur.fetchall():
                emotional_map[r["agent_id"]] = {
                    "stress": float(r["stress_level"] or 0),
                    "energy": float(r["energy_level"] or 0.8),
                    "mood": r["current_mood"] or "neutral",
                }

            # --- Active rest cycles (ended_at IS NULL) ---
            cur.execute("""
                SELECT agent_id, rest_type
                FROM agent_rest_cycles
                WHERE ended_at IS NULL
            """)
            resting_map = {}  # agent_id → rest_type
            for r in cur.fetchall():
                resting_map[r["agent_id"]] = r["rest_type"]

            # --- Budget data ---
            cur.execute("""
                SELECT agent_id, current_task_count, task_queue_limit,
                       tokens_used_today, token_limit_per_day
                FROM agent_budgets
            """)
            budget_map = {}
            for r in cur.fetchall():
                budget_map[r["agent_id"]] = {
                    "current_task_count": r["current_task_count"] or 0,
                    "task_queue_limit": r["task_queue_limit"] or 10,
                    "tokens_used_today": r["tokens_used_today"] or 0,
                    "token_limit_per_day": r["token_limit_per_day"] or 100000,
                }

            # Busy agents (running bridge_jobs)
            cur.execute("""
                SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'
            """)
            self._busy_agents = {r["agent_name"] for r in cur.fetchall()}

            cur.close()
            conn.close()

            # Merge into unified welfare cache
            # Collect all agent IDs from any of the three sources
            all_ids = (
                set(emotional_map.keys())
                | set(resting_map.keys())
                | set(budget_map.keys())
            )
            welfare = {}
            for aid in all_ids:
                emo = emotional_map.get(
                    aid, {"stress": 0.0, "energy": 0.8, "mood": "neutral"}
                )
                welfare[aid] = {
                    "stress": emo["stress"],
                    "energy": emo["energy"],
                    "mood": emo["mood"],
                    "resting": aid in resting_map,
                    "rest_type": resting_map.get(aid),
                    "budget": budget_map.get(
                        aid,
                        {
                            "current_task_count": 0,
                            "task_queue_limit": 10,
                            "tokens_used_today": 0,
                            "token_limit_per_day": 100000,
                        },
                    ),
                }

            self._welfare_cache = welfare
            self._welfare_cache_time = now
            logger.debug(
                f"[BridgeDispatcher] Welfare cache refreshed: {len(welfare)} agents"
            )
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Welfare cache refresh failed: {e}")

    def _score_agent(
        self,
        agent_name: str,
        agent_info: Dict,
        capability: str,
        station_code: str,
    ) -> tuple:
        """Score an agent for a given capability and station.

        Returns:
            (score, block_reason_or_None) — score is 0.0 if hard-blocked.
        """
        agent_id = agent_info.get("id")
        welfare = self._welfare_cache.get(agent_id, {})
        budget = welfare.get("budget", {})

        # ------------------------------------------------------------------
        # Hard blocks (score = 0, agent cannot be selected)
        # ------------------------------------------------------------------
        if welfare.get("resting"):
            return (
                0.0,
                f"{agent_name} is resting ({welfare.get('rest_type', 'unknown')})",
            )

        task_count = budget.get("current_task_count", 0)
        task_limit = budget.get("task_queue_limit", 10)
        if task_limit > 0 and task_count >= task_limit:
            return (
                0.0,
                f"{agent_name} budget exhausted ({task_count}/{task_limit} tasks)",
            )

        stress = welfare.get("stress", 0.0)
        energy = welfare.get("energy", 0.8)
        if stress >= 0.9 and energy <= 0.15:
            return (
                0.0,
                f"{agent_name} critical welfare (stress={stress}, energy={energy})",
            )

        # ------------------------------------------------------------------
        # Skills score
        # ------------------------------------------------------------------
        skill_entry = agent_info.get("skills", {}).get(capability, {})
        if skill_entry:
            skills_score = skill_entry.get("level", 1) / 5.0
        elif capability in CAPABILITY_REQUIRES_SKILL:
            # Capability requires explicit skill — don't use generous default.
            # Forces cross-station dispatch to an agent who actually has it.
            return (0.0, f"{agent_name} lacks required skill '{capability}'")
        else:
            skills_score = 0.3  # generous default — agent may still handle it

        # ------------------------------------------------------------------
        # Specialization score
        # ------------------------------------------------------------------
        station_specs = AGENT_SPECIALIZATION.get(station_code, {})
        preferred = station_specs.get(capability, station_specs.get("default"))
        specialization_score = 1.0 if agent_name == preferred else 0.0

        # ------------------------------------------------------------------
        # Welfare score — healthier agents score higher
        # ------------------------------------------------------------------
        welfare_score = (1.0 - stress) * energy

        # ------------------------------------------------------------------
        # Hard block: agent already has a running bridge_job
        # ------------------------------------------------------------------
        is_busy = agent_name in getattr(self, "_busy_agents", set())
        if is_busy:
            return (
                0.0,
                f"{agent_name} already has a running job (finish first)",
            )
        availability_score = 1.0

        # ------------------------------------------------------------------
        # Budget score — agents with more headroom preferred
        # ------------------------------------------------------------------
        if task_limit == 0:
            budget_score = 1.0
        else:
            budget_score = max(1.0 - (task_count / task_limit), 0.0)

        # ------------------------------------------------------------------
        # Composite weighted score
        # ------------------------------------------------------------------
        composite = (
            SELECTION_WEIGHTS["skills"] * skills_score
            + SELECTION_WEIGHTS["specialization"] * specialization_score
            + SELECTION_WEIGHTS["welfare"] * welfare_score
            + SELECTION_WEIGHTS["availability"] * availability_score
            + SELECTION_WEIGHTS["budget"] * budget_score
        )

        return (round(composite, 4), None)

    def _resolve_module_station(self, module_id: str) -> Optional[str]:
        """Look up the home station for a module from bridge_stations.modules."""
        now = time.time()
        if now - self._module_station_ts > 300:
            try:
                conn = self._get_db()
                cur = conn.cursor()
                cur.execute(
                    "SELECT station_code, modules FROM bridge_stations WHERE is_active = true"
                )
                cache = {}
                for row in cur.fetchall():
                    code = row[0]
                    for m in (row[1] or []):
                        cache[m.lower().strip()] = code
                cur.close()
                conn.close()
                self._module_station_cache = cache
                self._module_station_ts = now
            except Exception as e:
                logger.debug(f"[BridgeDispatcher] Module station cache failed: {e}")
        return self._module_station_cache.get(module_id.lower().strip())

    def _select_agent(self, capability: str, station_code: str) -> Optional[Dict]:
        """Select the best agent for a capability within a station.

        Uses multi-factor scoring: skills, specialization, welfare,
        availability, and budget headroom.  Hard-blocked agents (resting,
        budget exhausted, critical welfare) are filtered out.
        """
        self._refresh_agent_cache()
        self._refresh_welfare_cache()

        # Gather all candidates assigned to this station
        candidates = []
        for name, info in self._agent_cache.items():
            if info.get("station_code") == station_code:
                candidates.append((name, info))

        if not candidates:
            logger.warning(
                f"[BridgeDispatcher] No agents at station={station_code} "
                f"for capability='{capability}'"
            )
            return None

        # Score each candidate
        scored = []
        blocked = []
        for name, info in candidates:
            score, block_reason = self._score_agent(
                name, info, capability, station_code
            )
            if score > 0:
                scored.append((score, name, info))
            else:
                blocked.append((name, block_reason))

        if not scored:
            reasons = "; ".join(f"{n}: {r}" for n, r in blocked)
            logger.warning(
                f"[BridgeDispatcher] All {len(blocked)} agent(s) blocked for "
                f"capability='{capability}' station='{station_code}': {reasons}"
            )
            return None

        # Sort descending by score, pick the best
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_name, best_info = scored[0]

        logger.info(
            f"[BridgeDispatcher] Selected {best_name} (score={best_score}) for "
            f"capability='{capability}' station='{station_code}' "
            f"({len(scored)} eligible, {len(blocked)} blocked)"
        )

        return best_info

    def _execute_llm(
        self,
        model: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        prefer_gpu: bool = True,
        temperature: float = 0.5,
        timeout: int = 300,
    ) -> Dict:
        """Execute an LLM call using the existing archie_bridge functions."""
        try:
            from archie_bridge import call_ollama, call_ollama_json, call_ollama_cloud

            # Route to external providers — dynamic lookup from contractor_providers DB
            from external_providers import (
                get_provider_for_model,
                call_external,
                _get_provider_config,
            )

            ext_provider_key = get_provider_for_model(model)
            if ext_provider_key:
                ext_config = _get_provider_config(ext_provider_key)
                if ext_config and ext_config.get("is_cloud_proxy"):
                    return call_ollama_cloud(
                        prompt, model=model, system_prompt=system_prompt
                    )
                if ext_config:
                    return call_external(
                        ext_provider_key,
                        prompt,
                        model=model,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        timeout=timeout,
                    )

            # Route cloud models (fallback for :cloud suffix convention)
            if ":cloud" in model:
                return call_ollama_cloud(
                    prompt, model=model, system_prompt=system_prompt
                )

            # JSON mode
            if json_mode:
                result = call_ollama_json(
                    prompt, model=model, system_prompt=system_prompt, timeout=timeout
                )
                if result.get("success") and result.get("data"):
                    return {
                        "success": True,
                        "response": json.dumps(result["data"]),
                        "model": model,
                        "provider": "ollama",
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                    }
                return {
                    "success": False,
                    "error": result.get("error", "JSON parse failed"),
                    "response": result.get("raw", ""),
                    "model": model,
                    "provider": "ollama",
                }

            # Standard call
            return call_ollama(
                prompt, model=model, system_prompt=system_prompt, prefer_gpu=prefer_gpu
            )
        except ImportError:
            logger.error("[BridgeDispatcher] archie_bridge not available")
            return {
                "success": False,
                "error": "archie_bridge not available",
                "model": model,
            }

    def _log_execution(
        self,
        result: DispatchResult,
        module_id: str,
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ):
        """Log execution to task_execution_log for HR tracking."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO task_execution_log (
                    agent_id, agent_name, module_source, task_type, capability,
                    model_used, provider, prompt_tokens, completion_tokens,
                    tokens_used, duration_ms, success, error_message,
                    station_code, requested_by, priority, request_metadata, job_id
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    result.agent_id,
                    result.agent_name,
                    module_id,
                    result.capability,  # task_type = capability
                    result.capability,
                    result.model_used,
                    result.provider,
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.prompt_tokens + result.completion_tokens,
                    result.duration_ms,
                    result.success,
                    result.error,
                    result.station_code,
                    user_id,
                    "normal",
                    json.dumps(result.metadata or {}),
                    job_id,
                ),
            )
            # Also update agent-level performance summary
            if result.agent_id:
                cur.execute(
                    """
                    UPDATE agents SET
                        total_tasks_completed = total_tasks_completed + CASE WHEN %s THEN 1 ELSE 0 END,
                        success_rate = (
                            SELECT ROUND(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 2)
                            FROM task_execution_log WHERE agent_id = %s
                        ),
                        performance_score = (
                            SELECT ROUND(
                                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) * 60 +
                                LEAST(COUNT(*)::numeric / 100, 1.0) * 25 +
                                CASE WHEN AVG(duration_ms) < 30000 THEN 15
                                     WHEN AVG(duration_ms) < 60000 THEN 10
                                     ELSE 5 END,
                                2
                            )
                            FROM task_execution_log WHERE agent_id = %s
                        )
                    WHERE id = %s
                    """,
                    (
                        result.success,
                        result.agent_id,
                        result.agent_id,
                        result.agent_id,
                    ),
                )

            conn.commit()
            cur.close()
            conn.close()
            # After logging, update agent emotional state based on recent performance
            self._update_agent_welfare(result.agent_id, result.success)
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Failed to log execution: {e}")

    def _update_agent_welfare(self, agent_id: Optional[int], success: bool):
        """Update agent emotional state after each dispatch using 1-hour rolling window."""
        if not agent_id:
            return
        try:
            conn = self._get_db()
            cur = conn.cursor()
            # Get 1-hour rolling window stats
            cur.execute(
                """
                SELECT COUNT(*) as total,
                       COUNT(*) FILTER (WHERE success = false) as failures
                FROM task_execution_log
                WHERE agent_id = %s
                  AND created_at >= NOW() - INTERVAL '1 hour'
                """,
                (agent_id,),
            )
            row = cur.fetchone()
            total = row[0] if row else 0
            failures = row[1] if row else 0

            if total == 0:
                cur.close()
                conn.close()
                return

            utilization = min(total / 20.0, 1.0)
            error_rate = (failures / total) * 100 if total > 0 else 0
            stress = min(utilization, 1.0)
            energy = max(1.0 - stress * 0.5 - error_rate / 200, 0.1)

            mood = "focused"
            if stress >= 0.85:
                mood = "overwhelmed"
            elif stress >= 0.6:
                mood = "busy"
            elif energy <= 0.3:
                mood = "fatigued"

            cur.execute(
                """
                UPDATE agent_emotional_state
                SET stress_level = %s, energy_level = %s,
                    current_mood = %s, timestamp = NOW()
                WHERE agent_id = %s
                """,
                (round(stress, 3), round(energy, 3), mood, agent_id),
            )
            conn.commit()
            cur.close()
            conn.close()
            # Invalidate welfare cache so next dispatch sees fresh state
            self._welfare_cache_time = 0
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Welfare update skipped: {e}")

    def _get_escalation_threshold(self) -> int:
        """Read escalation threshold from platform_settings."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = 'escalation_threshold'"
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return int(row[0]) if row else 3
        except Exception:
            return 3

    def _agent_display(self, agent_name: str) -> str:
        """Get human-friendly display string for an agent.

        Returns 'FirstName LastName, Title' or display_name or code name.
        """
        info = self._agent_cache.get(agent_name, {})
        display = info.get("display_name", "")
        if display:
            title = info.get("title", "")
            return f"{display}, {title}" if title else display
        first = info.get("first_name", "")
        last = info.get("last_name", "")
        name = f"{first} {last}".strip()
        if name:
            title = info.get("title", "")
            return f"{name}, {title}" if title else name
        return agent_name

    def _get_routing_mode(self) -> str:
        """Read routing_mode from platform_settings. Returns 'full' on error."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = 'routing_mode'"
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0] if row else "full"
        except Exception:
            return "full"

    def _get_escalation_mode(self) -> str:
        """Read escalation_mode from platform_settings.

        Returns one of: 'auto', 'ask_first', 'local_only'.
        - auto: auto-escalate to free cloud, Telegram FYI
        - ask_first: request Telegram approval before any cloud escalation
        - local_only: never escalate, always use local LLM (queue/wait)
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = 'escalation_mode'"
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0] if row else "auto"
        except Exception:
            return "auto"

    # Cloud contractor models (free via OLLAMA_API_KEY)
    FREE_CLOUD_MODELS = [
        "minimax-m2.5:cloud",
        "qwen3-coder-next:cloud",
    ]

    def _check_agent_busy(
        self, agent_name: str, exclude_job_id: int = None
    ) -> Optional[Dict]:
        """Check if agent has a running bridge_job. Returns job dict or None.

        Args:
            agent_name: Agent to check.
            exclude_job_id: If provided, ignore this job (the caller's own job).
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            if exclude_job_id:
                cur.execute(
                    """
                    SELECT id, description, total_steps, completed_steps
                    FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'running' AND id != %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (agent_name, exclude_job_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, description, total_steps, completed_steps
                    FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'running'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (agent_name,),
                )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                total = row[2] or 1
                completed = row[3] or 0
                pct = round((completed / total) * 100, 1)
                return {
                    "id": row[0],
                    "description": row[1],
                    "progress_pct": pct,
                }
            return None
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _check_agent_busy failed: {e}")
            return None

    def _try_cloud_escalation(
        self,
        agent_name: str,
        busy_job: Dict,
        capability: str,
        prompt: str,
        module_id: str,
        system_prompt: Optional[str],
        json_mode: bool,
        timeout: int,
        routing_mode: str,
        station_code: str,
        user_id: Optional[int],
        job_id: Optional[int],
    ) -> Optional[DispatchResult]:
        """
        Attempt throughput escalation when primary agent is busy.

        Behavior depends on escalation_mode platform setting:
        - auto: try free cloud (auto-approve), then paid cloud via Telegram
        - ask_first: request Telegram approval before ANY cloud escalation
        - local_only: never escalate, always queue for local LLM

        Returns DispatchResult on success, None if escalation not possible.
        """
        if routing_mode == "local_only":
            return None  # Cannot escalate

        escalation_mode = self._get_escalation_mode()

        if escalation_mode == "local_only":
            logger.info(
                f"[BridgeDispatcher] Escalation blocked: escalation_mode=local_only. "
                f"{agent_name} busy ({busy_job['description']}), queuing for local."
            )
            return None  # Never escalate — queue for local

        if escalation_mode == "ask_first":
            # Request Telegram approval before any cloud escalation (including free)
            logger.info(
                f"[BridgeDispatcher] Escalation ask_first: {agent_name} busy "
                f"({busy_job['description']}, {busy_job['progress_pct']}%). "
                f"Requesting Telegram approval for cloud escalation."
            )
            try:
                from agent_loop import request_approval

                cloud_model = (
                    self.FREE_CLOUD_MODELS[0] if self.FREE_CLOUD_MODELS else "unknown"
                )
                request_approval(
                    action_type="cloud_throughput_escalation",
                    action_data={
                        "original_agent": agent_name,
                        "busy_job": busy_job,
                        "escalated_model": cloud_model,
                        "escalated_provider": "ollama_cloud",
                        "capability": capability,
                        "module_id": module_id,
                        "prompt_preview": prompt[:200],
                        "escalation_mode": "ask_first",
                    },
                    reason=(
                        f"{agent_name} busy ({busy_job['description']}, "
                        f"{busy_job['progress_pct']}%). "
                        f"Escalate to {cloud_model}? Or queue for local."
                    ),
                    requested_by="bridge_dispatcher",
                    tier=2,
                )
                self._log_escalation(
                    original_agent_id=None,
                    original_model=agent_name,
                    escalated_model=cloud_model,
                    escalated_provider="ollama_cloud",
                    capability=capability,
                    module_id=module_id,
                    reason=f"Throughput: awaiting cloud approval (ask_first)",
                    failure_count=0,
                    approval_method="telegram",
                    success=None,
                )
            except Exception as esc_err:
                logger.warning(
                    f"[BridgeDispatcher] ask_first approval request failed: {esc_err}"
                )
            return None  # Caller proceeds with local (busy) agent

        start = time.time()

        # --- Try free cloud contractors ---
        for cloud_model in self.FREE_CLOUD_MODELS:
            logger.info(
                f"[BridgeDispatcher] Throughput escalation: {agent_name} busy "
                f"({busy_job['description']}, {busy_job['progress_pct']}%). "
                f"Trying free cloud: {cloud_model}"
            )
            # Create visible bridge_job for 3D bridge view
            cloud_job_id = self._create_cloud_job(
                cloud_model, "ollama_cloud", station_code, capability, module_id
            )
            llm_result = self._execute_llm(
                model=cloud_model,
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=json_mode,
                timeout=timeout,
            )
            if llm_result.get("success"):
                self._complete_cloud_job(cloud_job_id, success=True)
                duration_ms = int((time.time() - start) * 1000)
                self._log_escalation(
                    original_agent_id=None,
                    original_model=agent_name,
                    escalated_model=cloud_model,
                    escalated_provider="ollama_cloud",
                    capability=capability,
                    module_id=module_id,
                    reason=f"Throughput: {agent_name} busy ({busy_job['description']})",
                    failure_count=0,
                    approval_method="auto",
                    success=True,
                )
                # Telegram FYI: notify that free cloud was used
                self._telegram_dispatch_advisory(
                    advisory_type="free_cloud",
                    module_id=module_id,
                    capability=capability,
                    home_station=self._resolve_module_station(module_id),
                    cloud_model=cloud_model,
                    cloud_provider="ollama_cloud",
                    reason=f"{agent_name} busy with job #{busy_job.get('id', '?')}",
                )

                result = DispatchResult(
                    success=True,
                    response=llm_result.get("response", ""),
                    agent_name=f"{agent_name}→{cloud_model}",
                    agent_id=None,
                    model_used=cloud_model,
                    station_code=station_code,
                    capability=capability,
                    duration_ms=duration_ms,
                    prompt_tokens=llm_result.get("prompt_tokens", 0),
                    completion_tokens=llm_result.get("completion_tokens", 0),
                    provider="ollama_cloud",
                    metadata={
                        "escalation": "throughput_free_cloud",
                        "original_agent": agent_name,
                        "is_cloud": True,
                        "cloud_model": cloud_model,
                        "cloud_provider": "ollama_cloud",
                    },
                )
                self._log_execution(result, module_id, user_id, job_id=job_id)
                return result
            else:
                self._complete_cloud_job(cloud_job_id, success=False)

        # --- Free cloud unavailable; request paid cloud via Telegram ---
        if routing_mode == "local_cloud":
            return None  # Cannot use paid

        logger.info(
            f"[BridgeDispatcher] Free cloud unavailable. "
            f"Requesting paid cloud approval for capability='{capability}'"
        )
        try:
            from agent_loop import request_approval

            next_tier = self._get_next_tier(self.FREE_CLOUD_MODELS[-1], capability)
            if next_tier and next_tier["is_paid"]:
                display = self._agent_display(agent_name)

                request_approval(
                    action_type="cloud_throughput_escalation",
                    action_data={
                        "original_agent": display,
                        "busy_job": busy_job,
                        "escalated_model": next_tier["model"],
                        "escalated_provider": next_tier["provider"],
                        "capability": capability,
                        "module_id": module_id,
                        "prompt_preview": prompt[:200],
                    },
                    reason=(
                        f"{display} busy ({busy_job['description']}, "
                        f"{busy_job['progress_pct']}%). Free cloud failed. "
                        f"Escalate to {next_tier['model']}?"
                    ),
                    requested_by="bridge_dispatcher",
                    tier=2,
                )
                self._log_escalation(
                    original_agent_id=None,
                    original_model=agent_name,
                    escalated_model=next_tier["model"],
                    escalated_provider=next_tier["provider"],
                    capability=capability,
                    module_id=module_id,
                    reason=f"Throughput: awaiting paid cloud approval",
                    failure_count=0,
                    approval_method="telegram",
                    success=None,
                )
                # Dashboard notification for paid cloud approval
                self._telegram_dispatch_advisory(
                    advisory_type="paid_cloud",
                    module_id=module_id,
                    capability=capability,
                    home_station=self._resolve_module_station(module_id),
                    cloud_model=next_tier["model"],
                    cloud_provider=next_tier.get("provider", "external"),
                )
        except Exception as esc_err:
            logger.warning(
                f"[BridgeDispatcher] Throughput approval request failed: {esc_err}"
            )

        return None  # Caller proceeds with original (busy) agent

    def _notify_throughput_escalation(
        self,
        agent_name: str,
        cloud_model: str,
        capability: str,
        module_id: str,
        busy_job: Dict,
        duration_ms: int,
    ):
        """Insert an agent_alert so Telegram notifier sends an FYI."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_alerts
                    (agent_id, alert_type, severity, title, message, details)
                VALUES (
                    (SELECT id FROM agents WHERE name = %s LIMIT 1),
                    'throughput_escalation', 'warning',
                    %s, %s, %s
                )
                """,
                (
                    agent_name,
                    f"Cloud escalation: {agent_name} → {cloud_model}",
                    (
                        f"{agent_name} is busy with \"{busy_job.get('description', '?')}\" "
                        f"({busy_job.get('progress_pct', 0)}%). "
                        f"Dispatched {capability} to {cloud_model} (free cloud). "
                        f"Module: {module_id} | Duration: {duration_ms}ms"
                    ),
                    json.dumps(
                        {
                            "original_agent": agent_name,
                            "cloud_model": cloud_model,
                            "capability": capability,
                            "module_id": module_id,
                            "busy_job": busy_job,
                            "duration_ms": duration_ms,
                        }
                    ),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(
                f"[BridgeDispatcher] _notify_throughput_escalation failed: {e}"
            )

    def _track_failure(self, agent_id: int, capability: str) -> int:
        """Increment failure count, return new count."""
        key = (agent_id, capability)
        self._failure_tracker[key] = self._failure_tracker.get(key, 0) + 1
        return self._failure_tracker[key]

    def _reset_failure(self, agent_id: int, capability: str):
        """Reset failure count on success."""
        self._failure_tracker.pop((agent_id, capability), None)

    def _get_next_tier(self, current_model: str, capability: str) -> Optional[Dict]:
        """Find the next escalation tier above current model."""
        try:
            from smart_router import SmartRouter, TIER_ORDER

            router = SmartRouter()
            available = router.get_available_tiers()
            configs = router._get_model_configs()

            current_tier = None
            for tier_name, config in configs.items():
                if config.model_name == current_model or current_model.startswith(
                    config.model_name.split(":")[0]
                ):
                    current_tier = tier_name
                    break

            if not current_tier:
                return None

            found_current = False
            for tier in available:
                if tier == current_tier:
                    found_current = True
                    continue
                if found_current and tier in configs:
                    config = configs[tier]
                    is_paid = tier in (
                        "haiku",
                        "sonnet",
                        "opus",
                    ) or config.provider not in ("ollama", "ollama_cloud")
                    return {
                        "tier": tier,
                        "model": config.model_name,
                        "provider": config.provider,
                        "is_paid": is_paid,
                    }
            return None
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] get_next_tier failed: {e}")
            return None

    def _log_escalation(
        self,
        original_agent_id,
        original_model,
        escalated_model,
        escalated_provider,
        capability,
        module_id,
        reason,
        failure_count,
        approval_method="auto",
        success=None,
        cost=0,
    ):
        """Log an escalation event to dispatch_escalation_log."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO dispatch_escalation_log
                (original_agent_id, original_model, escalated_model, escalated_provider,
                 capability, module_id, reason, failure_count, cost_usd,
                 approved_by, approval_method, success)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    original_agent_id,
                    original_model,
                    escalated_model,
                    escalated_provider,
                    capability,
                    module_id,
                    reason,
                    failure_count,
                    cost,
                    "system" if approval_method == "auto" else None,
                    approval_method,
                    success,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Failed to log escalation: {e}")

    # ========================================================================
    # CLOUD JOB VISIBILITY (temp bridge_jobs for 3D bridge view)
    # ========================================================================

    def _create_cloud_job(
        self, cloud_model, cloud_provider, station_code, capability, module_id
    ):
        """Create a temporary bridge_job so cloud dispatches appear on the isometric bridge."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES ('cloud_dispatch', %s, %s, 1, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    module_id,
                    f"Cloud {capability}",
                    f"CLOUD→{cloud_model}",
                    station_code,
                    json.dumps(
                        {
                            "dispatch_station": "CLOUD",
                            "cloud_model": cloud_model,
                            "cloud_provider": cloud_provider,
                            "is_cloud": True,
                            "home_station": station_code,
                        }
                    ),
                ),
            )
            job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            return job_id
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Cloud job creation failed: {e}")
            return None

    def _complete_cloud_job(self, cloud_job_id, success=True):
        """Mark a temporary cloud job as completed/failed."""
        if not cloud_job_id:
            return
        try:
            conn = self._get_db()
            cur = conn.cursor()
            status = "completed" if success else "failed"
            cur.execute(
                "UPDATE bridge_jobs SET status=%s, completed_steps=total_steps, "
                "completed_at=NOW() WHERE id=%s",
                (status, cloud_job_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Cloud job completion failed: {e}")

    # ========================================================================
    # BUDGET TRACKING
    # ========================================================================

    def _increment_agent_budget(self, agent_id: Optional[int], tokens_used: int = 0):
        """Increment agent's daily task count and token usage after successful dispatch."""
        if not agent_id:
            return
        try:
            conn = self._get_db()
            cur = conn.cursor()
            # Reset if past the daily reset time, then increment
            cur.execute("""
                UPDATE agent_budgets
                SET current_task_count = 1, tokens_used_today = %s,
                    token_reset_at = NOW() + INTERVAL '1 day', updated_at = NOW()
                WHERE agent_id = %s AND token_reset_at < NOW()
            """, (tokens_used, agent_id))
            if cur.rowcount == 0:
                # No reset needed — normal increment (or INSERT if row missing)
                cur.execute("""
                    INSERT INTO agent_budgets (agent_id, current_task_count, tokens_used_today,
                        task_queue_limit, token_limit_per_day, token_reset_at, updated_at)
                    VALUES (%s, 1, %s, 10, 100000, NOW() + INTERVAL '1 day', NOW())
                    ON CONFLICT (agent_id) DO UPDATE SET
                        current_task_count = agent_budgets.current_task_count + 1,
                        tokens_used_today = agent_budgets.tokens_used_today + %s,
                        updated_at = NOW()
                """, (agent_id, tokens_used, tokens_used))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Budget increment skipped: {e}")

    # ========================================================================
    # DYNAMIC AGENT CREATION
    # ========================================================================

    # Suggested model defaults by station (use local free models)
    _STATION_DEFAULT_MODEL = {
        "COMMAND": "dolphin3-8k:latest",
        "ANALYTICS": "qwen25-classify:latest",
        "ENGINEERING": "qwen3-coder-cpu:latest",
        "OPERATIONS": "dolphin3-8k:latest",
        "CREATIVE": "dolphin3-8k:latest",
        "RESEARCH": "qwen3-coder-cpu:latest",
    }

    def _check_creation_duplicates(
        self, capability: str, station_code: str
    ) -> Optional[str]:
        """Check for duplicate pending creation requests or recent creations.

        Returns a reason string if a duplicate is found, None if safe to create.
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check autonomy_approval_queue for pending create_agent requests
            # with matching capability + station in action_data
            cur.execute(
                """
                SELECT id, reason, created_at
                FROM autonomy_approval_queue
                WHERE action_type = 'create_agent'
                  AND status = 'pending'
                  AND action_data->>'capability' = %s
                  AND action_data->>'station_code' = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (capability, station_code),
            )
            pending = cur.fetchone()
            if pending:
                cur.close()
                conn.close()
                return (
                    f"Pending creation request #{pending['id']} already exists "
                    f"for capability='{capability}' station='{station_code}' "
                    f"(created {pending['created_at']})"
                )

            # Check agent_creation_events for recent (24h) creations
            # with same capability + station
            cur.execute(
                """
                SELECT id, child_agent_id, created_at
                FROM agent_creation_events
                WHERE station_requested = %s
                  AND capabilities_requested ? %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (station_code, capability),
            )
            recent = cur.fetchone()
            cur.close()
            conn.close()

            if recent:
                return (
                    f"Agent (id={recent['child_agent_id']}) was already created "
                    f"for capability='{capability}' station='{station_code}' "
                    f"within the last 24h (event #{recent['id']}, "
                    f"created {recent['created_at']})"
                )

            return None  # Safe to create
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _check_creation_duplicates failed: {e}")
            return None  # Fail open — allow creation attempt

    def _request_agent_creation(
        self, capability: str, station_code: str, reason: str
    ) -> bool:
        """Request dynamic agent creation via Telegram approval.

        Checks for duplicates first, then submits a tier-2 approval request.

        Returns True if request was submitted, False if blocked by dedup.
        """
        # Dedup check
        dup_reason = self._check_creation_duplicates(capability, station_code)
        if dup_reason:
            logger.info(
                f"[BridgeDispatcher] Agent creation blocked (duplicate): {dup_reason}"
            )
            return False

        # Safety rails: max sub-agents and generation depth
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM agents WHERE parent_agent_id = 2")
            sub_count = cur.fetchone()[0]
            cur.execute(
                "SELECT max_sub_agents FROM agent_budgets WHERE agent_id = 2"
            )
            row = cur.fetchone()
            max_subs = row[0] if row else 20
            cur.close()
            conn.close()
            if sub_count >= max_subs:
                logger.warning(
                    f"[BridgeDispatcher] Max sub-agents reached ({sub_count}/{max_subs}), "
                    f"cannot create agent for {capability}"
                )
                return False
        except Exception as rail_err:
            logger.debug(f"[BridgeDispatcher] Safety rail check error: {rail_err}")

        # Build suggested agent profile
        suggested_model = self._STATION_DEFAULT_MODEL.get(
            station_code, "dolphin3-8k:latest"
        )
        suggested_name = (
            f"Auto-{station_code.capitalize()}-{capability.replace('_', '-').title()}"
        )

        action_data = {
            "capability": capability,
            "station_code": station_code,
            "suggested_name": suggested_name,
            "suggested_model": suggested_model,
            "suggested_skills": [capability],
            "reason": reason,
        }

        try:
            from agent_loop import request_approval

            approval_id = request_approval(
                action_type="create_agent",
                action_data=action_data,
                reason=(
                    f"Skill gap: no available agent for capability='{capability}' "
                    f"at station='{station_code}'. {reason}. "
                    f"Suggested: {suggested_name} ({suggested_model})"
                ),
                requested_by="bridge_dispatcher",
                tier=2,
            )
            if approval_id:
                logger.info(
                    f"[BridgeDispatcher] Agent creation request #{approval_id} "
                    f"submitted for capability='{capability}' "
                    f"station='{station_code}'"
                )
                return True
            else:
                logger.warning(
                    "[BridgeDispatcher] request_approval returned None for "
                    f"create_agent capability='{capability}'"
                )
                return False
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _request_agent_creation failed: {e}")
            return False

    def _create_agent_from_approval(self, approval_data: Dict) -> Optional[int]:
        """Create a new agent from an approved creation request.

        Inserts into: agents, agent_skills, agent_budgets,
        agent_emotional_state, station_assignments, agent_creation_events,
        governance_audit_log.

        Args:
            approval_data: The action_data dict from the approval queue entry.

        Returns:
            New agent_id on success, None on failure.
        """
        _STATION_DEPARTMENT = {
            "COMMAND": "Command",
            "ANALYTICS": "Analytics",
            "ENGINEERING": "Engineering",
            "OPERATIONS": "Operations",
            "CREATIVE": "Creative",
            "RESEARCH": "Research",
        }

        capability = approval_data.get("capability", "general")
        station_code = approval_data.get("station_code", "COMMAND")
        suggested_name = approval_data.get("suggested_name", f"Auto-{capability}")
        suggested_model = approval_data.get(
            "suggested_model",
            self._STATION_DEFAULT_MODEL.get(station_code, "dolphin3-8k:latest"),
        )
        suggested_skills = approval_data.get("suggested_skills", [capability])
        reason = approval_data.get("reason", "Dynamic creation via dispatcher")

        # Parse name for first_name / last_name
        parts = suggested_name.split("-", 1)
        first_name = parts[0] if parts else suggested_name
        last_name = parts[1] if len(parts) > 1 else ""
        department = _STATION_DEPARTMENT.get(station_code, station_code)

        try:
            conn = self._get_db()
            cur = conn.cursor()

            # 1. INSERT into agents
            cur.execute(
                """
                INSERT INTO agents (
                    name, model, status, department, title,
                    first_name, last_name,
                    worker_type, cost_tier, agent_generation,
                    parent_agent_id, created_by_agent_id,
                    system_prompt, temperature, max_tokens
                ) VALUES (
                    %s, %s, 'active', %s, %s,
                    %s, %s,
                    'internal', 'free', 1,
                    2, 2,
                    %s, 0.5, 4096
                )
                RETURNING id
                """,
                (
                    suggested_name,
                    suggested_model,
                    department,
                    f"{capability.replace('_', ' ').title()} Specialist",
                    first_name,
                    last_name,
                    f"You are {suggested_name}, a specialist in {capability} "
                    f"at the {station_code} station.",
                ),
            )
            new_agent_id = cur.fetchone()[0]

            # 2. INSERT into agent_skills
            for skill in suggested_skills:
                cur.execute(
                    """
                    INSERT INTO agent_skills (
                        agent_id, skill_name, skill_category,
                        proficiency_level
                    ) VALUES (%s, %s, %s, 3)
                    ON CONFLICT (agent_id, skill_name) DO NOTHING
                    """,
                    (new_agent_id, skill, station_code.lower()),
                )

            # 3. INSERT into agent_budgets
            cur.execute(
                """
                INSERT INTO agent_budgets (
                    agent_id, token_limit_per_day, task_queue_limit,
                    can_create_sub_agents, max_sub_agents
                ) VALUES (%s, 100000, 10, FALSE, 0)
                ON CONFLICT (agent_id) DO NOTHING
                """,
                (new_agent_id,),
            )

            # 4. INSERT into agent_emotional_state
            cur.execute(
                """
                INSERT INTO agent_emotional_state (
                    agent_id, current_mood, energy_level, stress_level,
                    trigger_event
                ) VALUES (%s, 'neutral', 0.8, 0.1, 'initial_creation')
                """,
                (new_agent_id,),
            )

            # 5. INSERT into station_assignments
            cur.execute(
                """
                INSERT INTO station_assignments (
                    station_id, agent_id, assignment_type, priority, is_active
                ) VALUES (
                    (SELECT id FROM bridge_stations
                     WHERE station_code = %s LIMIT 1),
                    %s, 'primary', 50, TRUE
                )
                """,
                (station_code, new_agent_id),
            )

            # 6. INSERT into agent_creation_events
            cur.execute(
                """
                INSERT INTO agent_creation_events (
                    parent_agent_id, child_agent_id,
                    creation_reason, creation_source,
                    capabilities_requested, station_requested,
                    is_approved, approved_at
                ) VALUES (
                    2, %s,
                    %s, 'dispatcher',
                    %s, %s,
                    TRUE, NOW()
                )
                """,
                (
                    new_agent_id,
                    reason,
                    json.dumps(suggested_skills),
                    station_code,
                ),
            )

            # 7. INSERT into governance_audit_log
            cur.execute(
                """
                INSERT INTO governance_audit_log (
                    event_type, event_category, agent_id, action,
                    new_value, reason, outcome
                ) VALUES (
                    'agent_created', 'autonomy', %s, 'create',
                    %s, %s, 'success'
                )
                """,
                (
                    new_agent_id,
                    json.dumps(
                        {
                            "name": suggested_name,
                            "model": suggested_model,
                            "station": station_code,
                            "capability": capability,
                            "skills": suggested_skills,
                        }
                    ),
                    reason,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            # Invalidate cache so the new agent gets picked up
            self._cache_time = 0

            logger.info(
                f"[BridgeDispatcher] Created agent #{new_agent_id} "
                f"'{suggested_name}' for capability='{capability}' "
                f"station='{station_code}'"
            )
            return new_agent_id

        except Exception as e:
            logger.error(f"[BridgeDispatcher] _create_agent_from_approval failed: {e}")
            try:
                conn.rollback()
                cur.close()
                conn.close()
            except Exception:
                pass
            return None

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    def request_work(
        self,
        capability: str,
        prompt: str,
        module_id: str = "unknown",
        system_prompt: Optional[str] = None,
        context: Optional[Dict] = None,
        user_id: Optional[int] = None,
        priority: str = "normal",
        json_mode: bool = False,
        timeout: int = 300,
        prefer_gpu: bool = True,
        job_id: Optional[int] = None,
    ) -> DispatchResult:
        """
        Main entry point — request AI work by capability.

        Args:
            capability: What kind of work (e.g., 'classify', 'code', 'summarize')
            prompt: The work prompt
            module_id: Which module is requesting (for tracking)
            system_prompt: Override the agent's default system prompt
            context: Additional context dict
            user_id: User requesting the work
            priority: 'low', 'normal', 'high', 'critical'
            json_mode: Request JSON-formatted response
            timeout: Request timeout in seconds
            prefer_gpu: Whether to prefer GPU-capable models

        Returns:
            DispatchResult with response, agent info, and metrics
        """
        start = time.time()

        # Force-refresh busy agents list (bypass 30s welfare cache TTL)
        try:
            from psycopg2.extras import RealDictCursor

            bconn = self._get_db()
            bcur = bconn.cursor(cursor_factory=RealDictCursor)
            bcur.execute(
                "SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'"
            )
            self._busy_agents = {r["agent_name"] for r in bcur.fetchall()}
            bcur.close()
            bconn.close()
        except Exception as busy_err:
            logger.debug(f"[BridgeDispatcher] Busy agents refresh failed: {busy_err}")

        # 1. Map capability → station (home-first strategy)
        capability_station = CAPABILITY_STATION_MAP.get(capability, "COMMAND")
        home_station = self._resolve_module_station(module_id)

        agent = None
        dispatch_station = capability_station
        is_cross_station = False

        if home_station:
            agent = self._select_agent(capability, home_station)
            if agent:
                dispatch_station = home_station
            else:
                # Home station can't handle — fall to capability station
                agent = self._select_agent(capability, capability_station)
                dispatch_station = capability_station
                is_cross_station = home_station != capability_station
        else:
            agent = self._select_agent(capability, capability_station)
            dispatch_station = capability_station

        station_code = dispatch_station

        # 2. Fallback if no agent found — try cross-station, then cloud
        station_exhausted = False
        if not agent:
            station_exhausted = True
            blocked_station = home_station or capability_station

            # 2a. Try agents from OTHER worker stations (cross-station dispatch)
            #     Skip COMMAND — ARCHIE is the commander, not a worker.
            #     Only pick agents that actually have the requested skill.
            all_stations = set(
                info.get("station_code")
                for info in self._agent_cache.values()
                if info.get("station_code")
            )
            tried_stations = {blocked_station, "COMMAND"}
            if home_station and capability_station and home_station != capability_station:
                tried_stations.add(capability_station)

            for other_station in sorted(all_stations - tried_stations):
                # Check each agent at this station for the actual skill
                for agent_name_candidate, info in self._agent_cache.items():
                    if info.get("station_code") != other_station:
                        continue
                    # Must have the skill explicitly (not the generous 0.3 default)
                    if capability not in (info.get("skills") or {}):
                        continue
                    # Score the agent normally (checks busy, welfare, budget)
                    score, block_reason = self._score_agent(
                        agent_name_candidate, info, capability, other_station
                    )
                    if score <= 0:
                        continue

                    # Found a skilled, available agent at another station
                    display = self._agent_display(agent_name_candidate)

                    logger.info(
                        f"[BridgeDispatcher] Cross-station fallback: "
                        f"{blocked_station} exhausted → {other_station} "
                        f"({display}) for '{capability}'"
                    )

                    self._telegram_dispatch_advisory(
                        advisory_type="cross_station",
                        module_id=module_id,
                        home_station=blocked_station,
                        dispatch_station=other_station,
                        capability=capability,
                        agent_name=display,
                        reason=(
                            f"All agents at {blocked_station} are busy. "
                            f"Asking {display} at {other_station} to help."
                        ),
                    )

                    agent = info
                    station_code = other_station
                    dispatch_station = other_station
                    is_cross_station = True
                    station_exhausted = False
                    break
                if agent:
                    break

        if not agent and station_exhausted:
            blocked_station = home_station or capability_station

            # 2b. No agent at any station — Telegram advisory before cloud
            self._telegram_dispatch_advisory(
                advisory_type="cross_station",
                module_id=module_id,
                home_station=blocked_station,
                dispatch_station="CLOUD",
                capability=capability,
                reason=(
                    f"All agents across all stations are at capacity "
                    f"for '{capability}'. Attempting free cloud contractor."
                ),
            )

            # 2c. Try free cloud contractors
            routing_mode = self._get_routing_mode()
            if routing_mode != "local_only":
                for cloud_model in self.FREE_CLOUD_MODELS:
                    logger.info(
                        f"[BridgeDispatcher] Station {blocked_station} exhausted "
                        f"for '{capability}'. Trying cloud: {cloud_model}"
                    )
                    # Create visible bridge_job for 3D bridge view
                    cloud_job_id = self._create_cloud_job(
                        cloud_model, "ollama_cloud", blocked_station, capability, module_id
                    )
                    llm_result = self._execute_llm(
                        model=cloud_model,
                        prompt=prompt,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        timeout=timeout,
                    )
                    if llm_result.get("success"):
                        self._complete_cloud_job(cloud_job_id, success=True)
                        duration_ms = int((time.time() - start) * 1000)
                        self._telegram_dispatch_advisory(
                            advisory_type="free_cloud",
                            module_id=module_id,
                            capability=capability,
                            home_station=blocked_station,
                            cloud_model=cloud_model,
                            cloud_provider="ollama_cloud",
                            reason=f"Station {blocked_station} at capacity",
                        )
                        result = DispatchResult(
                            success=True,
                            response=llm_result.get("response", ""),
                            agent_name=f"CLOUD→{cloud_model}",
                            agent_id=None,
                            model_used=cloud_model,
                            station_code=blocked_station,
                            capability=capability,
                            duration_ms=duration_ms,
                            prompt_tokens=llm_result.get("prompt_tokens", 0),
                            completion_tokens=llm_result.get("completion_tokens", 0),
                            provider="ollama_cloud",
                            metadata={
                                "escalation": "station_exhausted_cloud",
                                "blocked_station": blocked_station,
                                "home_station": home_station,
                                "dispatch_station": "CLOUD",
                                "is_cross_station": True,
                                "is_cloud": True,
                                "cloud_model": cloud_model,
                                "cloud_provider": "ollama_cloud",
                                "capability_station": capability_station,
                            },
                        )
                        self._log_execution(result, module_id, user_id, job_id=job_id)
                        return result
                    else:
                        self._complete_cloud_job(cloud_job_id, success=False)

            # 2d. Free cloud failed — request paid cloud via Telegram approval
            if routing_mode not in ("local_only", "local_cloud"):
                try:
                    from agent_loop import request_approval

                    next_tier = self._get_next_tier(
                        self.FREE_CLOUD_MODELS[-1], capability
                    )
                    if next_tier and next_tier.get("is_paid"):
                        logger.info(
                            f"[BridgeDispatcher] Free cloud failed. "
                            f"Requesting paid cloud: {next_tier['model']}"
                        )
                        # Build agent display names for the notification
                        busy_names = [
                            self._agent_display(aname)
                            for aname, ainfo in self._agent_cache.items()
                            if ainfo.get("station_code") == blocked_station
                        ]
                        busy_str = ", ".join(busy_names) or blocked_station

                        request_approval(
                            action_type="cloud_throughput_escalation",
                            action_data={
                                "original_agent": busy_str,
                                "busy_job": {
                                    "id": 0,
                                    "description": f"All agents at {blocked_station} busy",
                                    "progress_pct": 0,
                                },
                                "escalated_model": next_tier["model"],
                                "escalated_provider": next_tier["provider"],
                                "capability": capability,
                                "module_id": module_id,
                                "prompt_preview": prompt[:200],
                            },
                            reason=(
                                f"All agents at {blocked_station} busy, "
                                f"free cloud failed. "
                                f"Escalate to {next_tier['model']}?"
                            ),
                            requested_by="bridge_dispatcher",
                            tier=2,
                        )
                        self._telegram_dispatch_advisory(
                            advisory_type="paid_cloud",
                            module_id=module_id,
                            capability=capability,
                            home_station=blocked_station,
                            cloud_model=next_tier["model"],
                            cloud_provider=next_tier.get("provider", "external"),
                        )
                except Exception as esc_err:
                    logger.warning(
                        f"[BridgeDispatcher] Paid cloud request failed: {esc_err}"
                    )

            # Last resort: ARCHIE fallback
            try:
                self._request_agent_creation(
                    capability=capability,
                    station_code=blocked_station,
                    reason=(
                        f"No available agent for capability='{capability}' "
                        f"at station='{blocked_station}' "
                        f"(module={module_id})"
                    ),
                )
            except Exception as creation_err:
                logger.debug(
                    f"[BridgeDispatcher] Creation request skipped: {creation_err}"
                )

            logger.warning(
                f"[BridgeDispatcher] No agent for capability='{capability}' "
                f"station='{blocked_station}', cloud unavailable, falling back to COMMAND"
            )
            agent = self._agent_cache.get(
                "ARCHIE",
                {
                    "id": 2,
                    "model": "dolphin3-8k:latest",
                    "system_prompt": None,
                    "temperature": 0.5,
                    "station_code": "COMMAND",
                },
            )
            station_code = "COMMAND"
            dispatch_station = "COMMAND"

        # 3. Determine model and system prompt
        model = agent.get("model", "dolphin3-8k:latest")
        if not system_prompt:
            system_prompt = agent.get("system_prompt")
        temperature = agent.get("temperature", 0.5)

        agent_name = None
        for name, info in self._agent_cache.items():
            if info.get("id") == agent.get("id"):
                agent_name = name
                break
        if not agent_name:
            agent_name = "ARCHIE"

        logger.info(
            f"[BridgeDispatcher] Dispatching: capability='{capability}' → "
            f"agent='{agent_name}' model='{model}' station='{station_code}' "
            f"module='{module_id}'"
        )

        # 3a. Cross-station Telegram advisory
        if is_cross_station and home_station:
            self._telegram_dispatch_advisory(
                advisory_type="cross_station",
                module_id=module_id,
                home_station=home_station,
                dispatch_station=dispatch_station,
                capability=capability,
                agent_name=agent_name,
            )

        # 3b. Inject learnings if available
        try:
            from bridge_learning import inject_learnings

            prompt = inject_learnings(agent_name, capability, prompt)
        except ImportError:
            pass

        # 3c. Routing mode enforcement
        # Ensures the bridge UI toggle (local_only/local_cloud/full) controls dispatch
        routing_mode = self._get_routing_mode()
        is_cloud = ":cloud" in model or model in ("minimax-m2.5", "qwen3-coder-next")
        is_paid_external = any(
            model.startswith(p) for p in ("gpt-4o", "llama-3.1-sonar", "grok", "claude")
        )

        if routing_mode == "local_only" and (is_cloud or is_paid_external):
            logger.warning(
                f"[BridgeDispatcher] Blocked by routing_mode=local_only: "
                f"model='{model}' capability='{capability}' module='{module_id}'"
            )
            return DispatchResult(
                success=False,
                response="",
                agent_name=agent_name,
                agent_id=agent.get("id"),
                model_used=model,
                station_code=station_code,
                capability=capability,
                error=f"Blocked: routing_mode=local_only, model={model} is cloud/external",
            )

        if routing_mode == "local_cloud" and is_paid_external:
            logger.warning(
                f"[BridgeDispatcher] Blocked by routing_mode=local_cloud: "
                f"model='{model}' capability='{capability}' module='{module_id}'"
            )
            return DispatchResult(
                success=False,
                response="",
                agent_name=agent_name,
                agent_id=agent.get("id"),
                model_used=model,
                station_code=station_code,
                capability=capability,
                error=f"Blocked: routing_mode=local_cloud, model={model} is paid external",
            )

        # 3d. Throughput escalation — if agent is busy, try cloud contractors
        # Exclude the caller's own job_id so a batch operation doesn't
        # escalate its own sub-dispatches to cloud.
        busy_job = self._check_agent_busy(agent_name, exclude_job_id=job_id)
        if busy_job and routing_mode != "local_only":
            escalated = self._try_cloud_escalation(
                agent_name=agent_name,
                busy_job=busy_job,
                capability=capability,
                prompt=prompt,
                module_id=module_id,
                system_prompt=system_prompt,
                json_mode=json_mode,
                timeout=timeout,
                routing_mode=routing_mode,
                station_code=station_code,
                user_id=user_id,
                job_id=job_id,
            )
            if escalated:
                return escalated
            # Otherwise fall through to dispatch to original agent anyway

        # 4. Execute the LLM call
        llm_result = self._execute_llm(
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            json_mode=json_mode,
            prefer_gpu=prefer_gpu,
            temperature=temperature,
            timeout=timeout,
        )

        duration_ms = int((time.time() - start) * 1000)

        # 4b. Escalation on failure
        if not llm_result.get("success", False):
            failure_count = self._track_failure(agent.get("id", 0), capability)
            threshold = self._get_escalation_threshold()

            if failure_count >= threshold:
                next_tier = self._get_next_tier(model, capability)
                if next_tier and not next_tier["is_paid"]:
                    logger.info(
                        f"[BridgeDispatcher] Auto-escalating {capability}: "
                        f"{model} -> {next_tier['model']} (free, {failure_count} failures)"
                    )
                    escalated_result = self._execute_llm(
                        model=next_tier["model"],
                        prompt=prompt,
                        system_prompt=system_prompt,
                        json_mode=json_mode,
                        prefer_gpu=prefer_gpu,
                        timeout=timeout,
                    )
                    if escalated_result.get("success"):
                        self._reset_failure(agent.get("id", 0), capability)
                        self._log_escalation(
                            agent.get("id"),
                            model,
                            next_tier["model"],
                            next_tier["provider"],
                            capability,
                            module_id,
                            f"{failure_count} consecutive failures",
                            failure_count,
                            approval_method="auto",
                            success=True,
                        )
                        try:
                            from bridge_learning import capture_learning

                            capture_learning(
                                failed_result=llm_result,
                                success_result=escalated_result,
                                capability=capability,
                                agent_name=agent_name,
                                module_id=module_id,
                                failure_count=failure_count,
                            )
                        except ImportError:
                            pass
                        llm_result = escalated_result
                        model = next_tier["model"]
                        duration_ms = int((time.time() - start) * 1000)
                elif next_tier and next_tier["is_paid"]:
                    logger.info(
                        f"[BridgeDispatcher] Paid escalation needed: {model} -> "
                        f"{next_tier['model']} ({next_tier['provider']}). Submitting for approval."
                    )
                    try:
                        from agent_loop import request_approval

                        request_approval(
                            action_type="escalation",
                            action_data={
                                "original_model": model,
                                "escalated_model": next_tier["model"],
                                "escalated_provider": next_tier["provider"],
                                "capability": capability,
                                "module_id": module_id,
                                "failure_count": failure_count,
                                "prompt_preview": prompt[:200],
                            },
                            reason=f"Escalation: {failure_count}x failures on {model} for {capability}",
                            tier=2,
                        )
                    except Exception as esc_err:
                        logger.warning(
                            f"[BridgeDispatcher] Approval submission failed: {esc_err}"
                        )
                    self._log_escalation(
                        agent.get("id"),
                        model,
                        next_tier["model"],
                        next_tier["provider"],
                        capability,
                        module_id,
                        f"{failure_count} failures, awaiting approval",
                        failure_count,
                        approval_method="telegram",
                        success=None,
                    )
                    # Dashboard notification for paid cloud approval
                    self._telegram_dispatch_advisory(
                        advisory_type="paid_cloud",
                        module_id=module_id,
                        capability=capability,
                        home_station=home_station,
                        cloud_model=next_tier["model"],
                        cloud_provider=next_tier.get("provider", "external"),
                    )
        else:
            self._reset_failure(agent.get("id", 0), capability)

        # 5. Build result
        result = DispatchResult(
            success=llm_result.get("success", False),
            response=llm_result.get("response", ""),
            agent_name=agent_name,
            agent_id=agent.get("id"),
            model_used=model,
            station_code=station_code,
            capability=capability,
            duration_ms=duration_ms,
            prompt_tokens=llm_result.get(
                "prompt_tokens", llm_result.get("prompt_eval_count", 0)
            ),
            completion_tokens=llm_result.get(
                "completion_tokens", llm_result.get("eval_count", 0)
            ),
            provider=llm_result.get("provider", "ollama"),
            error=llm_result.get("error"),
            metadata={
                "module_id": module_id,
                "priority": priority,
                "home_station": home_station,
                "dispatch_station": dispatch_station,
                "is_cross_station": is_cross_station,
                "capability_station": capability_station,
            },
        )

        # 6. Log for HR tracking
        self._log_execution(result, module_id, user_id, job_id=job_id)

        # 6b. Increment agent budget tracking
        if result.success:
            self._increment_agent_budget(
                agent.get("id"),
                tokens_used=result.prompt_tokens + result.completion_tokens,
            )

        return result

    def request_json(
        self,
        capability: str,
        prompt: str,
        module_id: str = "unknown",
        system_prompt: Optional[str] = None,
        user_id: Optional[int] = None,
        timeout: int = 120,
    ) -> Dict:
        """
        Convenience method for JSON-mode requests.
        Returns parsed dict on success, None on failure.
        """
        result = self.request_work(
            capability=capability,
            prompt=prompt,
            module_id=module_id,
            system_prompt=system_prompt,
            user_id=user_id,
            json_mode=True,
            timeout=timeout,
        )
        if result.success:
            try:
                return json.loads(result.response)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    def get_agent_for_module(self, module_id: str) -> Optional[Dict]:
        """
        Get the currently assigned agent for a module.
        Used by the agent badge system (Phase 4).
        """
        self._refresh_agent_cache()

        # Find which station owns this module
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT station_code, modules
                FROM bridge_stations
                WHERE is_active = TRUE AND %s = ANY(modules)
                LIMIT 1
            """,
                (module_id,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row:
                station_code = row["station_code"]
                # Get the default agent for this station
                station_specs = AGENT_SPECIALIZATION.get(station_code, {})
                agent_name = station_specs.get("default", "ARCHIE")
                agent_info = self._agent_cache.get(agent_name)
                if agent_info:
                    return {
                        "agent_name": agent_name,
                        "agent_id": agent_info["id"],
                        "model": agent_info["model"],
                        "station_code": station_code,
                        "status": "active",
                    }
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] get_agent_for_module failed: {e}")

        return None

    def get_model_for_capability(self, capability: str) -> str:
        """
        Get the model name for a capability without executing.
        Used by modules that need to know which model will handle their work
        (e.g., chat modules that use archie_bridge for conversation context).
        """
        station_code = CAPABILITY_STATION_MAP.get(capability, "COMMAND")
        agent = self._select_agent(capability, station_code)
        if agent:
            return agent.get("model", "")
        return ""

    def log_external_call(
        self,
        capability: str,
        module_id: str,
        model_used: str,
        duration_ms: int = 0,
        success: bool = True,
        error: Optional[str] = None,
        user_id: Optional[int] = None,
    ):
        """
        Log an AI call that happened outside the dispatcher (e.g., via archie_bridge).
        Ensures all AI activity appears in task_execution_log for HR tracking.
        """
        station_code = CAPABILITY_STATION_MAP.get(capability, "COMMAND")
        agent = self._select_agent(capability, station_code)
        agent_name = "ARCHIE"
        agent_id = 2
        if agent:
            agent_id = agent.get("id", 2)
            for name, info in self._agent_cache.items():
                if info.get("id") == agent_id:
                    agent_name = name
                    break

        result = DispatchResult(
            success=success,
            response="",
            agent_name=agent_name,
            agent_id=agent_id,
            model_used=model_used,
            station_code=station_code,
            capability=capability,
            duration_ms=duration_ms,
            error=error,
        )
        self._log_execution(result, module_id, user_id)

    # ========================================================================
    # IAAE GOVERNANCE INTEGRATION
    # ========================================================================

    def _log_governance(
        self,
        event_type: str,
        action: str,
        agent_name: Optional[str] = None,
        reason: Optional[str] = None,
        outcome: str = "success",
    ):
        """Log to governance_audit_log for Vigil overwatch.

        Makes batch job lifecycle visible to the IAAE transparency system.
        Uses direct DB insert (not iaae_routes) because this may be called
        from background threads without a Flask request context.
        Failures are silently logged — governance logging should never block work.
        """
        try:
            agent_id = None
            if agent_name and agent_name in self._agent_cache:
                agent_id = self._agent_cache[agent_name].get("id")

            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, action, reason, outcome)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (event_type, "bridge_dispatch", agent_id, action, reason, outcome),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Governance log skipped: {e}")

    def _telegram_dispatch_advisory(
        self,
        advisory_type: str,  # "cross_station", "free_cloud", "paid_cloud"
        module_id: str,
        capability: str,
        home_station: Optional[str] = None,
        dispatch_station: Optional[str] = None,
        agent_name: Optional[str] = None,
        cloud_model: Optional[str] = None,
        cloud_provider: Optional[str] = None,
        job_id: Optional[int] = None,
        reason: Optional[str] = None,
    ):
        """Send Telegram advisory with context-appropriate buttons.

        All escalation types get interactive buttons so the user can
        acknowledge, override, or escalate further.
        """
        # Suppress Telegram for high-volume internal batch capabilities
        SILENT_CAPABILITIES = {"translate", "detect_language"}
        if capability in SILENT_CAPABILITIES:
            logger.debug(
                f"[BridgeDispatcher] Silent advisory ({advisory_type}) "
                f"for batch capability '{capability}'"
            )
            return

        try:
            if advisory_type == "cross_station":
                agent_str = f" \u2192 {agent_name}" if agent_name else ""
                job_str = f" (job #{job_id})" if job_id else ""
                title = "Cross-Station Dispatch"
                message = (
                    f"{module_id} [{home_station}] needs '{capability}' "
                    f"\u2192 routed to {dispatch_station}{agent_str}{job_str}"
                )
                if reason:
                    message += f"\n{reason}"
                notif_type = "info"
                emoji = "\U0001f500"
                # Buttons: OK (acknowledge) + Escalate to Cloud
                buttons = [
                    {"text": "\u2705 OK", "callback_data": "esc_ack"},
                    {
                        "text": "\u2601\ufe0f Escalate to Cloud",
                        "callback_data": "esc_cloud",
                    },
                ]

            elif advisory_type == "free_cloud":
                title = "Free Cloud Contractor"
                message = (
                    f"{module_id} '{capability}' \u2192 {cloud_model} "
                    f"({cloud_provider or 'cloud'})"
                )
                if reason:
                    message += f"\n{reason}"
                notif_type = "info"
                emoji = "\u2601\ufe0f"
                # Buttons: OK + Escalate to Paid
                buttons = [
                    {"text": "\u2705 OK", "callback_data": "esc_ack"},
                    {
                        "text": "\U0001f4b3 Escalate to Paid",
                        "callback_data": "esc_paid",
                    },
                ]

            elif advisory_type == "paid_cloud":
                title = "Paid Cloud Requested"
                message = (
                    f"{module_id} '{capability}' requesting {cloud_model} "
                    f"({cloud_provider})\nAwaiting your approval"
                )
                notif_type = "warning"
                emoji = "\u26a0\ufe0f"
                # Buttons handled by request_approval → _send_approval_telegram
                buttons = None

            else:
                return

            # 1. Insert system_notification for dashboard
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO system_notifications
                   (type, title, message, source, priority)
                   VALUES (%s, %s, %s, 'bridge_dispatcher', %s)""",
                (
                    notif_type,
                    title,
                    message,
                    "normal",
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

            # 2. Send Telegram with buttons for cross_station + free_cloud
            if advisory_type in ("cross_station", "free_cloud") and buttons:
                try:
                    import os
                    import requests as _req

                    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    if bot_token:
                        tg_text = f"{emoji} *{title}*\n\n{message}"

                        payload = {
                            "text": tg_text,
                            "parse_mode": "Markdown",
                            "reply_markup": {
                                "inline_keyboard": [buttons]
                            },
                        }

                        tconn = self._get_db()
                        tcur = tconn.cursor()
                        tcur.execute(
                            "SELECT telegram_id FROM telegram_users "
                            "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                        )
                        trows = tcur.fetchall()
                        tcur.close()
                        tconn.close()
                        for trow in trows:
                            payload["chat_id"] = trow[0]
                            _req.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json=payload,
                                timeout=15,
                            )
                except Exception as tg_err:
                    logger.debug(
                        f"[BridgeDispatcher] Telegram advisory skipped: {tg_err}"
                    )

            logger.info(f"[BridgeDispatcher] {title}: {message}")

        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Dispatch advisory failed: {e}")

    # ========================================================================
    # JOB MANAGEMENT
    # ========================================================================

    def create_job(
        self,
        job_type: str,
        module_source: str,
        description: str,
        total_steps: int,
        capability: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Optional[int]:
        """Create a new bridge job for tracking multi-step operations.

        Prevents duplicate jobs: if a running job with the same job_type
        and module_source already exists, returns None so callers know
        the job was rejected.

        Args:
            job_type: Job category (e.g. 'batch_translate', 'reindex').
            module_source: Module requesting the job.
            description: Human-readable description.
            total_steps: Total number of steps to complete.
            capability: Bridge capability key for agent resolution (e.g. 'translate').
                        Falls back to parsing from job_type if not provided.
            metadata: Additional job metadata (language, batch_size, etc.).

        Returns:
            job_id on success, None on failure or duplicate.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()

            # ── Duplicate guard: block if same type+module already running ──
            cur.execute(
                """
                SELECT id FROM bridge_jobs
                WHERE job_type = %s AND module_source = %s AND status = 'running'
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_type, module_source),
            )
            existing = cur.fetchone()
            if existing:
                eid = existing[0] if isinstance(existing, (list, tuple)) else existing["id"]
                cur.close()
                conn.close()
                logger.info(
                    f"[BridgeDispatcher] Duplicate job blocked: {job_type}/{module_source} "
                    f"already running as job #{eid}"
                )
                self._log_governance(
                    "batch_job",
                    "duplicate_blocked",
                    reason=f"Duplicate {job_type}/{module_source} blocked — job #{eid} already running",
                    outcome="blocked",
                )
                return None

            # Force-refresh busy agents list (bypass 30s welfare cache TTL)
            # so we never assign a job to an agent mid-task
            try:
                from psycopg2.extras import RealDictCursor

                bconn = self._get_db()
                bcur = bconn.cursor(cursor_factory=RealDictCursor)
                bcur.execute(
                    "SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'"
                )
                self._busy_agents = {r["agent_name"] for r in bcur.fetchall()}
                bcur.close()
                bconn.close()
            except Exception as busy_err:
                logger.debug(f"[BridgeDispatcher] Busy agents refresh failed: {busy_err}")

            # Resolve agent name from capability→station→agent mapping (home-first)
            cap_key = capability or job_type.split("_")[0]
            capability_station = CAPABILITY_STATION_MAP.get(cap_key, "COMMAND")
            home_station = self._resolve_module_station(module_source)

            agent = None
            dispatch_station = capability_station
            is_cross_station = False

            if home_station:
                agent = self._select_agent(cap_key, home_station)
                if agent:
                    dispatch_station = home_station
                else:
                    agent = self._select_agent(cap_key, capability_station)
                    dispatch_station = capability_station
                    is_cross_station = home_station != capability_station
            else:
                agent = self._select_agent(cap_key, capability_station)
                dispatch_station = capability_station

            station_code = dispatch_station
            agent_name = None
            if agent:
                for name, info in self._agent_cache.items():
                    if info.get("id") == agent.get("id"):
                        agent_name = name
                        break

            # ── Cross-station fallback (mirrors dispatch() logic) ──
            if not agent:
                blocked_station = home_station or capability_station
                all_stations = set(
                    info.get("station_code")
                    for info in self._agent_cache.values()
                    if info.get("station_code")
                )
                tried_stations = {blocked_station, "COMMAND"}
                if (
                    home_station
                    and capability_station
                    and home_station != capability_station
                ):
                    tried_stations.add(capability_station)

                for other_station in sorted(all_stations - tried_stations):
                    for agent_name_candidate, info in self._agent_cache.items():
                        if info.get("station_code") != other_station:
                            continue
                        if cap_key not in (info.get("skills") or {}):
                            continue
                        score, _block = self._score_agent(
                            agent_name_candidate, info, cap_key, other_station
                        )
                        if score <= 0:
                            continue

                        agent = info
                        agent_name = agent_name_candidate
                        station_code = other_station
                        dispatch_station = other_station
                        is_cross_station = True
                        logger.info(
                            f"[BridgeDispatcher] create_job cross-station: "
                            f"{blocked_station} → {other_station} "
                            f"({self._agent_display(agent_name_candidate)}) "
                            f"for '{cap_key}'"
                        )
                        break
                    if agent:
                        break

            if not agent_name:
                # No agent available at any station — advisory only
                blocked_station = home_station or capability_station
                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_source,
                    home_station=blocked_station,
                    dispatch_station="OVERLOADED",
                    capability=cap_key,
                    reason=(
                        f"All agents at {blocked_station} are at capacity "
                        f"for '{cap_key}'. Job will run but station needs relief."
                    ),
                )
                # For LLM-based capabilities, try free cloud contractors
                llm_caps = {"code_analysis", "translate", "summarize", "classify", "chat"}
                if cap_key in llm_caps:
                    for cloud_model in self.FREE_CLOUD_MODELS:
                        self._telegram_dispatch_advisory(
                            advisory_type="free_cloud",
                            module_id=module_source,
                            capability=cap_key,
                            home_station=blocked_station,
                            cloud_model=cloud_model,
                            cloud_provider="ollama_cloud",
                            reason=f"Station {blocked_station} at capacity — cloud contractor available",
                        )
                        break  # Just advise about first available

            # Enrich metadata with dispatch info
            enriched_meta = dict(metadata or {})
            enriched_meta["home_station"] = home_station
            enriched_meta["dispatch_station"] = dispatch_station
            enriched_meta["is_cross_station"] = is_cross_station

            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES (%s, %s, %s, %s, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    job_type,
                    module_source,
                    description,
                    total_steps,
                    agent_name,
                    station_code,
                    json.dumps(enriched_meta),
                ),
            )
            job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            logger.info(
                f"[BridgeDispatcher] Created job #{job_id}: {description} "
                f"({total_steps} steps, agent={agent_name}, station={station_code})"
            )

            # ── Cross-station Telegram advisory ──
            if is_cross_station and home_station:
                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_source,
                    home_station=home_station,
                    dispatch_station=dispatch_station,
                    capability=cap_key,
                    agent_name=agent_name,
                    job_id=job_id,
                )

            # ── IAAE governance: log job creation for Vigil overwatch ──
            self._log_governance(
                "batch_job",
                "create_job",
                agent_name=agent_name,
                reason=f"Job #{job_id}: {description} ({total_steps} steps, module={module_source})",
                outcome="created",
            )

            # ── HR tracking: register workload on agent's budget ──
            # This makes _score_agent() see the load and eventually
            # block the agent / trigger escalation when limit is reached.
            if agent:
                self._increment_agent_budget(agent.get("id"), tokens_used=0)

            return job_id
        except Exception as e:
            logger.error(f"[BridgeDispatcher] create_job failed: {e}")
            return None

    def update_job_progress(
        self,
        job_id: int,
        completed_steps: int,
        failed_steps: int = 0,
        metadata_update: Optional[Dict] = None,
    ) -> bool:
        """Update progress counters and merge metadata for a running job.

        Args:
            job_id: The job to update.
            completed_steps: New total completed steps.
            failed_steps: New total failed steps.
            metadata_update: Dict to merge into existing metadata.

        Returns:
            True on success.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            if metadata_update:
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET completed_steps = %s, failed_steps = %s,
                        metadata = metadata || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        completed_steps,
                        failed_steps,
                        json.dumps(metadata_update),
                        job_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET completed_steps = %s, failed_steps = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (completed_steps, failed_steps, job_id),
                )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"[BridgeDispatcher] update_job_progress failed: {e}")
            return False

    def complete_job(self, job_id: int, status: str = "auto") -> bool:
        """Mark a job as completed (or failed/cancelled).

        If status is 'auto' (default), determines the final status from
        the job's completed_steps and failed_steps:
        - All failed, zero completed → 'failed'
        - Zero completed, zero failed → 'cancelled'
        - Otherwise → 'completed'

        Args:
            job_id: The job to complete.
            status: Final status or 'auto' to determine from counters.

        Returns:
            True on success.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()

            if status == "auto":
                cur.execute(
                    "SELECT completed_steps, failed_steps, total_steps FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row:
                    completed, failed, total = row[0] or 0, row[1] or 0, row[2] or 0
                    if completed == 0 and failed == 0:
                        status = "cancelled"
                    elif completed == 0 and failed > 0:
                        status = "failed"
                    else:
                        status = "completed"
                else:
                    status = "completed"

            cur.execute(
                """
                UPDATE bridge_jobs
                SET status = %s, completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING agent_name, module_source, description,
                          completed_steps, failed_steps, total_steps,
                          job_type,
                          (EXTRACT(EPOCH FROM (NOW() - created_at)) * 1000)::int
                """,
                (status, job_id),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"[BridgeDispatcher] Job #{job_id} → {status}")

            # ── IAAE governance: log job completion for Vigil overwatch ──
            if row:
                a_name = row[0]
                m_src = row[1]
                desc = row[2]
                c_steps = row[3] or 0
                f_steps = row[4] or 0
                t_steps = row[5] or 0
                j_type = row[6] or ""
                dur_ms = row[7] or 0
                self._log_governance(
                    "batch_job",
                    "complete_job",
                    agent_name=a_name,
                    reason=(
                        f"Job #{job_id} {status}: {desc} "
                        f"({c_steps}/{t_steps} done, {f_steps} failed, module={m_src})"
                    ),
                    outcome=status,
                )

                # ── HR tracking: log to task_execution_log + update welfare ──
                # This feeds the roster (recent tasks), agent performance stats,
                # and welfare (mood/stress/energy) so batch jobs are fully visible.
                if status in ("completed", "failed"):
                    agent_id = None
                    if a_name and a_name in self._agent_cache:
                        agent_id = self._agent_cache[a_name].get("id")
                    cap_key = j_type.split("_")[0] if j_type else "batch"
                    station_code = CAPABILITY_STATION_MAP.get(cap_key, "COMMAND")
                    batch_result = DispatchResult(
                        success=(status == "completed"),
                        response=f"Batch job #{job_id}: {desc}",
                        agent_name=a_name or "unassigned",
                        agent_id=agent_id,
                        model_used="batch",
                        station_code=station_code,
                        capability=j_type or "batch",
                        duration_ms=dur_ms,
                        error=f"{f_steps}/{t_steps} steps failed" if f_steps else None,
                    )
                    self._log_execution(batch_result, m_src or "unknown", job_id=job_id)

            return True
        except Exception as e:
            logger.error(f"[BridgeDispatcher] complete_job failed: {e}")
            return False

    # ========================================================================
    # STALE JOB REAPER
    # ========================================================================

    def reap_stale_jobs(self, max_age_minutes: int = 5) -> int:
        """Mark orphaned running jobs as failed.

        Background threads die on platform restart, leaving jobs stuck
        in 'running' state forever. This reaper finds jobs that haven't
        been updated in max_age_minutes and marks them failed.

        Called on startup and can be called periodically.

        Returns:
            Number of jobs reaped.
        """
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE bridge_jobs
                SET status = 'failed',
                    completed_at = NOW(),
                    updated_at = NOW(),
                    metadata = COALESCE(metadata, '{}'::jsonb)
                        || '{"reap_reason": "stale — no progress update"}'::jsonb
                WHERE status = 'running'
                  AND updated_at < NOW() - INTERVAL '%s minutes'
                RETURNING id, job_type, description, completed_steps, total_steps
                """,
                (max_age_minutes,),
            )
            reaped = cur.fetchall()
            conn.commit()
            cur.close()
            conn.close()

            if reaped:
                for r in reaped:
                    jid = r[0] if isinstance(r, (list, tuple)) else r["id"]
                    desc = r[2] if isinstance(r, (list, tuple)) else r["description"]
                    logger.warning(
                        f"[BridgeDispatcher] Reaped stale job #{jid}: {desc}"
                    )
                logger.info(
                    f"[BridgeDispatcher] Stale job reaper: {len(reaped)} orphaned jobs cleaned up"
                )
            return len(reaped)
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Stale job reaper failed: {e}")
            return 0

    # ========================================================================
    # CREW MANIFEST
    # ========================================================================

    # Hardware map: model → GPU or CPU
    MODEL_HARDWARE = {
        "dolphin3-8k:latest": "GPU",
        "dolphin3-8k": "GPU",
        "qwen25-classify:latest": "CPU",
        "qwen25-classify": "CPU",
        "arctic-embed-cpu:latest": "CPU",
        "arctic-embed-cpu": "CPU",
        "qwen3-coder-cpu:latest": "CPU",
        "qwen3-coder-cpu": "CPU",
        "minicpm-v-cpu:latest": "CPU",
        "minicpm-v-cpu": "CPU",
    }

    def get_crew_manifest(self) -> list:
        """
        Build a live roster of every agent's real-time status.

        Joins: agents, station_assignments, agent_emotional_state,
               bridge_jobs (running), task_execution_log (24h), knowledge_base.
        """
        self._refresh_agent_cache()
        if not self._agent_cache:
            return []

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # --- Wellness (emotional state) per agent ---
            cur.execute("""
                SELECT agent_id, stress_level, energy_level, current_mood
                FROM agent_emotional_state
            """)
            wellness_map = {
                r["agent_id"]: {
                    "stress": float(r["stress_level"] or 0),
                    "energy": float(r["energy_level"] or 0),
                    "mood": r["current_mood"] or "neutral",
                }
                for r in cur.fetchall()
            }

            # --- Active jobs (running) per agent ---
            cur.execute("""
                SELECT id, agent_name, description,
                       total_steps, completed_steps
                FROM bridge_jobs
                WHERE status = 'running'
            """)
            jobs_map = {}
            for j in cur.fetchall():
                total = j["total_steps"] or 1
                completed = j["completed_steps"] or 0
                pct = round((completed / total) * 100, 1) if total > 0 else 0
                jobs_map[j["agent_name"]] = {
                    "id": j["id"],
                    "description": j["description"],
                    "progress_pct": pct,
                }

            # --- 24h dispatch stats per agent ---
            cur.execute("""
                SELECT agent_name,
                       COUNT(*) AS dispatches,
                       AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) AS success_rate,
                       AVG(duration_ms) AS avg_duration_sec
                FROM task_execution_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
                GROUP BY agent_name
            """)
            stats_map = {}
            for r in cur.fetchall():
                stats_map[r["agent_name"]] = {
                    "dispatches": r["dispatches"],
                    "success_rate": round(float(r["success_rate"] or 0), 2),
                    "avg_duration_sec": round(
                        float(r["avg_duration_sec"] or 0) / 1000, 1
                    ),
                }

            # --- Learning count per agent (from task_execution_log unique capabilities) ---
            cur.execute("""
                SELECT agent_name, COUNT(DISTINCT capability) AS cnt
                FROM task_execution_log
                WHERE success = TRUE
                  AND created_at > NOW() - INTERVAL '30 days'
                GROUP BY agent_name
            """)
            learning_map = {r["agent_name"]: r["cnt"] for r in cur.fetchall()}

            # --- Rest cycles (check if agent is resting) ---
            cur.execute("""
                SELECT agent_id
                FROM agent_rest_cycles
                WHERE ended_at IS NULL
            """)
            resting_ids = {r["agent_id"] for r in cur.fetchall()}

            cur.close()
            conn.close()

            # Build manifest
            manifest = []
            for name, info in self._agent_cache.items():
                agent_id = info["id"]
                model = info.get("model", "")

                # Determine status
                if agent_id in resting_ids:
                    status = "resting"
                elif name in jobs_map:
                    status = "working"
                else:
                    status = "idle"

                hw = self.MODEL_HARDWARE.get(model, "CPU")

                first = info.get("first_name", "")
                last = info.get("last_name", "")
                full_name = f"{first} {last}".strip() if (first or last) else name

                manifest.append(
                    {
                        "name": name,
                        "full_name": full_name,
                        "title": info.get("title", ""),
                        "id": agent_id,
                        "agent_id": agent_id,
                        "station": info.get("station_code", "COMMAND"),
                        "model": model,
                        "hardware": hw,
                        "status": status,
                        "wellness": wellness_map.get(
                            agent_id,
                            {
                                "stress": 0.0,
                                "energy": 1.0,
                                "mood": "neutral",
                            },
                        ),
                        "current_job": jobs_map.get(name),
                        "stats_24h": stats_map.get(
                            name,
                            {
                                "dispatches": 0,
                                "success_rate": 0.0,
                                "avg_duration_sec": 0,
                            },
                        ),
                        "learning_count": learning_map.get(name, 0),
                    }
                )

            return manifest

        except Exception as e:
            logger.error(f"[BridgeDispatcher] get_crew_manifest failed: {e}")
            return []

    def get_dispatch_status(self) -> Dict:
        """Get current dispatch status for all stations (Phase 6: Bridge Command)."""
        self._refresh_agent_cache()

        stations = {}
        for name, info in self._agent_cache.items():
            sc = info["station_code"]
            if sc not in stations:
                stations[sc] = {"agents": [], "active": True}
            stations[sc]["agents"].append(
                {
                    "name": name,
                    "id": info["id"],
                    "model": info["model"],
                    "status": "active",
                }
            )

        return {
            "total_agents": len(self._agent_cache),
            "total_stations": len(stations),
            "stations": stations,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_dispatcher = None


def get_dispatcher() -> BridgeDispatcher:
    """Get the singleton BridgeDispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = BridgeDispatcher()
        # Reap orphaned jobs from previous runs on first init
        try:
            reaped = _dispatcher.reap_stale_jobs(max_age_minutes=5)
            if reaped:
                logger.info(f"[BridgeDispatcher] Startup reaper cleaned {reaped} stale jobs")
        except Exception:
            pass
    return _dispatcher


def dispatch(
    capability: str,
    prompt: str,
    module_id: str = "unknown",
    system_prompt: Optional[str] = None,
    user_id: Optional[int] = None,
    json_mode: bool = False,
    **kwargs,
) -> DispatchResult:
    """
    Convenience function — dispatch work without managing instances.

    Usage:
        from bridge_dispatcher import dispatch
        result = dispatch('classify', 'Is this positive?', module_id='sentiment')
        if result.success:
            print(result.response)
    """
    return get_dispatcher().request_work(
        capability=capability,
        prompt=prompt,
        module_id=module_id,
        system_prompt=system_prompt,
        user_id=user_id,
        json_mode=json_mode,
        **kwargs,
    )


def dispatch_json(
    capability: str,
    prompt: str,
    module_id: str = "unknown",
    system_prompt: Optional[str] = None,
    user_id: Optional[int] = None,
    **kwargs,
) -> Optional[Dict]:
    """
    Convenience function — dispatch work expecting JSON response.

    Usage:
        from bridge_dispatcher import dispatch_json
        data = dispatch_json('classify', 'Classify this text', module_id='tagger')
        if data:
            print(data['category'])
    """
    return get_dispatcher().request_json(
        capability=capability,
        prompt=prompt,
        module_id=module_id,
        system_prompt=system_prompt,
        user_id=user_id,
        **kwargs,
    )
