"""
Smart LLM Router - Intelligent Model Selection for Cost Optimization

Implements the Hybrid LLM Optimization strategy:
- Local (Ollama) → Haiku → Sonnet → Opus escalation
- Task-type based routing rules
- Auto-escalation on failures
- Claude-as-Judge pattern for quality assurance
- Per-agent Opus budget limits

Based on the Claude Code CLI - Smart Usage & Hybrid LLM Optimization Guide
"""

import json
import logging
import requests
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

# Database imports — direct psycopg2, mirroring department_dispatcher._get_db's working
# fallback. The old `from config import get_db` NEVER resolved (config.py exports no
# get_db), which left get_db=None forever: routing_mode was silently ignored and every
# DB-backed lookup degraded to defaults (audit 2026-08-17, proposal #3383).
try:
    import os

    import psycopg2
    from psycopg2.extras import RealDictCursor

    def get_db():
        # #5968: the password comes from the DOCKER SECRET, not the environment.
        # DB_PASSWORD is EMPTY in every process — measured len=0 in PID 1 of BOTH
        # archie_platform and archie_scheduler — and the real value lives only in
        # /run/secrets/db_password. `password=os.getenv("DB_PASSWORD", "")` therefore
        # sent an empty password on EVERY call, so this connection has NEVER succeeded:
        #     fe_sendauth: no password supplied
        # Every DB-backed lookup below (routing_mode, model tier configs, task-type
        # complexity thresholds, the Opus budget cap, v_model_usage_summary, floors)
        # silently fell back to hardcoded defaults, and the caller logs a WARNING and
        # continues — so the router LOOKED healthy while ignoring its own configuration.
        #
        # ⚠️ This is the SECOND time this exact symptom shipped here. The comment above
        # describes the first (a `from config import get_db` that never resolved, leaving
        # get_db=None "forever"). That was fixed by copying department_dispatcher's
        # connect() — but not its password resolution: the dispatcher uses
        # `from db import _get_db_password`, which reads the secret. The shape was copied
        # and the one line that mattered was not.
        #
        # Imported INSIDE the function deliberately: module-level would couple import
        # order and risk a cycle, and sys.modules makes the repeat cost nil.
        from database import _get_db_password

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "192.168.1.200"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

except ImportError:
    # Fallback for testing
    get_db = None
    RealDictCursor = None

logger = logging.getLogger(__name__)


class ModelTier(Enum):
    """Model tier hierarchy (lower = cheaper, higher = more capable)"""

    CLASSIFY = "classify"  # Tiny fast classifier (~1.5B, CPU, <500ms)
    LOCAL = "local"
    LOCAL_ANALYSIS = "local_analysis"
    VISION = "vision"  # Multimodal vision model (CPU)
    # MINIMAX_CLOUD retired 2026-08-17 (#5706) — minimax-m2.5:cloud 410s on every dispatch.
    QWEN3_CLOUD = "qwen3_cloud"
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"


@dataclass
class ModelConfig:
    """Configuration for a model tier"""

    tier: str
    provider: str
    model_name: str
    input_cost_per_1m: float
    output_cost_per_1m: float
    max_tokens: int = 4096
    fallback_model: Optional[str] = None


@dataclass
class RoutingRecommendation:
    """Recommendation from the smart router"""

    tier: str
    provider: str
    model_name: str
    reason: str
    should_escalate: bool = False
    use_claude_as_judge: bool = False
    estimated_cost: float = 0.0
    force_reset: bool = False


