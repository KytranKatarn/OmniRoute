"""
Bridge Learning — Capture knowledge from external AI successes.

When an external AI provider succeeds where local agents failed,
this module extracts what the local agent missed and stores it
as knowledge_base entries for future context injection.
"""

import json
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


_inject_warned = False  # see inject_learnings' except block


def capture_learning(
    failed_result: dict,
    success_result: dict,
    capability: str,
    agent_name: str,
    module_id: str,
    failure_count: int = 3,
):
    """
    Compare failed local result with successful external result.
    Extract what the local agent missed and store as knowledge card.
    """
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()

        # Use local model to analyze the difference
        failed_text = (failed_result.get("response", "") or failed_result.get("error", "No response"))[:500]
        success_text = success_result.get("response", "")[:1000]
        prompt = (
            f"Compare these two AI responses for a '{capability}' task.\n\n"
            f"FAILED RESPONSE (local agent):\n{failed_text}\n\n"
            f"SUCCESSFUL RESPONSE (external AI):\n{success_text}\n\n"
            f"What key insight or pattern did the external AI use that the local agent missed?\n"
            f"Respond in 2-3 sentences focusing on the actionable learning."
        )

        analysis = dispatcher.request_work(
            capability="summarize",
            prompt=prompt,
            module_id="bridge_learning",
            timeout=60,
        )

        if not analysis.success:
            logger.warning("[BridgeLearning] Analysis failed, storing raw comparison")
            learning_content = (
                f"External AI ({success_result.get('model', '?')}) succeeded where "
                f"{agent_name} failed on {capability}. Review the successful approach."
            )
        else:
            learning_content = analysis.response

        # Store as knowledge_base entry
        title = f"{agent_name} learning: {capability} -- {module_id}"
        tags = ["agent-learning", agent_name, capability, module_id]
        importance = min(0.9, 0.5 + (failure_count * 0.1))

        ai_analysis = {
            "agent_name": agent_name,
            "capability": capability,
            "failure_count": failure_count,
            "external_model": success_result.get("model", "unknown"),
            "external_provider": success_result.get("provider", "unknown"),
            "learning_type": "pattern_recognition",
            "module_id": module_id,
            "error_message": (failed_result.get("error", "") or "")[:500],
            "failed_model": failed_result.get("model", "unknown"),
        }

        from database import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO knowledge_base (title, content, source_type, tags, importance_score, ai_analysis)
                VALUES (%s, %s, 'agent_learning', %s, %s, %s)
                ON CONFLICT ON CONSTRAINT idx_kb_title_unique DO UPDATE SET
                    content = EXCLUDED.content, importance_score = EXCLUDED.importance_score,
                    ai_analysis = EXCLUDED.ai_analysis, updated_at = NOW()
            """,
                (title, learning_content, tags, importance, json.dumps(ai_analysis)),
            )
            conn.commit()
            cur.close()
            logger.info(f"[BridgeLearning] Captured learning: {title}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"[BridgeLearning] capture_learning failed: {e}")


def inject_learnings(
    agent_name: str,
    capability: str,
    prompt: str,
    max_cards: int = 3,
    proficiency_level: int = 3,
) -> str:
    """
    Search knowledge_base for relevant learning cards and prepend to prompt.

    proficiency_level scales max_cards: effective_max = max(1, proficiency_level).
    Default proficiency_level=3 preserves backward-compatible max_cards=3.

    Returns the enhanced prompt with learning context prepended,
    or the original prompt if no learnings found.
    """
    conn = None
    try:
        from database import get_db
        from psycopg2.extras import RealDictCursor

        # Proficiency scales how many learning cards are injected
        effective_max = max(1, proficiency_level)

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT title, content, importance_score
            FROM knowledge_base
            WHERE source_type = 'agent_learning'
              AND %s = ANY(tags) AND %s = ANY(tags)
              -- knowledge_base has NO is_archived column. This filter used to read
              -- `AND is_archived = FALSE`, so the query raised UndefinedColumn on
              -- EVERY call, the except below swallowed it at debug level, and this
              -- function returned the prompt UNCHANGED. Agent-learning injection has
              -- therefore never once worked. Measured 2026-09-08: 85 occurrences of
              -- `column "is_archived" does not exist` in a single hour.
              -- `review_status` is the real column, and this is the same exclusion
              -- the MCP knowledge search uses (mcp_server/tools/knowledge.py:209).
              AND (review_status IS NULL OR review_status <> 'rejected')
            ORDER BY importance_score DESC, updated_at DESC
            LIMIT %s
        """,
            (agent_name, capability, effective_max),
        )

        cards = cur.fetchall()
        cur.close()

        if not cards:
            return prompt

        learning_context = "--- LEARNING CONTEXT (from previous escalations) ---\n"
        for card in cards:
            learning_context += f"- {card['content']}\n"
        learning_context += "--- END LEARNING CONTEXT ---\n\n"

        return learning_context + prompt

    except Exception as e:
        # 🔴 WARN, not debug. A silent debug line is exactly why a phantom column went
        # unnoticed on a path that runs on EVERY dispatch. Once per process, because
        # this is hot — a per-call warning would replace a silent bug with an
        # unreadable log (the same trade made in semantic_scanner, PR #3244).
        global _inject_warned
        if not _inject_warned:
            _inject_warned = True
            logger.warning(
                "[BridgeLearning] inject_learnings failed — prompts are being sent "
                "WITHOUT learning context (logged once per process): %s",
                e,
            )
        return prompt
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
