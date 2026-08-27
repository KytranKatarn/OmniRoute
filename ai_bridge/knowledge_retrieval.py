"""
Knowledge Retrieval System for A.R.C.H.I.E.'s Consciousness
LOCAL-FIRST architecture - Checks unified knowledge base BEFORE external APIs

Updated for Phase 3: Unified Brain Integration
- Uses unified_knowledge_search.py for intelligent ranking
- Prioritizes mistake_learned (1.3x) to prevent repetition
- Searches across all knowledge types (vault, memories, improvements, mistakes)
"""

import logging

logger = logging.getLogger(__name__)

from psycopg2.extras import RealDictCursor
import os
import re
import sys
from typing import List, Dict, Optional
from db import get_db

# Add platform_v2 to path for unified_knowledge_search
platform_path = "/mnt/archie_brain/platform_v2"
if platform_path not in sys.path:
    sys.path.insert(0, platform_path)

try:
    from tools.consciousness.services.unified_knowledge_search import (
        unified_knowledge_search,
        get_mistake_learnings,
        get_top_knowledge,
    )

    UNIFIED_SEARCH_AVAILABLE = True
except ImportError as e:
    print(f"[Knowledge Retrieval] WARNING: unified_knowledge_search not available: {e}")
    UNIFIED_SEARCH_AVAILABLE = False


def extract_keywords(user_message: str) -> List[str]:
    """
    Extract relevant keywords from user message to search knowledge base
    """
    message_lower = user_message.lower()
    keywords = []

    # Programming languages
    if "python" in message_lower:
        keywords.extend(["python", "python-code", "python-script"])
    if "javascript" in message_lower or "js" in message_lower:
        keywords.extend(["javascript", "javascript-code"])
    if "automation" in message_lower or "automate" in message_lower:
        keywords.extend(["automation", "n8n-workflow", "automation-script"])
    if "agent" in message_lower or "ai" in message_lower:
        keywords.extend(["ai-agent", "agent-example", "multi-agent"])
    if "prompt" in message_lower:
        keywords.extend(["system-prompt", "prompt-template", "prompt-engineering"])
    if "workflow" in message_lower:
        keywords.extend(["n8n-workflow", "workflow-template", "automation"])
    if "example" in message_lower or "how to" in message_lower:
        keywords.extend(["example", "tutorial", "beginner"])
    if "database" in message_lower or "sql" in message_lower:
        keywords.extend(["python-database", "data-science"])
    if "test" in message_lower or "testing" in message_lower:
        keywords.extend(["python-testing", "tutorial"])
    if "iot" in message_lower or "sensor" in message_lower or "device" in message_lower:
        keywords.extend(["python-iot"])
    if "error" in message_lower or "bug" in message_lower or "fix" in message_lower:
        keywords.extend(["error", "bug", "fix", "debugging"])

    # Task types
    if "beginner" in message_lower or "learn" in message_lower or "tutorial" in message_lower:
        keywords.extend(["beginner", "tutorial", "example"])
    if "advanced" in message_lower or "complex" in message_lower:
        keywords.extend(["advanced", "expert"])

    return list(set(keywords))


def get_relevant_knowledge(user_message: str, max_results: int = 5) -> str:
    """
    Get relevant knowledge snippets for A.R.C.H.I.E. based on user message
    LOCAL-FIRST: Searches unified knowledge base with intelligent ranking

    Priority Order (by importance multiplier):
    1. mistake_learned (1.3x) - PREVENT REPETITION!
    2. vault_note (1.2x) - Curated documentation
    3. code_snippet (1.1x) - Proven patterns
    4. improvement (1.0x) - Historical fixes
    5. github_file (0.8x) - Indexed files
    6. conversation_memory (0.8x) - Dynamic learning

    Args:
        user_message: The user's question/request
        max_results: Maximum number of knowledge snippets to return

    Returns:
        Formatted string with relevant knowledge context
    """

    if not UNIFIED_SEARCH_AVAILABLE:
        return "[Knowledge Retrieval] Unified search not available\n"

    try:
        # Use unified_knowledge_search with intelligent ranking
        search_results = unified_knowledge_search(query=user_message, types=None, limit=max_results)  # Search ALL types

        results = search_results.get("results", [])

        if not results:
            return ""

        # Format results for A.R.C.H.I.E.'s context
        knowledge_context = "\n\n=== 🧠 RELEVANT KNOWLEDGE FROM MY BRAIN ===\n"
        knowledge_context += f"I found {len(results)} relevant resources (ranked by importance):\n\n"

        for idx, item in enumerate(results, 1):
            knowledge_type = item["knowledge_type"]

            # Emoji mapping by type
            type_emoji = {
                "mistake_learned": "⚠️",
                "vault_note": "📚",
                "code_snippet": "💻",
                "improvement": "🔧",
                "conversation_memory": "💭",
                "github_file": "📁",
            }

            emoji = type_emoji.get(knowledge_type, "📄")
            title = item.get("title", "Untitled")
            category = item.get("category", "General")
            importance = item.get("importance_score", 0.5)
            weighted_score = item.get("weighted_score", importance)

            knowledge_context += f"{idx}. {emoji} {title}\n"
            knowledge_context += f"   Type: {knowledge_type} | Category: {category}\n"
            knowledge_context += f"   Importance: {importance:.2f} (weighted: {weighted_score:.2f})\n"

            # Special handling for mistake_learned
            if knowledge_type == "mistake_learned":
                knowledge_context += f"   ⚠️ IMPORTANT: This is a documented error to prevent repetition!\n"

            # Add content snippet
            content = item.get("content", "")
            if content:
                snippet = content[:300] if len(content) > 300 else content
                knowledge_context += f"   Content: {snippet}...\n"

            # Add tags if available
            tags = item.get("tags", [])
            if tags:
                knowledge_context += f"   Tags: {', '.join(tags[:5])}\n"

            knowledge_context += "\n"

        knowledge_context += "=== END KNOWLEDGE BASE ===\n"
        knowledge_context += "NOTE: You can reference these resources when helping the user.\n"
        knowledge_context += (
            "If you find mistake_learned entries (⚠️), make sure to warn the user about these known errors!\n"
        )

        return knowledge_context

    except Exception as e:
        print(f"[Knowledge Retrieval] Error in get_relevant_knowledge: {e}")
        import traceback

        traceback.print_exc()
        return f"[Knowledge Retrieval] Error: {str(e)}\n"