# Default model configurations
DEFAULT_MODEL_CONFIGS = {
    "classify": ModelConfig(
        tier="classify",
        provider="ollama",
        model_name="qwen25-classify",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        max_tokens=4096,
    ),
    "local": ModelConfig(
        tier="local",
        provider="ollama",
        model_name="dolphin3-8k:latest",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        max_tokens=8192,
    ),
    "local_analysis": ModelConfig(
        tier="local_analysis",
        provider="ollama",
        model_name="qwen3-coder-cpu:latest",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        max_tokens=32768,
    ),
    "vision": ModelConfig(
        tier="vision",
        provider="ollama",
        model_name="minicpm-v-cpu",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        max_tokens=4096,
    ),
    # "minimax_cloud" retired 2026-08-17 (#5706) — minimax-m2.5 410s on every dispatch.
    "qwen3_cloud": ModelConfig(
        tier="qwen3_cloud",
        provider="ollama_cloud",
        model_name="qwen3-coder-next",
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        max_tokens=32768,
    ),
    "haiku": ModelConfig(
        tier="haiku",
        provider="claude",
        model_name="claude-3-haiku-20240307",
        input_cost_per_1m=0.25,
        output_cost_per_1m=1.25,
        max_tokens=4096,
    ),
    "sonnet": ModelConfig(
        tier="sonnet",
        provider="claude",
        model_name="claude-sonnet-4-20250514",
        input_cost_per_1m=3.00,
        output_cost_per_1m=15.00,
        max_tokens=8192,
    ),
    "opus": ModelConfig(
        tier="opus",
        provider="claude",
        model_name="claude-opus-4-20250514",
        input_cost_per_1m=15.00,
        output_cost_per_1m=75.00,
        max_tokens=16384,
    ),
}

# Tier escalation order (classify and vision are capability-specific, not in main escalation chain)
TIER_ORDER = [
    "classify",
    "local",
    "local_analysis",
    "qwen3_cloud",
    "openai",
    "perplexity",
    "grok",
    "haiku",
    "sonnet",
    "opus",
]

# Capability-based routing: maps capability requirements to preferred tiers
CAPABILITY_ROUTING = {
    "classify": "classify",  # Intent routing, sentiment, tagging
    "sentiment": "classify",  # Emotion detection
    "tagging": "classify",  # Auto-tagging
    "vision": "vision",  # Image understanding
    "multimodal": "vision",  # Image + text
    "json": "local",  # Structured output (any model with format=json)
    "code": "local_analysis",  # Code generation/analysis
    "code_review": "local_analysis",  # Code scanning/review (Dev Pipeline)
    "conversation": "local",  # Chat
    "summarize": "local",  # Summarization
    "embed": "local",  # (handled by embedding service, not router)
    "translate": "local_analysis",  # Translation via the 'translate' capability (mistral:7b / gemma3:12b)
    "detect_language": "classify",  # Language detection via qwen25-classify
    "image_generation": "qwen3_cloud",  # Placeholder — actual routing via media adapters (was minimax_cloud, retired #5706)
    "video_generation": "qwen3_cloud",  # Placeholder — actual routing via media adapters (was minimax_cloud, retired #5706)
    "audio_tts": "local",  # Local Kokoro/XTTS first
    "audio_music": "qwen3_cloud",  # Placeholder — actual routing via media adapters (was minimax_cloud, retired #5706)
}

# Capability taxonomy — maps detected intent to normalized capability tags
# Must match department_capability_profiles.required_capabilities and contractor_providers.capabilities
CAPABILITY_TAXONOMY = {
    "code_generation": ["code", "generate code", "implement", "build function", "create class", "write code"],
    "code_review": ["review code", "audit code", "check code", "code quality", "pr review"],
    "debugging": ["debug", "fix bug", "error", "traceback", "exception", "stack trace"],
    "architecture": ["architect", "design system", "refactor", "restructure", "migration plan"],
    "summarization": ["summarize", "summary", "tldr", "brief", "recap"],
    "reasoning": ["reason", "analyze", "think through", "logic", "explain why", "evaluate"],
    "creative_writing": ["write story", "creative", "compose", "draft article", "blog post"],
    "image_gen": ["image", "picture", "draw", "generate image", "visual", "illustration"],
    "vision": ["describe image", "what is this image", "analyze photo", "ocr"],
    "classification": ["classify", "categorize", "label", "tag", "sort into"],
    "data_analysis": ["data", "statistics", "chart", "graph", "trend", "forecast"],
    "fact_checking": ["fact check", "verify claim", "is this true", "source check"],
    "translation": ["translate", "language", "multilingual", "localize"],
    "conversation": ["chat", "talk", "discuss", "help me", "question"],
    "ethics_reasoning": ["ethical", "creed", "compliance", "policy violation", "governance"],
    "research_synthesis": ["research", "find information", "investigate", "literature review"],
    "embedding": ["embed", "vector", "similarity search", "semantic"],
    "knowledge_extraction": ["extract", "parse", "pull out", "identify entities"],
    "news_writing": ["news", "article", "headline", "press release", "editorial"],
    "bias_detection": ["bias", "fairness", "balanced", "perspective"],
}


