"""
Memory Service - Phase 9: Long-Term Memory
Provides semantic search, memory collections, and decay management

Features:
- Embedding generation via the fleet-aware embedding service (arctic-embed-cpu, 768-dim, #3525)
- Semantic similarity search
- Memory collections CRUD
- Memory associations
- Decay and reinforcement
"""

import os
from database import _get_db_password
import json
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "arctic-embed-cpu")
EMBEDDING_DIMENSION = 768  # arctic-embed-cpu dimension


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# =============================================================================
# EMBEDDING GENERATION
# =============================================================================


def generate_embedding(text: str) -> Optional[List[float]]:
    """Generate embedding via the cluster-delegated, fleet-aware embedding service
    (#3525): routes to online nodes that have the embedder loaded (hub primary +
    outpost backups) with failover. Falls back to the legacy hub-direct call only
    if the fleet service can't be imported, so it's never worse than before."""
    try:
        from ai_bridge.embedding_service import generate_embedding as _fleet_embed

        return _fleet_embed(text)
    except Exception as e:  # noqa: BLE001 — fleet path optional, never break search
        logger.debug("fleet embedding unavailable (%s) — legacy hub-direct fallback", e)

    # Legacy hub-direct fallback (single node, no failover)
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBEDDING_MODEL, "prompt": text[:8000]},  # Limit text length
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("embedding")
        else:
            logger.error(f"Embedding generation failed: {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return None


def store_embedding(source_type: str, source_id: int, content: str) -> bool:
    """Generate and store embedding for a memory"""
    embedding = generate_embedding(content)
    if not embedding:
        return False

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Store as REAL[] since pgvector may not be available
        cur.execute(
            """
            INSERT INTO memory_embeddings (source_type, source_id, embedding, content_preview, embedding_model)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_type, source_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                content_preview = EXCLUDED.content_preview,
                updated_at = NOW()
        """,
            (source_type, source_id, embedding, content[:500], EMBEDDING_MODEL),
        )

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Store embedding error: {e}")
        return False

    finally:
        cur.close()
        conn.close()


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sum(x * x for x in a) ** 0.5
    magnitude_b = sum(x * x for x in b) ** 0.5

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


# =============================================================================
# SEMANTIC SEARCH
# =============================================================================


def semantic_search(
    query: str,
    source_types: Optional[List[str]] = None,
    limit: int = 10,
    min_similarity: float = 0.3,
) -> List[Dict]:
    """Search knowledge base by semantic similarity using pgvector IVFFlat index.

    Uses the idx_kb_embedding IVFFlat index (cosine ops) to search ALL embedded
    entries (29,000+) in a single indexed query. Previously fetched only the 500
    most-recent rows and scored in Python — this fix removes that 98% blindspot.

    Falls back to text search if embedding generation fails.
    """

    # Generate query embedding
    query_embedding = generate_embedding(query)
    if not query_embedding:
        logger.warning("Could not generate query embedding, falling back to text search")
        return text_search(query, source_types, limit)

    # Format embedding for pgvector <=> operator
    query_vec = "[" + ",".join(str(f) for f in query_embedding) + "]"
    # Fetch extra rows so min_similarity filtering still returns `limit` results
    fetch_limit = max(limit * 5, 50)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Recall: the KB uses an HNSW vector index (idx_kb_embedding_hnsw, migrated
        # from a stale ivfflat index whose default probes=1 silently missed best
        # matches — see KB index-health work). Raise hnsw.ef_search above its
        # default (40) for stronger recall; latency cost is negligible at ~30K
        # rows. The legacy ivfflat.probes line is a harmless no-op kept for safety
        # if the index is ever rebuilt as ivfflat. try/except keeps older pgvector safe.
        try:
            cur.execute("SET hnsw.ef_search = 100")
            cur.execute("SET ivfflat.probes = 10")
        except Exception:
            pass

        # pgvector native similarity search — uses HNSW index (idx_kb_embedding_hnsw)
        # 1 - (embedding <=> query) converts cosine distance → cosine similarity
        if source_types:
            cur.execute(
                """
                SELECT id, title, content, knowledge_type, category, tags,
                       quality_score, review_status,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_base
                WHERE embedding IS NOT NULL
                  AND knowledge_type = ANY(%s)
                  AND (review_status IS NULL OR review_status != 'rejected')
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, source_types, query_vec, fetch_limit),
            )
        else:
            cur.execute(
                """
                SELECT id, title, content, knowledge_type, category, tags,
                       quality_score, review_status,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_base
                WHERE embedding IS NOT NULL
                  AND (review_status IS NULL OR review_status != 'rejected')
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, query_vec, fetch_limit),
            )

        rows = cur.fetchall()

        results = []
        for row in rows:
            similarity = float(row["similarity"] or 0)
            if similarity >= min_similarity:
                results.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "content": (row["content"] or "")[:500],
                        "knowledge_type": row["knowledge_type"],
                        "category": row["category"],
                        "tags": row["tags"],
                        "similarity": round(similarity, 4),
                        "quality_score": row["quality_score"],
                        "review_status": row["review_status"],
                        # Compatibility fields for callers expecting old format
                        "source_type": row["knowledge_type"],
                        "source_id": row["id"],
                    }
                )

        # pgvector ORDER BY <=> already sorted by similarity ascending (distance),
        # so results are in correct order (most similar first after 1-distance)
        return results[:limit]

    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return []

    finally:
        cur.close()
        conn.close()


