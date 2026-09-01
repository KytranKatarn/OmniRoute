"""
Local Answer Generator for A.R.C.H.I.E. (Phase 3)

Generates answers directly from knowledge base without external LLM calls.
Saves API costs by answering simple queries locally with high confidence.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-10
"""

import os
from database import _get_db_password
import sys
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add platform_v2 to path for database access
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

try:
    import psycopg2
except ImportError:
    psycopg2 = None

logger = logging.getLogger("archie_platform")


def get_db():
    """Get database connection"""
    if not psycopg2:
        raise ImportError("psycopg2 not available")

    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def analyze_query_complexity(query: str) -> str:
    """
    Analyze query complexity to determine if local answer is appropriate.

    Returns: 'very_low' | 'low' | 'medium' | 'high' | 'very_high'

    very_low: Simple lookups, definitions
    low: How-to questions, error fixes
    medium: General questions
    high: Reasoning, comparison, analysis
    very_high: Creative tasks, debugging, design
    """
    q = query.lower()

    # Very low complexity: Simple lookups
    very_low_patterns = [
        "what is",
        "what are",
        "define",
        "show me",
        "example of",
        "give me an example",
        "list",
        "what does",
        "meaning of",
    ]
    if any(pattern in q for pattern in very_low_patterns):
        return "very_low"

    # Low complexity: How-to questions, fixes
    low_patterns = [
        "how to",
        "how do i",
        "how can i",
        "fix error",
        "solve",
        "prevent",
        "avoid",
        "steps to",
    ]
    if any(pattern in q for pattern in low_patterns):
        return "low"

    # High complexity: Reasoning required
    high_patterns = [
        "why",
        "why does",
        "why is",
        "compare",
        "difference between",
        "vs",
        "best way",
        "should i",
        "which is better",
        "explain why",
        "reason",
    ]
    if any(pattern in q for pattern in high_patterns):
        return "high"

    # Very high complexity: Analysis, creative, debugging
    very_high_patterns = [
        "analyze",
        "debug",
        "diagnose",
        "design",
        "architect",
        "build",
        "create",
        "develop",
        "implement",
        "optimize",
        "improve",
        "refactor",
        "review my code",
        "whats wrong",
    ]
    if any(pattern in q for pattern in very_high_patterns):
        return "very_high"

    # Default: medium complexity
    return "medium"


def can_answer_locally(query: str, knowledge_results: List[Dict]) -> Dict[str, Any]:
    """
    Determine if we can answer the query locally without external LLM.

    Args:
        query: User's question
        knowledge_results: Results from knowledge base search

    Returns:
        {
            'can_answer': bool,
            'confidence': float (0-1),
            'strategy': 'direct' | 'synthesize' | 'llm_required',
            'reason': str
        }
    """

    # Step 1: Check if we have any results
    if not knowledge_results or len(knowledge_results) == 0:
        return {
            "can_answer": False,
            "confidence": 0.0,
            "strategy": "llm_required",
            "reason": "No knowledge found in database",
        }

    # Step 2: Analyze query complexity
    complexity = analyze_query_complexity(query)

    # Very high complexity always requires LLM
    if complexity in ["very_high", "high"]:
        return {
            "can_answer": False,
            "confidence": 0.0,
            "strategy": "llm_required",
            "reason": f"Query too complex ({complexity}) - requires reasoning/analysis",
        }

    # Step 3: Evaluate top result quality
    top_result = knowledge_results[0]
    weighted_score = top_result.get("weighted_score", top_result.get("importance_score", 0))
    knowledge_type = top_result.get("knowledge_type", "")

    # HIGH CONFIDENCE: Single authoritative source
    # mistake_learned or vault_note with high score
    # Week 2: Raised to 0.90 for conservative testing
    if weighted_score >= 0.90 and knowledge_type in ["mistake_learned", "vault_note"]:

        return {
            "can_answer": True,
            "confidence": float(weighted_score),
            "strategy": "direct",
            "reason": f"High-quality {knowledge_type} (score: {weighted_score:.2f})",
        }

    # MEDIUM CONFIDENCE: Multiple good sources
    if len(knowledge_results) >= 2:
        # Calculate average score of top 3 results
        top_results = knowledge_results[:3]
        avg_score = sum(r.get("weighted_score", r.get("importance_score", 0)) for r in top_results) / len(top_results)

        # If average score is good and query is simple enough
        # Week 2: Raised to 0.75 for conservative testing
        if avg_score >= 0.75 and complexity in ["very_low", "low"]:
            return {
                "can_answer": True,
                "confidence": float(avg_score),
                "strategy": "synthesize",
                "reason": f"Multiple good sources (avg: {avg_score:.2f})",
            }

    # LOW CONFIDENCE: Use LLM with knowledge augmentation
    return {
        "can_answer": False,
        "confidence": 0.5,
        "strategy": "llm_required",
        "reason": f"Insufficient confidence (top score: {weighted_score:.2f})",
    }


