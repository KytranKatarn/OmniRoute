"""RAG Query Service — semantic search + context retrieval from knowledge base.

Used by: /archie-recall skill, /archie-research skill, CLI knowledge queries,
and Bridge auto-context injection.

Import:
    from services.rag_service import search_knowledge, get_rag_context
"""

import json
import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)


def search_knowledge(query, limit=10, knowledge_types=None, min_importance=0.0):
    """Semantic search across the knowledge base.

    Uses embedding similarity when available, falls back to text search.

    Args:
        query: Search query string
        limit: Max results (capped at 50)
        knowledge_types: Optional filter (e.g., ['vault_note', 'mistake_learned'])
        min_importance: Minimum importance_score filter (0.0-1.0)

    Returns:
        List of dicts with: id, title, content (truncated), knowledge_type,
        importance_score, similarity
    """
    limit = min(int(limit), 50)
    results = []

    # Try embedding-based search first
    try:
        query_embedding = _generate_embedding(query)
        if query_embedding:
            results = _vector_search(query_embedding, limit, knowledge_types, min_importance)
    except Exception as e:
        logger.debug("Vector search failed, falling back to text: %s", e)

    # Fallback to text search
    if not results:
        results = _text_search(query, limit, knowledge_types, min_importance)

    return results


def get_rag_context(query, max_tokens=2000, knowledge_types=None):
    """Get formatted RAG context for injecting into prompts.

    Returns a string of relevant KB entries formatted for LLM consumption.
    """
    results = search_knowledge(query, limit=8, knowledge_types=knowledge_types)
    # Filter out low-quality entries from RAG context (stricter than search)
    results = [r for r in results if r.get("quality_score") is None or r.get("quality_score", 0) >= 0.5][:5]
    if not results:
        return ""

    context_parts = ["--- Relevant Knowledge ---"]
    total_chars = 0
    max_chars = max_tokens * 4  # rough token-to-char estimate

    for r in results:
        entry = f"\n[{r['knowledge_type']}] {r['title']}\n{r['content']}"
        if total_chars + len(entry) > max_chars:
            break
        context_parts.append(entry)
        total_chars += len(entry)

    context_parts.append("--- End Knowledge ---\n")
    return "\n".join(context_parts)


def search_mistakes(query, limit=5):
    """Search specifically for mistake_learned entries.

    High priority for error prevention — these have 1.3x search weight.
    """
    return search_knowledge(query, limit=limit, knowledge_types=["mistake_learned"])


def _generate_embedding(text):
    """Generate embedding vector for a query using Ollama arctic-embed."""
    import urllib.request

    data = json.dumps({"model": "arctic-embed-cpu:latest", "prompt": text}).encode()
    req = urllib.request.Request(
        "http://192.168.1.200:11434/api/embeddings",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            embedding = result.get("embedding")
            if embedding and len(embedding) > 0:
                return embedding
    except Exception as e:
        logger.debug("Embedding generation failed: %s", e)
    return None


def _vector_search(embedding, limit, knowledge_types, min_importance):
    """Search using cosine similarity against stored embeddings (pgvector)."""
    embedding_json = json.dumps(embedding)

    with get_db_cursor(commit=False) as (conn, cur):
        try:
            if knowledge_types:
                placeholders = ",".join(["%s"] * len(knowledge_types))
                cur.execute(
                    f"""
                    SELECT id, title, LEFT(content, 500) as content,
                           knowledge_type, importance_score,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM knowledge_base
                    WHERE embedding IS NOT NULL
                      AND (source_type IS DISTINCT FROM 'agent_proposed' OR review_status = 'approved')
                      AND knowledge_type IN ({placeholders})
                      AND importance_score >= %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """,
                    [embedding_json] + list(knowledge_types) + [min_importance, embedding_json, limit],
                )
            else:
                cur.execute(
                    """
                    SELECT id, title, LEFT(content, 500) as content,
                           knowledge_type, importance_score,
                           1 - (embedding <=> %s::vector) as similarity
                    FROM knowledge_base
                    WHERE embedding IS NOT NULL
                      AND (source_type IS DISTINCT FROM 'agent_proposed' OR review_status = 'approved')
                      AND importance_score >= %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """,
                    [embedding_json, min_importance, embedding_json, limit],
                )

            rows = cur.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                # Convert Decimal to float for JSON serialization
                if d.get("importance_score") is not None:
                    d["importance_score"] = float(d["importance_score"])
                if d.get("similarity") is not None:
                    d["similarity"] = round(float(d["similarity"]), 4)
                results.append(d)
            return results
        except Exception as e:
            logger.debug("pgvector query failed: %s", e)
            return []


def _text_search(query, limit, knowledge_types, min_importance):
    """Fallback text search using ILIKE."""
    conditions = [
        "importance_score >= %s",
        # Quarantine agent-proposed writes until C.O.D.E.X. approves (#3534 P3).
        "(source_type IS DISTINCT FROM 'agent_proposed' OR review_status = 'approved')",
    ]
    params = [min_importance]

    if knowledge_types:
        placeholders = ",".join(["%s"] * len(knowledge_types))
        conditions.append(f"knowledge_type IN ({placeholders})")
        params.extend(knowledge_types)

    # Search in title and content
    conditions.append("(title ILIKE %s OR content ILIKE %s)")
    search_term = f"%{query}%"
    params.extend([search_term, search_term])
    params.append(limit)

    where = " AND ".join(conditions)

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            f"""
            SELECT id, title, LEFT(content, 500) as content, knowledge_type,
                   importance_score, 0.5 as similarity
            FROM knowledge_base
            WHERE {where}
            ORDER BY importance_score DESC
            LIMIT %s
        """,
            params,
        )
        rows = cur.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("importance_score") is not None:
                d["importance_score"] = float(d["importance_score"])
            if d.get("similarity") is not None:
                d["similarity"] = float(d["similarity"])
            results.append(d)
        return results
