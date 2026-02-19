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

    # Research station capabilities
    "knowledge_analysis": "RESEARCH",
    "summarize": "RESEARCH",
    "document_analysis": "RESEARCH",
    "fact_checking": "RESEARCH",
    "semantic_search": "RESEARCH",
    "context_retrieval": "RESEARCH",

    # Creative station — translation (language content creation)
    "translate": "CREATIVE",

    # Analytics — language detection (classification task)
    "detect_language": "ANALYTICS",

    # Generic fallbacks
    "analysis": "ANALYTICS",
    "general": "COMMAND",
    "json": "ANALYTICS",
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
                    "title": agent.get("title") or "",
                }
            self._cache_time = now
            logger.info(f"[BridgeDispatcher] Cached {len(self._agent_cache)} agents")
        except Exception as e:
            logger.error(f"[BridgeDispatcher] Cache refresh failed: {e}")

    def _select_agent(self, capability: str, station_code: str) -> Optional[Dict]:
        """Select the best agent for a capability within a station."""
        self._refresh_agent_cache()

        # Check station specialization map
        station_specs = AGENT_SPECIALIZATION.get(station_code, {})
        agent_name = station_specs.get(capability, station_specs.get("default"))

        if agent_name and agent_name in self._agent_cache:
            return self._agent_cache[agent_name]

        # Fallback: find any agent at this station
        for name, info in self._agent_cache.items():
            if info["station_code"] == station_code:
                return {**info, "name": name}

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
            from archie_bridge import call_ollama, call_ollama_json, call_ollama_cloud

            # Route to external providers
            if model in ("gpt-4o-mini", "gpt-4o"):
                from external_providers import call_openai
                return call_openai(prompt, model=model, system_prompt=system_prompt,
                                 json_mode=json_mode, timeout=timeout)
            if model.startswith("llama-3.1-sonar"):
                from external_providers import call_perplexity
                return call_perplexity(prompt, model=model, system_prompt=system_prompt,
                                      json_mode=json_mode, timeout=timeout)
            if model.startswith("grok"):
                from external_providers import call_grok
                return call_grok(prompt, model=model, system_prompt=system_prompt,
                               json_mode=json_mode, timeout=timeout)

            # Route cloud models
            if ":cloud" in model or model in ("minimax-m2.5", "qwen3-coder-next"):
                return call_ollama_cloud(prompt, model=model, system_prompt=system_prompt)

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
            return {"success": False, "error": "archie_bridge not available", "model": model}

    def _log_execution(self, result: DispatchResult, module_id: str, user_id: Optional[int] = None, job_id: Optional[int] = None):
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
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Failed to log execution: {e}")

    def _get_escalation_threshold(self) -> int:
        """Read escalation threshold from platform_settings."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_threshold'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return int(row[0]) if row else 3
        except Exception:
            return 3

    def _get_routing_mode(self) -> str:
        """Read routing_mode from platform_settings. Returns 'full' on error."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
            row = cur.fetchone()
            cur.close()
            conn.close()
            return row[0] if row else "full"
        except Exception:
            return "full"

    # Cloud contractor models (free via OLLAMA_API_KEY)
    FREE_CLOUD_MODELS = [
        "minimax-m2.5:cloud",
        "qwen3-coder-next:cloud",
    ]

    def _check_agent_busy(self, agent_name: str) -> Optional[Dict]:
        """Check if agent has a running bridge_job. Returns job dict or None."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
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

        1. Try free cloud contractors (auto-approve)
        2. If unavailable/failed, request paid cloud via Telegram approval
        Returns DispatchResult on success, None if escalation not possible.
        """
        if routing_mode == "local_only":
            return None  # Cannot escalate

        start = time.time()

        # --- Try free cloud contractors ---
        for cloud_model in self.FREE_CLOUD_MODELS:
            logger.info(
                f"[BridgeDispatcher] Throughput escalation: {agent_name} busy "
                f"({busy_job['description']}, {busy_job['progress_pct']}%). "
                f"Trying free cloud: {cloud_model}"
            )
            llm_result = self._execute_llm(
                model=cloud_model,
                prompt=prompt,
                system_prompt=system_prompt,
                json_mode=json_mode,
                timeout=timeout,
            )
            if llm_result.get("success"):
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
                self._notify_throughput_escalation(
                    agent_name=agent_name,
                    cloud_model=cloud_model,
                    capability=capability,
                    module_id=module_id,
                    busy_job=busy_job,
                    duration_ms=duration_ms,
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
                    metadata={"escalation": "throughput_free_cloud", "original_agent": agent_name},
                )
                self._log_execution(result, module_id, user_id, job_id=job_id)
                return result

        # --- Free cloud unavailable; request paid cloud via Telegram ---
        if routing_mode == "local_cloud":
            return None  # Cannot use paid

        logger.info(
            f"[BridgeDispatcher] Free cloud unavailable. "
            f"Requesting paid cloud approval for capability='{capability}'"
        )
        try:
            from agent_loop import request_approval

            next_tier = self._get_next_tier(
                self.FREE_CLOUD_MODELS[-1], capability
            )
            if next_tier and next_tier["is_paid"]:
                request_approval(
                    action_type="cloud_throughput_escalation",
                    action_data={
                        "original_agent": agent_name,
                        "busy_job": busy_job,
                        "escalated_model": next_tier["model"],
                        "escalated_provider": next_tier["provider"],
                        "capability": capability,
                        "module_id": module_id,
                        "prompt_preview": prompt[:200],
                    },
                    reason=(
                        f"{agent_name} busy ({busy_job['description']}, "
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
        except Exception as esc_err:
            logger.warning(f"[BridgeDispatcher] Throughput approval request failed: {esc_err}")

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
                    json.dumps({
                        "original_agent": agent_name,
                        "cloud_model": cloud_model,
                        "capability": capability,
                        "module_id": module_id,
                        "busy_job": busy_job,
                        "duration_ms": duration_ms,
                    }),
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] _notify_throughput_escalation failed: {e}")

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
                if config.model_name == current_model or current_model.startswith(config.model_name.split(":")[0]):
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
                    is_paid = tier in ("haiku", "sonnet", "opus") or config.provider not in ("ollama", "ollama_cloud")
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

    def _log_escalation(self, original_agent_id, original_model, escalated_model,
                         escalated_provider, capability, module_id, reason,
                         failure_count, approval_method="auto", success=None, cost=0):
        """Log an escalation event to dispatch_escalation_log."""
        try:
            conn = self._get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO dispatch_escalation_log
                (original_agent_id, original_model, escalated_model, escalated_provider,
                 capability, module_id, reason, failure_count, cost_usd,
                 approved_by, approval_method, success)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (original_agent_id, original_model, escalated_model, escalated_provider,
                  capability, module_id, reason, failure_count, cost,
                  "system" if approval_method == "auto" else None,
                  approval_method, success))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"[BridgeDispatcher] Failed to log escalation: {e}")

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

        # 1. Map capability → station
        station_code = CAPABILITY_STATION_MAP.get(capability, "COMMAND")

        # 2. Select agent for this station + capability
        agent = self._select_agent(capability, station_code)

        if not agent:
            # Fallback: use ARCHIE/COMMAND with dolphin3-8k
            logger.warning(
                f"[BridgeDispatcher] No agent for capability='{capability}' "
                f"station='{station_code}', falling back to COMMAND"
            )
            agent = self._agent_cache.get("ARCHIE", {
                "id": 2,
                "model": "dolphin3-8k:latest",
                "system_prompt": None,
                "temperature": 0.5,
                "station_code": "COMMAND",
            })
            station_code = "COMMAND"

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
            model.startswith(p)
            for p in ("gpt-4o", "llama-3.1-sonar", "grok", "claude")
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
        busy_job = self._check_agent_busy(agent_name)
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
                        model=next_tier["model"], prompt=prompt,
                        system_prompt=system_prompt, json_mode=json_mode,
                        prefer_gpu=prefer_gpu, timeout=timeout,
                    )
                    if escalated_result.get("success"):
                        self._reset_failure(agent.get("id", 0), capability)
                        self._log_escalation(
                            agent.get("id"), model, next_tier["model"],
                            next_tier["provider"], capability, module_id,
                            f"{failure_count} consecutive failures", failure_count,
                            approval_method="auto", success=True,
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
                        logger.warning(f"[BridgeDispatcher] Approval submission failed: {esc_err}")
                    self._log_escalation(
                        agent.get("id"), model, next_tier["model"],
                        next_tier["provider"], capability, module_id,
                        f"{failure_count} failures, awaiting approval", failure_count,
                        approval_method="telegram", success=None,
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
            prompt_tokens=llm_result.get("prompt_tokens", llm_result.get("prompt_eval_count", 0)),
            completion_tokens=llm_result.get("completion_tokens", llm_result.get("eval_count", 0)),
            provider=llm_result.get("provider", "ollama"),
            error=llm_result.get("error"),
            metadata={"module_id": module_id, "priority": priority},
        )

        # 6. Log for HR tracking
        self._log_execution(result, module_id, user_id, job_id=job_id)

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
            cur.execute("""
                SELECT station_code, modules
                FROM bridge_stations
                WHERE is_active = TRUE AND %s = ANY(modules)
                LIMIT 1
            """, (module_id,))
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

        Args:
            job_type: Job category (e.g. 'batch_translate', 'reindex').
            module_source: Module requesting the job.
            description: Human-readable description.
            total_steps: Total number of steps to complete.
            capability: Bridge capability key for agent resolution (e.g. 'translate').
                        Falls back to parsing from job_type if not provided.
            metadata: Additional job metadata (language, batch_size, etc.).

        Returns:
            job_id on success, None on failure.
        """
        try:
            # Resolve agent name from capability→station→agent mapping
            cap_key = capability or job_type.split("_")[0]
            station_code = CAPABILITY_STATION_MAP.get(cap_key, "COMMAND")
            agent = self._select_agent(cap_key, station_code)
            agent_name = None
            if agent:
                for name, info in self._agent_cache.items():
                    if info.get("id") == agent.get("id"):
                        agent_name = name
                        break

            conn = self._get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO bridge_jobs (job_type, module_source, description,
                    total_steps, status, agent_name, metadata)
                VALUES (%s, %s, %s, %s, 'running', %s, %s)
                RETURNING id
                """,
                (
                    job_type,
                    module_source,
                    description,
                    total_steps,
                    agent_name,
                    json.dumps(metadata or {}),
                ),
            )
            job_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()
            logger.info(
                f"[BridgeDispatcher] Created job #{job_id}: {description} "
                f"({total_steps} steps, agent={agent_name})"
            )
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
                    (completed_steps, failed_steps, json.dumps(metadata_update), job_id),
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
                """,
                (status, job_id),
            )
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"[BridgeDispatcher] Job #{job_id} → {status}")
            return True
        except Exception as e:
            logger.error(f"[BridgeDispatcher] complete_job failed: {e}")
            return False

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
                    "avg_duration_sec": round(float(r["avg_duration_sec"] or 0) / 1000, 1),
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

                manifest.append({
                    "name": name,
                    "full_name": full_name,
                    "title": info.get("title", ""),
                    "agent_id": agent_id,
                    "station": info.get("station_code", "COMMAND"),
                    "model": model,
                    "hardware": hw,
                    "status": status,
                    "wellness": wellness_map.get(agent_id, {
                        "stress": 0.0, "energy": 1.0, "mood": "neutral",
                    }),
                    "current_job": jobs_map.get(name),
                    "stats_24h": stats_map.get(name, {
                        "dispatches": 0, "success_rate": 0.0, "avg_duration_sec": 0,
                    }),
                    "learning_count": learning_map.get(name, 0),
                })

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
            stations[sc]["agents"].append({
                "name": name,
                "id": info["id"],
                "model": info["model"],
                "status": "active",
            })

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