def generate_direct_local_response(query: str, result: Dict) -> str:
    """
    Generate response from single high-quality source.

    Args:
        query: User's question
        result: Single knowledge base entry

    Returns:
        Formatted response string
    """
    knowledge_type = result["knowledge_type"]
    title = result.get("title", "Untitled")
    content = result.get("content", "")
    category = result.get("category", "General")
    importance = result.get("importance_score", 0.5)
    created_at = result.get("created_at", "")

    # Format created date
    date_str = ""
    if created_at:
        try:
            if isinstance(created_at, str):
                date_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                date_obj = created_at
            date_str = date_obj.strftime("%Y-%m-%d")
        except Exception:
            date_str = str(created_at)[:10]

    # mistake_learned responses (highest priority)
    if knowledge_type == "mistake_learned":
        return f"""⚠️ KNOWN ISSUE DETECTED

**{title}**

{content}

**Category:** {category}
**Documented:** {date_str}

This is a documented error pattern that has been encountered before. Please review the solution above carefully.

---
*Source: A.R.C.H.I.E. Knowledge Base - Mistake Prevention System*
*Confidence: High - This is a known pattern to avoid*
*Type: {knowledge_type}*
"""

    # vault_note responses (curated documentation)
    elif knowledge_type == "vault_note":
        return f"""📚 From Documentation: **{title}**

{content}

**Category:** {category}
**Importance:** {importance:.2f}

---
*Source: A.R.C.H.I.E. Curated Knowledge Vault*
*This is curated, high-quality documentation*
*Type: {knowledge_type}*
"""

    # code_snippet responses
    elif knowledge_type == "code_snippet":
        # Check if content looks like code
        is_code = any(char in content[:100] for char in ["{", "}", "(", ")", ";", "def ", "function", "class "])

        if is_code:
            return f"""💻 Code Example: **{title}**

```
{content}
```

**Category:** {category}
**Purpose:** Demonstrates {category.lower()} patterns

---
*Source: A.R.C.H.I.E. Code Library*
*Type: {knowledge_type}*
"""
        else:
            return f"""💻 **{title}**

{content}

**Category:** {category}

---
*Source: A.R.C.H.I.E. Code Library*
*Type: {knowledge_type}*
"""

    # improvement responses
    elif knowledge_type == "improvement":
        return f"""🔧 From Previous Improvement: **{title}**

{content}

**Category:** {category}
**Date:** {date_str}

---
*Source: A.R.C.H.I.E. Improvement Tracking*
*This documents a real change made to the codebase*
*Type: {knowledge_type}*
"""

    # Default format for other types
    else:
        type_emoji = {"conversation_memory": "💭", "github_file": "📁"}.get(knowledge_type, "📄")

        return f"""{type_emoji} **{title}**

{content}

**Category:** {category}
**Type:** {knowledge_type}

---
*Source: A.R.C.H.I.E. Knowledge Base*
"""