def text_search(query: str, source_types: Optional[List[str]] = None, limit: int = 10) -> List[Dict]:
    """Fallback text search when embeddings unavailable"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    results = []

    try:
        # Search knowledge_base
        if not source_types or "knowledge_base" in source_types:
            cur.execute(
                """
                SELECT id, title, content, importance_score, knowledge_type, tags, source_type
                FROM knowledge_base
                WHERE content ILIKE %s OR title ILIKE %s
                ORDER BY importance_score DESC
                LIMIT %s
            """,
                (f"%{query}%", f"%{query}%", limit),
            )

            for row in cur.fetchall():
                results.append(
                    {
                        "source_type": "knowledge_base",
                        "source_id": row["id"],
                        "title": row["title"],
                        "content": row["content"][:500],
                        "importance": (float(row["importance_score"]) if row["importance_score"] else 0.5),
                        "entry_type": row["knowledge_type"],
                        "tags": row["tags"] or [],
                        "similarity": 0.7,  # Placeholder for text match
                    }
                )

        # Search long_term_memory
        if not source_types or "long_term_memory" in source_types:
            cur.execute(
                """
                SELECT id, memory_type, category, content, importance_score, tags
                FROM long_term_memory
                WHERE content ILIKE %s
                ORDER BY importance_score DESC
                LIMIT %s
            """,
                (f"%{query}%", limit),
            )

            for row in cur.fetchall():
                results.append(
                    {
                        "source_type": "long_term_memory",
                        "source_id": row["id"],
                        "title": f"{row['memory_type']}: {row['category'] or 'General'}",
                        "content": row["content"][:500] if row["content"] else "",
                        "importance": (float(row["importance_score"]) if row["importance_score"] else 0.5),
                        "tags": row["tags"] or [],
                        "similarity": 0.6,
                    }
                )

        # Sort by importance
        results.sort(key=lambda x: x.get("importance", 0), reverse=True)

        return results[:limit]

    except Exception as e:
        logger.error(f"Text search error: {e}")
        return []

    finally:
        cur.close()
        conn.close()


def get_memory_content(source_type: str, source_id: int) -> Dict:
    """Get full content of a memory by type and ID"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        if source_type == "knowledge_base":
            cur.execute(
                """
                SELECT id, title, content, importance, entry_type, tags,
                       source_type, source_id as ref_id, created_at
                FROM knowledge_base WHERE id = %s
            """,
                (source_id,),
            )

        elif source_type == "long_term_memory":
            cur.execute(
                """
                SELECT id, memory_type as title, content, importance_score as importance,
                       category as entry_type, tags, source_module, created_at
                FROM long_term_memory WHERE id = %s
            """,
                (source_id,),
            )

        elif source_type == "agent_memory":
            cur.execute(
                """
                SELECT am.id, am.memory_type as title, am.content,
                       am.importance_score as importance, am.emotional_valence,
                       a.name as agent_name, am.created_at
                FROM agent_memory am
                LEFT JOIN agents a ON am.agent_id = a.id
                WHERE am.id = %s
            """,
                (source_id,),
            )

        else:
            return {}

        row = cur.fetchone()
        return dict(row) if row else {}

    except Exception as e:
        logger.error(f"Get memory content error: {e}")
        return {}

    finally:
        cur.close()
        conn.close()