def _get_routing_mode() -> str:
    """Read routing_mode from platform_settings. Returns 'full' on error."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else "full"
    except Exception:
        return "full"


class SmartRouter:
    """
    Intelligent model routing based on task type, complexity, and cost.

    Strategy:
    1. Local LLM for drafts, formatting, summaries (FREE)
    2. Sonnet for standard coding tasks (workhorse)
    3. Opus only for architecture, complex debugging (15% max)
    """

    def __init__(self):
        self._model_configs = None
        self._routing_rules = None

    def get_available_tiers(self, routing_mode: str = None) -> list:
        """Filter TIER_ORDER based on routing mode."""
        if routing_mode is None:
            routing_mode = _get_routing_mode()

        local_tiers = {"classify", "local", "local_analysis", "vision"}
        cloud_tiers = {"qwen3_cloud"}  # minimax_cloud retired #5706

        if routing_mode == "local_only":
            return [t for t in TIER_ORDER if t in local_tiers]
        elif routing_mode == "local_cloud":
            return [t for t in TIER_ORDER if t in local_tiers | cloud_tiers]
        else:
            return list(TIER_ORDER)

    def _get_model_configs(self) -> Dict[str, ModelConfig]:
        """Load model configurations from database or use defaults"""
        if self._model_configs is not None:
            return self._model_configs

        try:
            if get_db is None:
                return DEFAULT_MODEL_CONFIGS

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT tier_name, provider, model_name, input_cost_per_1m,
                       output_cost_per_1m, max_tokens, fallback_model
                FROM model_tier_configs
                WHERE is_active = TRUE
            """
            )

            rows = cur.fetchall()
            cur.close()
            conn.close()

            if not rows:
                return DEFAULT_MODEL_CONFIGS

            configs = {}
            for row in rows:
                configs[row["tier_name"]] = ModelConfig(
                    tier=row["tier_name"],
                    provider=row["provider"],
                    model_name=row["model_name"],
                    input_cost_per_1m=float(row["input_cost_per_1m"] or 0),
                    output_cost_per_1m=float(row["output_cost_per_1m"] or 0),
                    max_tokens=row["max_tokens"] or 4096,
                    fallback_model=row["fallback_model"],
                )

            self._model_configs = configs
            return configs

        except Exception as e:
            logger.warning(f"Error loading model configs: {e}, using defaults")
            return DEFAULT_MODEL_CONFIGS

    def _get_routing_rules(self) -> Dict[str, dict]:
        """Load routing rules from database"""
        if self._routing_rules is not None:
            return self._routing_rules

        try:
            if get_db is None:
                return self._default_routing_rules()

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT task_type, description, complexity_threshold,
                       preferred_tier, fallback_tier, max_context_tokens,
                       require_reset_on_escalate, claude_as_judge
                FROM task_routing_rules
                WHERE is_active = TRUE
            """
            )

            rows = cur.fetchall()
            cur.close()
            conn.close()

            rules = {row["task_type"]: dict(row) for row in rows}
            self._routing_rules = rules
            return rules

        except Exception as e:
            logger.warning(f"Error loading routing rules: {e}, using defaults")
            return self._default_routing_rules()

    def suggest_model_by_capability(
        self,
        capability: str,
        fallback_task_type: str = "code_simple",
        **kwargs,
    ) -> RoutingRecommendation:
        """
        Route by capability requirement rather than task type.

        Args:
            capability: Required capability (classify, vision, json, code, etc.)
            fallback_task_type: Fall back to task-based routing if capability unknown

        Returns:
            RoutingRecommendation
        """
        tier = CAPABILITY_ROUTING.get(capability)
        if tier:
            available = self.get_available_tiers()
            if tier not in available:
                # Tier blocked by routing mode — find first available
                configs = self._get_model_configs()
                for t in available:
                    if t in configs:
                        return RoutingRecommendation(
                            tier=configs[t].tier,
                            provider=configs[t].provider,
                            model_name=configs[t].model_name,
                            reason=f"Capability '{capability}' tier '{tier}' blocked by routing mode, using '{t}'",
                        )
            configs = self._get_model_configs()
            config = configs.get(tier)
            if config:
                return RoutingRecommendation(
                    tier=config.tier,
                    provider=config.provider,
                    model_name=config.model_name,
                    reason=f"Capability '{capability}' -> {tier} tier",
                )
        # Fall back to task-based routing
        return self.suggest_model(task_type=fallback_task_type, **kwargs)

    def _default_routing_rules(self) -> Dict[str, dict]:
        """Default routing rules if database not available"""
        return {
            "classify": {
                "preferred_tier": "classify",
                "fallback_tier": "local",
                "complexity_threshold": 2,
                "claude_as_judge": False,
            },
            "sentiment": {
                "preferred_tier": "classify",
                "fallback_tier": "local",
                "complexity_threshold": 2,
                "claude_as_judge": False,
            },
            "tagging": {
                "preferred_tier": "classify",
                "fallback_tier": "local",
                "complexity_threshold": 3,
                "claude_as_judge": False,
            },
            "vision": {
                "preferred_tier": "vision",
                "fallback_tier": "sonnet",
                "complexity_threshold": 5,
                "claude_as_judge": False,
            },
            "conversation": {
                "preferred_tier": "local",
                "fallback_tier": "local",
                "complexity_threshold": 7,
                "claude_as_judge": False,
            },
            "format": {
                "preferred_tier": "classify",
                "fallback_tier": "local",
                "complexity_threshold": 3,
                "claude_as_judge": False,
            },
            "rewrite": {
                "preferred_tier": "local",
                "fallback_tier": "sonnet",
                "complexity_threshold": 4,
                "claude_as_judge": True,
            },
            "summarize": {
                "preferred_tier": "local",
                "fallback_tier": "haiku",
                "complexity_threshold": 3,
                "claude_as_judge": False,
            },
            "code_simple": {
                "preferred_tier": "sonnet",
                "fallback_tier": "sonnet",
                "complexity_threshold": 5,
                "claude_as_judge": False,
            },
            "code_complex": {
                "preferred_tier": "sonnet",
                "fallback_tier": "opus",
                "complexity_threshold": 7,
                "claude_as_judge": False,
            },
            "refactor": {
                "preferred_tier": "sonnet",
                "fallback_tier": "opus",
                "complexity_threshold": 6,
                "claude_as_judge": False,
            },
            "architecture": {
                "preferred_tier": "opus",
                "fallback_tier": "opus",
                "complexity_threshold": 8,
                "claude_as_judge": False,
            },
            "debug_simple": {
                "preferred_tier": "sonnet",
                "fallback_tier": "sonnet",
                "complexity_threshold": 5,
                "claude_as_judge": False,
            },
            "debug_hard": {
                "preferred_tier": "opus",
                "fallback_tier": "opus",
                "complexity_threshold": 8,
                "claude_as_judge": False,
            },
            "review": {
                "preferred_tier": "sonnet",
                "fallback_tier": "sonnet",
                "complexity_threshold": 5,
                "claude_as_judge": True,
            },
            "test_scaffold": {
                "preferred_tier": "haiku",
                "fallback_tier": "sonnet",
                "complexity_threshold": 3,
                "claude_as_judge": False,
            },
            "documentation": {
                "preferred_tier": "local",
                "fallback_tier": "sonnet",
                "complexity_threshold": 4,
                "claude_as_judge": True,
            },
            "sql": {
                "preferred_tier": "sonnet",
                "fallback_tier": "sonnet",
                "complexity_threshold": 5,
                "claude_as_judge": False,
            },
            "api_design": {
                "preferred_tier": "sonnet",
                "fallback_tier": "opus",
                "complexity_threshold": 6,
                "claude_as_judge": False,
            },
            "security_audit": {
                "preferred_tier": "opus",
                "fallback_tier": "opus",
                "complexity_threshold": 7,
                "claude_as_judge": False,
            },
        }

    def suggest_model(
        self,
        task_type: str,
        complexity: int = 5,
        context_tokens: int = 0,
        agent_id: Optional[int] = None,
        failure_count: int = 0,
    ) -> RoutingRecommendation:
        """
        Get recommended model for a task.

        Args:
            task_type: Type of task (format, code_simple, architecture, etc.)
            complexity: Task complexity score 1-10
            context_tokens: Estimated context token count
            agent_id: Agent ID for budget checking
            failure_count: Number of previous failures

        Returns:
            RoutingRecommendation with tier, model, and reasoning
        """
        configs = self._get_model_configs()
        rules = self._get_routing_rules()

        # Get routing rule for task type
        rule = rules.get(
            task_type,
            rules.get(
                "code_simple",
                {
                    "preferred_tier": "sonnet",
                    "fallback_tier": "sonnet",
                    "complexity_threshold": 5,
                    "claude_as_judge": False,
                },
            ),
        )

        # Start with preferred tier
        tier = rule.get("preferred_tier", "sonnet")
        reason_parts = [f"Task type '{task_type}' maps to {tier}"]
        use_judge = rule.get("claude_as_judge", False)
        force_reset = False

        # Check complexity threshold
        threshold = rule.get("complexity_threshold", 5)
        if complexity > threshold:
            fallback = rule.get("fallback_tier")
            if fallback and fallback != tier:
                tier = fallback
                reason_parts.append(f"complexity {complexity} > threshold {threshold} → {tier}")

        # Check for escalation based on failures
        should_escalate = False
        if failure_count >= 3 and tier != "opus":
            tier = self._escalate_tier(tier)
            should_escalate = True
            force_reset = rule.get("require_reset_on_escalate", True)
            reason_parts.append(f"{failure_count} failures → escalated to {tier}")

        # Check agent's Opus budget if trying to use Opus
        if tier == "opus" and agent_id:
            over_budget, budget_info = self._check_opus_budget(agent_id)
            if over_budget:
                tier = "sonnet"
                reason_parts.append(f"Opus budget exceeded ({budget_info}) → downgraded to sonnet")

        # Get model config
        config = configs.get(tier, DEFAULT_MODEL_CONFIGS.get(tier, DEFAULT_MODEL_CONFIGS["sonnet"]))

        # Estimate cost
        estimated_cost = self._estimate_cost(config, context_tokens)

        return RoutingRecommendation(
            tier=tier,
            provider=config.provider,
            model_name=config.model_name,
            reason="; ".join(reason_parts),
            should_escalate=should_escalate,
            use_claude_as_judge=use_judge and tier == "local",
            estimated_cost=estimated_cost,
            force_reset=force_reset,
        )

    def _escalate_tier(self, current_tier: str) -> str:
        """Get next tier up from current"""
        try:
            idx = TIER_ORDER.index(current_tier)
            if idx < len(TIER_ORDER) - 1:
                return TIER_ORDER[idx + 1]
        except ValueError:
            pass
        return current_tier

    def _check_opus_budget(self, agent_id: int) -> Tuple[bool, str]:
        """Check if agent has exceeded their Opus budget"""
        try:
            if get_db is None:
                return False, "N/A"

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT max_opus_percentage, opus_usage_this_month, total_tasks_this_month
                FROM agents WHERE id = %s
            """,
                (agent_id,),
            )

            agent = cur.fetchone()
            cur.close()
            conn.close()

            if not agent:
                return False, "Agent not found"

            max_pct = float(agent["max_opus_percentage"] or 0.15)
            usage = int(agent["opus_usage_this_month"] or 0)
            total = int(agent["total_tasks_this_month"] or 0)

            if total == 0:
                return False, "0 tasks"

            current_pct = usage / total
            budget_info = f"{current_pct:.1%} of {max_pct:.0%} max"

            return current_pct >= max_pct, budget_info

        except Exception as e:
            logger.error(f"Error checking Opus budget: {e}")
            return False, "Error"

    def _estimate_cost(self, config: ModelConfig, context_tokens: int) -> float:
        """Estimate cost for a task with given model"""
        # Assume ~1000 output tokens average
        output_tokens = 1000

        input_cost = (context_tokens / 1_000_000) * config.input_cost_per_1m
        output_cost = (output_tokens / 1_000_000) * config.output_cost_per_1m

        return round(input_cost + output_cost, 6)

    def get_escalation_prompt(self, original_prompt: str, failures: int, error_context: str = "") -> str:
        """
        Generate an enhanced prompt for Opus escalation.

        When escalating to Opus, include failure context and request
        careful, deep reasoning.
        """
        return f"""This task has failed {failures} times with lighter models.
Focus on deep reasoning and correctness. Assume prior attempts were insufficient.

{f"Previous error context: {error_context}" if error_context else ""}

IMPORTANT: Take your time. Think step by step. Provide a final, defensible solution.

---

Original task:
{original_prompt}"""

    def track_execution(
        self,
        agent_id: Optional[int],
        task_type: str,
        tier: str,
        model: str,
        provider: str,
        outcome: str,
        tokens: int = 0,
        cost: float = 0.0,
        escalated: bool = False,
        claude_as_judge: bool = False,
        error_message: str = None,
    ) -> Optional[int]:
        """
        Track task execution for analytics.

        Returns execution ID or None on error.
        """
        try:
            if get_db is None:
                return None

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                INSERT INTO task_executions
                (agent_id, task_type, model_tier_used, model_name, provider,
                 outcome, total_tokens, cost, escalated, claude_as_judge_used, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    agent_id,
                    task_type,
                    tier,
                    model,
                    provider,
                    outcome,
                    tokens,
                    cost,
                    escalated,
                    claude_as_judge,
                    error_message,
                ),
            )

            result = cur.fetchone()
            execution_id = result["id"] if result else None

            conn.commit()
            cur.close()
            conn.close()

            # Single-writer path: increment monthly usage counters via
            # agent_service so the agents table only has one canonical
            # mutation surface (Project #241 Track C.3).
            if agent_id:
                try:
                    from services import agent_service

                    agent_service.increment_usage(agent_id, tier)
                except Exception as exc:
                    logger.warning(f"increment_usage failed for agent {agent_id}: {exc}")

            return execution_id

        except Exception as e:
            logger.error(f"Error tracking execution: {e}")
            return None

    def get_usage_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get model usage analytics for the past N days"""
        try:
            if get_db is None:
                return {"error": "Database not available"}

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get summary from view
            cur.execute("SELECT * FROM v_model_usage_summary")
            tier_summary = cur.fetchall()

            # Get cost savings estimate
            cur.execute(
                """
                SELECT
                    SUM(cost) as actual_cost,
                    SUM(total_tokens) as total_tokens,
                    COUNT(*) FILTER (WHERE model_tier_used = 'local') as local_tasks,
                    COUNT(*) FILTER (WHERE claude_as_judge_used = TRUE) as judge_tasks,
                    COUNT(*) FILTER (WHERE model_tier_used = 'opus') as opus_tasks
                FROM task_executions
                WHERE started_at >= NOW() - INTERVAL '%s days'
            """,
                (days,),
            )

            cost_data = cur.fetchone()

            cur.close()
            conn.close()

            # Calculate estimated savings vs all-Opus
            total_tokens = cost_data["total_tokens"] or 0
            actual_cost = float(cost_data["actual_cost"] or 0)
            opus_cost_estimate = total_tokens * 0.000045  # Rough Opus estimate

            return {
                "tier_summary": [dict(t) for t in tier_summary],
                "total_cost": actual_cost,
                "estimated_opus_cost": opus_cost_estimate,
                "estimated_savings": opus_cost_estimate - actual_cost,
                "local_tasks": cost_data["local_tasks"] or 0,
                "judge_tasks": cost_data["judge_tasks"] or 0,
                "opus_tasks": cost_data["opus_tasks"] or 0,
                "days": days,
            }

        except Exception as e:
            logger.error(f"Error getting analytics: {e}")
            return {"error": str(e)}

    def _detect_capability(self, prompt: str) -> str:
        """Detect the primary capability needed from the prompt text.

        Returns a normalized capability tag matching department_capability_profiles
        and contractor_providers.capabilities taxonomy.
        """
        if not prompt:
            return "conversation"
        prompt_lower = prompt.lower()
        best_match = "conversation"  # default fallback
        best_score = 0
        for capability, keywords in CAPABILITY_TAXONOMY.items():
            score = sum(1 for kw in keywords if kw in prompt_lower)
            if score > best_score:
                best_score = score
                best_match = capability
        return best_match

    def classify_task(self, prompt: str, context: dict = None, return_capability: bool = False):
        """
        Classify a task based on prompt content.

        This is a simple heuristic classifier. In production,
        you might use a more sophisticated approach or even
        an LLM for classification.

        Args:
            prompt: The task prompt to classify.
            context: Optional context dict.
            return_capability: If True, returns (tier, capability) tuple.
                               If False (default), returns just the tier string.
        """
        prompt_lower = prompt.lower()

        # Architecture/design tasks
        if any(kw in prompt_lower for kw in ["architecture", "design system", "high-level", "system design"]):
            tier = "architecture"
        # Security tasks
        elif any(kw in prompt_lower for kw in ["security", "vulnerability", "audit", "penetration", "cve"]):
            tier = "security_audit"
        # Complex debugging
        elif any(
            kw in prompt_lower
            for kw in [
                "race condition",
                "memory leak",
                "deadlock",
                "crash",
                "intermittent",
            ]
        ):
            tier = "debug_hard"
        # Simple debugging
        elif any(kw in prompt_lower for kw in ["debug", "fix bug", "error", "exception", "traceback"]):
            tier = "debug_simple"
        # Refactoring
        elif any(kw in prompt_lower for kw in ["refactor", "restructure", "clean up", "improve code"]):
            tier = "refactor"
        # Code review
        elif any(kw in prompt_lower for kw in ["review", "code review", "pr review", "pull request"]):
            tier = "review"
        # API design
        elif any(kw in prompt_lower for kw in ["api design", "endpoint design", "rest api", "graphql"]):
            tier = "api_design"
        # SQL
        elif any(kw in prompt_lower for kw in ["sql", "query", "database", "migration"]):
            tier = "sql"
        # Documentation
        elif any(kw in prompt_lower for kw in ["document", "readme", "docstring", "jsdoc", "comment"]):
            tier = "documentation"
        # Tests
        elif any(kw in prompt_lower for kw in ["test", "unit test", "integration test", "spec"]):
            tier = "test_scaffold"
        # Formatting
        elif any(kw in prompt_lower for kw in ["format", "lint", "prettier", "style"]):
            tier = "format"
        # Summarization
        elif any(kw in prompt_lower for kw in ["summarize", "summary", "tldr", "overview"]):
            tier = "summarize"
        # Rewrite
        elif any(kw in prompt_lower for kw in ["rewrite", "rephrase", "improve writing"]):
            tier = "rewrite"
        # Check complexity indicators for code tasks
        elif any(
            kw in prompt_lower
            for kw in [
                "multiple files",
                "across",
                "entire",
                "whole codebase",
                "full implementation",
            ]
        ):
            tier = "code_complex"
        else:
            # Default to simple coding
            tier = "code_simple"

        if return_capability:
            capability = self._detect_capability(prompt)
            return tier, capability
        return tier

    def get_loaded_model(self) -> Optional[str]:
        """
        Check which Ollama model is currently loaded in GPU memory.
        Checks local Ollama instance (where the GPU is) via /api/ps.

        Returns:
            Model name string (e.g. 'dolphin3:latest') or None
        """
        try:
            import os

            # Check local Ollama (where the GPU lives), not remote nodes
            local_host = os.getenv("OLLAMA_LOCAL_HOST", "host.docker.internal")
            local_port = os.getenv("OLLAMA_LOCAL_PORT", "11434")
            resp = requests.get(f"http://{local_host}:{local_port}/api/ps", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                if models:
                    return models[0].get("name")
        except Exception as e:
            logger.debug(f"Could not check loaded Ollama model: {e}")
        return None

    def can_downgrade(self, loaded_model: str, task_type: str) -> bool:
        """
        Check if the currently loaded model can handle a task even if it's
        not the recommended model. Avoids GPU model swaps on constrained hardware.

        Args:
            loaded_model: The model currently in GPU memory
            task_type: The classified task type

        Returns:
            True if the loaded model can handle this task type
        """
        # Tasks that any general model can handle
        simple_tasks = {
            "conversation",
            "format",
            "code_simple",
            "documentation",
            "summarize",
            "rewrite",
            "sql",
            "test_scaffold",
        }
        if task_type in simple_tasks:
            return True

        # dolphin3 can handle moderate tasks
        if "dolphin3" in loaded_model:
            moderate_tasks = {"refactor", "review", "debug_simple", "api_design"}
            if task_type in moderate_tasks:
                return True

        return False

    def suggest_model_with_hardware(
        self,
        task_type: str,
        complexity: int = 5,
        agent_id: Optional[int] = None,
        failure_count: int = 0,
    ) -> RoutingRecommendation:
        """
        GPU-aware model suggestion. Extends suggest_model() with hardware state.

        Checks what model is loaded and avoids swaps where possible.
        If the task requires a higher tier than what's loaded locally,
        routes to Claude proxy instead of swapping models.
        """
        # Get base recommendation
        rec = self.suggest_model(
            task_type,
            complexity=complexity,
            agent_id=agent_id,
            failure_count=failure_count,
        )

        # Cloud tiers don't use local GPU — pass through
        if rec.provider == "ollama_cloud":
            return rec

        # Only apply GPU-awareness to local ollama tiers
        if rec.provider != "ollama" or rec.tier not in ("local", "local_analysis"):
            return rec

        loaded = self.get_loaded_model()
        if not loaded:
            return rec

        requested = rec.model_name
        # If already loaded, great
        if loaded == requested or loaded.split(":")[0] == requested.split(":")[0]:
            rec.reason += f"; {loaded} already loaded (fast path)"
            return rec

        # Can the loaded model handle it?
        if self.can_downgrade(loaded, task_type):
            return RoutingRecommendation(
                tier="local",
                provider="ollama",
                model_name=loaded,
                reason=f"{loaded} already loaded, can handle '{task_type}' (avoiding swap)",
                should_escalate=False,
                estimated_cost=0.0,
            )

        # Swap would be needed — route to Claude proxy instead
        return RoutingRecommendation(
            tier="sonnet",
            provider="claude",
            model_name="claude-sonnet-4-20250514",
            reason=f"Task '{task_type}' needs model swap ({loaded} → {requested}); routing to Claude to avoid GPU crash",
            should_escalate=True,
            estimated_cost=rec.estimated_cost,
        )


def get_department_escalation_chain(department: str) -> List[str]:
    """Get ordered list of departments to try, based on floor proximity.

    Order: target dept -> same-floor depts (alphabetical) -> other floors (by deck) -> cloud fallback.
    Used by the orchestration engine / dispatcher when selecting which agent
    (and therefore which department) should handle a task.  The smart router
    itself deals with *model* selection; this helper is complementary.

    Args:
        department: Department code to start from (e.g. 'ENGINEERING')

    Returns:
        Ordered list of department codes to attempt.
    """
    conn = None
    try:
        if get_db is None:
            return [department]

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find the floor for this department
        cur.execute(
            "SELECT code, departments FROM floors WHERE %s = ANY(departments)",
            (department,),
        )
        row = cur.fetchone()
        if not row:
            return [department]  # unknown dept, just try it

        same_floor = sorted(d for d in row["departments"] if d != department)

        # Get other floors ordered by deck_number
        cur.execute(
            "SELECT departments FROM floors WHERE code != %s ORDER BY deck_number",
            (row["code"],),
        )
        other_floors = [d for floor_row in cur.fetchall() for d in sorted(floor_row["departments"])]

        cur.close()
        return [department] + same_floor + other_floors

    except Exception as e:
        logger.error(f"Department escalation chain lookup failed: {e}")
        return [department]
    finally:
        if conn:
            conn.close()


# Singleton instance
_router_instance = None


def get_router() -> SmartRouter:
    """Get singleton router instance"""
    global _router_instance
    if _router_instance is None:
        _router_instance = SmartRouter()
    return _router_instance


# Convenience functions
def suggest_model(task_type: str, **kwargs) -> RoutingRecommendation:
    """Convenience function to get model suggestion"""
    return get_router().suggest_model(task_type, **kwargs)


def track_execution(**kwargs) -> Optional[int]:
    """Convenience function to track execution"""
    return get_router().track_execution(**kwargs)


def classify_task(prompt: str, context: dict = None, return_capability: bool = False):
    """Convenience function to classify task.

    Args:
        prompt: The task prompt to classify.
        context: Optional context dict.
        return_capability: If True, returns (tier, capability) tuple.
                           If False (default), returns just the tier string.
    """
    return get_router().classify_task(prompt, context, return_capability=return_capability)


def get_loaded_model() -> Optional[str]:
    """Convenience function to check loaded Ollama model"""
    return get_router().get_loaded_model()


def suggest_model_with_hardware(task_type: str, **kwargs) -> RoutingRecommendation:
    """Convenience function for GPU-aware model suggestion"""
    return get_router().suggest_model_with_hardware(task_type, **kwargs)


def department_escalation_chain(department: str) -> List[str]:
    """Convenience function to get floor-aware department escalation order"""
    return get_department_escalation_chain(department)