def get_relevant_knowledge_enhanced(query: str, max_results: int = 10, use_semantic: bool = False) -> List[Dict]:
    """
    Enhanced knowledge retrieval that returns structured results for local answer generation.

    This is the enhanced version that:
    - Returns List[Dict] instead of formatted string
    - Supports semantic/hybrid search (when use_semantic=True and infrastructure available)
    - Falls back to keyword search gracefully

    Args:
        query: User's question/request
        max_results: Maximum number of results to return
        use_semantic: Enable semantic/hybrid search (default: False, uses keyword-only)

    Returns:
        List of knowledge base entries as dicts with all fields
    """

    if not UNIFIED_SEARCH_AVAILABLE:
        return []

    try:
        # For now, use keyword-only search via unified_knowledge_search
        # TODO: Add semantic search when embedding infrastructure is ready
        # if use_semantic and check_ollama_available():
        #     from knowledge_hybrid_search import KnowledgeHybridSearch
        #     searcher = KnowledgeHybridSearch(keyword_weight=0.3, semantic_weight=0.7)
        #     results = searcher.hybrid_search(query, limit=max_results * 2)
        #     # Apply type weights...
        #     return results[:max_results]

        # Current implementation: keyword-only via unified_knowledge_search
        search_results = unified_knowledge_search(query=query, types=None, limit=max_results)  # Search ALL types

        results = search_results.get("results", [])

        # Ensure weighted_score is present for all results
        for r in results:
            if "weighted_score" not in r:
                r["weighted_score"] = r.get("importance_score", 0.5)

        return results

    except Exception as e:
        print(f"[Knowledge Retrieval] Error in get_relevant_knowledge_enhanced: {e}")
        import traceback

        traceback.print_exc()
        return []


def check_for_known_mistakes(user_message: str) -> Optional[str]:
    """
    Check if user message relates to a known mistake
    Returns formatted warning if mistake found, None otherwise

    This is called FIRST to prevent users from repeating documented errors!
    """
    if not UNIFIED_SEARCH_AVAILABLE:
        return None

    try:
        # Get all mistake learnings
        mistakes = get_mistake_learnings(limit=20)

        if not mistakes:
            return None

        # Check if user message relates to any known mistake
        message_lower = user_message.lower()

        for mistake in mistakes:
            title = mistake.get("title", "").lower()
            content = mistake.get("content", "").lower()
            category = mistake.get("category", "").lower()

            # Simple keyword matching
            if any(word in message_lower for word in ["error", "bug", "problem", "issue", "fail"]):
                # Check if mistake title/content/category matches query
                if any(
                    keyword in title or keyword in content or keyword in category
                    for keyword in extract_keywords(user_message)
                ):

                    # Found a relevant mistake!
                    warning = "\n\n⚠️ === KNOWN MISTAKE WARNING ===\n"
                    warning += f"I found a documented error related to your question:\n\n"
                    warning += f"Title: {mistake['title']}\n"
                    warning += f"Category: {mistake['category']}\n\n"
                    warning += f"{mistake['content'][:500]}...\n\n"
                    warning += "This mistake has been documented to prevent repetition.\n"
                    warning += "=== END WARNING ===\n\n"

                    return warning

        return None

    except Exception as e:
        print(f"[Knowledge Retrieval] Error checking mistakes: {e}")
        return None