# =============================================================================
# MEMORY COLLECTIONS
# =============================================================================


def create_collection(
    name: str,
    description: str = None,
    user_id: int = None,
    agent_id: int = None,
    collection_type: str = "manual",
    filter_criteria: dict = None,
    icon: str = None,
    color: str = None,
) -> Optional[int]:
    """Create a new memory collection"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO memory_collections
            (name, description, user_id, agent_id, collection_type, filter_criteria, icon, color)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                name,
                description,
                user_id,
                agent_id,
                collection_type,
                json.dumps(filter_criteria) if filter_criteria else None,
                icon,
                color,
            ),
        )

        collection_id = cur.fetchone()[0]
        conn.commit()
        return collection_id

    except Exception as e:
        conn.rollback()
        logger.error(f"Create collection error: {e}")
        return None

    finally:
        cur.close()
        conn.close()


def get_collections(user_id: int = None, agent_id: int = None) -> List[Dict]:
    """Get memory collections"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        if user_id:
            cur.execute(
                """
                SELECT c.*, COUNT(ci.id) as item_count
                FROM memory_collections c
                LEFT JOIN memory_collection_items ci ON c.id = ci.collection_id
                WHERE c.user_id = %s OR c.is_private = FALSE
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC
            """,
                (user_id,),
            )
        elif agent_id:
            cur.execute(
                """
                SELECT c.*, COUNT(ci.id) as item_count
                FROM memory_collections c
                LEFT JOIN memory_collection_items ci ON c.id = ci.collection_id
                WHERE c.agent_id = %s
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC
            """,
                (agent_id,),
            )
        else:
            cur.execute(
                """
                SELECT c.*, COUNT(ci.id) as item_count
                FROM memory_collections c
                LEFT JOIN memory_collection_items ci ON c.id = ci.collection_id
                WHERE c.is_private = FALSE
                GROUP BY c.id
                ORDER BY c.is_pinned DESC, c.updated_at DESC
                LIMIT 50
            """
            )

        return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        logger.error(f"Get collections error: {e}")
        return []

    finally:
        cur.close()
        conn.close()


def add_to_collection(
    collection_id: int,
    memory_type: str,
    memory_id: int,
    notes: str = None,
    added_by: int = None,
) -> bool:
    """Add a memory to a collection"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Get current max position
        cur.execute(
            """
            SELECT COALESCE(MAX(position), 0) + 1
            FROM memory_collection_items
            WHERE collection_id = %s
        """,
            (collection_id,),
        )
        position = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO memory_collection_items
            (collection_id, memory_type, memory_id, position, notes, added_by)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (collection_id, memory_type, memory_id) DO UPDATE
            SET notes = EXCLUDED.notes
        """,
            (collection_id, memory_type, memory_id, position, notes, added_by),
        )

        # Update collection timestamp
        cur.execute(
            """
            UPDATE memory_collections SET updated_at = NOW()
            WHERE id = %s
        """,
            (collection_id,),
        )

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Add to collection error: {e}")
        return False

    finally:
        cur.close()
        conn.close()


def get_collection_items(collection_id: int) -> List[Dict]:
    """Get all items in a collection with full content"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT ci.*, u.username as added_by_name
            FROM memory_collection_items ci
            LEFT JOIN users u ON ci.added_by = u.id
            WHERE ci.collection_id = %s
            ORDER BY ci.position
        """,
            (collection_id,),
        )

        items = []
        for row in cur.fetchall():
            item = dict(row)
            # Fetch full content
            content = get_memory_content(item["memory_type"], item["memory_id"])
            item["memory"] = content
            items.append(item)

        return items

    except Exception as e:
        logger.error(f"Get collection items error: {e}")
        return []

    finally:
        cur.close()
        conn.close()