def generate_synthesized_local_response(query: str, results: List[Dict]) -> str:
    """
    Generate response by synthesizing multiple knowledge sources.

    Args:
        query: User's question
        results: List of knowledge base entries

    Returns:
        Formatted synthesized response
    """
    # Group results by type
    mistakes = [r for r in results if r["knowledge_type"] == "mistake_learned"]
    vault_notes = [r for r in results if r["knowledge_type"] == "vault_note"]
    code_snippets = [r for r in results if r["knowledge_type"] == "code_snippet"]
    improvements = [r for r in results if r["knowledge_type"] == "improvement"]
    other = [
        r
        for r in results
        if r["knowledge_type"] not in ["mistake_learned", "vault_note", "code_snippet", "improvement"]
    ]

    parts = []
    parts.append("Based on A.R.C.H.I.E.'s knowledge base, here's what I found:\n")

    # Mistakes first (highest priority)
    if mistakes:
        parts.append("\n⚠️ **KNOWN ISSUES TO AVOID:**\n")
        for m in mistakes[:2]:  # Top 2 mistakes
            title = m.get("title", "Untitled")
            content = m.get("content", "")[:250]  # First 250 chars
            parts.append(f"- **{title}**")
            parts.append(f"  {content}{'...' if len(m.get('content', '')) > 250 else ''}\n")

    # Documentation
    if vault_notes:
        parts.append("\n📚 **DOCUMENTATION:**\n")
        for v in vault_notes[:2]:  # Top 2 vault notes
            title = v.get("title", "Untitled")
            content = v.get("content", "")[:300]  # First 300 chars
            parts.append(f"**{title}**")
            parts.append(f"{content}{'...' if len(v.get('content', '')) > 300 else ''}\n")

    # Code examples
    if code_snippets:
        parts.append("\n💻 **CODE EXAMPLES:**\n")
        for c in code_snippets[:1]:  # Top 1 code snippet
            title = c.get("title", "Code Example")
            content = c.get("content", "")[:200]  # First 200 chars
            parts.append(f"**{title}**")
            parts.append(f"```\n{content}{'...' if len(c.get('content', '')) > 200 else ''}\n```\n")

    # Improvements
    if improvements:
        parts.append("\n🔧 **RELATED IMPROVEMENTS:**\n")
        for imp in improvements[:1]:  # Top 1 improvement
            title = imp.get("title", "Improvement")
            parts.append(f"- {title}\n")

    # Footer
    parts.append("\n---")
    parts.append(f"*Synthesized from {len(results)} knowledge sources*")
    parts.append("*For deeper analysis or specific guidance, ask me to elaborate*")

    return "\n".join(parts)


def generate_local_response(query: str, results: List[Dict], strategy: str) -> str:
    """
    Generate complete local response based on strategy.

    Args:
        query: User's question
        results: Knowledge base results
        strategy: 'direct' or 'synthesize'

    Returns:
        Complete formatted response
    """
    if strategy == "direct":
        # Single authoritative source
        return generate_direct_local_response(query, results[0])

    elif strategy == "synthesize":
        # Multiple sources
        return generate_synthesized_local_response(query, results)

    else:
        # Fallback
        return generate_synthesized_local_response(query, results)


