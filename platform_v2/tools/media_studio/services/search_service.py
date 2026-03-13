"""Search service — faceted filters, text search, semantic embedding search.

Combines ILIKE text search with cosine similarity on prompt_embedding vectors.
pgvector required for production semantic search; JSONB fallback capped at 5,000 rows.
"""

import logging
import math
from typing import Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Max rows for JSONB fallback semantic search
_JSONB_SEMANTIC_CAP = 5000

# Whether pgvector is available (detected on first use)
_pgvector_available = None


def _check_pgvector() -> bool:
    """Check if pgvector extension is installed."""
    global _pgvector_available
    if _pgvector_available is not None:
        return _pgvector_available
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            _pgvector_available = cur.fetchone() is not None
    except Exception:
        _pgvector_available = False
    return _pgvector_available


def search_media(
    owner_type: str,
    owner_id: int,
    query: Optional[str] = None,
    filters: Optional[Dict] = None,
    page: int = 1,
    per_page: int = 20,
) -> Dict:
    """Main search entry point: text + faceted + semantic.

    Args:
        query: Free text search (ILIKE on prompt + semantic if embeddings available)
        filters: Dict with optional keys: media_type, tags, model, provider,
                 date_from, date_to, min_width, min_height, collection_id
    """
    filters = filters or {}
    offset = (page - 1) * per_page

    # Build WHERE clauses
    conditions = ["ml.is_deleted = false", "ml.owner_type = %s", "ml.owner_id = %s"]
    params = [owner_type, owner_id]

    if filters.get("media_type"):
        conditions.append("ml.media_type = %s")
        params.append(filters["media_type"])

    if filters.get("model"):
        conditions.append("ml.model = %s")
        params.append(filters["model"])

    if filters.get("provider"):
        conditions.append("ml.provider = %s")
        params.append(filters["provider"])

    if filters.get("date_from"):
        conditions.append("ml.created_at >= %s")
        params.append(filters["date_from"])

    if filters.get("date_to"):
        conditions.append("ml.created_at <= %s")
        params.append(filters["date_to"])

    if filters.get("min_width"):
        conditions.append("ml.width >= %s")
        params.append(filters["min_width"])

    if filters.get("min_height"):
        conditions.append("ml.height >= %s")
        params.append(filters["min_height"])

    # Tag filter: media must have ALL specified tags
    tag_ids = filters.get("tags", [])
    if tag_ids:
        conditions.append(
            """
            ml.id IN (
                SELECT media_id FROM media_tag_map
                WHERE tag_id = ANY(%s)
                GROUP BY media_id
                HAVING COUNT(DISTINCT tag_id) = %s
            )
            """
        )
        params.extend([tag_ids, len(tag_ids)])

    # Collection filter
    if filters.get("collection_id"):
        conditions.append("ml.id IN (SELECT media_id FROM media_collection_items WHERE collection_id = %s)")
        params.append(filters["collection_id"])

    # Text search on prompt
    if query and query.strip():
        conditions.append("ml.prompt ILIKE %s")
        params.append(f"%{query.strip()}%")

    where = " AND ".join(conditions)

    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) as total FROM media_library ml WHERE {where}", params)
        total = cur.fetchone()["total"]

        cur.execute(
            f"""
            SELECT ml.id, ml.media_type, ml.file_path, ml.thumbnail_path, ml.prompt,
                   ml.model, ml.provider, ml.seed, ml.width, ml.height,
                   ml.is_favorite, ml.metadata, ml.created_at
            FROM media_library ml
            WHERE {where}
            ORDER BY ml.created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )
        items = [dict(row) for row in cur.fetchall()]

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def embed_prompt(media_id: int, prompt: str) -> bool:
    """Generate and store embedding for a media item's prompt."""
    if not prompt or not prompt.strip():
        return False

    try:
        from ai_bridge.embedding_service import generate_embedding

        vector = generate_embedding(prompt.strip())
        if not vector:
            return False

        with get_db_cursor(commit=True) as (conn, cur):
            if _check_pgvector():
                cur.execute(
                    "UPDATE media_library SET prompt_embedding = %s WHERE id = %s",
                    (str(vector), media_id),
                )
            else:
                import psycopg2.extras

                cur.execute(
                    "UPDATE media_library SET prompt_embedding = %s WHERE id = %s",
                    (psycopg2.extras.Json(vector), media_id),
                )
        return True
    except Exception as e:
        logger.warning(f"Failed to embed prompt for media {media_id}: {e}")
        return False


def semantic_search(query_text: str, owner_type: str, owner_id: int, limit: int = 20) -> List[Dict]:
    """Cosine similarity search on prompt_embedding."""
    if not query_text or not query_text.strip():
        return []

    try:
        from ai_bridge.embedding_service import generate_embedding

        query_vector = generate_embedding(query_text.strip())
        if not query_vector:
            return []
    except Exception as e:
        logger.warning(f"Failed to generate query embedding: {e}")
        return []

    if _check_pgvector():
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                       1 - (prompt_embedding <=> %s) as similarity
                FROM media_library
                WHERE owner_type = %s AND owner_id = %s
                    AND is_deleted = false AND prompt_embedding IS NOT NULL
                ORDER BY prompt_embedding <=> %s
                LIMIT %s
                """,
                (str(query_vector), owner_type, owner_id, str(query_vector), limit),
            )
            return [dict(row) for row in cur.fetchall()]
    else:
        # JSONB fallback — capped at _JSONB_SEMANTIC_CAP rows
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) as cnt FROM media_library
                WHERE owner_type = %s AND owner_id = %s
                    AND is_deleted = false AND prompt_embedding IS NOT NULL
                """,
                (owner_type, owner_id),
            )
            cnt = cur.fetchone()["cnt"]
            if cnt > _JSONB_SEMANTIC_CAP:
                logger.warning(
                    f"Semantic search skipped: {cnt} rows exceeds JSONB cap of {_JSONB_SEMANTIC_CAP}. Install pgvector."
                )
                return []

            cur.execute(
                """
                SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                       prompt_embedding
                FROM media_library
                WHERE owner_type = %s AND owner_id = %s
                    AND is_deleted = false AND prompt_embedding IS NOT NULL
                """,
                (owner_type, owner_id),
            )
            rows = cur.fetchall()

        # Compute cosine similarity in Python
        results = []
        for row in rows:
            stored = row["prompt_embedding"]
            if not stored:
                continue
            sim = _cosine_similarity(query_vector, stored)
            d = dict(row)
            del d["prompt_embedding"]
            d["similarity"] = sim
            results.append(d)

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_search_facets(owner_type: str, owner_id: int) -> Dict:
    """Return distinct values for filter dropdowns."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT DISTINCT media_type FROM media_library WHERE owner_type = %s AND owner_id = %s AND is_deleted = false ORDER BY media_type",
            (owner_type, owner_id),
        )
        types = [row["media_type"] for row in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT model FROM media_library WHERE owner_type = %s AND owner_id = %s AND is_deleted = false AND model IS NOT NULL ORDER BY model",
            (owner_type, owner_id),
        )
        models = [row["model"] for row in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT provider FROM media_library WHERE owner_type = %s AND owner_id = %s AND is_deleted = false AND provider IS NOT NULL ORDER BY provider",
            (owner_type, owner_id),
        )
        providers = [row["provider"] for row in cur.fetchall()]

        # Tags used by this owner's media
        cur.execute(
            """
            SELECT DISTINCT t.id, t.name, t.tag_type
            FROM media_tags t
            JOIN media_tag_map m ON m.tag_id = t.id
            JOIN media_library ml ON ml.id = m.media_id
            WHERE ml.owner_type = %s AND ml.owner_id = %s AND ml.is_deleted = false
            ORDER BY t.name
            """,
            (owner_type, owner_id),
        )
        tags = [dict(row) for row in cur.fetchall()]

    return {"types": types, "models": models, "providers": providers, "tags": tags}