# =============================================================================
# MEMORY ASSOCIATIONS
# =============================================================================


def create_association(
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    association_type: str = "related",
    strength: float = 0.5,
    is_bidirectional: bool = True,
    created_by: str = "system",
) -> bool:
    """Create an association between two memories"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO memory_associations
            (source_type, source_id, target_type, target_id, association_type, strength, is_bidirectional, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_type, source_id, target_type, target_id)
            DO UPDATE SET
                strength = GREATEST(memory_associations.strength, EXCLUDED.strength),
                association_type = EXCLUDED.association_type
        """,
            (
                source_type,
                source_id,
                target_type,
                target_id,
                association_type,
                strength,
                is_bidirectional,
                created_by,
            ),
        )

        conn.commit()
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Create association error: {e}")
        return False

    finally:
        cur.close()
        conn.close()


def get_related_memories(memory_type: str, memory_id: int, limit: int = 10) -> List[Dict]:
    """Get memories related to a specific memory"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(
            """
            SELECT
                CASE WHEN source_type = %s AND source_id = %s THEN target_type ELSE source_type END as related_type,
                CASE WHEN source_type = %s AND source_id = %s THEN target_id ELSE source_id END as related_id,
                association_type,
                strength
            FROM memory_associations
            WHERE (source_type = %s AND source_id = %s)
               OR (target_type = %s AND target_id = %s AND is_bidirectional = TRUE)
            ORDER BY strength DESC
            LIMIT %s
        """,
            (
                memory_type,
                memory_id,
                memory_type,
                memory_id,
                memory_type,
                memory_id,
                memory_type,
                memory_id,
                limit,
            ),
        )

        results = []
        for row in cur.fetchall():
            item = dict(row)
            content = get_memory_content(item["related_type"], item["related_id"])
            item["memory"] = content
            results.append(item)

        return results

    except Exception as e:
        logger.error(f"Get related memories error: {e}")
        return []

    finally:
        cur.close()
        conn.close()


def find_similar_memories(memory_type: str, memory_id: int, threshold: float = 0.7) -> List[Dict]:
    """Find similar memories using embeddings and create associations"""
    # Get the source memory content
    content = get_memory_content(memory_type, memory_id)
    if not content.get("content"):
        return []

    # Search for similar
    similar = semantic_search(content["content"], limit=10, min_similarity=threshold)

    # Create associations for similar memories
    for match in similar:
        if match["source_type"] != memory_type or match["source_id"] != memory_id:
            create_association(
                memory_type,
                memory_id,
                match["source_type"],
                match["source_id"],
                association_type="related",
                strength=match["similarity"],
                created_by="embedding_similarity",
            )

    return similar


# =============================================================================
# MEMORY COLLECTION POINTS (Auto-capture)
# =============================================================================


def record_memory(
    content: str,
    memory_type: str = "observation",
    category: str = None,
    importance: float = 0.5,
    tags: List[str] = None,
    user_id: int = None,
    agent_id: int = None,
    source_module: str = None,
    metadata: dict = None,
    generate_embedding: bool = True,
) -> Optional[int]:
    """Record a new memory with optional embedding"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        if agent_id:
            # Store in agent_memory
            cur.execute(
                """
                INSERT INTO agent_memory
                (agent_id, memory_type, content, importance_score, source_module, context)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    agent_id,
                    memory_type,
                    content,
                    importance,
                    source_module,
                    json.dumps(metadata) if metadata else None,
                ),
            )

            memory_id = cur.fetchone()[0]
            source = "agent_memory"

        else:
            # Store in long_term_memory
            cur.execute(
                """
                INSERT INTO long_term_memory
                (user_id, memory_type, category, content, importance_score, tags, source_module, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    user_id,
                    memory_type,
                    category,
                    content,
                    importance,
                    tags,
                    source_module,
                    json.dumps(metadata) if metadata else None,
                ),
            )

            memory_id = cur.fetchone()[0]
            source = "long_term_memory"

        conn.commit()

        # Generate and store embedding
        if generate_embedding and memory_id:
            store_embedding(source, memory_id, content)

        # Log the access
        log_memory_access(source, memory_id, "create", "system")

        return memory_id

    except Exception as e:
        conn.rollback()
        logger.error(f"Record memory error: {e}")
        return None

    finally:
        cur.close()
        conn.close()


