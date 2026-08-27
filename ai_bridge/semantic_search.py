"""
Semantic Search Module for ARCHIE Consciousness Intelligence

Implements hybrid search combining vector similarity (70%) and keyword matching (30%).
Uses pgvector for vector search and PostgreSQL full-text search for keywords.

Usage:
    from ai_bridge.semantic_search import search, get_search_service

    # Simple search
    results = search("docker networking bridge mode", limit=10)

    # With filters
    results = search("authentication", filters={"category": "pattern"})
"""

import json
import logging
from typing import Optional
from dataclasses import dataclass
import psycopg2
from psycopg2.extras import RealDictCursor

from ai_bridge.embedding_service import generate_embedding
from db import get_db

logger = logging.getLogger(__name__)

# Configuration
VECTOR_WEIGHT = 0.7  # 70% vector similarity
KEYWORD_WEIGHT = 0.3  # 30% keyword matching
DEFAULT_LIMIT = 10
MIN_SCORE_THRESHOLD = 0.1


@dataclass
class SearchResult:
    """A single search result"""

    id: int
    title: str
    summary: str
    content: str
    category: str
    score: float
    vector_score: float
    keyword_score: float
    tags: list
    source_type: str
    created_at: str


class SemanticSearch:
    """Hybrid semantic search service"""

    def __init__(self):
        self._embedding_available = None

    def _check_embedding_availability(self) -> bool:
        """Check if embeddings are available in the database"""
        if self._embedding_available is not None:
            return self._embedding_available

        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT COUNT(*) FROM knowledge_base
                    WHERE embedding IS NOT NULL
                    """
                )
                count = cur.fetchone()[0]
                self._embedding_available = count > 0
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
            return self._embedding_available
        except Exception as e:
            logger.error(f"Error checking embedding availability: {e}")
            return False

    def search(
        self,
        query: str,
        limit: int = DEFAULT_LIMIT,
        filters: Optional[dict] = None,
        vector_only: bool = False,
        keyword_only: bool = False,
    ) -> list:
        """
        Perform hybrid search combining vector and keyword matching.

        Args:
            query: Search query text
            limit: Maximum results to return
            filters: Optional filters (category, source_type, tags)
            vector_only: Use only vector search
            keyword_only: Use only keyword search

        Returns:
            List of SearchResult objects
        """
        if not query or not query.strip():
            return []

        # Check if embeddings are available
        has_embeddings = self._check_embedding_availability()

        # Decide search strategy
        if keyword_only or not has_embeddings:
            return self._keyword_search(query, limit, filters)
        elif vector_only:
            return self._vector_search(query, limit, filters)
        else:
            return self._hybrid_search(query, limit, filters)

    def _vector_search(
        self,
        query: str,
        limit: int,
        filters: Optional[dict],
    ) -> list:
        """Perform vector similarity search"""
        # Generate query embedding
        query_embedding = generate_embedding(query)
        if not query_embedding:
            logger.warning("Failed to generate query embedding, falling back to keyword")
            return self._keyword_search(query, limit, filters)

        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Build filter clause
                filter_clause, filter_params = self._build_filter_clause(filters)

                # Vector similarity search using cosine distance
                sql = f"""
                    SELECT
                        id, title, content, category, tags, source_type, created_at,
                        1 - (embedding <=> %s::vector) as vector_score,
                        COALESCE(
                            (ai_analysis->>'summary')::text,
                            LEFT(content, 200)
                        ) as summary
                    FROM knowledge_base
                    WHERE embedding IS NOT NULL
                    {filter_clause}
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """

                params = [query_embedding] + filter_params + [query_embedding, limit * 2]
                cur.execute(sql, params)
                rows = cur.fetchall()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            results = []
            for row in rows[:limit]:
                results.append(
                    SearchResult(
                        id=row["id"],
                        title=row["title"],
                        summary=row["summary"] or "",
                        content=row["content"][:500] if row["content"] else "",
                        category=row["category"] or "",
                        score=float(row["vector_score"] or 0),
                        vector_score=float(row["vector_score"] or 0),
                        keyword_score=0.0,
                        tags=row["tags"] or [],
                        source_type=row["source_type"] or "",
                        created_at=str(row["created_at"]) if row["created_at"] else "",
                    )
                )
            return results

        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return self._keyword_search(query, limit, filters)

    def _keyword_search(
        self,
        query: str,
        limit: int,
        filters: Optional[dict],
    ) -> list:
        """Perform PostgreSQL full-text search"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Build filter clause
                filter_clause, filter_params = self._build_filter_clause(filters)

                # Full-text search with ranking
                sql = f"""
                    SELECT
                        id, title, content, category, tags, source_type, created_at,
                        ts_rank_cd(search_vector, plainto_tsquery('english', %s)) as keyword_score,
                        COALESCE(
                            (ai_analysis->>'summary')::text,
                            LEFT(content, 200)
                        ) as summary
                    FROM knowledge_base
                    WHERE search_vector @@ plainto_tsquery('english', %s)
                    {filter_clause}
                    ORDER BY keyword_score DESC
                    LIMIT %s
                """

                params = [query, query] + filter_params + [limit * 2]
                cur.execute(sql, params)
                rows = cur.fetchall()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            results = []
            for row in rows[:limit]:
                score = float(row["keyword_score"] or 0)
                # Normalize keyword score (ts_rank can vary widely)
                normalized_score = min(1.0, score / 0.5) if score > 0 else 0
                results.append(
                    SearchResult(
                        id=row["id"],
                        title=row["title"],
                        summary=row["summary"] or "",
                        content=row["content"][:500] if row["content"] else "",
                        category=row["category"] or "",
                        score=normalized_score,
                        vector_score=0.0,
                        keyword_score=normalized_score,
                        tags=row["tags"] or [],
                        source_type=row["source_type"] or "",
                        created_at=str(row["created_at"]) if row["created_at"] else "",
                    )
                )
            return results

        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []

    def _hybrid_search(
        self,
        query: str,
        limit: int,
        filters: Optional[dict],
    ) -> list:
        """
        Perform hybrid search with score fusion.

        Combines vector similarity (70%) and keyword matching (30%).
        """
        # Get both result sets
        vector_results = self._vector_search(query, limit * 2, filters)
        keyword_results = self._keyword_search(query, limit * 2, filters)

        # Build score map by ID
        scores = {}  # id -> {vector_score, keyword_score, result}

        for r in vector_results:
            scores[r.id] = {
                "vector_score": r.vector_score,
                "keyword_score": 0.0,
                "result": r,
            }

        for r in keyword_results:
            if r.id in scores:
                scores[r.id]["keyword_score"] = r.keyword_score
            else:
                scores[r.id] = {
                    "vector_score": 0.0,
                    "keyword_score": r.keyword_score,
                    "result": r,
                }

        # Calculate fused scores
        fused = []
        for id, data in scores.items():
            fused_score = VECTOR_WEIGHT * data["vector_score"] + KEYWORD_WEIGHT * data["keyword_score"]

            if fused_score >= MIN_SCORE_THRESHOLD:
                result = data["result"]
                result.score = fused_score
                result.vector_score = data["vector_score"]
                result.keyword_score = data["keyword_score"]
                fused.append(result)

        # Sort by fused score and return top results
        fused.sort(key=lambda r: r.score, reverse=True)
        return fused[:limit]

    def _build_filter_clause(self, filters: Optional[dict]) -> tuple:
        """Build SQL WHERE clause from filters.

        Always excludes quarantined agent-proposed KB writes (#3534 Phase 3):
        they surface only after C.O.D.E.X. promotes review_status to 'approved'.
        Applied to both the vector and keyword search paths (both interpolate
        this clause). Independent of embedding state — quarantine never leaks
        even if the embedding loop fills a pending row.
        """
        quarantine = "AND (source_type IS DISTINCT FROM 'agent_proposed' OR review_status = 'approved')"
        if not filters:
            return quarantine, []

        clauses = [quarantine]
        params = []

        if filters.get("category"):
            clauses.append("AND category = %s")
            params.append(filters["category"])

        if filters.get("source_type"):
            clauses.append("AND source_type = %s")
            params.append(filters["source_type"])

        if filters.get("tags"):
            clauses.append("AND tags && %s")
            params.append(filters["tags"])

        if filters.get("min_importance"):
            clauses.append("AND importance_score >= %s")
            params.append(filters["min_importance"])

        return " ".join(clauses), params

    def get_similar(self, knowledge_id: int, limit: int = 5) -> list:
        """Find similar knowledge entries by vector similarity"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Get the embedding for the source entry
                cur.execute(
                    """
                    SELECT embedding FROM knowledge_base
                    WHERE id = %s AND embedding IS NOT NULL
                    """,
                    (knowledge_id,),
                )
                row = cur.fetchone()
                if not row:
                    return []

                source_embedding = row["embedding"]

                # Find similar entries
                cur.execute(
                    """
                    SELECT
                        id, title, category, tags,
                        1 - (embedding <=> %s::vector) as similarity,
                        COALESCE(
                            (ai_analysis->>'summary')::text,
                            LEFT(content, 200)
                        ) as summary
                    FROM knowledge_base
                    WHERE id != %s AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (source_embedding, knowledge_id, source_embedding, limit),
                )

                rows = cur.fetchall()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "category": row["category"],
                    "tags": row["tags"],
                    "similarity": float(row["similarity"]),
                    "summary": row["summary"],
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Get similar failed: {e}")
            return []

    def get_stats(self) -> dict:
        """Get search service statistics"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                # Count total entries
                cur.execute("SELECT COUNT(*) FROM knowledge_base")
                total = cur.fetchone()[0]

                # Count entries with embeddings
                cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE embedding IS NOT NULL")
                with_embeddings = cur.fetchone()[0]

                # Count entries with search_vector
                cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE search_vector IS NOT NULL")
                with_search_vector = cur.fetchone()[0]
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            return {
                "total_entries": total,
                "with_embeddings": with_embeddings,
                "with_search_vector": with_search_vector,
                "embedding_coverage": (round(with_embeddings / total * 100, 1) if total > 0 else 0),
                "vector_search_available": with_embeddings > 0,
                "keyword_search_available": with_search_vector > 0,
            }

        except Exception as e:
            logger.error(f"Get stats failed: {e}")
            return {"error": str(e)}


# Singleton instance
_search_service: Optional[SemanticSearch] = None


def get_search_service() -> SemanticSearch:
    """Get or create singleton search service instance"""
    global _search_service
    if _search_service is None:
        _search_service = SemanticSearch()
    return _search_service


def search(
    query: str,
    limit: int = DEFAULT_LIMIT,
    filters: Optional[dict] = None,
) -> list:
    """Convenience function for search"""
    service = get_search_service()
    return service.search(query, limit, filters)


def search_stats() -> dict:
    """Convenience function for stats"""
    service = get_search_service()
    return service.get_stats()


if __name__ == "__main__":
    # Test when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing Semantic Search...")
    print("-" * 40)

    # Get stats
    stats = search_stats()
    print(f"\nSearch Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Test keyword search
    print("\nTesting keyword search for 'docker'...")
    results = search("docker", limit=5)
    print(f"Found {len(results)} results")
    for r in results[:3]:
        print(f"  - [{r.score:.2f}] {r.title}")
