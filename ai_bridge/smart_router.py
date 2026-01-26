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
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

# Database imports
try:
    from config import get_db
    from psycopg2.extras import RealDictCursor
except ImportError:
    # Fallback for testing
    get_db = None
    RealDictCursor = None

logger = logging.getLogger(__name__)


class ModelTier(Enum):
    """Model tier hierarchy (lower = cheaper, higher = more capable)"""
    LOCAL = "local"
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
    'local': ModelConfig(
        tier='local',
        provider='ollama',
        model_name='deepseek-coder-v2:16b',
        input_cost_per_1m=0.0,
        output_cost_per_1m=0.0,
        max_tokens=8192
    ),
    'haiku': ModelConfig(
        tier='haiku',
        provider='claude',
        model_name='claude-3-haiku-20240307',
        input_cost_per_1m=0.25,
        output_cost_per_1m=1.25,
        max_tokens=4096
    ),
    'sonnet': ModelConfig(
        tier='sonnet',
        provider='claude',
        model_name='claude-sonnet-4-20250514',
        input_cost_per_1m=3.00,
        output_cost_per_1m=15.00,
        max_tokens=8192
    ),
    'opus': ModelConfig(
        tier='opus',
        provider='claude',
        model_name='claude-opus-4-20250514',
        input_cost_per_1m=15.00,
        output_cost_per_1m=75.00,
        max_tokens=16384
    )
}