def log_memory_access(
    memory_type: str,
    memory_id: int,
    access_type: str = "read",
    accessor_type: str = "system",
    accessor_id: int = None,
    context: dict = None,
):
    """Log memory access for analytics"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO memory_access_log
            (memory_type, memory_id, access_type, accessor_type, accessor_id, context)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            (
                memory_type,
                memory_id,
                access_type,
                accessor_type,
                accessor_id,
                json.dumps(context) if context else None,
            ),
        )

        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error(f"Log access error: {e}")

    finally:
        cur.close()
        conn.close()


# =============================================================================
# DECAY AND REINFORCEMENT
# =============================================================================


def apply_decay() -> int:
    """Apply memory decay (call periodically)"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT apply_memory_decay()")
        count = cur.fetchone()[0]
        conn.commit()
        return count

    except Exception as e:
        conn.rollback()
        logger.error(f"Apply decay error: {e}")
        return 0

    finally:
        cur.close()
        conn.close()


def reinforce_memory(memory_type: str, memory_id: int, boost: float = 0.05) -> Optional[float]:
    """Reinforce a memory (increase importance on access)"""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT reinforce_memory(%s, %s, %s)", (memory_type, memory_id, boost))
        new_score = cur.fetchone()[0]
        conn.commit()
        return float(new_score) if new_score else None

    except Exception as e:
        conn.rollback()
        logger.error(f"Reinforce memory error: {e}")
        return None

    finally:
        cur.close()
        conn.close()


# =============================================================================
# STATISTICS
# =============================================================================


def get_memory_stats() -> Dict:
    """Get memory system statistics"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        stats = {}

        # Count by type
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM knowledge_base) as knowledge_base,
                (SELECT COUNT(*) FROM long_term_memory) as long_term_memory,
                (SELECT COUNT(*) FROM agent_memory WHERE is_deleted = FALSE) as agent_memory,
                (SELECT COUNT(*) FROM memory_embeddings) as embeddings,
                (SELECT COUNT(*) FROM memory_collections) as collections,
                (SELECT COUNT(*) FROM memory_associations) as associations
        """
        )
        counts = cur.fetchone()
        stats["counts"] = dict(counts)

        # Recent activity
        cur.execute(
            """
            SELECT access_type, COUNT(*) as count
            FROM memory_access_log
            WHERE accessed_at > NOW() - INTERVAL '24 hours'
            GROUP BY access_type
        """
        )
        stats["recent_activity"] = {row["access_type"]: row["count"] for row in cur.fetchall()}

        # Importance distribution
        cur.execute(
            """
            SELECT
                CASE
                    WHEN importance_score >= 0.8 THEN 'high'
                    WHEN importance_score >= 0.5 THEN 'medium'
                    ELSE 'low'
                END as level,
                COUNT(*) as count
            FROM long_term_memory
            GROUP BY level
        """
        )
        stats["importance_distribution"] = {row["level"]: row["count"] for row in cur.fetchall()}

        # Top accessed memories
        cur.execute(
            """
            SELECT memory_type, memory_id, COUNT(*) as access_count
            FROM memory_access_log
            WHERE accessed_at > NOW() - INTERVAL '7 days'
            GROUP BY memory_type, memory_id
            ORDER BY access_count DESC
            LIMIT 5
        """
        )
        stats["top_accessed"] = [dict(row) for row in cur.fetchall()]

        return stats

    except Exception as e:
        logger.error(f"Get stats error: {e}")
        return {}

    finally:
        cur.close()
        conn.close()