def estimate_cost_savings(
    query: str,
    default_model: str = "claude-sonnet-4",
    default_provider: str = "anthropic",
) -> Dict[str, Any]:
    """
    Estimate cost savings from answering locally instead of using LLM.

    Assumptions:
    - Query tokens: len(query) / 4 (rough estimate)
    - Context tokens we would send: ~300 (knowledge context)
    - Output tokens we would generate: ~400 (average response)

    Args:
        query: User's question
        default_model: Model that would have been used
        default_provider: Provider that would have been used

    Returns:
        {
            'tokens_saved': int,
            'cost_saved': float,
            'model': str,
            'provider': str
        }
    """
    # Estimate tokens
    query_tokens = max(10, len(query) // 4)
    context_tokens = 300  # Knowledge context we prepend
    output_tokens = 400  # Average response length

    total_tokens = query_tokens + context_tokens + output_tokens

    # Cost per 1M tokens (approximate)
    COST_PER_MILLION = {
        "anthropic": {
            "claude-sonnet-4": 3.00,  # $3 per 1M input, $15 per 1M output (average)
            "claude-sonnet-3.5": 3.00,
            "claude-opus-4": 15.00,
        },
        "openai": {"gpt-4": 30.00, "gpt-4-turbo": 10.00, "gpt-3.5-turbo": 0.50},
    }

    # Get cost rate
    provider_costs = COST_PER_MILLION.get(default_provider, {})
    cost_rate = provider_costs.get(default_model, 3.00)  # Default $3/1M

    # Calculate cost (weighted: input cheaper, output more expensive)
    input_tokens = query_tokens + context_tokens
    input_cost = (input_tokens / 1_000_000) * (cost_rate * 0.33)  # Input is ~1/3 of avg
    output_cost = (output_tokens / 1_000_000) * (cost_rate * 3.0)  # Output is ~3x
    total_cost = input_cost + output_cost

    return {
        "tokens_saved": total_tokens,
        "cost_saved": round(total_cost, 6),
        "model": default_model,
        "provider": default_provider,
    }


def track_local_answer_usage(
    query: str,
    knowledge_ids: List[int],
    confidence: float,
    strategy: str,
    user_id: Optional[int] = None,
    default_model: str = "claude-sonnet-4",
    default_provider: str = "anthropic",
) -> bool:
    """
    Track local answer usage and cost savings in database.

    Args:
        query: User's question
        knowledge_ids: IDs of knowledge entries used
        confidence: Confidence score (0-1)
        strategy: 'direct' or 'synthesize'
        user_id: User ID (optional)
        default_model: Model that would have been used
        default_provider: Provider that would have been used

    Returns:
        True if tracking successful, False otherwise
    """
    try:
        # Estimate savings
        savings = estimate_cost_savings(query, default_model, default_provider)

        # Hash query for deduplication
        query_hash = hashlib.sha256(query.encode()).hexdigest()

        conn = get_db()
        cur = conn.cursor()

        # Store savings record (table created by migration 016)
        cur.execute(
            """
            INSERT INTO local_answer_savings
            (query_hash, query_preview, knowledge_ids, confidence_score,
             strategy, estimated_tokens_saved, estimated_cost_saved,
             would_have_used_model, would_have_used_provider, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (query_hash) DO UPDATE
            SET created_at = NOW()
        """,
            (
                query_hash,
                query[:100],  # First 100 chars
                knowledge_ids,
                confidence,
                strategy,
                savings["tokens_saved"],
                savings["cost_saved"],
                default_model,
                default_provider,
                user_id,
            ),
        )

        # Update knowledge entry statistics
        for kid in knowledge_ids:
            cur.execute(
                """
                UPDATE knowledge_base
                SET times_used_locally = COALESCE(times_used_locally, 0) + 1,
                    estimated_cost_saved = COALESCE(estimated_cost_saved, 0) + %s,
                    last_accessed = NOW(),
                    access_count = COALESCE(access_count, 0) + 1
                WHERE id = %s
            """,
                (savings["cost_saved"], kid),
            )

        conn.commit()
        cur.close()
        conn.close()

        logger.info(
            f"[Local Answer] Tracked usage: {len(knowledge_ids)} entries, " f"${savings['cost_saved']:.4f} saved"
        )

        return True

    except Exception as e:
        logger.error(f"[Local Answer] Error tracking usage: {e}")
        return False


# Convenience function for easy testing
if __name__ == "__main__":
    # Test query complexity analysis
    test_queries = [
        "What is A.R.C.H.I.E.?",
        "How to fix database error?",
        "Why does my code fail?",
        "Debug this function",
        "Compare PostgreSQL and MySQL",
    ]

    print("Query Complexity Analysis Test:\n")
    for q in test_queries:
        complexity = analyze_query_complexity(q)
        print(f"{q:<40} → {complexity}")

    print("\n✅ local_answer_generator.py module loaded successfully")