# Tier escalation order
TIER_ORDER = ['local', 'haiku', 'sonnet', 'opus']


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

    def _get_model_configs(self) -> Dict[str, ModelConfig]:
        """Load model configurations from database or use defaults"""
        if self._model_configs is not None:
            return self._model_configs

        try:
            if get_db is None:
                return DEFAULT_MODEL_CONFIGS

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("""
                SELECT tier_name, provider, model_name, input_cost_per_1m,
                       output_cost_per_1m, max_tokens, fallback_model
                FROM model_tier_configs
                WHERE is_active = TRUE
            """)

            rows = cur.fetchall()
            cur.close()
            conn.close()

            if not rows:
                return DEFAULT_MODEL_CONFIGS

            configs = {}
            for row in rows:
                configs[row['tier_name']] = ModelConfig(
                    tier=row['tier_name'],
                    provider=row['provider'],
                    model_name=row['model_name'],
                    input_cost_per_1m=float(row['input_cost_per_1m'] or 0),
                    output_cost_per_1m=float(row['output_cost_per_1m'] or 0),
                    max_tokens=row['max_tokens'] or 4096,
                    fallback_model=row['fallback_model']
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

            cur.execute("""
                SELECT task_type, description, complexity_threshold,
                       preferred_tier, fallback_tier, max_context_tokens,
                       require_reset_on_escalate, claude_as_judge
                FROM task_routing_rules
                WHERE is_active = TRUE
            """)

            rows = cur.fetchall()
            cur.close()
            conn.close()

            rules = {row['task_type']: dict(row) for row in rows}
            self._routing_rules = rules
            return rules

        except Exception as e:
            logger.warning(f"Error loading routing rules: {e}, using defaults")
            return self._default_routing_rules()

    def _default_routing_rules(self) -> Dict[str, dict]:
        """Default routing rules if database not available"""
        return {
            'format': {'preferred_tier': 'local', 'fallback_tier': 'haiku', 'complexity_threshold': 3, 'claude_as_judge': False},
            'rewrite': {'preferred_tier': 'local', 'fallback_tier': 'sonnet', 'complexity_threshold': 4, 'claude_as_judge': True},
            'summarize': {'preferred_tier': 'local', 'fallback_tier': 'haiku', 'complexity_threshold': 3, 'claude_as_judge': False},
            'code_simple': {'preferred_tier': 'sonnet', 'fallback_tier': 'sonnet', 'complexity_threshold': 5, 'claude_as_judge': False},
            'code_complex': {'preferred_tier': 'sonnet', 'fallback_tier': 'opus', 'complexity_threshold': 7, 'claude_as_judge': False},
            'refactor': {'preferred_tier': 'sonnet', 'fallback_tier': 'opus', 'complexity_threshold': 6, 'claude_as_judge': False},
            'architecture': {'preferred_tier': 'opus', 'fallback_tier': 'opus', 'complexity_threshold': 8, 'claude_as_judge': False},
            'debug_simple': {'preferred_tier': 'sonnet', 'fallback_tier': 'sonnet', 'complexity_threshold': 5, 'claude_as_judge': False},
            'debug_hard': {'preferred_tier': 'opus', 'fallback_tier': 'opus', 'complexity_threshold': 8, 'claude_as_judge': False},
            'review': {'preferred_tier': 'sonnet', 'fallback_tier': 'sonnet', 'complexity_threshold': 5, 'claude_as_judge': True},
            'test_scaffold': {'preferred_tier': 'haiku', 'fallback_tier': 'sonnet', 'complexity_threshold': 3, 'claude_as_judge': False},
            'documentation': {'preferred_tier': 'local', 'fallback_tier': 'sonnet', 'complexity_threshold': 4, 'claude_as_judge': True},
            'sql': {'preferred_tier': 'sonnet', 'fallback_tier': 'sonnet', 'complexity_threshold': 5, 'claude_as_judge': False},
            'api_design': {'preferred_tier': 'sonnet', 'fallback_tier': 'opus', 'complexity_threshold': 6, 'claude_as_judge': False},
            'security_audit': {'preferred_tier': 'opus', 'fallback_tier': 'opus', 'complexity_threshold': 7, 'claude_as_judge': False},
        }

    def suggest_model(
        self,
        task_type: str,
        complexity: int = 5,
        context_tokens: int = 0,
        agent_id: Optional[int] = None,
        failure_count: int = 0
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
        rule = rules.get(task_type, rules.get('code_simple', {
            'preferred_tier': 'sonnet',
            'fallback_tier': 'sonnet',
            'complexity_threshold': 5,
            'claude_as_judge': False
        }))

        # Start with preferred tier
        tier = rule.get('preferred_tier', 'sonnet')
        reason_parts = [f"Task type '{task_type}' maps to {tier}"]
        use_judge = rule.get('claude_as_judge', False)
        force_reset = False

        # Check complexity threshold
        threshold = rule.get('complexity_threshold', 5)
        if complexity > threshold:
            fallback = rule.get('fallback_tier')
            if fallback and fallback != tier:
                tier = fallback
                reason_parts.append(f"complexity {complexity} > threshold {threshold} → {tier}")

        # Check for escalation based on failures
        should_escalate = False
        if failure_count >= 3 and tier != 'opus':
            tier = self._escalate_tier(tier)
            should_escalate = True
            force_reset = rule.get('require_reset_on_escalate', True)
            reason_parts.append(f"{failure_count} failures → escalated to {tier}")

        # Check agent's Opus budget if trying to use Opus
        if tier == 'opus' and agent_id:
            over_budget, budget_info = self._check_opus_budget(agent_id)
            if over_budget:
                tier = 'sonnet'
                reason_parts.append(f"Opus budget exceeded ({budget_info}) → downgraded to sonnet")

        # Get model config
        config = configs.get(tier, DEFAULT_MODEL_CONFIGS.get(tier, DEFAULT_MODEL_CONFIGS['sonnet']))

        # Estimate cost
        estimated_cost = self._estimate_cost(config, context_tokens)

        return RoutingRecommendation(
            tier=tier,
            provider=config.provider,
            model_name=config.model_name,
            reason="; ".join(reason_parts),
            should_escalate=should_escalate,
            use_claude_as_judge=use_judge and tier == 'local',
            estimated_cost=estimated_cost,
            force_reset=force_reset
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

            cur.execute("""
                SELECT max_opus_percentage, opus_usage_this_month, total_tasks_this_month
                FROM agents WHERE id = %s
            """, (agent_id,))

            agent = cur.fetchone()
            cur.close()
            conn.close()

            if not agent:
                return False, "Agent not found"

            max_pct = float(agent['max_opus_percentage'] or 0.15)
            usage = int(agent['opus_usage_this_month'] or 0)
            total = int(agent['total_tasks_this_month'] or 0)

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
        error_message: str = None
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

            cur.execute("""
                INSERT INTO task_executions
                (agent_id, task_type, model_tier_used, model_name, provider,
                 outcome, total_tokens, cost, escalated, claude_as_judge_used, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                agent_id, task_type, tier, model, provider,
                outcome, tokens, cost, escalated, claude_as_judge, error_message
            ))

            result = cur.fetchone()
            execution_id = result['id'] if result else None

            # Update agent stats
            if agent_id:
                cur.execute("""
                    UPDATE agents SET
                        total_tasks_this_month = COALESCE(total_tasks_this_month, 0) + 1,
                        opus_usage_this_month = CASE
                            WHEN %s = 'opus'
                            THEN COALESCE(opus_usage_this_month, 0) + 1
                            ELSE COALESCE(opus_usage_this_month, 0)
                        END
                    WHERE id = %s
                """, (tier, agent_id))

            conn.commit()
            cur.close()
            conn.close()

            return execution_id

        except Exception as e:
            logger.error(f"Error tracking execution: {e}")
            return None

    def get_usage_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get model usage analytics for the past N days"""
        try:
            if get_db is None:
                return {'error': 'Database not available'}

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get summary from view
            cur.execute("SELECT * FROM v_model_usage_summary")
            tier_summary = cur.fetchall()

            # Get cost savings estimate
            cur.execute("""
                SELECT
                    SUM(cost) as actual_cost,
                    SUM(total_tokens) as total_tokens,
                    COUNT(*) FILTER (WHERE model_tier_used = 'local') as local_tasks,
                    COUNT(*) FILTER (WHERE claude_as_judge_used = TRUE) as judge_tasks,
                    COUNT(*) FILTER (WHERE model_tier_used = 'opus') as opus_tasks
                FROM task_executions
                WHERE started_at >= NOW() - INTERVAL '%s days'
            """, (days,))

            cost_data = cur.fetchone()

            cur.close()
            conn.close()

            # Calculate estimated savings vs all-Opus
            total_tokens = cost_data['total_tokens'] or 0
            actual_cost = float(cost_data['actual_cost'] or 0)
            opus_cost_estimate = total_tokens * 0.000045  # Rough Opus estimate

            return {
                'tier_summary': [dict(t) for t in tier_summary],
                'total_cost': actual_cost,
                'estimated_opus_cost': opus_cost_estimate,
                'estimated_savings': opus_cost_estimate - actual_cost,
                'local_tasks': cost_data['local_tasks'] or 0,
                'judge_tasks': cost_data['judge_tasks'] or 0,
                'opus_tasks': cost_data['opus_tasks'] or 0,
                'days': days
            }

        except Exception as e:
            logger.error(f"Error getting analytics: {e}")
            return {'error': str(e)}

    def classify_task(self, prompt: str, context: dict = None) -> str:
        """
        Classify a task based on prompt content.

        This is a simple heuristic classifier. In production,
        you might use a more sophisticated approach or even
        an LLM for classification.
        """
        prompt_lower = prompt.lower()

        # Architecture/design tasks
        if any(kw in prompt_lower for kw in ['architecture', 'design system', 'high-level', 'system design']):
            return 'architecture'

        # Security tasks
        if any(kw in prompt_lower for kw in ['security', 'vulnerability', 'audit', 'penetration', 'cve']):
            return 'security_audit'

        # Complex debugging
        if any(kw in prompt_lower for kw in ['race condition', 'memory leak', 'deadlock', 'crash', 'intermittent']):
            return 'debug_hard'

        # Simple debugging
        if any(kw in prompt_lower for kw in ['debug', 'fix bug', 'error', 'exception', 'traceback']):
            return 'debug_simple'

        # Refactoring
        if any(kw in prompt_lower for kw in ['refactor', 'restructure', 'clean up', 'improve code']):
            return 'refactor'

        # Code review
        if any(kw in prompt_lower for kw in ['review', 'code review', 'pr review', 'pull request']):
            return 'review'

        # API design
        if any(kw in prompt_lower for kw in ['api design', 'endpoint design', 'rest api', 'graphql']):
            return 'api_design'

        # SQL
        if any(kw in prompt_lower for kw in ['sql', 'query', 'database', 'migration']):
            return 'sql'

        # Documentation
        if any(kw in prompt_lower for kw in ['document', 'readme', 'docstring', 'jsdoc', 'comment']):
            return 'documentation'

        # Tests
        if any(kw in prompt_lower for kw in ['test', 'unit test', 'integration test', 'spec']):
            return 'test_scaffold'

        # Formatting
        if any(kw in prompt_lower for kw in ['format', 'lint', 'prettier', 'style']):
            return 'format'

        # Summarization
        if any(kw in prompt_lower for kw in ['summarize', 'summary', 'tldr', 'overview']):
            return 'summarize'

        # Rewrite
        if any(kw in prompt_lower for kw in ['rewrite', 'rephrase', 'improve writing']):
            return 'rewrite'

        # Check complexity indicators for code tasks
        complexity_indicators = ['multiple files', 'across', 'entire', 'whole codebase', 'full implementation']
        if any(kw in prompt_lower for kw in complexity_indicators):
            return 'code_complex'

        # Default to simple coding
        return 'code_simple'


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


def classify_task(prompt: str, context: dict = None) -> str:
    """Convenience function to classify task"""
    return get_router().classify_task(prompt, context)