def get_knowledge_stats() -> Dict:
    """
    Get statistics about indexed knowledge

    Returns:
        Dict with stats about the unified knowledge base
    """
    if not UNIFIED_SEARCH_AVAILABLE:
        return {}

    try:
        from tools.consciousness.services.unified_knowledge_search import get_knowledge_stats as get_unified_stats

        return get_unified_stats()
    except Exception as e:
        logger.warning("Error getting knowledge stats: %s", e)
        return {}


def search_by_type(knowledge_type: str, limit: int = 10) -> List[Dict]:
    """
    Get top knowledge entries by type

    Args:
        knowledge_type: 'vault_note', 'mistake_learned', 'improvement', etc.
        limit: Maximum results

    Returns:
        List of knowledge entries
    """
    if not UNIFIED_SEARCH_AVAILABLE:
        return []

    try:
        return get_top_knowledge(knowledge_type=knowledge_type, limit=limit)
    except Exception as e:
        print(f"Error searching by type: {e}")
        return []


# ============================================================================
# UNIFIED KNOWLEDGE SERVICE INTEGRATION (Phase 4)
# ============================================================================

# Import UnifiedKnowledgeService
try:
    from services.unified_knowledge import get_unified_knowledge_service

    UNIFIED_SERVICE_AVAILABLE = True
except ImportError:
    UNIFIED_SERVICE_AVAILABLE = False
    print("[Knowledge Retrieval] UnifiedKnowledgeService not available")


def get_agent_context(task_description: str, agent_type: str = "general") -> Dict:
    """
    Get full context for an AI agent before executing a task.
    Uses the UnifiedKnowledgeService for comprehensive context.

    This is the recommended function for AI agents to call before
    executing any task, as it:
    1. Checks for similar mistakes (HIGHEST PRIORITY)
    2. Retrieves relevant knowledge
    3. Finds similar past tasks
    4. Provides suggestions

    Args:
        task_description: What the agent is about to do
        agent_type: Type of agent (development, infrastructure, etc.)

    Returns:
        Dict with mistakes_to_avoid, relevant_knowledge, similar_past_tasks, suggestions
    """
    if not UNIFIED_SERVICE_AVAILABLE:
        # Fallback to basic knowledge retrieval
        return {
            "mistakes_to_avoid": [],
            "relevant_knowledge": get_relevant_knowledge_enhanced(task_description, max_results=5),
            "similar_past_tasks": [],
            "suggestions": [{"type": "info", "message": "Using fallback knowledge retrieval"}],
        }

    try:
        service = get_unified_knowledge_service()
        return service.get_agent_context(task_description, agent_type)
    except Exception as e:
        print(f"[Knowledge Retrieval] Agent context error: {e}")
        return {
            "mistakes_to_avoid": [],
            "relevant_knowledge": [],
            "similar_past_tasks": [],
            "suggestions": [{"type": "error", "message": str(e)}],
        }


def record_mistake_from_error(error: Exception, context: Dict = None) -> Optional[int]:
    """
    Record a mistake to the knowledge base from an exception.
    Part of the Mistake Learning Loop - called when errors occur.

    Args:
        error: The exception that was caught
        context: Additional context (session_id, git_branch, etc.)

    Returns:
        Knowledge entry ID or None
    """
    if not UNIFIED_SERVICE_AVAILABLE:
        print("[Knowledge Retrieval] Cannot record mistake: UnifiedKnowledgeService not available")
        return None

    try:
        service = get_unified_knowledge_service()

        error_type = type(error).__name__
        error_message = str(error)

        # Try to extract solution from traceback
        import traceback

        tb = traceback.format_exc()

        return service.record_mistake(
            error_type=error_type,
            error_message=error_message,
            solution=f"Error occurred. Traceback:\n{tb[:500]}",
            context=context or {},
            tags=[error_type.lower(), "auto-recorded"],
        )

    except Exception as e:
        print(f"[Knowledge Retrieval] Record mistake error: {e}")
        return None


# Test function
if __name__ == "__main__":
    print("Testing LOCAL-FIRST knowledge retrieval...")
    print("=" * 60)

    # Get stats
    stats = get_knowledge_stats()
    print(f"\nKnowledge Base Stats:")
    print(f"  Total Entries: {stats.get('total_entries', 0)}")
    print(f"  Mistake Learnings: {stats.get('mistake_count', 0)}")

    # Test search
    test_message = "How do I fix a database column error?"
    print(f"\nTest Query: {test_message}")
    print("=" * 60)

    # Check for known mistakes FIRST
    mistake_warning = check_for_known_mistakes(test_message)
    if mistake_warning:
        print(mistake_warning)

    # Get relevant knowledge
    knowledge = get_relevant_knowledge(test_message, max_results=5)
    print(knowledge)
