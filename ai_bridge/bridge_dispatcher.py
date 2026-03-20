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
import requests
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass

try:
    from ai_bridge.schemas.agent_schemas import validate_schema as _validate_handoff_schema
except ImportError:
    try:
        from schemas.agent_schemas import validate_schema as _validate_handoff_schema
    except ImportError:
        _validate_handoff_schema = None

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
    "security_analysis": "SECURITY",
    # Security station capabilities
    "vulnerability_scan": "SECURITY",
    "threat_analysis": "SECURITY",
    "device_audit": "SECURITY",
    "dns_report": "SECURITY",
    "network_scan": "SECURITY",
    "camera_check": "SECURITY",
    "filter_review": "SECURITY",
    "ssl_check": "SECURITY",
    "incident_response": "SECURITY",
    "policy_review": "SECURITY",
    "ssh_audit": "SECURITY",
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
    "translate",            # Needs a capable chat LLM — not a classifier or embedder
    "knowledge_analysis",   # Deep JSON analysis — needs qwen3-coder-cpu or better
    "image_generation",     # ComfyUI skill — only Pixel has this
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

# Shift lifecycle states
SHIFT_STATES = ("active", "winding_down", "cooldown", "off_duty")

# Thresholds for automatic state transitions
WINDING_DOWN_BUDGET_PCT = 0.80  # 80% budget used -> winding down
WINDING_DOWN_STRESS = 0.70  # stress >= 0.7 -> winding down
COOLDOWN_BUDGET_PCT = 0.95  # 95% budget -> cooldown
COOLDOWN_STRESS = 0.85  # stress >= 0.85 -> cooldown
WINDING_DOWN_SCORE_PENALTY = 0.30  # 30% score penalty when winding down


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
        # Dynamic specialization cache from benchmarks (10-minute TTL)
        self._dynamic_spec_cache = {}  # (station, capability) → agent_name
        self._dynamic_spec_ts = 0
        self._dynamic_spec_ttl = 600
        # Fleet health tracking — node_db_id → {"online": bool, "last_check": timestamp}
        self._fleet_health_cache = {}

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
                       a.max_tokens, a.status, a.shift_state,
                       a.first_name, a.last_name, a.title,
                       a.display_name, a.image_model,
                       bs.station_code, bs.default_llm
                FROM agents a
                LEFT JOIN station_assignments sa ON a.id = sa.agent_id AND sa.is_active = TRUE
                LEFT JOIN bridge_stations bs ON sa.station_id = bs.id AND bs.is_active = TRUE
                WHERE a.status = 'active'
                ORDER BY COALESCE(sa.priority, 999)
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
                    "image_model": agent.get("image_model"),
                    "shift_state": agent.get("shift_state") or "active",
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

            # --- Fleet extension: add remote node agents to cache ---
            try:
                conn3 = self._get_db()
                cur3 = conn3.cursor(cursor_factory=RealDictCursor)
                cur3.execute("""
                    SELECT na.id AS node_agent_id, na.name, na.node_id,
                           na.source_agent_id, na.model AS local_model,
                           na.station_codes, na.status,
                           rn.node_id AS node_str_id, rn.hostname,
                           rn.last_heartbeat, rn.status AS node_status,
                           rn.gpu_vram_gb, rn.ram_gb
                    FROM node_agents na
                    JOIN remote_nodes rn ON rn.id = na.node_id
                    WHERE na.status = 'active'
                      AND rn.status = 'online'
                      AND rn.last_heartbeat > NOW() - INTERVAL '90 seconds'
                """)
                fleet_agents = cur3.fetchall()
                cur3.close()
                conn3.close()

                fleet_count = 0
                for row in fleet_agents:
                    cache_key = f"fleet:{row['node_str_id']}:{row['name']}"
                    self._agent_cache[cache_key] = {
                        "id": row["node_agent_id"],
                        "source_agent_id": row["source_agent_id"],
                        "name": row["name"],
                        "model": row["local_model"],
                        "station_codes": row["station_codes"] or [],
                        "status": row["status"],
                        "node_id": row["node_str_id"],
                        "node_db_id": row["node_id"],
                        "hostname": row["hostname"],
                        "is_remote": True,
                        "gpu_vram_gb": row["gpu_vram_gb"],
                        "ram_gb": row["ram_gb"],
                        "shift_state": "active",
                        "stress": 0.0,
                        "energy": 1.0,
                        "task_count": 0,
                        "task_limit": 10,
                        "skills": {},
                    }
                    fleet_count += 1

                if fleet_count:
                    logger.info(
                        f"[BridgeDispatcher] Fleet cache: {fleet_count} remote agents"
                    )
            except Exception as fleet_err:
                logger.warning(
                    f"[BridgeDispatcher] Fleet cache population failed: {fleet_err}"
                )

            self._cache_time = now
            logger.info(f"[BridgeDispatcher] Cached {len(self._agent_cache)} agents")
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Cache refresh failed: {e}")

    def _get_station_slot_occupancy(self, station_code):
        """Count current slot occupancy at a station from active bridge_jobs.
        Returns dict with primary/auxiliary/contractor counts and capacity config.
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, max_primary, max_auxiliary, allow_overflow
                FROM bridge_stations WHERE station_code = %s AND is_active = true
            """,
                (station_code,),
            )
            station = cur.fetchone()
            if not station:
                cur.close()
                conn.close()
                return {
                    "primary": 0,
                    "auxiliary": 0,
                    "contractor": 0,
                    "total": 0,
                    "max_primary": 2,
                    "max_auxiliary": 1,
                    "allow_overflow": True,
                }

            # Count primary crew: jobs at this station that are NOT cross-station or cloud
            # Count auxiliary: cross-station jobs targeting this station (module_station or dispatch_station)
            # Count contractors: cloud jobs at this station
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM bridge_jobs
                     WHERE status = 'running' AND station_code = %s
                     AND (metadata->>'is_cross_station') IS DISTINCT FROM 'true'
                     AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                    ) AS primary_count,
                    (SELECT COUNT(*) FROM bridge_jobs
                     WHERE status = 'running'
                     AND metadata->>'is_cross_station' = 'true'
                     AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                     AND (metadata->>'module_station' = %s OR metadata->>'dispatch_station' = %s)
                    ) AS auxiliary_count,
                    (SELECT COUNT(*) FROM bridge_jobs
                     WHERE status = 'running' AND station_code = %s
                     AND metadata->>'is_cloud' = 'true'
                    ) AS contractor_count
            """,
                (station_code, station_code, station_code, station_code),
            )
            counts = cur.fetchone() or {}
            cur.close()
            conn.close()

            primary = counts.get("primary_count", 0) or 0
            auxiliary = counts.get("auxiliary_count", 0) or 0
            contractor = counts.get("contractor_count", 0) or 0
            return {
                "primary": primary,
                "auxiliary": auxiliary,
                "contractor": contractor,
                "total": primary + auxiliary + contractor,
                "max_primary": station.get("max_primary", 2),
                "max_auxiliary": station.get("max_auxiliary", 1),
                "allow_overflow": station.get("allow_overflow", True),
                "station_id": station.get("id"),
            }
        except Exception as e:
            logger.warning(
                f"[CAPACITY] Error getting slot occupancy for {station_code}: {e}"
            )
            return {
                "primary": 0,
                "auxiliary": 0,
                "contractor": 0,
                "total": 0,
                "max_primary": 2,
                "max_auxiliary": 1,
                "allow_overflow": True,
            }

    def _station_aux_available(self, requesting_station, cur=None):
        """Check if a station can accept a cross-station auxiliary agent.

        Rules (3-slot model):
        1. ALL assigned crew must be busy before auxiliary is allowed.
           A station with 1 agent can get aux help once that agent is working.
           A station with 2 agents needs both busy before aux.
        2. Only 1 auxiliary slot per station (max_auxiliary from bridge_stations).

        Pass an existing cursor to reuse a transaction (prevents race conditions
        when called inside create_job's advisory-locked transaction).

        Returns (available: bool, aux_count: int, max_aux: int, reason: str).
        """
        own_conn = False
        try:
            if cur is None:
                from psycopg2.extras import RealDictCursor

                conn = self._get_db()
                cur = conn.cursor(cursor_factory=RealDictCursor)
                own_conn = True

            # Acquire station-level advisory lock to prevent concurrent aux dispatches
            station_lock_key = hash(f"aux_lock:{requesting_station}") % (2**31)
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (station_lock_key,))

            cur.execute(
                "SELECT id, max_primary, max_auxiliary FROM bridge_stations "
                "WHERE station_code = %s AND is_active = true",
                (requesting_station,),
            )
            station = cur.fetchone()
            if not station:
                if own_conn:
                    cur.close()
                    conn.close()
                return True, 0, 1, ""

            max_aux = station["max_auxiliary"] or 1

            # Rule 1: All assigned crew must be busy before auxiliary help
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM station_assignments
                WHERE station_id = %s
                AND assignment_type = 'primary'
                AND is_active = TRUE
            """,
                (station["id"],),
            )
            assigned_count = cur.fetchone()["cnt"]
            if assigned_count == 0:
                if own_conn:
                    cur.close()
                    conn.close()
                reason = (
                    f"{requesting_station} has no crew assigned. "
                    f"At least one agent must be assigned before auxiliary dispatch."
                )
                return False, 0, max_aux, reason

            # Rule 2: Check auxiliary slot availability
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM bridge_jobs
                WHERE status = 'running'
                AND metadata->>'is_cross_station' = 'true'
                AND (metadata->>'is_cloud') IS DISTINCT FROM 'true'
                AND (
                    metadata->>'module_station' = %s
                    OR metadata->>'dispatch_station' = %s
                )
            """,
                (requesting_station, requesting_station),
            )
            aux_count = cur.fetchone()["cnt"]
            if own_conn:
                cur.close()
                conn.close()

            if aux_count >= max_aux:
                return False, aux_count, max_aux, f"Auxiliary slot full ({aux_count}/{max_aux})"

            return True, aux_count, max_aux, ""
        except Exception as e:
            logger.warning(
                f"[CAPACITY] Error checking aux availability at "
                f"{requesting_station}: {e}"
            )
            if own_conn:
                try:
                    cur.close()
                    conn.close()
                except Exception as e:
                    logger.warning("DB cleanup failed in rate limiter: %s", e)
            return True, 0, 1, ""  # Fail open

    def _log_capacity_event(
        self,
        station_code,
        event_type,
        agent_id=None,
        agent_name=None,
        home_station_id=None,
        job_id=None,
        capability=None,
        slot_number=None,
        reason=None,
        metadata=None,
    ):
        """Log a station capacity event for workload intelligence (ADR-055)."""
        try:
            from psycopg2.extras import Json

            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM bridge_stations WHERE station_code = %s",
                (station_code,),
            )
            row = cur.fetchone()
            station_id = row[0] if row else None
            if station_id is None:
                logger.warning(
                    f"[CAPACITY] Unknown station_code '{station_code}', skipping event log"
                )
                cur.close()
                conn.close()
                return
            cur.execute(
                """
                INSERT INTO station_capacity_events
                    (station_id, event_type, agent_id, agent_name, home_station_id,
                     job_id, capability, slot_number, reason, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    station_id,
                    event_type,
                    agent_id,
                    agent_name,
                    home_station_id,
                    job_id,
                    capability,
                    slot_number,
                    reason,
                    Json(metadata or {}),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(
                f"[CAPACITY] Error logging event {event_type} for {station_code}: {e}"
            )

    def _refresh_welfare_cache(self, skip_busy_refresh: bool = False):
        """Load agent welfare state (emotional, rest cycles, budgets) with 30s TTL.

        Populates self._welfare_cache keyed by agent_id with:
        - stress, energy, mood (from agent_emotional_state)
        - resting: bool (from agent_rest_cycles where ended_at IS NULL)
        - rest_type: str or None (type of active rest cycle)
        - budget: dict with task/token usage and limits (from agent_budgets)

        Args:
            skip_busy_refresh: If True, don't overwrite _busy_agents.
                Used when request_work() has already set _busy_agents
                with job_id/prefer_agent exclusions.
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
                       tokens_used_today, token_limit_per_day, token_reset_at
                FROM agent_budgets
            """)
            budget_map = {}
            for r in cur.fetchall():
                # If reset is overdue, treat as fresh budget (the actual reset
                # happens on next task dispatch via _increment_agent_budget)
                reset_overdue = (
                    r["token_reset_at"] is not None
                    and r["token_reset_at"] < datetime.now()
                )
                budget_map[r["agent_id"]] = {
                    "current_task_count": 0 if reset_overdue else (r["current_task_count"] or 0),
                    "task_queue_limit": r["task_queue_limit"] or 10,
                    "tokens_used_today": 0 if reset_overdue else (r["tokens_used_today"] or 0),
                    "token_limit_per_day": r["token_limit_per_day"] or 100000,
                }

            # Busy agents (running bridge_jobs)
            # Skip if request_work() already set _busy_agents with proper
            # job_id exclusion and prefer_agent handling.
            if not skip_busy_refresh:
                cur.execute("""
                    SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'
                """)
                self._busy_agents = {r["agent_name"] for r in cur.fetchall()}

            # Include shift_state in cache (queried before cursor close)
            cur.execute("SELECT id, shift_state FROM agents WHERE status = 'active'")
            shift_state_map = {}
            for r in cur.fetchall():
                shift_state_map[r["id"]] = r["shift_state"] or "active"

            # Load performance rankings into cache for dispatch scoring
            cur.execute("""
                SELECT agent_id, capability, rank_score, rank_position, sample_size
                FROM agent_performance_rankings
            """)
            perf_map = {}
            for r in cur.fetchall():
                aid = r["agent_id"]
                if aid not in perf_map:
                    perf_map[aid] = {}
                perf_map[aid][r["capability"]] = {
                    "rank_score": float(r["rank_score"]),
                    "rank_position": r["rank_position"],
                    "sample_size": r["sample_size"],
                }

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
                    "shift_state": shift_state_map.get(aid, "active"),
                    "budget": budget_map.get(
                        aid,
                        {
                            "current_task_count": 0,
                            "task_queue_limit": 10,
                            "tokens_used_today": 0,
                            "token_limit_per_day": 100000,
                        },
                    ),
                    "perf_rankings": perf_map.get(aid, {}),
                }

            self._welfare_cache = welfare
            self._welfare_cache_time = now
            logger.debug(
                f"[BridgeDispatcher] Welfare cache refreshed: {len(welfare)} agents"
            )

            # Check for shift state transitions (uses own connection)
            try:
                from psycopg2.extras import RealDictCursor as RDC2

                conn2 = self._get_db()
                cur2 = conn2.cursor(cursor_factory=RDC2)
                self._check_shift_transitions(cur2)
                conn2.commit()
                cur2.close()
                conn2.close()
            except Exception as te:
                logger.warning(
                    f"[BridgeDispatcher] Shift transition check failed: {te}"
                )
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Welfare cache refresh failed: {e}")

    def _get_dynamic_specialization(
        self, station_code: str, capability: str
    ) -> Optional[str]:
        """Return the top benchmark performer for *capability* at *station*.

        Uses a 10-minute cache.  Falls back to ``None`` so the caller can
        check the static ``AGENT_SPECIALIZATION`` dict.
        """
        _NO_WINNER = ""  # sentinel for "queried DB, no winner found"
        now = time.time()
        cache_key = (station_code, capability)

        if (now - self._dynamic_spec_ts) < self._dynamic_spec_ttl:
            cached = self._dynamic_spec_cache.get(cache_key)
            if cached is not None:
                return cached if cached != _NO_WINNER else None

        # Query latest completed benchmark whose capability matches
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT r.agent_name
                    FROM action_benchmark_results r
                    JOIN action_benchmark_runs br ON br.id = r.run_id
                    WHERE br.status = 'completed'
                      AND br.station_code = %s
                      AND br.test_config->>'capability' = %s
                      AND r.rank = 1
                      AND r.success = TRUE
                    ORDER BY br.started_at DESC
                    LIMIT 1
                    """,
                    (station_code, capability),
                )
                row = cur.fetchone()
            finally:
                cur.close()
                conn.close()

            agent_name = row["agent_name"] if row else None
            self._dynamic_spec_cache[cache_key] = agent_name or _NO_WINNER
            self._dynamic_spec_ts = now
            return agent_name

        except Exception as e:
            logger.debug(
                "Dynamic specialization lookup failed (%s/%s): %s",
                station_code,
                capability,
                e,
            )
            return None

    # ------------------------------------------------------------------
    # Shift lifecycle engine — graduated handoff
    # ------------------------------------------------------------------

    def _check_shift_transitions(self, cur):
        """Check active/winding_down agents for automatic state transitions.

        Called during welfare cache refresh.  Uses the caller's cursor —
        does NOT commit or close it.
        """
        cur.execute("""
            SELECT a.id, a.name, a.shift_state,
                   ab.current_task_count, ab.task_queue_limit,
                   ab.tokens_used_today, ab.token_limit_per_day
            FROM agents a
            LEFT JOIN agent_budgets ab ON a.id = ab.agent_id
            WHERE a.status = 'active'
              AND a.shift_state IN ('active', 'winding_down')
        """)
        rows = cur.fetchall()

        for row in rows:
            agent_id = row["id"]
            agent_name = row["name"]
            current_state = row["shift_state"] or "active"

            # Calculate budget percentage (higher of task% and token%)
            task_count = row["current_task_count"] or 0
            task_limit = row["task_queue_limit"] or 10
            tokens_used = row["tokens_used_today"] or 0
            token_limit = row["token_limit_per_day"] or 100000

            task_pct = task_count / task_limit if task_limit > 0 else 0.0
            token_pct = tokens_used / token_limit if token_limit > 0 else 0.0
            budget_pct = max(task_pct, token_pct)

            # Get stress from welfare cache
            welfare = self._welfare_cache.get(agent_id, {})
            stress = welfare.get("stress", 0.0)

            # Check cooldown thresholds first (higher priority)
            if budget_pct >= COOLDOWN_BUDGET_PCT or stress >= COOLDOWN_STRESS:
                if current_state != "cooldown":
                    reason = (
                        f"budget={budget_pct:.0%}"
                        if budget_pct >= COOLDOWN_BUDGET_PCT
                        else f"stress={stress:.2f}"
                    )
                    self._transition_shift_state(
                        cur, agent_id, agent_name, "cooldown", reason
                    )
            # Then winding_down thresholds
            elif budget_pct >= WINDING_DOWN_BUDGET_PCT or stress >= WINDING_DOWN_STRESS:
                if current_state == "active":
                    reason = (
                        f"budget={budget_pct:.0%}"
                        if budget_pct >= WINDING_DOWN_BUDGET_PCT
                        else f"stress={stress:.2f}"
                    )
                    self._transition_shift_state(
                        cur, agent_id, agent_name, "winding_down", reason
                    )

    def _transition_shift_state(self, cur, agent_id, agent_name, new_state, reason):
        """Transition an agent to a new shift state, logging the rotation.

        Does NOT commit — caller owns the transaction.
        """
        from psycopg2.extras import Json

        logger.info(
            "[ShiftLifecycle] %s (%d) → %s (reason: %s)",
            agent_name, agent_id, new_state, reason,
        )

        # Get current station
        cur.execute("""
            SELECT sa.station_id, bs.station_code
            FROM station_assignments sa
            JOIN bridge_stations bs ON sa.station_id = bs.id
            WHERE sa.agent_id = %s AND sa.is_active = TRUE
            LIMIT 1
        """, (agent_id,))
        station_row = cur.fetchone()
        station_id = station_row["station_id"] if station_row else None
        station_code = station_row["station_code"] if station_row else "UNKNOWN"

        # Close previous rotation log entry
        cur.execute("""
            UPDATE agent_rotation_log SET ended_at = NOW()
            WHERE agent_id = %s AND ended_at IS NULL
        """, (agent_id,))

        # Insert new rotation log entry
        cur.execute("""
            INSERT INTO agent_rotation_log
                (agent_id, station_id, shift_state, reason, started_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (agent_id, station_id, new_state, reason))

        # Update agent shift_state
        cur.execute(
            "UPDATE agents SET shift_state = %s WHERE id = %s",
            (new_state, agent_id),
        )

        # Create system notification
        cur.execute("""
            INSERT INTO system_notifications (type, title, message, metadata, created_at)
            VALUES ('info', %s, %s, %s, NOW())
        """, (
            f"Shift transition: {agent_name}",
            f"{agent_name} transitioned to {new_state} at {station_code} (reason: {reason})",
            Json({"agent_id": agent_id, "agent_name": agent_name,
                  "new_state": new_state, "station_code": station_code,
                  "reason": reason}),
        ))

        # If cooldown, find a replacement
        if new_state == "cooldown" and station_id:
            replacement = self._find_replacement(
                cur, agent_id, station_id, station_code
            )
            if replacement:
                # Update the rotation log for the exhausted agent with replaced_by
                cur.execute("""
                    UPDATE agent_rotation_log SET replaced_by = %s
                    WHERE id = (
                        SELECT id FROM agent_rotation_log
                        WHERE agent_id = %s AND ended_at IS NULL
                        ORDER BY started_at DESC LIMIT 1
                    )
                """, (replacement["id"], agent_id))
                logger.info(
                    "[ShiftLifecycle] Replacement for %s: %s",
                    agent_name, replacement["name"],
                )

        # Update welfare cache in-memory
        if agent_id in self._welfare_cache:
            self._welfare_cache[agent_id]["shift_state"] = new_state

    def _find_replacement(self, cur, exhausted_agent_id, station_id, station_code):
        """Find and activate the best replacement agent for a station.

        Scores candidates on skill proficiency, RAM fit, rest time,
        and historical performance.  Returns the activated agent dict
        or None.
        """
        # Get recent capabilities needed at this station (last 7 days)
        cur.execute("""
            SELECT DISTINCT capability FROM task_execution_log
            WHERE station_code = %s
              AND created_at > NOW() - INTERVAL '7 days'
        """, (station_code,))
        recent_caps = [r["capability"] for r in cur.fetchall()]

        # Find candidate agents
        cur.execute("""
            SELECT a.id, a.name
            FROM agents a
            WHERE a.status = 'active'
              AND a.shift_state IN ('active', 'off_duty')
              AND a.id != %s
              AND a.name NOT IN (
                  SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'
              )
              AND a.id NOT IN (
                  SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL
              )
              AND a.id NOT IN (
                  SELECT agent_id FROM station_assignments
                  WHERE station_id = %s AND is_active = TRUE
              )
        """, (exhausted_agent_id, station_id))
        candidates = cur.fetchall()

        if not candidates:
            logger.debug("[ShiftLifecycle] No replacement candidates for station %s", station_code)
            return None

        best_score = -1.0
        best_candidate = None

        for cand in candidates:
            cid = cand["id"]

            # Skill proficiency (40%) — average proficiency across recent capabilities
            if recent_caps:
                cur.execute("""
                    SELECT AVG(proficiency_level) as avg_prof
                    FROM agent_skills
                    WHERE agent_id = %s AND skill_name = ANY(%s)
                """, (cid, recent_caps))
                skill_row = cur.fetchone()
                avg_prof = float(skill_row["avg_prof"] or 0) if skill_row else 0.0
                skill_score = avg_prof / 5.0
            else:
                skill_score = 0.3  # generous default

            # RAM fit (30%) — default 0.3 (no easy way to check loaded status from DB)
            ram_score = 0.3

            # Time since last shift (20%) — hours rested / 8.0, capped at 1.0
            cur.execute("""
                SELECT EXTRACT(EPOCH FROM (NOW() - MAX(ended_at))) / 3600.0 as hours_rested
                FROM agent_rotation_log
                WHERE agent_id = %s AND ended_at IS NOT NULL
            """, (cid,))
            rest_row = cur.fetchone()
            hours_rested = float(rest_row["hours_rested"] or 0) if rest_row else 8.0
            rest_score = min(hours_rested / 8.0, 1.0)

            # Historical performance (10%) — average rank_score
            cur.execute("""
                SELECT AVG(rank_score) as avg_rank
                FROM agent_performance_rankings
                WHERE agent_id = %s
            """, (cid,))
            perf_row = cur.fetchone()
            perf_score = float(perf_row["avg_rank"] or 0.5) if perf_row else 0.5

            # Weighted composite
            score = (
                0.40 * skill_score
                + 0.30 * ram_score
                + 0.20 * rest_score
                + 0.10 * perf_score
            )

            if score > best_score:
                best_score = score
                best_candidate = {"id": cid, "name": cand["name"], "score": score}

        if best_candidate:
            self._transition_shift_state(
                cur,
                best_candidate["id"],
                best_candidate["name"],
                "active",
                "replacement_activated",
            )

        return best_candidate

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

        # Agent must be active — paused, resting-in-lounge, or any non-active
        # status means they are unavailable for dispatch.
        agent_status = agent_info.get("status", "active")
        if agent_status != "active":
            return (
                0.0,
                f"{agent_name} is {agent_status} (not available for dispatch)",
            )

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
        # Specialization score: prefer performance ranking over static mapping
        # ------------------------------------------------------------------
        specialization_score = 0.0
        agent_id = agent_info.get("id")
        if agent_id:
            # Try performance ranking first (data-driven)
            perf_welfare = self._welfare_cache.get(agent_id, {})
            rank_data = perf_welfare.get("perf_rankings", {}).get(capability)
            if rank_data and rank_data.get("sample_size", 0) >= 10:
                specialization_score = rank_data["rank_score"]
            else:
                # Fall back to dynamic benchmark winner
                dyn_winner = self._get_dynamic_specialization(station_code, capability)
                if dyn_winner and dyn_winner == agent_name:
                    specialization_score = 1.0
                else:
                    # Fall back to static specialization map
                    station_specs = AGENT_SPECIALIZATION.get(station_code, {})
                    default_specs = AGENT_SPECIALIZATION.get("default", {})
                    preferred = station_specs.get(capability) or default_specs.get(capability)
                    specialization_score = 1.0 if preferred == agent_name else 0.0

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

        # Apply shift state modifiers
        shift_state = agent_info.get("shift_state", "active")
        if shift_state == "winding_down":
            composite *= 1.0 - WINDING_DOWN_SCORE_PENALTY
        elif shift_state == "cooldown":
            return (0.0, f"{agent_name} is in cooldown (finishing current job only)")
        elif shift_state == "off_duty":
            return (0.0, f"{agent_name} is off duty (resting)")

        # Fleet: network cost penalty for remote node agents
        if agent_info.get("is_remote"):
            composite *= 0.85  # 15% penalty for remote dispatch latency
            if not agent_info.get("model_loaded", True):
                composite *= 0.7  # Additional 30% if model not loaded on node

        return (round(composite, 4), None)

    def _resolve_station(self, capability: str) -> str:
        """Resolve station for capability, checking mission profile overrides first."""
        try:
            from ai_bridge.mission_manager import MissionManager

            mm = MissionManager()
            overrides = mm.get_routing_overrides()
            if overrides and capability in overrides:
                return overrides[capability]
        except Exception as e:
            logger.warning("Capability routing override failed for %s: %s", capability, e)
        return CAPABILITY_STATION_MAP.get(capability, "COMMAND")

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
        key = module_id.lower().strip()
        result = self._module_station_cache.get(key)
        if not result and "_" in key:
            # Try base module name (e.g. "consciousness_linguistics" → "consciousness")
            base = key.split("_")[0]
            result = self._module_station_cache.get(base)
        return result

    def _select_agent(
        self,
        capability: str,
        station_code: str,
        skip_busy_refresh: bool = False,
    ) -> Optional[Dict]:
        """Select the best agent for a capability within a station.

        Uses multi-factor scoring: skills, specialization, welfare,
        availability, and budget headroom.  Hard-blocked agents (resting,
        budget exhausted, critical welfare) are filtered out.
        """
        self._refresh_agent_cache()
        self._refresh_welfare_cache(skip_busy_refresh=skip_busy_refresh)

        # Gather all candidates assigned to this station
        # Handles both local agents (station_code string) and
        # fleet agents (station_codes array)
        candidates = []
        for name, info in self._agent_cache.items():
            agent_station = info.get("station_code", "")
            agent_stations = info.get("station_codes", [])
            if agent_station == station_code or station_code in agent_stations:
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

    # ====================================================================
    # FLEET NODE DISPATCH — Cross-node agent fallback (ADR-xxx)
    # ====================================================================

    def _find_fleet_agent(
        self,
        station_code: str,
        capability: str,
        model_preference: Optional[str] = None,
    ) -> Optional[Dict]:
        """Find an available agent on a fleet node for cross-node dispatch.

        Checks remote_nodes for online fleet nodes, then looks for agents
        assigned to the requested station whose model is available on
        that node.  Returns agent info dict or None.
        """
        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Find node agents on matching stations with online nodes
            cur.execute(
                """
                SELECT na.name AS agent_name,
                       na.model,
                       na.station_codes,
                       na.hub_agent_id,
                       rn.id AS node_id,
                       rn.node_name,
                       rn.hostname AS node_hostname,
                       rn.port AS node_port
                FROM node_agents na
                JOIN remote_nodes rn ON rn.id = na.node_id
                WHERE rn.is_active = true
                  AND (
                      rn.last_heartbeat > NOW() - INTERVAL '2 minutes'
                      OR rn.deployment_mode = 'starbase'
                  )
                  AND %s = ANY(na.station_codes)
                ORDER BY rn.last_heartbeat DESC NULLS LAST
                """,
                (station_code,),
            )
            candidates = cur.fetchall()
            cur.close()
            conn.close()

            if not candidates:
                logger.debug(
                    f"[BridgeDispatcher] No fleet agents for station={station_code}"
                )
                return None

            # Check each candidate — verify model is reachable on the node
            for candidate in candidates:
                agent_name = candidate["agent_name"]
                model = candidate["model"]
                hostname = candidate["node_hostname"]
                port = candidate["node_port"] or 11434

                # If caller wants a specific model, skip non-matching agents
                if model_preference and model != model_preference:
                    continue

                # Verify model is available on the node's Ollama
                try:
                    tags_resp = requests.get(
                        f"http://{hostname}:{port}/api/tags",
                        timeout=5,
                    )
                    if tags_resp.status_code == 200:
                        available_models = [
                            m.get("name", "")
                            for m in tags_resp.json().get("models", [])
                        ]
                        # Match model name (with or without :latest tag)
                        model_found = any(
                            m == model or m.startswith(f"{model}:")
                            or model.startswith(f"{m.split(':')[0]}:")
                            for m in available_models
                        )
                        if not model_found:
                            logger.debug(
                                f"[BridgeDispatcher] Fleet agent {agent_name} "
                                f"model '{model}' not on node {hostname}"
                            )
                            continue
                except Exception as tag_err:
                    logger.debug(
                        f"[BridgeDispatcher] Cannot reach node {hostname}:{port} "
                        f"Ollama: {tag_err}"
                    )
                    continue

                logger.info(
                    f"[BridgeDispatcher] Fleet agent found: {agent_name} "
                    f"(model={model}) on node {candidate['node_name']} "
                    f"({hostname}:{port}) for station={station_code}"
                )
                return {
                    "agent_name": agent_name,
                    "model": model,
                    "node_hostname": hostname,
                    "node_port": port,
                    "node_id": candidate["node_id"],
                    "node_name": candidate["node_name"],
                }

            logger.debug(
                f"[BridgeDispatcher] No reachable fleet agents for "
                f"station={station_code} capability={capability}"
            )
            return None

        except Exception as e:
            logger.warning(
                f"[BridgeDispatcher] Fleet agent lookup failed: {e}"
            )
            return None

    def _dispatch_to_node(
        self,
        agent_info: Dict,
        prompt: str,
        system_prompt: Optional[str] = None,
        options: Optional[Dict] = None,
        capability: str = "unknown",
        module_id: str = "unknown",
        station_code: str = "UNKNOWN",
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ) -> Optional[Dict]:
        """Dispatch a job to a fleet node's Ollama API.

        Creates a bridge_job for tracking, calls the remote Ollama,
        returns dict with response text and metadata, or None on failure.
        """
        hostname = agent_info["node_hostname"]
        port = agent_info["node_port"] or 11434
        model = agent_info["model"]
        agent_name = agent_info["agent_name"]
        node_id = agent_info["node_id"]
        node_name = agent_info.get("node_name", "unknown")

        # Create bridge_job for tracking
        bridge_job_id = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES (%s, %s, %s, 1, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    capability,
                    module_id,
                    f"Fleet dispatch to {node_name}: {prompt[:80]}",
                    agent_name,
                    station_code,
                    json.dumps({
                        "node_id": node_id,
                        "node_name": node_name,
                        "node_hostname": hostname,
                        "is_remote": True,
                        "capability": capability,
                    }),
                ),
            )
            bridge_job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as job_err:
            logger.warning(
                f"[BridgeDispatcher] Failed to create fleet bridge_job: {job_err}"
            )

        # Auto warm-boot: ensure model loaded on node before calling
        try:
            readiness = self.ensure_model_ready(
                agent_name, model,
                target_host={"hostname": hostname, "port": port, "node_db_id": node_id}
            )
            if readiness and not readiness.get("ready"):
                logger.warning(f"[BridgeDispatcher] Node model {model} not ready on {node_name}")
        except Exception as wb_err:
            logger.debug(f"[BridgeDispatcher] Node warm boot check failed: {wb_err}")

        # Call the node's Ollama API
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
            if system_prompt:
                payload["system"] = system_prompt
            if options:
                payload["options"] = options

            logger.info(
                f"[BridgeDispatcher] Dispatching to fleet node {node_name} "
                f"({hostname}:{port}) agent={agent_name} model={model}"
            )

            resp = requests.post(
                f"http://{hostname}:{port}/api/generate",
                json=payload,
                timeout=120,
            )

            if resp.status_code == 200:
                data = resp.json()
                response_text = data.get("response", "")

                # Mark bridge_job complete
                if bridge_job_id:
                    try:
                        conn = self._get_db()
                        cur = conn.cursor()
                        cur.execute(
                            """
                            UPDATE bridge_jobs
                            SET status = 'completed',
                                completed_steps = 1,
                                completed_at = NOW()
                            WHERE id = %s
                            """,
                            (bridge_job_id,),
                        )
                        conn.commit()
                        cur.close()
                        conn.close()
                    except Exception as _exc:
                        pass

                logger.info(
                    f"[BridgeDispatcher] Fleet dispatch success: "
                    f"{agent_name}@{node_name} returned "
                    f"{len(response_text)} chars"
                )

                return {
                    "success": True,
                    "response": response_text,
                    "agent_name": agent_name,
                    "model": model,
                    "node_id": node_id,
                    "node_name": node_name,
                    "bridge_job_id": bridge_job_id,
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                }
            else:
                logger.warning(
                    f"[BridgeDispatcher] Fleet node {hostname}:{port} "
                    f"returned HTTP {resp.status_code}"
                )

        except requests.exceptions.Timeout:
            logger.warning(
                f"[BridgeDispatcher] Fleet dispatch timeout (120s) to "
                f"{hostname}:{port} model={model}"
            )
        except Exception as e:
            logger.warning(
                f"[BridgeDispatcher] Fleet dispatch failed: {e}"
            )

        # Mark bridge_job failed
        if bridge_job_id:
            try:
                conn = self._get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET status = 'failed',
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (bridge_job_id,),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as _exc:
                pass

        return None

    # ================================================================
    # Image Generation Escalation (Project #164)
    # 4-tier: Node ComfyUI → Hub ComfyUI → Free Cloud → Paid Cloud
    # ================================================================

    def _select_comfyui_host(self) -> tuple:
        """Find the best available ComfyUI host.

        Returns (comfyui_url, node_db_id) or (None, None) if all busy.
        Priority: fleet nodes (faster GPUs) → hub (fallback).
        """
        # Check fleet nodes first
        try:
            from ai_bridge.node_router import select_best_image_node

            node_info = select_best_image_node("comfyui")
            if node_info:
                node_hostname = node_info.get("hostname") or node_info.get("vpn_ip")
                node_port = node_info.get("comfyui_port", 8188)
                node_db_id = node_info.get("id")
                if not self._is_image_host_busy(node_hostname):
                    url = f"http://{node_hostname}:{node_port}"
                    logger.info(
                        "[ImageEscalation] Node ComfyUI available: %s (id=%s)",
                        url,
                        node_db_id,
                    )
                    return url, node_db_id
                logger.info("[ImageEscalation] Node ComfyUI busy, trying hub")
        except Exception as e:
            logger.warning("[ImageEscalation] Node router check failed: %s", e)

        # Fall back to hub ComfyUI
        hub_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
        if not self._is_image_host_busy("hub"):
            logger.info("[ImageEscalation] Hub ComfyUI available: %s", hub_host)
            return hub_host, None

        logger.info("[ImageEscalation] All local ComfyUI hosts busy")
        return None, None

    def _is_image_host_busy(self, target_host: str) -> bool:
        """Check bridge_jobs metadata for running image_generation jobs on a host."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*) FROM bridge_jobs
                WHERE job_type = 'image_generation'
                  AND status = 'running'
                  AND metadata->>'target_host' = %s
                """,
                (target_host,),
            )
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return count > 0
        except Exception:
            return False

    def _escalate_image_to_cloud(
        self,
        agent_name: str,
        agent: Dict,
        prompt: str,
        context: Dict,
        station_code: str,
        capability: str,
        module_id: str,
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ) -> "DispatchResult":
        """Escalate image gen to cloud: free contractors (Tier 1), then paid (Tier 2).

        Free cloud providers auto-execute. Paid providers require async
        Telegram approval via contractor_approval_requests.
        """
        agent_id = agent.get("id")

        # --- Tier 1: Free cloud contractors (auto-approve) ---
        try:
            from ai_bridge.external_providers import (
                generate_media,
                get_providers_with_capability,
            )

            free_providers = [
                p
                for p in get_providers_with_capability("image_gen")
                if p.get("tier_position", 99) <= 4
                and p.get("provider_key") not in ("comfyui", "ollama_diffuser")
            ]
            for provider in free_providers:
                pkey = provider["provider_key"]
                logger.info("[ImageEscalation] Trying free cloud: %s", pkey)
                try:
                    result = generate_media(
                        pkey,
                        {
                            "type": "image",
                            "prompt": prompt,
                            "params": context.get("image_params", {}),
                        },
                    )
                    if result and result.get("success"):
                        # Log usage
                        self._log_cloud_image_usage(
                            pkey, user_id, result.get("cost_usd", 0)
                        )
                        return DispatchResult(
                            success=True,
                            response=result.get("file_path", ""),
                            agent_name=agent_name,
                            agent_id=agent_id,
                            model_used=result.get("model", pkey),
                            station_code=station_code,
                            capability=capability,
                            provider=pkey,
                            metadata={
                                "file_path": result.get("file_path"),
                                "provider": pkey,
                                "escalation": "free_cloud",
                            },
                        )
                except Exception as e:
                    logger.warning(
                        "[ImageEscalation] Free cloud %s failed: %s", pkey, e
                    )
        except ImportError:
            logger.warning("[ImageEscalation] external_providers not available")

        # --- Tier 2: Paid cloud contractors (async Telegram approval) ---
        logger.info(
            "[ImageEscalation] All free options exhausted, submitting Tier 2 approval"
        )

        # Create pending bridge_job
        pending_job_id = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES ('image_generation', %s, %s, 1, 'pending_approval', %s, %s, %s)
                RETURNING id
                """,
                (
                    module_id,
                    f"Cloud image gen (pending approval): {prompt[:60]}",
                    agent_name,
                    station_code,
                    json.dumps({
                        "target_host": "cloud",
                        "prompt": prompt,
                        "escalation": "paid_cloud",
                        "user_id": user_id,
                        "image_params": context.get("image_params", {}),
                    }),
                ),
            )
            pending_job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error("[ImageEscalation] Failed to create pending job: %s", e)

        # Submit async approval via Telegram
        try:
            from ai_bridge.agent_loop import request_approval

            request_approval(
                action_type="cloud_throughput_escalation",
                action_data={
                    "job_id": pending_job_id,
                    "prompt": prompt[:100],
                    "capability": "image_gen",
                },
                reason=(
                    "All local + free cloud image generators busy. "
                    "Paid cloud image generation requested."
                ),
                tier=2,
            )
        except Exception as e:
            logger.error("[ImageEscalation] Failed to submit approval: %s", e)

        return DispatchResult(
            success=False,
            response="Image generation queued — awaiting cloud approval via Telegram",
            agent_name=agent_name,
            agent_id=agent_id,
            model_used="pending",
            station_code=station_code,
            capability=capability,
            provider="cloud_pending",
            metadata={
                "escalation": "pending_approval",
                "job_id": pending_job_id,
            },
        )

    def _log_cloud_image_usage(
        self, provider: str, user_id: Optional[int], cost_usd: float
    ):
        """Log cloud image generation to cloud_model_usage."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO cloud_model_usage
                    (model_name, provider, prompt_tokens, completion_tokens,
                     cost_usd, user_id, task_type, success)
                VALUES (%s, %s, 0, 0, %s, %s, 'image_generation', true)
                """,
                (f"{provider}_image", provider, cost_usd, user_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning("[ImageEscalation] Failed to log usage: %s", e)

    def _execute_comfyui(
        self,
        agent_name: str,
        agent: Dict,
        image_model: str,
        prompt: str,
        context: Dict,
        station_code: str,
        capability: str,
        module_id: str,
        user_id: Optional[int] = None,
        job_id: Optional[int] = None,
    ) -> "DispatchResult":
        """Execute image generation with 4-tier escalation.

        1. Fleet node ComfyUI (fastest GPU) → free
        2. Hub ComfyUI (fallback) → free
        3. Free cloud contractors (HuggingFace, Cloudflare) → free
        4. Paid cloud contractors (DALL-E 3, Imagen 3) → Telegram approval

        Handles VRAM management, creates bridge_job for tracking, returns DispatchResult.
        """
        from ai_bridge.comfyui_service import ComfyUIService

        agent_id = agent.get("id")

        # --- Escalation: find best available ComfyUI host ---
        comfyui_host, node_db_id = self._select_comfyui_host()

        if comfyui_host is None:
            # All local ComfyUI busy → escalate to cloud
            return self._escalate_image_to_cloud(
                agent_name, agent, prompt, context,
                station_code, capability, module_id, user_id, job_id,
            )

        # --- Instantiate ComfyUI service with selected host ---
        comfyui = ComfyUIService(host=comfyui_host)
        target_host = "hub" if node_db_id is None else (
            comfyui_host.replace("http://", "").split(":")[0]
        )

        # --- Create bridge_job to mark agent busy ---
        bridge_job_id = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, station_code, metadata)
                VALUES ('image_generation', %s, %s, 1, 'running', %s, %s, %s)
                RETURNING id
                """,
                (
                    module_id,
                    f"Image gen: {prompt[:80]}",
                    agent_name,
                    station_code,
                    json.dumps({
                        "image_model": image_model,
                        "provider": "comfyui",
                        "capability": capability,
                        "target_host": target_host,
                        "comfyui_host": comfyui_host,
                        "node_db_id": node_db_id,
                    }),
                ),
            )
            bridge_job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            self._busy_agents.add(agent_name)
            logger.info(
                "[BridgeDispatcher] ComfyUI job #%s started: %s → %s (%s)",
                bridge_job_id, agent_name, target_host, image_model,
            )
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Failed to create bridge_job: {e}")

        # --- VRAM swap: unload Ollama GPU models if SDXL needs full GPU ---
        ollama_models_unloaded = []
        is_xl = "xl" in image_model.lower()
        if is_xl:
            ollama_models_unloaded = self._vram_swap_for_comfyui(node_db_id)

        # --- Determine resolution ---
        width, height = (1024, 1024) if is_xl else (512, 512)
        width = context.get("width", width)
        height = context.get("height", height)
        steps = context.get("steps", 20)
        cfg = context.get("cfg", 7.0)

        # --- Generate image ---
        try:
            result = comfyui.generate_image(
                prompt=prompt,
                model=image_model,
                steps=steps,
                width=width,
                height=height,
                cfg=cfg,
            )
        except Exception as e:
            result = None
            logger.error(f"[BridgeDispatcher] ComfyUI generation error: {e}")

        # --- Reload Ollama GPU models after SDXL ---
        if ollama_models_unloaded:
            self._vram_restore_after_comfyui(ollama_models_unloaded, node_db_id)

        # --- Complete bridge_job ---
        if bridge_job_id:
            try:
                conn = self._get_db()
                cur = conn.cursor()
                success = result and result.success
                cur.execute(
                    """
                    UPDATE bridge_jobs
                    SET status = %s, completed_steps = 1, completed_at = NOW()
                    WHERE id = %s
                    """,
                    ("completed" if success else "failed", bridge_job_id),
                )
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                logger.error(f"[BridgeDispatcher] Failed to complete bridge_job: {e}")
            self._busy_agents.discard(agent_name)

        # --- Build DispatchResult ---
        if result and result.success:
            metadata = result.metadata or {}
            metadata["file_path"] = result.file_path
            metadata["bridge_job_id"] = bridge_job_id
            metadata["target_host"] = target_host
            if ollama_models_unloaded:
                metadata["vram_swap"] = ollama_models_unloaded
            return DispatchResult(
                success=True,
                response=result.file_path,
                agent_name=agent_name,
                agent_id=agent_id,
                model_used=image_model,
                station_code=station_code,
                capability=capability,
                provider="comfyui",
                metadata=metadata,
            )
        else:
            error_msg = result.error if result else "ComfyUI service unreachable"
            # If local ComfyUI failed, try cloud escalation
            if not result or not result.success:
                logger.info(
                    "[ImageEscalation] Local ComfyUI on %s failed, trying cloud",
                    target_host,
                )
                cloud_result = self._escalate_image_to_cloud(
                    agent_name, agent, prompt, context,
                    station_code, capability, module_id, user_id, job_id,
                )
                if cloud_result.success:
                    return cloud_result

            return DispatchResult(
                success=False,
                response="",
                agent_name=agent_name,
                agent_id=agent_id,
                model_used=image_model,
                station_code=station_code,
                capability=capability,
                provider="comfyui",
                error=error_msg,
                metadata={"bridge_job_id": bridge_job_id},
            )

    # ================================================================
    # RAG Auto-Context Injection (Task #1130)
    # ================================================================
    _rag_cache: Dict[str, Any] = {}  # {cache_key: {"ts": float, "context": str}}
    _RAG_CACHE_TTL = 300  # 5 minutes
    _RAG_MIN_RELEVANCE = 0.7
    _RAG_MAX_ENTRIES = 3

    def _is_auto_context_enabled(self) -> bool:
        """Check platform_settings for rag_auto_context flag."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT value FROM platform_settings WHERE key = 'rag_auto_context'"
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0].lower() in ("true", "1", "enabled") if row else False
        except Exception:
            return False

    def _get_rag_context(self, prompt: str) -> Optional[str]:
        """
        Retrieve relevant KB context for a prompt via semantic search.

        Returns a formatted context string to prepend, or None if no
        relevant results found. Results are cached for 5 minutes keyed
        on the first 200 chars of the prompt.
        """
        import hashlib

        cache_key = hashlib.md5(prompt[:200].encode()).hexdigest()
        now = time.time()

        # Check cache
        cached = self._rag_cache.get(cache_key)
        if cached and (now - cached["ts"]) < self._RAG_CACHE_TTL:
            return cached["context"]

        try:
            from ai_bridge.semantic_search import search as semantic_search

            results = semantic_search(prompt, limit=self._RAG_MAX_ENTRIES)
            if not results:
                self._rag_cache[cache_key] = {"ts": now, "context": None}
                return None

            # Filter by relevance threshold
            relevant = [r for r in results if r.score and r.score >= self._RAG_MIN_RELEVANCE]
            if not relevant:
                self._rag_cache[cache_key] = {"ts": now, "context": None}
                return None

            # Build context block
            parts = ["[Auto-Context from Knowledge Base]"]
            for r in relevant:
                title = r.title or f"KB#{r.id}"
                content = (r.content or "")[:800]
                parts.append(f"--- {title} (relevance: {r.score:.2f}) ---\n{content}")
            parts.append("[End Auto-Context]\n")

            context_str = "\n".join(parts)
            self._rag_cache[cache_key] = {"ts": now, "context": context_str}

            # Evict old cache entries (keep max 100)
            if len(self._rag_cache) > 100:
                oldest_keys = sorted(
                    self._rag_cache, key=lambda k: self._rag_cache[k]["ts"]
                )[:50]
                for k in oldest_keys:
                    self._rag_cache.pop(k, None)

            return context_str

        except Exception as e:
            logger.debug(f"[BridgeDispatcher] RAG context retrieval failed: {e}")
            self._rag_cache[cache_key] = {"ts": now, "context": None}
            return None

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
            from ai_bridge.archie_bridge import call_ollama, call_ollama_json, call_ollama_cloud

            # Route to external providers — dynamic lookup from contractor_providers DB
            from ai_bridge.external_providers import (
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

            # Auto warm-boot: ensure model is loaded before calling Ollama
            try:
                readiness = self.ensure_model_ready("_dispatch", model)
                if readiness and not readiness.get("ready"):
                    logger.warning(f"[BridgeDispatcher] Model {model} not ready: {readiness}")
            except Exception as wb_err:
                logger.debug(f"[BridgeDispatcher] Warm boot check failed: {wb_err}")

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

            # Standard call (routes through node_router for starship nodes)
            result = call_ollama(
                prompt, model=model, system_prompt=system_prompt,
                prefer_gpu=prefer_gpu, timeout=timeout,
            )
            # Tag starship node routing in provider field
            node_id = result.get("node_id")
            if node_id and node_id != "archie-starbase":
                result["provider"] = f"starship:{node_id}"
                logger.info(
                    f"[BridgeDispatcher] Routed {model} to starship node {node_id}"
                )
            return result
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
            # Determine worker_type from escalation metadata
            meta = result.metadata or {}
            is_contractor = meta.get("is_cloud", False)
            worker_type = "contract" if is_contractor else "internal"

            cur.execute(
                """
                INSERT INTO task_execution_log (
                    agent_id, agent_name, module_source, task_type, capability,
                    model_used, provider, prompt_tokens, completion_tokens,
                    tokens_used, duration_ms, success, error_message,
                    station_code, requested_by, priority, request_metadata, job_id,
                    worker_type
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s
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
                    worker_type,
                ),
            )
            # Also update agent-level performance summary
            # Skip when contractor did the work — don't credit the agent
            if result.agent_id and not is_contractor:
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
            # Record agent memory from this task execution
            self._record_agent_memory(result, module_id)
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

    def _record_agent_memory(self, result: DispatchResult, module_id: str):
        """Create an agent_memory record summarising what the agent did.

        Keeps memories brief (no LLM call) — just logs the task capability,
        module, model used, and outcome so the MEM tab has content.
        """
        if not result.agent_id:
            return
        # Skip contractor/cloud work — memory belongs to internal agents
        meta = result.metadata or {}
        if meta.get("is_cloud"):
            return
        try:
            # Build a concise memory string
            outcome = "completed successfully" if result.success else f"failed: {result.error or 'unknown error'}"
            content = (
                f"Handled {result.capability or 'task'} for {module_id} "
                f"using {result.model_used or 'unknown model'}. "
                f"Task {outcome}."
            )
            # Determine memory type & importance
            memory_type = "skill" if result.success else "interaction"
            importance = 0.55 if result.success else 0.65  # failures slightly more important to remember

            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_memory
                    (agent_id, memory_type, content, importance_score,
                     source_module, context)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    result.agent_id,
                    memory_type,
                    content,
                    importance,
                    module_id,
                    json.dumps({
                        "capability": result.capability,
                        "model": result.model_used,
                        "station": result.station_code,
                        "duration_ms": result.duration_ms,
                        "success": result.success,
                        "tokens": result.prompt_tokens + result.completion_tokens,
                    }),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Agent memory skipped: {e}")

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
        except Exception as _exc:
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
        except Exception as _exc:
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
        except Exception as _exc:
            return "auto"

    # Cloud contractor models (free via OLLAMA_API_KEY)
    FREE_CLOUD_MODELS = [
        "minimax-m2.5:cloud",
        "qwen3-coder-next:cloud",
    ]

    # Proficiency tier mapping: level → tier name
    _PROFICIENCY_TIERS = {1: "novice", 2: "novice", 3: "intermediate", 4: "advanced", 5: "advanced"}

    def _augment_for_proficiency(
        self,
        agent_name: str,
        capability: str,
        proficiency_level: int,
        system_prompt: Optional[str],
        routing_mode: str,
    ) -> tuple:
        """Augment system prompt and optionally override model based on proficiency.

        Returns (augmented_system_prompt, model_override_or_None).
        """
        tier = self._PROFICIENCY_TIERS.get(proficiency_level, "novice")

        # Query skill_training_templates for this capability + tier
        try:
            from database import get_db

            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT system_prompt_addon, model_override "
                "FROM skill_training_templates WHERE skill_name = %s AND level_tier = %s",
                (capability, tier),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] _augment_for_proficiency DB error: {e}")
            return (system_prompt, None)

        if not row:
            return (system_prompt, None)

        addon, model_override = row

        # Append proficiency addon to system prompt
        if addon and system_prompt:
            system_prompt = system_prompt + "\n\n--- PROFICIENCY GUIDANCE (" + tier.upper() + ") ---\n" + addon + "\n--- END PROFICIENCY GUIDANCE ---"
        elif addon:
            system_prompt = addon

        # Model override only for advanced tier + CAPABILITY_REQUIRES_SKILL tasks
        resolved_override = None
        if (
            proficiency_level >= 4
            and model_override
            and capability in CAPABILITY_REQUIRES_SKILL
        ):
            is_cloud = ":cloud" in model_override or model_override in (
                "minimax-m2.5",
                "qwen3-coder-next",
            )
            is_paid = any(
                model_override.startswith(p)
                for p in ("gpt-4o", "llama-3.1-sonar", "grok", "claude")
            )

            if routing_mode == "local_only":
                # Block all cloud/external overrides
                resolved_override = None
            elif routing_mode == "local_cloud" and is_paid:
                # Block paid, allow free cloud
                resolved_override = None
            elif proficiency_level == 4 and is_paid:
                # Lv4 only gets free cloud
                resolved_override = None
            else:
                resolved_override = model_override

            if resolved_override:
                logger.info(
                    f"[BridgeDispatcher] Proficiency override: agent='{agent_name}' "
                    f"capability='{capability}' level={proficiency_level} "
                    f"tier='{tier}' model_override='{resolved_override}'"
                )

        # Check for active training with failure analysis — inject coaching context
        try:
            conn2 = get_db()
            cur2 = conn2.cursor()
            cur2.execute("""
                SELECT failure_analysis FROM training_assignments
                WHERE agent_id = (SELECT id FROM agents WHERE name = %s LIMIT 1)
                  AND skill_name = %s AND status = 'in_progress'
                  AND failure_analysis IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """, (agent_name, capability))
            training_row = cur2.fetchone()
            cur2.close()
            conn2.close()
            if training_row and training_row[0]:
                coaching = training_row[0][:1500]
                if system_prompt:
                    system_prompt += (
                        "\n\n--- ACTIVE TRAINING: FAILURE CORRECTION ---\n"
                        + coaching
                        + "\nApply these corrections to improve your performance.\n"
                        "--- END TRAINING CONTEXT ---"
                    )
                else:
                    system_prompt = coaching
        except Exception as e:
            logger.debug(f"[BridgeDispatcher] Training context lookup error: {e}")

        return (system_prompt, resolved_override)

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

        # ALL cloud escalation requires Telegram approval (3-slot model).
        # Cloud is the 4th slot — always needs human approval.
        logger.info(
            f"[BridgeDispatcher] Cloud approval required: {agent_name} busy "
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
                    "escalation_mode": escalation_mode,
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
                reason=f"Throughput: awaiting cloud approval",
                failure_count=0,
                approval_method="telegram",
                success=None,
            )
        except Exception as esc_err:
            logger.warning(
                f"[BridgeDispatcher] Cloud approval request failed: {esc_err}"
            )
        return None  # Always return None — no auto-cloud

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
            from ai_bridge.smart_router import SmartRouter, TIER_ORDER

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
            except Exception as _exc:
                pass
            return None

    # ========================================================================
    # ========================================================================
    # FLEET DISPATCH
    # ========================================================================

    def _dispatch_to_remote_node(
        self, agent_info, capability, prompt, module_id,
        system_prompt, station_code, start_time,
    ):
        """Dispatch a job to a remote node via mesh_sync_log."""
        import json as _json

        node_id = agent_info["node_id"]
        agent_name = agent_info.get("name", "unknown")
        payload = {
            "capability": capability,
            "prompt": prompt,
            "module_id": module_id,
            "system_prompt": system_prompt,
            "target_agent": agent_name,
            "target_model": agent_info.get("model"),
            "station_codes": agent_info.get("station_codes", []),
        }

        try:
            from psycopg2.extras import RealDictCursor

            conn = self._get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                INSERT INTO mesh_sync_log
                    (node_id, sync_type, payload, status, sent_at)
                VALUES (%s, 'job_request', %s, 'sent', NOW())
                RETURNING id
                """,
                (node_id, _json.dumps(payload)),
            )
            sync_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Fleet dispatch DB error: {e}")
            # Fall back to ARCHIE on failure
            return DispatchResult(
                success=False,
                response=f"Fleet dispatch failed: {e}",
                agent_name="ARCHIE",
                agent_id=2,
                model_used="fallback",
                station_code=station_code,
                capability=capability,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"[BridgeDispatcher] Fleet dispatch: job_request #{sync_id} "
            f"to {node_id} agent {agent_name} for '{capability}'"
        )

        return DispatchResult(
            success=True,
            response=f"Dispatched to fleet node {node_id} agent {agent_name}",
            agent_name=agent_name,
            agent_id=agent_info.get("id"),
            model_used=agent_info.get("model", "unknown"),
            station_code=station_code,
            capability=capability,
            duration_ms=duration_ms,
            metadata={
                "fleet_dispatch": True,
                "sync_id": sync_id,
                "node_id": node_id,
                "hostname": agent_info.get("hostname"),
            },
        )

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
        prefer_agent: Optional[str] = None,
        local_only: bool = False,
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
            prefer_agent: Lock dispatch to this agent (for batch consistency).
                          The agent stays assigned for all items in a batch job.
            local_only: Force local-only routing (no cloud/external models).
                        Used by batch/loop jobs to avoid cloud escalation.

        Returns:
            DispatchResult with response, agent info, and metrics
        """
        start = time.time()

        # Force-refresh busy agents list (bypass 30s welfare cache TTL)
        try:
            from psycopg2.extras import RealDictCursor

            bconn = self._get_db()
            bcur = bconn.cursor(cursor_factory=RealDictCursor)
            if job_id:
                # Exclude the current batch job — the assigned agent should be
                # available for work within its own batch, not blocked by it.
                bcur.execute(
                    "SELECT DISTINCT agent_name FROM bridge_jobs "
                    "WHERE status = 'running' AND id != %s",
                    (job_id,),
                )
            else:
                bcur.execute(
                    "SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'"
                )
            self._busy_agents = {r["agent_name"] for r in bcur.fetchall()}
            # Batch agent lock: always unblock the preferred agent so they
            # handle every item in the batch, not just the first.
            if prefer_agent:
                self._busy_agents.discard(prefer_agent)
            # Auto-resolve prefer_agent from job_id for batch consistency —
            # any caller that passes job_id gets the same agent automatically.
            if job_id and not prefer_agent:
                bcur.execute(
                    "SELECT agent_name FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = bcur.fetchone()
                if row and row["agent_name"]:
                    prefer_agent = row["agent_name"]
                    self._busy_agents.discard(prefer_agent)
            bcur.close()
            bconn.close()
        except Exception as busy_err:
            logger.debug(f"[BridgeDispatcher] Busy agents refresh failed: {busy_err}")

        # 1. Map capability → station (home-first, mission-profile-aware)
        capability_station = self._resolve_station(capability)
        home_station = self._resolve_module_station(module_id)

        agent = None
        dispatch_station = capability_station
        is_cross_station = False

        # skip_busy_refresh=True: request_work() already set _busy_agents
        # with proper job_id exclusion + prefer_agent handling above.
        # Don't let _refresh_welfare_cache() overwrite it.
        _sbr = bool(prefer_agent or job_id)

        # 1a. If prefer_agent is set, force-select that specific agent
        #     (used by benchmarks to test each agent individually).
        if prefer_agent and prefer_agent in self._agent_cache:
            agent = self._agent_cache[prefer_agent]
            dispatch_station = agent.get("station_code", capability_station)
        elif home_station:
            agent = self._select_agent(capability, home_station, skip_busy_refresh=_sbr)
            if agent:
                dispatch_station = home_station
            else:
                # Home station can't handle — fall to capability station
                agent = self._select_agent(capability, capability_station, skip_busy_refresh=_sbr)
                dispatch_station = capability_station
                is_cross_station = home_station != capability_station
        else:
            agent = self._select_agent(capability, capability_station, skip_busy_refresh=_sbr)
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
            #     Enforce max_auxiliary: only 1 cross-station helper per station.
            aux_ok, aux_count, max_aux, aux_reason = self._station_aux_available(
                blocked_station
            )
            if not aux_ok:
                logger.info(
                    f"[BridgeDispatcher] {blocked_station} aux blocked: "
                    f"{aux_reason}. Skipping cross-station → cloud."
                )
            else:
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

        # 2b. Fleet node fallback — check remote nodes for available agents
        if not agent and station_exhausted:
            blocked_station = home_station or capability_station
            fleet_agent = self._find_fleet_agent(
                blocked_station, capability
            )
            if fleet_agent:
                logger.info(
                    f"[BridgeDispatcher] Fleet fallback: hub exhausted → "
                    f"dispatching to {fleet_agent['agent_name']}@"
                    f"{fleet_agent['node_name']} for '{capability}'"
                )
                fleet_result = self._dispatch_to_node(
                    agent_info=fleet_agent,
                    prompt=prompt,
                    system_prompt=system_prompt,
                    options={"temperature": 0.7},
                    capability=capability,
                    module_id=module_id,
                    station_code=blocked_station,
                    user_id=user_id,
                    job_id=job_id,
                )
                if fleet_result and fleet_result.get("success"):
                    duration_ms = int((time.time() - start) * 1000)

                    self._telegram_dispatch_advisory(
                        advisory_type="cross_station",
                        module_id=module_id,
                        home_station=blocked_station,
                        dispatch_station=f"FLEET→{fleet_agent['node_name']}",
                        capability=capability,
                        agent_name=fleet_agent["agent_name"],
                        reason=(
                            f"Hub agents busy at {blocked_station}. "
                            f"Dispatched to fleet node "
                            f"{fleet_agent['node_name']}."
                        ),
                    )

                    # Log capacity event for fleet dispatch
                    self._log_capacity_event(
                        station_code=blocked_station,
                        event_type="fleet_dispatch",
                        agent_name=fleet_agent["agent_name"],
                        capability=capability,
                        reason=(
                            f"Fleet dispatch to {fleet_agent['node_name']} "
                            f"({fleet_agent['node_hostname']})"
                        ),
                        metadata={
                            "node_id": fleet_agent["node_id"],
                            "node_name": fleet_agent["node_name"],
                            "model": fleet_agent["model"],
                            "is_remote": True,
                        },
                    )

                    result = DispatchResult(
                        success=True,
                        response=fleet_result.get("response", ""),
                        agent_name=fleet_agent["agent_name"],
                        agent_id=None,
                        model_used=fleet_agent["model"],
                        station_code=blocked_station,
                        capability=capability,
                        duration_ms=duration_ms,
                        prompt_tokens=fleet_result.get("prompt_tokens", 0),
                        completion_tokens=fleet_result.get(
                            "completion_tokens", 0
                        ),
                        provider="fleet_node",
                        metadata={
                            "escalation": "fleet_dispatch",
                            "blocked_station": blocked_station,
                            "home_station": home_station,
                            "dispatch_station": f"FLEET→{fleet_agent['node_name']}",
                            "is_cross_station": True,
                            "is_remote": True,
                            "node_id": fleet_agent["node_id"],
                            "node_name": fleet_agent["node_name"],
                            "node_hostname": fleet_agent["node_hostname"],
                            "capability_station": capability_station,
                        },
                    )
                    self._log_execution(
                        result, module_id, user_id, job_id=job_id
                    )
                    return result
                else:
                    logger.info(
                        f"[BridgeDispatcher] Fleet dispatch failed for "
                        f"'{capability}' — falling through to cloud"
                    )

        if not agent and station_exhausted:
            blocked_station = home_station or capability_station

            # 2c. All 3 station slots (Primary + Secondary + Auxiliary) are
            #     full.  Cloud is the 4th slot — requires Telegram approval.
            routing_mode = "local_only" if local_only else self._get_routing_mode()
            if routing_mode != "local_only":
                try:
                    from agent_loop import request_approval

                    busy_names = [
                        self._agent_display(aname)
                        for aname, ainfo in self._agent_cache.items()
                        if ainfo.get("station_code") == blocked_station
                    ]
                    busy_str = ", ".join(busy_names) or blocked_station

                    logger.info(
                        f"[BridgeDispatcher] {blocked_station} at full capacity "
                        f"(3 slots). Requesting cloud approval via Telegram."
                    )
                    request_approval(
                        action_type="cloud_throughput_escalation",
                        action_data={
                            "original_agent": busy_str,
                            "busy_job": {
                                "id": 0,
                                "description": (
                                    f"Station {blocked_station} at full capacity "
                                    f"(Primary + Secondary + Auxiliary filled)"
                                ),
                                "progress_pct": 0,
                            },
                            "escalated_model": self.FREE_CLOUD_MODELS[0],
                            "escalated_provider": "ollama_cloud",
                            "capability": capability,
                            "module_id": module_id,
                            "prompt_preview": prompt[:200] if prompt else "",
                        },
                        reason=(
                            f"Station {blocked_station} at full capacity "
                            f"(all 3 slots filled). Approve cloud contractor "
                            f"for '{capability}'?"
                        ),
                        requested_by="bridge_dispatcher",
                        tier=2,
                    )
                except Exception as cloud_req_err:
                    logger.warning(
                        f"[BridgeDispatcher] Cloud approval request failed: "
                        f"{cloud_req_err}"
                    )

                # Also send Telegram advisory for visibility
                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_id,
                    home_station=blocked_station,
                    dispatch_station="CLOUD",
                    capability=capability,
                    reason=(
                        f"All 3 slots at {blocked_station} are filled "
                        f"for '{capability}'. Cloud approval requested."
                    ),
                )

            # 2d. Try free cloud contractors (only if escalation_mode is auto)
            escalation_mode = self._get_escalation_mode()
            if routing_mode != "local_only" and escalation_mode == "auto":
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
                        # ── Capacity event: cloud contractor (ADR-055) ──
                        self._log_capacity_event(
                            station_code=blocked_station,
                            event_type="cloud_contractor",
                            agent_name=f"CLOUD→{cloud_model}",
                            capability=capability,
                            reason=f"Cloud contractor {cloud_model} for {capability}",
                            metadata={
                                "cloud_model": cloud_model,
                                "module_id": module_id,
                            },
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

            # 2e. Free cloud failed — request paid cloud via Telegram approval
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

        # 2f. Fleet: if selected agent is on a remote node, dispatch via mesh
        if agent and agent.get("is_remote"):
            return self._dispatch_to_remote_node(
                agent, capability, prompt, module_id, system_prompt,
                station_code, start,
            )

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

        # 3.5 Proficiency-aware augmentation
        skill_entry = agent.get("skills", {}).get(capability, {})
        proficiency_level = skill_entry.get("level", 1) if skill_entry else 1

        augmented_prompt, model_override = self._augment_for_proficiency(
            agent_name, capability, proficiency_level,
            system_prompt, "local_only" if local_only else self._get_routing_mode(),
        )
        system_prompt = augmented_prompt
        if model_override:
            model = model_override

        logger.info(
            f"[BridgeDispatcher] Dispatching: capability='{capability}' → "
            f"agent='{agent_name}' model='{model}' station='{station_code}' "
            f"module='{module_id}' proficiency=Lv{proficiency_level}"
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

        # 3b. Inject learnings if available (proficiency scales card count)
        try:
            from bridge_learning import inject_learnings

            prompt = inject_learnings(
                agent_name, capability, prompt,
                proficiency_level=proficiency_level,
            )
        except ImportError:
            pass

        # 3c. Routing mode enforcement
        # Ensures the bridge UI toggle (local_only/local_cloud/full) controls dispatch
        routing_mode = "local_only" if local_only else self._get_routing_mode()
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

        # ── Capacity event logging (ADR-055) ──
        occupancy = self._get_station_slot_occupancy(station_code)
        if is_cross_station:
            slot_number = (
                occupancy["primary"] + occupancy["auxiliary"] + 1
            )
            max_cap = (
                occupancy["max_primary"] + occupancy["max_auxiliary"]
            )
            cap_event_type = (
                "auxiliary_filled"
                if slot_number <= max_cap
                else "overflow_dispatch"
            )
        else:
            slot_number = occupancy["primary"] + 1
            cap_event_type = "primary_dispatch"
        self._log_capacity_event(
            station_code=station_code,
            event_type=cap_event_type,
            agent_id=agent.get("id") if agent else None,
            agent_name=agent_name,
            capability=capability,
            slot_number=slot_number,
            reason=f"{'cross-station' if is_cross_station else 'primary'} dispatch for {capability}",
            metadata={
                "module_id": module_id,
                "is_cross_station": is_cross_station,
            },
        )

        # 4. Execute — ComfyUI branch for image generation, LLM for everything else
        escalation_info = None  # Tracks failure→cloud escalation for metrics
        original_model = model  # Preserve for escalation metadata

        image_model = (context or {}).get("image_model") or agent.get("image_model")
        if capability == "image_generation" and image_model:
            # Route to ComfyUI instead of Ollama
            comfyui_result = self._execute_comfyui(
                agent_name=agent_name,
                agent=agent,
                image_model=image_model,
                prompt=prompt,
                context=context or {},
                station_code=station_code,
                capability=capability,
                module_id=module_id,
                user_id=user_id,
                job_id=job_id,
            )
            duration_ms = int((time.time() - start) * 1000)
            comfyui_result.duration_ms = duration_ms
            self._log_execution(comfyui_result, module_id, user_id, job_id=job_id)
            return comfyui_result

        # 4a. RAG auto-context injection (Task #1130)
        #     Prepend relevant KB entries to the prompt when enabled.
        #     Skips JSON mode (structured output) and image generation.
        rag_injected = False
        if not json_mode and self._is_auto_context_enabled():
            try:
                rag_context = self._get_rag_context(prompt)
                if rag_context:
                    prompt = f"{rag_context}\n{prompt}"
                    rag_injected = True
                    logger.debug(
                        f"[BridgeDispatcher] RAG context injected "
                        f"({len(rag_context)} chars) for {capability}"
                    )
            except Exception as rag_err:
                logger.debug(f"[BridgeDispatcher] RAG injection skipped: {rag_err}")

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
                        escalation_info = {
                            "escalation": "failure_auto_escalation",
                            "original_model": original_model,
                            "is_cloud": True,
                            "cloud_model": next_tier["model"],
                            "cloud_provider": next_tier["provider"],
                            "failure_count": failure_count,
                        }
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
        result_metadata = {
            "module_id": module_id,
            "priority": priority,
            "home_station": agent.get("station_code") if agent and is_cross_station else home_station,
            "dispatch_station": home_station if is_cross_station else dispatch_station,
            "is_cross_station": is_cross_station,
            "capability_station": capability_station,
            "agent_station": agent.get("station_code") if agent else None,
            "module_station": home_station,
        }
        # Merge failure-escalation flags so Bridge Command tracks contractor work
        if escalation_info:
            result_metadata.update(escalation_info)

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
            metadata=result_metadata,
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
        is_overflow: bool = False,
    ):
        """Send Telegram advisory with context-appropriate buttons.

        All escalation types get interactive buttons so the user can
        acknowledge, override, or escalate further.
        """
        # Suppress per-request Telegram for high-volume batch capabilities
        # but ALWAYS notify on cloud escalations (free_cloud, paid_cloud)
        SILENT_CAPABILITIES = {"detect_language"}
        BATCH_SILENT_TYPES = {"cross_station", "same_station"}
        if capability in SILENT_CAPABILITIES and not is_overflow:
            logger.debug(
                f"[BridgeDispatcher] Silent advisory ({advisory_type}) "
                f"for batch capability '{capability}'"
            )
            return
        if capability == "translate" and advisory_type in BATCH_SILENT_TYPES:
            logger.debug(
                f"[BridgeDispatcher] Silent advisory ({advisory_type}) "
                f"for translate batch (cloud escalations still notify)"
            )
            return

        try:
            if advisory_type == "cross_station":
                # Get occupancy at the REQUESTING station (where work is needed),
                # not the agent's home station
                requesting = home_station or dispatch_station or "COMMAND"
                occ = self._get_station_slot_occupancy(requesting)
                slots_used = occ["total"]
                max_cap = occ["max_primary"] + occ["max_auxiliary"]
                is_over = slots_used > max_cap

                agent_label = self._agent_display(agent_name) if agent_name else "an agent"
                station_label = requesting
                home_label = dispatch_station or "another station"

                if is_over:
                    title = "Station Capacity Overflow"
                    message = (
                        f"Commander, {station_label} station is experiencing elevated "
                        f"request volume.\n\n"
                        f"All {max_cap} slots are occupied. "
                        f"{agent_label} from {home_label} "
                        f"dispatched as overflow (slot {slots_used}/{max_cap}) "
                        f"for {capability} task.\n\n"
                        f"Module: {module_id}"
                    )
                    notif_type = "warning"
                    emoji = "\u26a0\ufe0f"
                else:
                    title = "Cross-Station Dispatch"
                    message = (
                        f"Commander, {station_label} station needed assistance "
                        f"with {capability}.\n\n"
                        f"{agent_label} from {home_label} is assisting "
                        f"as auxiliary (slot {slots_used}/{max_cap}).\n\n"
                        f"Module: {module_id}"
                    )
                    notif_type = "info"
                    emoji = "\U0001f500"

                job_str = f" (job #{job_id})" if job_id else ""
                if job_str:
                    message += job_str
                if reason:
                    message += f"\n{reason}"

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
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()

            # ── Advisory lock to prevent race conditions on concurrent create_job ──
            lock_key = hash(f"{job_type}:{module_source}") % (2**31)
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))

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
                conn.rollback()
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

            # Force-refresh busy agents from DB (inside advisory lock transaction)
            cur.execute(
                "SELECT DISTINCT agent_name FROM bridge_jobs WHERE status = 'running'"
            )
            self._busy_agents = {r[0] for r in cur.fetchall()}

            # Resolve agent name from capability→station→agent mapping (home-first)
            cap_key = capability or job_type.split("_")[0]
            capability_station = self._resolve_station(cap_key)
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
            #     Enforce max_auxiliary: only 1 cross-station helper per station.
            #     Use a RealDictCursor on the SAME connection to share the
            #     transaction and its advisory lock, preventing race conditions.
            if not agent:
                blocked_station = home_station or capability_station
                from psycopg2.extras import RealDictCursor

                aux_cur = conn.cursor(cursor_factory=RealDictCursor)
                aux_ok, aux_count, max_aux, aux_reason = self._station_aux_available(
                    blocked_station, cur=aux_cur
                )
                aux_cur.close()

                if not aux_ok:
                    logger.info(
                        f"[BridgeDispatcher] create_job: {blocked_station} "
                        f"aux blocked: {aux_reason}. "
                        f"Skipping cross-station → cloud approval."
                    )
                else:
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
                # All 3 station slots (Primary + Secondary + Auxiliary) are
                # full.  Request cloud approval via Telegram and REJECT the
                # job so no orphan (agentless) jobs are created.
                blocked_station = home_station or capability_station
                logger.info(
                    f"[BridgeDispatcher] create_job: {blocked_station} at "
                    f"full capacity for '{cap_key}'. Requesting cloud approval."
                )

                try:
                    from agent_loop import request_approval

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
                                "description": (
                                    f"Station {blocked_station} at full capacity "
                                    f"(Primary + Secondary + Auxiliary filled). "
                                    f"Job: {description or job_type}"
                                ),
                                "progress_pct": 0,
                            },
                            "escalated_model": self.FREE_CLOUD_MODELS[0],
                            "escalated_provider": "ollama_cloud",
                            "capability": cap_key,
                            "module_id": module_source,
                        },
                        reason=(
                            f"Station {blocked_station} at full capacity. "
                            f"Approve cloud for '{cap_key}' "
                            f"({description or job_type})?"
                        ),
                        requested_by="bridge_dispatcher",
                        tier=2,
                    )
                except Exception as cloud_err:
                    logger.warning(
                        f"[BridgeDispatcher] Cloud approval request failed: "
                        f"{cloud_err}"
                    )

                self._telegram_dispatch_advisory(
                    advisory_type="cross_station",
                    module_id=module_source,
                    home_station=blocked_station,
                    dispatch_station="CLOUD_PENDING",
                    capability=cap_key,
                    reason=(
                        f"All 3 slots at {blocked_station} are filled "
                        f"for '{cap_key}'. Cloud approval requested — "
                        f"job rejected until slot opens."
                    ),
                )

                # REJECT — do not create an orphan job with no agent
                return None

            # Enrich metadata with dispatch info
            # agent_station = the agent's actual home station (for visual shading)
            agent_home = agent.get("station_code") if agent else None
            enriched_meta = dict(metadata or {})
            enriched_meta["home_station"] = agent_home or home_station
            enriched_meta["dispatch_station"] = home_station if is_cross_station else dispatch_station
            enriched_meta["is_cross_station"] = is_cross_station
            enriched_meta["agent_station"] = agent_home
            enriched_meta["module_station"] = home_station

            # ── Capacity check: determine slot number (ADR-055) ──
            occupancy = self._get_station_slot_occupancy(station_code)
            if is_cross_station:
                slot_number = occupancy["max_primary"] + occupancy["auxiliary"] + 1
                if occupancy["auxiliary"] >= occupancy["max_auxiliary"]:
                    if not occupancy["allow_overflow"]:
                        logger.info(
                            f"[CAPACITY] {station_code} at capacity, overflow disabled — "
                            f"job still created but flagged"
                        )
                    slot_number = occupancy["primary"] + occupancy["auxiliary"] + 1
            else:
                slot_number = occupancy["primary"] + 1

            # ── Final DB-level guard: agent must not have another running job ──
            if agent_name:
                cur.execute(
                    """
                    SELECT id, description FROM bridge_jobs
                    WHERE agent_name = %s AND status = 'running'
                    LIMIT 1
                    """,
                    (agent_name,),
                )
                busy_row = cur.fetchone()
                if busy_row:
                    busy_id = busy_row[0]
                    busy_desc = busy_row[1]
                    conn.rollback()
                    cur.close()
                    conn.close()
                    logger.warning(
                        f"[BridgeDispatcher] Agent guard: {agent_name} already running "
                        f"job #{busy_id} ({busy_desc}) — cannot assign new job"
                    )
                    return None

            # ── Station capacity guard: check running jobs at this station ──
            cur.execute(
                """
                SELECT COUNT(*) FROM bridge_jobs
                WHERE station_code = %s AND status = 'running'
                """,
                (station_code,),
            )
            station_running = cur.fetchone()[0]
            max_station = (
                occupancy.get("max_primary", 2) + occupancy.get("max_auxiliary", 1)
            )
            if station_running >= max_station and not occupancy.get("allow_overflow"):
                conn.rollback()
                cur.close()
                conn.close()
                logger.warning(
                    f"[BridgeDispatcher] Station guard: {station_code} at capacity "
                    f"({station_running}/{max_station} running) — job rejected"
                )
                return None

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

            # ── Schema validation: soft-validate input if schema specified ──
            input_schema = enriched_meta.get("input_schema")
            input_data = enriched_meta.get("input_data")
            if input_schema and input_data:
                is_valid, schema_errors = _validate_handoff_schema(
                    input_data, input_schema
                )
                if not is_valid:
                    logger.warning(
                        f"[BridgeDispatcher] Job #{job_id} input schema "
                        f"'{input_schema}' validation failed: {schema_errors}"
                    )
                else:
                    logger.debug(
                        f"[BridgeDispatcher] Job #{job_id} input validated "
                        f"against '{input_schema}'"
                    )

            # ── Capacity event logging (ADR-055) ──
            cap_event_type = "primary_dispatch"
            if is_cross_station:
                max_cap = occupancy.get("max_primary", 2) + occupancy.get(
                    "max_auxiliary", 1
                )
                cap_event_type = (
                    "auxiliary_filled"
                    if slot_number <= max_cap
                    else "overflow_dispatch"
                )
            self._log_capacity_event(
                station_code=station_code,
                event_type=cap_event_type,
                agent_id=agent.get("id") if agent else None,
                agent_name=agent_name,
                job_id=job_id,
                capability=cap_key,
                slot_number=slot_number,
                reason=f"{'cross-station' if is_cross_station else 'primary'} dispatch for {cap_key}",
                metadata={
                    "module_source": module_source,
                    "is_cross_station": is_cross_station,
                },
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
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as _exc:
                    pass

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
        conn = None
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
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as _exc:
                    pass

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
        conn = None
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
                          (EXTRACT(EPOCH FROM (NOW() - created_at)) * 1000)::int,
                          station_code,
                          metadata
                """,
                (status, job_id),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"[BridgeDispatcher] Job #{job_id} → {status}")

            # ── Schema validation: soft-validate output if schema specified ──
            if row and row[9]:
                try:
                    job_meta = (
                        row[9]
                        if isinstance(row[9], dict)
                        else json.loads(row[9])
                    )
                    output_schema = job_meta.get("output_schema")
                    output_data = job_meta.get("output_data")
                    if output_schema and output_data:
                        is_valid, schema_errors = _validate_handoff_schema(
                            output_data, output_schema
                        )
                        if not is_valid:
                            logger.warning(
                                f"[BridgeDispatcher] Job #{job_id} output schema "
                                f"'{output_schema}' validation failed: "
                                f"{schema_errors}"
                            )
                        else:
                            logger.debug(
                                f"[BridgeDispatcher] Job #{job_id} output "
                                f"validated against '{output_schema}'"
                            )
                except Exception as schema_err:
                    logger.debug(
                        f"[BridgeDispatcher] Job #{job_id} output schema "
                        f"check skipped: {schema_err}"
                    )

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
                job_station = row[8] or ""
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

                # ── Capacity event: slot freed (ADR-055) ──
                if job_station:
                    agent_id_for_cap = None
                    if a_name and a_name in self._agent_cache:
                        agent_id_for_cap = self._agent_cache[a_name].get("id")
                    self._log_capacity_event(
                        station_code=job_station,
                        event_type="slot_freed",
                        agent_id=agent_id_for_cap,
                        agent_name=a_name,
                        job_id=job_id,
                        capability=j_type,
                        reason=f"Job {status} — slot freed",
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

                # ── Server-side loop: auto-retrigger next batch ──
                try:
                    from tools.consciousness.processing_routes import server_loop_retrigger

                    server_loop_retrigger(j_type, m_src, status)
                except Exception as loop_err:
                    logger.debug(f"[BridgeDispatcher] server_loop_retrigger skipped: {loop_err}")

            return True
        except Exception as e:
            logger.error(f"[BridgeDispatcher] complete_job failed: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as _exc:
                    pass

    # ========================================================================
    # DURABLE EXECUTION — CHECKPOINTS (Task #955)
    # ========================================================================

    def save_checkpoint(self, job_id, step, total_steps, state=None):
        """Save checkpoint for a running job so it can be resumed on failure."""
        try:
            from database import get_db_cursor
            from psycopg2.extras import Json

            checkpoint = {
                "step": step,
                "total_steps": total_steps,
                "state": state or {},
                "checkpointed_at": datetime.now().isoformat(),
            }
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE bridge_jobs
                       SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{checkpoint}', %s)
                       WHERE id = %s""",
                    (Json(checkpoint), job_id),
                )
            logger.debug(f"[BridgeDispatcher] Checkpoint saved for job #{job_id} at step {step}/{total_steps}")
        except Exception as e:
            logger.debug(f"Checkpoint save failed for job {job_id}: {e}")

    def get_checkpoint(self, job_id):
        """Get checkpoint data for a job, or None if no checkpoint exists."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT metadata->'checkpoint' as checkpoint FROM bridge_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                return row[0] if row and row[0] else None
        except Exception as _exc:
            return None

    def resume_job(self, job_id):
        """Resume a failed job from its last checkpoint.

        Returns dict with resume info on success, None if job not resumable.
        """
        try:
            from database import get_db_cursor
            from psycopg2.extras import RealDictCursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT * FROM bridge_jobs WHERE id = %s AND status = 'failed'",
                    (job_id,),
                )
                job = cur.fetchone()
                if not job:
                    return None

                checkpoint = (job.get("metadata") or {}).get("checkpoint")
                if not checkpoint:
                    return None

                # Reset job to running, keep checkpoint intact for the executor
                cur.execute(
                    """UPDATE bridge_jobs
                       SET status = 'running', error_message = NULL,
                           completed_at = NULL, updated_at = NOW()
                       WHERE id = %s""",
                    (job_id,),
                )

            logger.info(
                f"[BridgeDispatcher] Job #{job_id} resumed from step {checkpoint.get('step')}"
            )
            return {
                "job_id": job_id,
                "resume_from_step": checkpoint.get("step"),
                "state": checkpoint.get("state"),
            }
        except Exception as e:
            logger.debug(f"Resume job failed for {job_id}: {e}")
            return None

    # ========================================================================
    # STALE JOB REAPER
    # ========================================================================

    def reap_stale_jobs(self, max_age_minutes: int = 5, reason: str = "stale — no progress update") -> int:
        """Mark orphaned running jobs as failed.

        Background threads die on platform restart, leaving jobs stuck
        in 'running' state forever. This reaper finds jobs that haven't
        been updated in max_age_minutes and marks them failed.

        Called on startup (max_age_minutes=0) and periodically (max_age_minutes=5).

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
                        || jsonb_build_object('reap_reason', %s)
                WHERE status = 'running'
                  AND updated_at < NOW() - INTERVAL '%s minutes'
                RETURNING id, job_type, description, completed_steps, total_steps
                """,
                (reason, max_age_minutes),
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

    # Approximate model sizes in GB for VRAM/RAM fitting
    MODEL_SIZE_GB = {
        "qwen2.5:1.5b": 1.0,
        "smollm2:1.7b": 1.8,
        "llama3.2:3b": 2.0,
        "phi3.5": 2.2,
        "mistral:7b": 4.4,
        "qwen2.5-coder:7b": 4.7,
        "dolphin3": 4.9,
        "gemma2:9b": 5.4,
        "qwen2.5vl:7b": 6.0,
        "gemma3:12b": 8.1,
        "llama3.1:8b": 4.9,
        "aya:8b": 5.0,
        "qwen2.5:7b": 4.7,
    }

    def assign_agents_to_node(self, node_db_id: int, max_agents: int = 5) -> list:
        """
        Assign barracked agents to a node based on node hardware.

        Rules:
        - Check node's GPU VRAM and RAM from remote_nodes
        - Find barracked agents NOT already on this node
        - Prefer agents whose model size fits the node's VRAM (GPU advantage)
        - Assign up to max_agents
        - Set station_codes based on the node's station assignments
        - If barracked count drops to 5 or below, log advisory notification

        Returns: list of assigned agent names
        """
        from psycopg2.extras import RealDictCursor

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Get node hardware
            cur.execute(
                "SELECT id, gpu_vram_gb, ram_gb FROM remote_nodes WHERE id = %s",
                (node_db_id,),
            )
            node = cur.fetchone()
            if not node:
                logger.warning("assign_agents_to_node: node %s not found", node_db_id)
                return []

            gpu_vram = float(node["gpu_vram_gb"] or 0)
            ram_gb = float(node["ram_gb"] or 0)

            # 2. Get station codes for this node
            cur.execute(
                """
                SELECT bs.station_code
                FROM node_station_assignments nsa
                JOIN bridge_stations bs ON bs.id = nsa.station_id
                WHERE nsa.node_id = %s AND nsa.is_active = TRUE
                ORDER BY bs.station_code
                """,
                (node_db_id,),
            )
            node_stations = [r["station_code"] for r in cur.fetchall()]
            if not node_stations:
                logger.warning(
                    "assign_agents_to_node: node %s has no station assignments",
                    node_db_id,
                )
                return []

            # 3. Find barracked agents NOT already on this node, with real model names
            cur.execute(
                """
                SELECT a.id, a.name, a.first_name, a.last_name,
                       a.display_name, a.title, a.model, a.gpu_tools,
                       ARRAY_AGG(DISTINCT bs.station_code) FILTER (
                           WHERE bs.station_code IS NOT NULL
                       ) as station_codes
                FROM agents a
                LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = TRUE
                LEFT JOIN bridge_stations bs ON bs.id = sa.station_id
                WHERE a.shift_state = 'barracked'
                  AND a.status = 'active'
                  AND (a.model LIKE '%%:%%' OR a.model LIKE '%%/%%')
                  AND a.id NOT IN (
                      SELECT hub_agent_id FROM node_agents
                      WHERE node_id = %s AND hub_agent_id IS NOT NULL
                  )
                GROUP BY a.id
                ORDER BY a.name
                """,
                (node_db_id,),
            )
            candidates = cur.fetchall()

            if not candidates:
                logger.info(
                    "assign_agents_to_node: no eligible barracked agents for node %s",
                    node_db_id,
                )
                return []

            # 4. Score candidates: prefer models that fit VRAM, then smaller first
            def _score_agent(agent):
                model = agent["model"] or ""
                # Lookup known size or estimate from model name
                size = self.MODEL_SIZE_GB.get(model, None)
                if size is None:
                    # Try base name without tag
                    base = model.split(":")[0] if ":" in model else model
                    size = self.MODEL_SIZE_GB.get(base, 5.0)  # default 5GB

                fits_vram = size <= gpu_vram if gpu_vram > 0 else False
                fits_ram = size <= (ram_gb * 0.7) if ram_gb > 0 else False

                # Score: fits VRAM = 100 bonus, fits RAM = 50 bonus
                # Subtract size so smaller models are preferred (tie-breaker)
                score = 0
                if fits_vram:
                    score += 100
                if fits_ram:
                    score += 50
                score -= size  # prefer smaller
                return score

            candidates.sort(key=_score_agent, reverse=True)

            # 5. Build station allocation: COMMAND gets max 1, others get max 2
            station_slots = {}
            for sc in node_stations:
                station_slots[sc] = 1 if sc == "COMMAND" else 2

            # 6. Assign agents up to max_agents, distributing across stations
            assigned = []
            station_fill = {sc: 0 for sc in node_stations}

            for agent in candidates:
                if len(assigned) >= max_agents:
                    break

                # Pick best station for this agent
                agent_stations = agent["station_codes"] or []
                target_station = None

                # Prefer a station the agent is already assigned to on the hub
                for sc in agent_stations:
                    if sc in station_slots and station_fill.get(sc, 0) < station_slots[sc]:
                        target_station = sc
                        break

                # Fall back to any node station with capacity
                if not target_station:
                    for sc in node_stations:
                        if station_fill.get(sc, 0) < station_slots[sc]:
                            target_station = sc
                            break

                if not target_station:
                    # All stations full
                    continue

                # INSERT into node_agents
                cur.execute(
                    """
                    INSERT INTO node_agents (
                        node_id, source_agent_id, hub_agent_id,
                        name, first_name, last_name, display_name,
                        title, model, status, station_codes,
                        config_version, gpu_tools
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, 'active', %s,
                        1, %s
                    )
                    """,
                    (
                        node_db_id,
                        agent["id"],
                        agent["id"],
                        agent["name"],
                        agent.get("first_name"),
                        agent.get("last_name"),
                        agent["display_name"],
                        agent.get("title"),
                        agent["model"],
                        [target_station],
                        json.dumps(agent["gpu_tools"] or []),
                    ),
                )
                station_fill[target_station] += 1
                assigned.append(agent["name"])
                logger.info(
                    "Assigned barracked agent %s (model=%s) to node %s station %s",
                    agent["name"],
                    agent["model"],
                    node_db_id,
                    target_station,
                )

            conn.commit()

            # 7. Check remaining barracked count — advisory if <= 5
            if assigned:
                cur.execute(
                    """
                    SELECT COUNT(*) as cnt FROM agents
                    WHERE shift_state = 'barracked' AND status = 'active'
                    """
                )
                remaining = cur.fetchone()["cnt"]
                if remaining <= 5:
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                            (type, title, message, created_at)
                        VALUES
                            ('alert',
                             'Low barracked agent pool',
                             %s,
                             NOW())
                        """,
                        (
                            f"Only {remaining} barracked agents remaining after "
                            f"assigning {len(assigned)} to node {node_db_id}. "
                            f"Consider promoting or creating new agents.",
                        ),
                    )
                    conn.commit()
                    logger.warning(
                        "Barracked agent pool low: %d remaining", remaining
                    )

            logger.info(
                "assign_agents_to_node: assigned %d agents to node %s: %s",
                len(assigned),
                node_db_id,
                assigned,
            )
            return assigned

        except Exception as _exc:
            conn.rollback()
            logger.exception(
                "assign_agents_to_node failed for node %s", node_db_id
            )
            return []
        finally:
            conn.close()

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

            # --- Ollama loaded models (for LLM readiness) ---
            loaded_models = {}  # model_name -> size_gb
            gpu_models_live = set()  # models currently on GPU (size_vram > 0)
            try:
                import requests as _req
                import os

                _ollama_host = os.getenv(
                    "OLLAMA_LOCAL_HOST", "archie_ollama"
                )
                _ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
                _ps_resp = _req.get(
                    f"http://{_ollama_host}:{_ollama_port}/api/ps", timeout=5
                )
                if _ps_resp.status_code == 200:
                    for m in _ps_resp.json().get("models", []):
                        mname = m.get("name", "")
                        msize = m.get("size", 0) / (1024**3)  # bytes→GB
                        vram_bytes = m.get("size_vram", 0)
                        # Store both full name and without :latest
                        loaded_models[mname] = round(msize, 1)
                        if mname.endswith(":latest"):
                            loaded_models[mname.replace(":latest", "")] = round(
                                msize, 1
                            )
                        # Track GPU models by live VRAM usage
                        if vram_bytes and vram_bytes > 0:
                            gpu_models_live.add(mname)
                            if mname.endswith(":latest"):
                                gpu_models_live.add(mname.replace(":latest", ""))
            except Exception as _exc:
                pass  # Ollama unavailable — all agents show as "swap"

            # Get disk sizes for all models (to estimate swap eligibility)
            model_disk_gb = {}
            try:
                _tags_resp = _req.get(
                    f"http://{_ollama_host}:{_ollama_port}/api/tags", timeout=5
                )
                if _tags_resp.status_code == 200:
                    for m in _tags_resp.json().get("models", []):
                        mname = m.get("name", "")
                        disk_gb = round(m.get("size", 0) / (1024**3), 1)
                        model_disk_gb[mname] = disk_gb
                        if mname.endswith(":latest"):
                            model_disk_gb[mname.replace(":latest", "")] = disk_gb
            except Exception as _exc:
                pass

            # RAM budget for swap eligibility
            _swap_buffer_gb = 10.0
            try:
                import psutil as _ps

                _total_ram = _ps.virtual_memory().total / (1024**3)
                _swap_buffer_gb = round(_total_ram * 0.80 * 0.10, 1)
            except Exception as _exc:
                pass

            # Station codes per agent (array from station_assignments)
            station_codes_map = {}  # agent_id → [station_code, ...]
            try:
                sc_conn = self._get_db()
                sc_cur = sc_conn.cursor(cursor_factory=RealDictCursor)
                sc_cur.execute("""
                    SELECT sa.agent_id, bs.station_code
                    FROM station_assignments sa
                    JOIN bridge_stations bs ON bs.id = sa.station_id
                    WHERE sa.is_active = true
                    ORDER BY sa.agent_id, bs.station_code
                """)
                for r in sc_cur.fetchall():
                    aid = r["agent_id"]
                    if aid not in station_codes_map:
                        station_codes_map[aid] = []
                    if r["station_code"] not in station_codes_map[aid]:
                        station_codes_map[aid].append(r["station_code"])
                sc_cur.close()
                sc_conn.close()
            except Exception as sc_err:
                logger.debug(f"[BridgeDispatcher] station_codes query failed: {sc_err}")

            # Deployed agents → node lookup (agent_id → {node_db_id, node_name})
            deployed_node_map = {}
            try:
                dn_conn = self._get_db()
                dn_cur = dn_conn.cursor(cursor_factory=RealDictCursor)
                dn_cur.execute("""
                    SELECT na.hub_agent_id, rn.id as node_db_id,
                           rn.node_name, rn.hostname as node_hostname
                    FROM node_agents na
                    JOIN remote_nodes rn ON rn.id = na.node_id
                    WHERE na.hub_agent_id IS NOT NULL AND na.status = 'active'
                """)
                for r in dn_cur.fetchall():
                    deployed_node_map[r["hub_agent_id"]] = {
                        "node_db_id": r["node_db_id"],
                        "node_name": r["node_name"],
                        "node_hostname": r["node_hostname"],
                    }
                dn_cur.close()
                dn_conn.close()
            except Exception as e:
                logger.debug(f"[BridgeDispatcher] station_codes query failed: {e}")
                pass

            # Node loaded models — query each node's /api/ps for deployed agents
            node_loaded_models = {}  # agent_id → set of loaded model names
            _checked_nodes = {}
            for aid, ninfo in deployed_node_map.items():
                nid = ninfo["node_db_id"]
                if nid not in _checked_nodes:
                    try:
                        import requests as _nreq
                        dn2_conn = self._get_db()
                        dn2_cur = dn2_conn.cursor(cursor_factory=RealDictCursor)
                        dn2_cur.execute("SELECT hostname, port FROM remote_nodes WHERE id = %s", (nid,))
                        nr = dn2_cur.fetchone()
                        dn2_cur.close()
                        dn2_conn.close()
                        if nr:
                            ps = _nreq.get(f"http://{nr['hostname']}:{nr['port']}/api/ps", timeout=3)
                            if ps.status_code == 200:
                                _checked_nodes[nid] = {
                                    m["name"] for m in ps.json().get("models", [])
                                }
                            else:
                                _checked_nodes[nid] = set()
                        else:
                            _checked_nodes[nid] = set()
                    except Exception as _exc:
                        _checked_nodes[nid] = set()
                node_loaded_models[aid] = _checked_nodes[nid]

            # Build manifest — hub agents only, skip fleet: prefixed node copies
            manifest = []
            for name, info in self._agent_cache.items():
                if name.startswith("fleet:"):
                    continue
                agent_id = info["id"]
                model = info.get("model", "")

                # Reconcile stale deployed state — if agent claims
                # deployed but no active node_agents record exists, treat
                # as returned to hub (node went offline).
                _shift = info.get("shift_state", "active")
                if _shift == "deployed" and agent_id not in deployed_node_map:
                    _shift = "barracked"

                # Determine status
                if agent_id in resting_ids:
                    status = "resting"
                elif name in jobs_map:
                    status = "working"
                else:
                    status = "idle"

                # Hardware: use live VRAM data, fall back to static map
                image_model = info.get("image_model")
                if model in gpu_models_live:
                    hw = "GPU"
                elif image_model:
                    # Agent has a GPU tool (e.g. ComfyUI image gen)
                    hw = "GPU"
                else:
                    hw = self.MODEL_HARDWARE.get(model, "CPU")

                # LLM readiness: check node Ollama for deployed agents, hub for others
                _is_deployed = _shift == "deployed"
                _agent_loaded = node_loaded_models.get(agent_id, set()) if _is_deployed else set()

                if model and model.endswith(":cloud"):
                    llm_status = "cloud"
                    llm_size_gb = 0
                elif _is_deployed and model and (model in _agent_loaded or model.replace(":latest", "") in {m.replace(":latest", "") for m in _agent_loaded}):
                    llm_status = "loaded"
                    llm_size_gb = model_disk_gb.get(model, 0)
                elif not _is_deployed and model and model in loaded_models:
                    llm_status = "loaded"
                    llm_size_gb = loaded_models[model]
                else:
                    # Estimate runtime size (~1.3x disk) to check swap fit
                    disk_gb = model_disk_gb.get(model, 0)
                    est_runtime_gb = round(disk_gb * 1.3, 1)
                    llm_size_gb = est_runtime_gb
                    if est_runtime_gb > 0 and est_runtime_gb <= _swap_buffer_gb:
                        llm_status = "swap"
                    elif disk_gb == 0:
                        # Model not downloaded or unknown
                        llm_status = "barracked"
                    else:
                        llm_status = "barracked"

                first = info.get("first_name", "")
                last = info.get("last_name", "")
                full_name = f"{first} {last}".strip() if (first or last) else name

                # GPU tools (ComfyUI image gen, future: video)
                gpu_tools = []
                if image_model:
                    gpu_tools.append(
                        {
                            "type": "image_generation",
                            "model": image_model,
                            "provider": "comfyui",
                        }
                    )

                manifest.append(
                    {
                        "name": name,
                        "display_name": info.get("display_name") or full_name,
                        "full_name": full_name,
                        "title": info.get("title", ""),
                        "id": agent_id,
                        "agent_id": agent_id,
                        "station": info.get("station_code", "COMMAND"),
                        "station_codes": station_codes_map.get(agent_id, []),
                        "shift_state": _shift,
                        "model": model,
                        "image_model": image_model,
                        "hardware": hw,
                        "gpu_tools": gpu_tools,
                        "llm_status": llm_status,
                        "llm_size_gb": llm_size_gb,
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
                        "node_db_id": deployed_node_map.get(agent_id, {}).get("node_db_id"),
                        "node_name": deployed_node_map.get(agent_id, {}).get("node_name"),
                        "node_hostname": deployed_node_map.get(agent_id, {}).get("node_hostname"),
                        "location": (
                            f"node:{deployed_node_map[agent_id]['node_name']}"
                            if agent_id in deployed_node_map
                            else "hub"
                        ),
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

    # ========================================================================
    # AGENTS-AS-TOOLS — Lightweight hierarchical delegation (Task #959)
    # ========================================================================

    def delegate_subtask(
        self, parent_job_id: int, capability: str, prompt: str, timeout: int = 60
    ) -> Dict[str, Any]:
        """Delegate a subtask to another agent without creating a full Bridge job.

        Used for quick agent-to-agent delegation within a workflow.
        E.g. an analyst agent can ask a scanner agent for a quick nmap check.

        Returns the result directly (synchronous within timeout).
        """
        try:
            import requests

            # Find the right station for this capability
            station = self._resolve_station(capability)

            # Get an active agent model for this station
            from database import get_db_cursor
            from psycopg2.extras import RealDictCursor

            model = None
            with get_db_cursor(commit=False) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT a.model FROM agents a
                    JOIN station_assignments sa ON sa.agent_id = a.id
                    JOIN bridge_stations bs ON bs.id = sa.station_id
                    WHERE bs.station_code = %s
                      AND sa.is_active = true
                      AND a.shift_state = 'active'
                    LIMIT 1
                    """,
                    (station,),
                )
                row = cur.fetchone()
                if row:
                    model = row["model"]

            if not model:
                return {
                    "success": False,
                    "error": f"No available agent for capability={capability} (station={station})",
                }

            # Route through Bridge call_ollama (ADR-013 compliance)
            from ai_bridge.archie_bridge import call_ollama

            result_text = call_ollama(model, prompt, timeout=timeout)

            if result_text:
                result = {"response": result_text}
                logger.info(
                    f"Subtask delegated: parent_job={parent_job_id}, "
                    f"capability={capability}, model={model}"
                )

                # Track delegation in parent job metadata
                try:
                    from psycopg2.extras import Json

                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            """
                            UPDATE bridge_jobs
                            SET metadata = jsonb_set(
                                COALESCE(metadata, '{}'),
                                '{delegations}',
                                COALESCE(metadata->'delegations', '[]'::jsonb) || %s::jsonb
                            )
                            WHERE id = %s
                            """,
                            (
                                Json(
                                    [
                                        {
                                            "capability": capability,
                                            "model": model,
                                            "timestamp": datetime.now().isoformat(),
                                        }
                                    ]
                                ),
                                parent_job_id,
                            ),
                        )
                except Exception as _exc:
                    pass

                return {
                    "success": True,
                    "response": result.get("response", result_text),
                    "model": model,
                }

            return {
                "success": False,
                "error": f"No response from model {model}",
            }
        except Exception as e:
            logger.debug(f"Subtask delegation failed: {e}")
            return {"success": False, "error": str(e)}

    # ========================================================================
    # MODEL ORCHESTRATION — 3-tier warm/cold management
    # ========================================================================

    def get_host_capacity(self, node_db_id=None):
        """
        Return capacity info for a host (hub or fleet node).

        Args:
            node_db_id: Integer DB id from remote_nodes table.
                        None = hub (local Ollama).

        Returns dict with gpu_vram_total/used/free, ram_total/used/free,
        loaded_models list, and comfyui status.
        """
        if node_db_id is not None:
            return self._get_node_capacity(node_db_id)
        return self._get_hub_capacity()

    def _get_hub_capacity(self):
        """Capacity for the local hub Ollama instance."""
        ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
        ollama_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
        ollama_url = f"http://{ollama_host}:{ollama_port}"
        hostname = ollama_host
        port = int(ollama_port)

        result = {
            "hostname": hostname,
            "port": port,
            "gpu_vram_total": 0.0,
            "gpu_vram_used": 0.0,
            "gpu_vram_free": 0.0,
            "ram_total": 0.0,
            "ram_used_by_models": 0.0,
            "ram_free": 0.0,
            "loaded_models": [],
            "comfyui_active": False,
            "comfyui_vram_gb": 0.0,
        }

        # -- GPU info from Ollama /api/ps (size_vram on loaded models) --
        # Hub GPU: Quadro M4000 8GB
        gpu_vram_total = 8.0  # Known hardware
        gpu_vram_used = 0.0

        # -- Loaded models --
        try:
            ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
            if ps_resp.status_code == 200:
                models_data = ps_resp.json().get("models", [])
                for m in models_data:
                    name = m.get("name", "unknown")
                    size_vram = m.get("size_vram", 0) / (1024**3)  # bytes→GB
                    size_total = m.get("size", 0) / (1024**3)
                    size_ram = max(0.0, size_total - size_vram)
                    result["loaded_models"].append({
                        "name": name,
                        "vram_gb": round(size_vram, 2),
                        "ram_gb": round(size_ram, 2),
                        "expires_at": m.get("expires_at", ""),
                    })
                    gpu_vram_used += size_vram
                    result["ram_used_by_models"] += size_ram
        except Exception as e:
            logger.warning(f"[ModelOrch] Hub /api/ps failed: {e}")

        result["gpu_vram_total"] = gpu_vram_total
        result["gpu_vram_used"] = round(gpu_vram_used, 2)
        result["gpu_vram_free"] = round(max(0, gpu_vram_total - gpu_vram_used), 2)
        result["ram_used_by_models"] = round(result["ram_used_by_models"], 2)

        # -- System RAM (best-effort via Ollama /api/tags or known value) --
        # Hub has 128GB, 80% budget = ~102GB for models
        ram_total = 102.0  # ADR-078 budget
        result["ram_total"] = ram_total
        result["ram_free"] = round(
            max(0, ram_total - result["ram_used_by_models"]), 2
        )

        # -- ComfyUI status --
        try:
            comfyui_host = os.getenv(
                "COMFYUI_HOST", "http://host.docker.internal:8188"
            )
            cu_resp = requests.get(f"{comfyui_host}/system_stats", timeout=5)
            if cu_resp.status_code == 200:
                cu_data = cu_resp.json()
                devices = cu_data.get("devices", [])
                for dev in devices:
                    if dev.get("type") == "cuda":
                        vram_used = dev.get("vram_total", 0) - dev.get(
                            "vram_free", dev.get("vram_total", 0)
                        )
                        result["comfyui_vram_gb"] = round(
                            vram_used / (1024**3), 2
                        )
                        result["comfyui_active"] = vram_used > 100_000_000
                        # Subtract ComfyUI from available GPU VRAM
                        cu_gb = result["comfyui_vram_gb"]
                        result["gpu_vram_used"] = round(
                            result["gpu_vram_used"] + cu_gb, 2
                        )
                        result["gpu_vram_free"] = round(
                            max(0, gpu_vram_total - result["gpu_vram_used"]), 2
                        )
        except Exception as _exc:
            pass  # ComfyUI may not be running

        return result

    def _get_node_capacity(self, node_db_id):
        """Capacity for a remote fleet node."""
        result = {
            "hostname": "unknown",
            "port": 11434,
            "gpu_vram_total": 0.0,
            "gpu_vram_used": 0.0,
            "gpu_vram_free": 0.0,
            "ram_total": 0.0,
            "ram_used_by_models": 0.0,
            "ram_free": 0.0,
            "loaded_models": [],
            "comfyui_active": False,
            "comfyui_vram_gb": 0.0,
        }

        # -- Look up node from DB --
        conn = None
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT hostname, port, gpu_vram_gb, ram_gb,
                       gpu_available, comfyui_available, comfyui_port,
                       vpn_ip
                FROM remote_nodes WHERE id = %s AND is_active = true
                """,
                (node_db_id,),
            )
            row = cur.fetchone()
            cur.close()
            if not row:
                logger.warning(
                    f"[ModelOrch] Node id={node_db_id} not found or inactive"
                )
                return result
        except Exception as e:
            logger.error(f"[ModelOrch] DB lookup for node {node_db_id}: {e}")
            return result
        finally:
            if conn:
                conn.close()

        hostname = row[0] or row[7] or "unknown"  # hostname or vpn_ip
        port = row[1] or 11434
        gpu_vram_total = row[2] or 0.0
        ram_total_raw = row[3] or 0.0
        ram_total = round(ram_total_raw * 0.8, 1)  # 80% budget
        gpu_available = row[4]
        comfyui_available = row[5]
        comfyui_port = row[6] or 8188

        result["hostname"] = hostname
        result["port"] = port
        result["gpu_vram_total"] = gpu_vram_total
        result["ram_total"] = ram_total

        ollama_url = f"http://{hostname}:{port}"
        gpu_vram_used = 0.0

        # -- Loaded models --
        try:
            ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
            if ps_resp.status_code == 200:
                models_data = ps_resp.json().get("models", [])
                for m in models_data:
                    name = m.get("name", "unknown")
                    size_vram = m.get("size_vram", 0) / (1024**3)
                    size_total = m.get("size", 0) / (1024**3)
                    size_ram = max(0.0, size_total - size_vram)
                    result["loaded_models"].append({
                        "name": name,
                        "vram_gb": round(size_vram, 2),
                        "ram_gb": round(size_ram, 2),
                        "expires_at": m.get("expires_at", ""),
                    })
                    gpu_vram_used += size_vram
                    result["ram_used_by_models"] += size_ram
        except Exception as e:
            logger.warning(f"[ModelOrch] Node {hostname} /api/ps failed: {e}")

        result["gpu_vram_used"] = round(gpu_vram_used, 2)
        result["gpu_vram_free"] = round(
            max(0, gpu_vram_total - gpu_vram_used), 2
        )
        result["ram_used_by_models"] = round(result["ram_used_by_models"], 2)
        result["ram_free"] = round(
            max(0, ram_total - result["ram_used_by_models"]), 2
        )

        # -- ComfyUI on node --
        if comfyui_available:
            try:
                cu_resp = requests.get(
                    f"http://{hostname}:{comfyui_port}/system_stats", timeout=5
                )
                if cu_resp.status_code == 200:
                    cu_data = cu_resp.json()
                    for dev in cu_data.get("devices", []):
                        if dev.get("type") == "cuda":
                            vram_used = dev.get("vram_total", 0) - dev.get(
                                "vram_free", dev.get("vram_total", 0)
                            )
                            result["comfyui_vram_gb"] = round(
                                vram_used / (1024**3), 2
                            )
                            result["comfyui_active"] = vram_used > 100_000_000
                            cu_gb = result["comfyui_vram_gb"]
                            result["gpu_vram_used"] = round(
                                result["gpu_vram_used"] + cu_gb, 2
                            )
                            result["gpu_vram_free"] = round(
                                max(0, gpu_vram_total - result["gpu_vram_used"]),
                                2,
                            )
            except Exception as _exc:
                pass

        return result

    def ensure_model_ready(self, agent_name, model, target_host=None):
        """
        Ensure a model is loaded and ready for inference on the target host.

        3-tier strategy:
            1. GPU (VRAM) — fastest, check if already loaded with VRAM
            2. CPU (RAM)  — warm standby, loaded but no VRAM
            3. Cold (disk) — not loaded, needs warm boot

        Args:
            agent_name: Name of the agent requesting the model.
            model: Ollama model tag (e.g. "llama3.2:3b").
            target_host: Dict with {"hostname": str, "port": int} for remote
                         node, or None for hub.

        Returns:
            {
                "ready": bool,
                "tier": "gpu" | "cpu" | "cold",
                "host": str,
                "warm_boot_ms": int,
            }
        """
        start_ms = time.time() * 1000

        # Resolve Ollama URL
        if target_host:
            hostname = target_host.get("hostname", "unknown")
            port = target_host.get("port", 11434)
            ollama_url = f"http://{hostname}:{port}"
            node_db_id = target_host.get("node_db_id")
        else:
            hostname = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
            port = int(os.getenv("OLLAMA_LOCAL_PORT", "11434"))
            ollama_url = f"http://{hostname}:{port}"
            node_db_id = None

        host_label = f"{hostname}:{port}"

        # -- Step 1: Check if model is already loaded --
        try:
            ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
            if ps_resp.status_code == 200:
                for m in ps_resp.json().get("models", []):
                    if m.get("name", "") == model or m.get("model", "") == model:
                        size_vram = m.get("size_vram", 0)
                        size_total = m.get("size", 0)
                        if size_vram > 0 and size_vram >= size_total * 0.5:
                            logger.info(
                                f"[ModelOrch] {model} hot on GPU @ {host_label}"
                            )
                            return {
                                "ready": True,
                                "tier": "gpu",
                                "host": host_label,
                                "warm_boot_ms": 0,
                            }
                        else:
                            logger.info(
                                f"[ModelOrch] {model} warm in RAM @ {host_label}"
                            )
                            return {
                                "ready": True,
                                "tier": "cpu",
                                "host": host_label,
                                "warm_boot_ms": 0,
                            }
        except Exception as e:
            logger.error(f"[ModelOrch] /api/ps failed on {host_label}: {e}")
            return {
                "ready": False,
                "tier": "cold",
                "host": host_label,
                "warm_boot_ms": 0,
            }

        # -- Step 2: Model is cold — need to warm boot --
        logger.info(
            f"[ModelOrch] {model} cold on {host_label}, warm booting for {agent_name}"
        )

        # Get capacity to decide GPU vs CPU loading
        capacity = self.get_host_capacity(node_db_id)
        gpu_free = capacity.get("gpu_vram_free", 0)
        ram_free = capacity.get("ram_free", 0)

        # Estimate model size (use Ollama /api/show if available, else heuristic)
        model_size_gb = self._estimate_model_size(model, ollama_url)

        # Decide loading strategy
        num_gpu = 0  # default: CPU only
        if model_size_gb <= gpu_free and not capacity.get("comfyui_active", False):
            num_gpu = 99  # Full GPU offload
            target_tier = "gpu"
            logger.info(
                f"[ModelOrch] Loading {model} to GPU "
                f"(need {model_size_gb:.1f}GB, free {gpu_free:.1f}GB)"
            )
        elif model_size_gb <= ram_free:
            target_tier = "cpu"
            logger.info(
                f"[ModelOrch] Loading {model} to RAM "
                f"(need {model_size_gb:.1f}GB, free {ram_free:.1f}GB)"
            )
        else:
            # Need to evict LRU model first
            target_tier = "cpu"
            evicted = self._evict_lru_model(
                capacity, model_size_gb, ollama_url
            )
            if not evicted:
                logger.error(
                    f"[ModelOrch] Cannot free enough RAM for {model} "
                    f"on {host_label} (need {model_size_gb:.1f}GB, "
                    f"free {ram_free:.1f}GB)"
                )
                return {
                    "ready": False,
                    "tier": "cold",
                    "host": host_label,
                    "warm_boot_ms": int(time.time() * 1000 - start_ms),
                }

        # -- Step 3: Load the model --
        try:
            load_resp = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "keep_alive": "24h",
                    "options": {"num_gpu": num_gpu, "num_predict": 1},
                    "stream": False,
                },
                timeout=300,
            )
            elapsed_ms = int(time.time() * 1000 - start_ms)

            if load_resp.status_code == 200:
                logger.info(
                    f"[ModelOrch] {model} loaded to {target_tier} on "
                    f"{host_label} in {elapsed_ms}ms"
                )
                return {
                    "ready": True,
                    "tier": target_tier,
                    "host": host_label,
                    "warm_boot_ms": elapsed_ms,
                }
            else:
                logger.error(
                    f"[ModelOrch] Load {model} failed: "
                    f"HTTP {load_resp.status_code} — {load_resp.text[:200]}"
                )
                return {
                    "ready": False,
                    "tier": "cold",
                    "host": host_label,
                    "warm_boot_ms": elapsed_ms,
                }
        except Exception as e:
            elapsed_ms = int(time.time() * 1000 - start_ms)
            logger.error(f"[ModelOrch] Load {model} exception: {e}")
            return {
                "ready": False,
                "tier": "cold",
                "host": host_label,
                "warm_boot_ms": elapsed_ms,
            }

    def _estimate_model_size(self, model, ollama_url):
        """
        Estimate model runtime size in GB.
        Uses /api/show for real size, falls back to name-based heuristic.
        """
        try:
            resp = requests.post(
                f"{ollama_url}/api/show",
                json={"name": model},
                timeout=10,
            )
            if resp.status_code == 200:
                details = resp.json().get("details", {})
                param_size = details.get("parameter_size", "")
                # Parse "3.2B", "7B", "70B" etc.
                if param_size:
                    num_str = param_size.upper().replace("B", "").strip()
                    try:
                        params_b = float(num_str)
                        # ~0.6 bytes per param for Q4 quant → GB
                        return round(params_b * 0.6, 1)
                    except ValueError:
                        pass
                # Fallback: use model file size * 1.3
                model_info = resp.json().get("modelinfo", {})
                for key, val in model_info.items():
                    if "parameter" in key.lower() and isinstance(val, (int, float)):
                        return round(val / 1e9 * 0.6, 1)
        except Exception as _exc:
            pass

        # Name-based heuristic
        name_lower = model.lower()
        if "70b" in name_lower or "72b" in name_lower:
            return 40.0
        elif "34b" in name_lower or "35b" in name_lower:
            return 20.0
        elif "14b" in name_lower or "13b" in name_lower:
            return 8.0
        elif "8b" in name_lower or "7b" in name_lower:
            return 5.0
        elif "3b" in name_lower or "4b" in name_lower:
            return 2.5
        elif "1b" in name_lower or "1.7b" in name_lower:
            return 1.5
        elif "0.5b" in name_lower or "smol" in name_lower:
            return 0.5
        return 4.0  # Conservative default

    def _evict_lru_model(self, capacity, needed_gb, ollama_url):
        """
        Evict least-recently-used loaded model(s) to free RAM.

        Returns True if enough space was freed, False otherwise.
        """
        loaded = capacity.get("loaded_models", [])
        if not loaded:
            return False

        # Sort by expires_at ascending (soonest expiry = least recently used)
        # Models with empty expires_at go first (likely stale)
        def _sort_key(m):
            exp = m.get("expires_at", "")
            return exp if exp else "0000"

        candidates = sorted(loaded, key=_sort_key)

        freed_gb = 0.0
        for candidate in candidates:
            cname = candidate.get("name", "")
            c_ram = candidate.get("ram_gb", 0)
            c_vram = candidate.get("vram_gb", 0)
            c_total = c_ram + c_vram

            if c_total < 0.1:
                continue  # Skip tiny/unknown

            try:
                resp = requests.post(
                    f"{ollama_url}/api/generate",
                    json={"model": cname, "keep_alive": 0},
                    timeout=10,
                )
                if resp.status_code == 200:
                    freed_gb += c_total
                    logger.info(
                        f"[ModelOrch] Evicted {cname} "
                        f"(freed {c_total:.1f}GB, total freed {freed_gb:.1f}GB)"
                    )
                    if freed_gb >= needed_gb:
                        return True
            except Exception as e:
                logger.warning(f"[ModelOrch] Failed to evict {cname}: {e}")

        return freed_gb >= needed_gb

    def unload_model(self, model, target_host=None):
        """Unload a model from Ollama (set keep_alive=0).

        Args:
            model: Ollama model tag (e.g. "llama3.2:3b").
            target_host: Dict with {"hostname": str, "port": int} for remote
                         node, or None for hub.

        Returns:
            {"success": bool, "message": str}
        """
        if target_host:
            hostname = target_host.get("hostname", "unknown")
            port = target_host.get("port", 11434)
            ollama_url = f"http://{hostname}:{port}"
        else:
            hostname = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
            port = int(os.getenv("OLLAMA_LOCAL_PORT", "11434"))
            ollama_url = f"http://{hostname}:{port}"

        host_label = f"{hostname}:{port}"
        try:
            resp = requests.post(
                f"{ollama_url}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=30,
            )
            if resp.status_code == 200:
                logger.info(f"[ModelOrch] Unloaded {model} on {host_label}")
                return {"success": True, "message": f"{model} unloaded"}
            return {
                "success": False,
                "message": f"Ollama returned {resp.status_code}",
            }
        except Exception as e:
            logger.warning(f"[ModelOrch] Failed to unload {model} on {host_label}: {e}")
            return {"success": False, "message": str(e)}


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

    def _vram_swap_for_comfyui(self, node_db_id=None):
        """Unload GPU models from Ollama to free VRAM for ComfyUI SDXL.

        Works on hub (default) or any fleet node.
        Returns list of unloaded model names for later restore.
        """
        unloaded = []
        try:
            import requests as _req

            if node_db_id:
                cap = self._get_node_capacity(node_db_id)
            else:
                cap = self._get_hub_capacity()
            ollama_url = f"http://{cap['hostname']}:{cap['port']}"

            for m in cap.get("loaded_models", []):
                if m.get("vram_gb", 0) > 0:
                    mname = m["name"]
                    _req.post(
                        f"{ollama_url}/api/generate",
                        json={"model": mname, "keep_alive": 0},
                        timeout=10,
                    )
                    unloaded.append(mname)
                    logger.info(
                        f"[BridgeDispatcher] VRAM swap: unloaded {mname} "
                        f"on {'node ' + str(node_db_id) if node_db_id else 'hub'}"
                    )
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] VRAM swap failed: {e}")
        return unloaded

    def _vram_restore_after_comfyui(self, model_names, node_db_id=None):
        """Reload GPU models after ComfyUI finishes, freeing ComfyUI VRAM first.

        Works on hub (default) or any fleet node.
        """
        try:
            import requests as _req

            # Free ComfyUI VRAM
            if node_db_id:
                cap = self._get_node_capacity(node_db_id)
                comfyui_host = f"http://{cap['hostname']}:8188"
            else:
                comfyui_host = os.getenv("COMFYUI_HOST", "http://host.docker.internal:8188")
                cap = self._get_hub_capacity()
            ollama_url = f"http://{cap['hostname']}:{cap['port']}"

            _req.post(
                f"{comfyui_host}/free",
                json={"unload_models": True},
                timeout=10,
            )
            target = "node " + str(node_db_id) if node_db_id else "hub"
            logger.info(f"[BridgeDispatcher] Freed ComfyUI VRAM on {target}")

            # Reload models on GPU
            for mname in model_names:
                _req.post(
                    f"{ollama_url}/api/generate",
                    json={"model": mname, "prompt": "", "keep_alive": "24h"},
                    timeout=30,
                )
                logger.info(f"[BridgeDispatcher] VRAM swap: reloaded {mname} on {target}")
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] VRAM restore failed: {e}")


    # ========================================================================
    # FLEET HEALTH — Node offline/online protocol
    # ========================================================================

    def check_fleet_health(self):
        """Monitor node heartbeats and handle offline/online transitions.

        Called periodically (e.g., every 30s by agent loop).
        - Nodes with stale heartbeats (>2 min) → return agents to barracks
        - Nodes that come back online → restore previously deployed agents
        - Starbase nodes are always considered online (skip heartbeat check)
        - Idempotent: duplicate calls for same state produce no extra notifications
        """
        from psycopg2.extras import RealDictCursor

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get all active, non-starbase nodes
            cur.execute(
                """
                SELECT id, node_name, deployment_mode, last_heartbeat,
                       (last_heartbeat > NOW() - INTERVAL '2 minutes') AS heartbeat_fresh
                FROM remote_nodes
                WHERE is_active = true
                  AND deployment_mode != 'starbase'
                ORDER BY id
                """
            )
            nodes = cur.fetchall()

            for node in nodes:
                node_id = node["id"]
                node_name = node["node_name"] or f"Node-{node_id}"
                is_online = bool(node["heartbeat_fresh"])
                prev = self._fleet_health_cache.get(node_id)
                was_online = prev["online"] if prev else True  # assume online if first check

                # Update cache
                self._fleet_health_cache[node_id] = {
                    "online": is_online,
                    "last_check": datetime.utcnow().isoformat(),
                }

                # --- TRANSITION: online → offline ---
                if was_online and not is_online:
                    self._handle_node_offline(cur, conn, node_id, node_name)

                # --- TRANSITION: offline → online ---
                elif not was_online and is_online:
                    self._handle_node_online(cur, conn, node_id, node_name)

            cur.close()
        except Exception as e:
            logger.error("[BridgeDispatcher] check_fleet_health error: %s", e)
        finally:
            try:
                conn.close()
            except Exception as _exc:
                pass

    def _handle_node_offline(self, cur, conn, node_id, node_name):
        """Return all agents on this node to barracks and log notification."""
        # 1. Find agents deployed to this node
        cur.execute(
            """
            SELECT na.hub_agent_id, na.name
            FROM node_agents na
            WHERE na.node_id = %s AND na.status = 'active' AND na.hub_agent_id IS NOT NULL
            """,
            (node_id,),
        )
        deployed = cur.fetchall()

        if not deployed:
            logger.info(
                "[BridgeDispatcher] Node %s offline but had no active agents", node_name
            )
            # Still log notification for visibility
            cur.execute(
                """
                INSERT INTO system_notifications (type, message, created_at)
                VALUES ('warning', %s, NOW())
                """,
                (f"Node {node_name} went offline — 0 agents affected",),
            )
            conn.commit()
            return

        agent_ids = [r["hub_agent_id"] for r in deployed]
        agent_names = [r["name"] for r in deployed]

        # 2. Return agents to barracks
        cur.execute(
            """
            UPDATE agents SET shift_state = 'barracked'
            WHERE id = ANY(%s) AND shift_state = 'deployed'
            """,
            (agent_ids,),
        )

        # 3. Mark node_agents inactive
        cur.execute(
            """
            UPDATE node_agents SET status = 'inactive'
            WHERE node_id = %s AND status = 'active'
            """,
            (node_id,),
        )

        # 4. Log notification
        msg = (
            f"Node {node_name} went offline — "
            f"{len(agent_ids)} agents returned to barracks: {', '.join(agent_names)}"
        )
        cur.execute(
            """
            INSERT INTO system_notifications (type, message, created_at)
            VALUES ('warning', %s, NOW())
            """,
            (msg,),
        )
        conn.commit()
        logger.warning("[BridgeDispatcher] %s", msg)

    def _handle_node_online(self, cur, conn, node_id, node_name):
        """Restore previously deployed agents when a node comes back online."""
        # 1. Find agents that were on this node before it went offline
        cur.execute(
            """
            SELECT na.hub_agent_id, na.name
            FROM node_agents na
            WHERE na.node_id = %s AND na.status = 'inactive' AND na.hub_agent_id IS NOT NULL
            """,
            (node_id,),
        )
        previous = cur.fetchall()

        restored = []
        skipped = []

        for agent_row in previous:
            agent_id = agent_row["hub_agent_id"]
            agent_name = agent_row["name"]

            # Check if agent is still in barracks (not reassigned elsewhere)
            cur.execute(
                """
                SELECT shift_state FROM agents WHERE id = %s
                """,
                (agent_id,),
            )
            agent = cur.fetchone()
            if not agent:
                skipped.append(agent_name)
                continue

            if agent["shift_state"] == "barracked":
                # Reactivate
                cur.execute(
                    "UPDATE node_agents SET status = 'active' WHERE node_id = %s AND hub_agent_id = %s",
                    (node_id, agent_id),
                )
                cur.execute(
                    "UPDATE agents SET shift_state = 'deployed' WHERE id = %s",
                    (agent_id,),
                )
                restored.append(agent_name)
            else:
                # Already reassigned elsewhere
                skipped.append(agent_name)

        # 2. If not enough agents restored, fill from barracks
        new_assigned = []
        expected = len(previous) if previous else 0
        if len(restored) < expected:
            shortfall = expected - len(restored)
            try:
                new_names = self.assign_agents_to_node(node_id, max_agents=shortfall)
                new_assigned = new_names
            except Exception as e:
                logger.warning(
                    "[BridgeDispatcher] Could not fill node %s from barracks: %s",
                    node_name,
                    e,
                )

        # 3. Log notification
        parts = [f"Node {node_name} back online"]
        if restored:
            parts.append(f"{len(restored)} agents restored: {', '.join(restored)}")
        if new_assigned:
            parts.append(f"{len(new_assigned)} new assigned: {', '.join(new_assigned)}")
        if skipped:
            parts.append(f"{len(skipped)} already reassigned: {', '.join(skipped)}")

        msg = " — ".join(parts)
        cur.execute(
            """
            INSERT INTO system_notifications (type, message, created_at)
            VALUES ('info', %s, NOW())
            """,
            (msg,),
        )
        conn.commit()
        logger.info("[BridgeDispatcher] %s", msg)

    # ========================================================================
    # MODEL STATE PERSISTENCE — Save/restore loaded models across restarts
    # ========================================================================

    def _save_model_state(self, node_db_id=None):
        """Save currently loaded models to model_load_state table.

        Args:
            node_db_id: If None, saves hub state. If int, saves node state.
        """
        from psycopg2.extras import RealDictCursor

        host_type = "node" if node_db_id else "hub"
        ollama_url = None

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Ensure table exists
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS model_load_state (
                    id SERIAL PRIMARY KEY,
                    host_type VARCHAR(20) NOT NULL,
                    node_db_id INTEGER,
                    model_name VARCHAR(200) NOT NULL,
                    tier VARCHAR(10) NOT NULL,
                    size_gb NUMERIC(6,1),
                    saved_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(host_type, node_db_id, model_name)
                )
                """
            )
            conn.commit()

            # Determine Ollama URL
            if node_db_id:
                cur.execute(
                    "SELECT hostname, port FROM remote_nodes WHERE id = %s",
                    (node_db_id,),
                )
                node = cur.fetchone()
                if not node:
                    logger.warning("[BridgeDispatcher] _save_model_state: node %s not found", node_db_id)
                    return
                ollama_url = f"http://{node['hostname']}:{node['port'] or 11434}"
            else:
                ollama_url = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
                if not ollama_url.startswith("http"):
                    ollama_url = f"http://{ollama_url}"

            # Get loaded models via /api/ps
            try:
                resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
                resp.raise_for_status()
                models = resp.json().get("models", [])
            except Exception as e:
                logger.warning("[BridgeDispatcher] _save_model_state: cannot reach %s: %s", ollama_url, e)
                return

            # Clear old state for this host
            if node_db_id:
                cur.execute(
                    "DELETE FROM model_load_state WHERE host_type = 'node' AND node_db_id = %s",
                    (node_db_id,),
                )
            else:
                cur.execute(
                    "DELETE FROM model_load_state WHERE host_type = 'hub' AND node_db_id IS NULL"
                )

            # Insert current state
            for m in models:
                model_name = m.get("name", m.get("model", ""))
                size_bytes = m.get("size", 0)
                size_gb = round(size_bytes / (1024**3), 1) if size_bytes else 0

                # Determine tier from GPU offload
                details = m.get("details", {})
                gpu_layers = m.get("size_vram", 0)
                tier = "gpu" if gpu_layers and gpu_layers > 0 else "cpu"

                cur.execute(
                    """
                    INSERT INTO model_load_state (host_type, node_db_id, model_name, tier, size_gb, saved_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (host_type, node_db_id, model_name)
                    DO UPDATE SET tier = EXCLUDED.tier, size_gb = EXCLUDED.size_gb, saved_at = NOW()
                    """,
                    (host_type, node_db_id, model_name, tier, size_gb),
                )

            conn.commit()
            logger.info(
                "[BridgeDispatcher] Saved %d model states for %s%s",
                len(models),
                host_type,
                f" (node {node_db_id})" if node_db_id else "",
            )

        except Exception as e:
            logger.error("[BridgeDispatcher] _save_model_state error: %s", e)
        finally:
            try:
                conn.close()
            except Exception as _exc:
                pass

    def _restore_model_state(self, node_db_id=None):
        """Restore previously loaded models from model_load_state table.

        Issues warm-boot requests (keep_alive generate) for each saved model.

        Args:
            node_db_id: If None, restores hub state. If int, restores node state.
        """
        from psycopg2.extras import RealDictCursor

        host_type = "node" if node_db_id else "hub"

        conn = self._get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'model_load_state'
                )
                """
            )
            if not cur.fetchone()["exists"]:
                logger.info("[BridgeDispatcher] model_load_state table does not exist, skipping restore")
                return

            # Get saved models
            if node_db_id:
                cur.execute(
                    """
                    SELECT model_name, tier, size_gb
                    FROM model_load_state
                    WHERE host_type = 'node' AND node_db_id = %s
                    ORDER BY tier DESC, size_gb DESC
                    """,
                    (node_db_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT model_name, tier, size_gb
                    FROM model_load_state
                    WHERE host_type = 'hub' AND node_db_id IS NULL
                    ORDER BY tier DESC, size_gb DESC
                    """
                )
            saved = cur.fetchall()
            cur.close()

            if not saved:
                logger.info("[BridgeDispatcher] No saved model state for %s%s",
                            host_type, f" (node {node_db_id})" if node_db_id else "")
                return

            # Determine Ollama URL
            if node_db_id:
                cur2 = conn.cursor(cursor_factory=RealDictCursor)
                cur2.execute(
                    "SELECT hostname, port FROM remote_nodes WHERE id = %s",
                    (node_db_id,),
                )
                node = cur2.fetchone()
                cur2.close()
                if not node:
                    return
                ollama_url = f"http://{node['hostname']}:{node['port'] or 11434}"
            else:
                ollama_url = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
                if not ollama_url.startswith("http"):
                    ollama_url = f"http://{ollama_url}"

            # Warm-boot each model
            loaded = 0
            failed = 0
            for row in saved:
                model_name = row["model_name"]
                try:
                    resp = requests.post(
                        f"{ollama_url}/api/generate",
                        json={"model": model_name, "prompt": "", "keep_alive": "24h"},
                        timeout=120,
                    )
                    if resp.status_code == 200:
                        loaded += 1
                        logger.info("[BridgeDispatcher] Restored model %s on %s", model_name, host_type)
                    else:
                        failed += 1
                        logger.warning(
                            "[BridgeDispatcher] Failed to restore %s: HTTP %s",
                            model_name,
                            resp.status_code,
                        )
                except Exception as e:
                    failed += 1
                    logger.warning("[BridgeDispatcher] Failed to restore %s: %s", model_name, e)

            logger.info(
                "[BridgeDispatcher] Model restore complete for %s%s: %d loaded, %d failed",
                host_type,
                f" (node {node_db_id})" if node_db_id else "",
                loaded,
                failed,
            )

        except Exception as e:
            logger.error("[BridgeDispatcher] _restore_model_state error: %s", e)
        finally:
            try:
                conn.close()
            except Exception as _exc:
                pass


_dispatcher = None


def get_dispatcher() -> BridgeDispatcher:
    """Get the singleton BridgeDispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = BridgeDispatcher()
        # Reap ALL orphaned jobs from previous runs on first init.
        # No background threads survive a container restart, so any
        # job still marked 'running' is guaranteed stale.
        try:
            reaped = _dispatcher.reap_stale_jobs(
                max_age_minutes=0,
                reason="orphaned — platform restarted",
            )
            if reaped:
                logger.info(f"[BridgeDispatcher] Startup reaper cleaned {reaped} stale jobs")
        except Exception as _exc:
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
    # Input validation
    if not capability or not isinstance(capability, str):
        raise ValueError("capability must be a non-empty string")
    if not prompt or not isinstance(prompt, str):
        raise ValueError("prompt must be a non-empty string")
    if len(prompt) > 100000:
        raise ValueError("prompt exceeds maximum length (100,000 chars)")
    if user_id is not None and not isinstance(user_id, int):
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = None

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
    # Input validation
    if not capability or not isinstance(capability, str):
        return None
    if not prompt or not isinstance(prompt, str):
        return None
    if len(prompt) > 100000:
        return None
    if user_id is not None and not isinstance(user_id, int):
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = None

    return get_dispatcher().request_json(
        capability=capability,
        prompt=prompt,
        module_id=module_id,
        system_prompt=system_prompt,
        user_id=user_id,
        **kwargs,
    )
