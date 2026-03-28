"""RAG service for Claude sessions — semantic search across all knowledge.

Searches: knowledge_base, project_decisions, vault notes, ADRs, GitHub indexed content.
Returns relevant context formatted for LLM consumption.
"""

import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)


def search_relevant_context(query, limit=5, categories=None):
    """Semantic search across knowledge_base using existing embeddings.
    Falls back to text search if embeddings unavailable."""
    # Delegate to the new rag_service for proper vector search
    from services.rag_service import search_knowledge as _rag_search

    return _rag_search(query, limit=limit, knowledge_types=None)


def get_module_context(module_name):
    """Get all relevant knowledge for a specific module."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT title, content, category, importance_score
            FROM knowledge_base
            WHERE (category = %s OR tags::text ILIKE %s OR content ILIKE %s)
            ORDER BY importance_score DESC
            LIMIT 10
        """,
            (module_name, f"%{module_name}%", f"%{module_name}%"),
        )
        return [dict(r) for r in cur.fetchall()]


def get_recent_decisions(module_name=None, limit=5):
    """Get recent architectural decisions, optionally filtered by module."""
    with get_db_cursor() as (conn, cur):
        if module_name:
            cur.execute(
                """
                SELECT decision, context, consequences, created_at
                FROM project_decisions
                WHERE decision ILIKE %s OR context ILIKE %s
                ORDER BY created_at DESC LIMIT %s
            """,
                (f"%{module_name}%", f"%{module_name}%", limit),
            )
        else:
            cur.execute(
                """
                SELECT decision, context, consequences, created_at
                FROM project_decisions
                ORDER BY created_at DESC LIMIT %s
            """,
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]


def build_session_context(topics):
    """Build a comprehensive context block for a Claude session.
    topics: list of keywords/module names to search for."""
    context_parts = []
    for topic in topics[:5]:  # cap at 5 topics
        results = search_relevant_context(topic, limit=3)
        if results:
            context_parts.append(f"\n## Knowledge: {topic}")
            for r in results:
                title = r.get("title", "")
                content = str(r.get("content", ""))[:300]
                context_parts.append(f"- **{title}**: {content}")

    decisions = get_recent_decisions(limit=3)
    if decisions:
        context_parts.append("\n## Recent Decisions")
        for d in decisions:
            context_parts.append(f"- {str(d.get('decision', ''))[:200]}")

    return "\n".join(context_parts)
