"""
Knowledge Base Hybrid Search System
Combines keyword search (30%) with semantic search (70%) for optimal results

Purpose:
- Keyword search: Fast, exact matching for specific terms
- Semantic search: AI-powered understanding of meaning/intent
- Hybrid scoring: Weighted combination for best results
- Handles both code entities and documentation

Author: A.R.C.H.I.E. Platform
Date: 2026-01-06
"""

from typing import Dict, List, Optional
import logging
import re
from .knowledge_embedding_generator import KnowledgeEmbeddingGenerator

logger = logging.getLogger(__name__)


class KnowledgeHybridSearch:
    """Hybrid search combining keyword and semantic approaches"""

    def __init__(self, keyword_weight: float = 0.3, semantic_weight: float = 0.7):
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight
        self.embedding_generator = KnowledgeEmbeddingGenerator()

    def keyword_search(self, query: str, limit: int = 50) -> List[Dict]:
        """
        Perform keyword-based search using PostgreSQL full-text search

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of knowledge entries with keyword match scores
        """
        try:
            from tools.database import db
            import sqlalchemy

            # Clean and prepare query
            search_terms = self._extract_search_terms(query)

            if not search_terms:
                return []

            # Build search query with multiple fields
            # Search in: entity_name, description, purpose, documentation
            sql_query = """
                SELECT
                    id,
                    knowledge_type,
                    entity_name,
                    file_path,
                    description,
                    purpose,
                    code_snippet,
                    documentation,
                    complexity_score,
                    importance_score,
                    tags,
                    metadata,
                    (
                        -- Calculate keyword match score
                        CASE WHEN entity_name ILIKE %s THEN 10 ELSE 0 END +
                        CASE WHEN entity_name ILIKE %s THEN 5 ELSE 0 END +
                        CASE WHEN description ILIKE %s THEN 3 ELSE 0 END +
                        CASE WHEN purpose ILIKE %s THEN 3 ELSE 0 END +
                        CASE WHEN documentation ILIKE %s THEN 2 ELSE 0 END +
                        CASE WHEN ARRAY_TO_STRING(tags, ',') ILIKE %s THEN 4 ELSE 0 END
                    ) AS keyword_score
                FROM knowledge_base
                WHERE
                    entity_name ILIKE %s OR
                    description ILIKE %s OR
                    purpose ILIKE %s OR
                    documentation ILIKE %s OR
                    ARRAY_TO_STRING(tags, ',') ILIKE %s
                ORDER BY keyword_score DESC
                LIMIT %s
            """

            # Prepare search patterns
            exact_match = f"%{query}%"
            partial_match = f"%{search_terms[0]}%" if search_terms else exact_match

            with db.engine.connect() as conn:
                result = conn.execute(
                    sqlalchemy.text(sql_query),
                    (
                        exact_match,  # exact match in entity_name
                        partial_match,  # partial match in entity_name
                        exact_match,  # description
                        exact_match,  # purpose
                        exact_match,  # documentation
                        exact_match,  # tags
                        exact_match,  # WHERE clause filters
                        exact_match,
                        exact_match,
                        exact_match,
                        exact_match,
                        limit,
                    ),
                )

                results = []
                for row in result:
                    results.append(
                        {
                            "id": row[0],
                            "knowledge_type": row[1],
                            "entity_name": row[2],
                            "file_path": row[3],
                            "description": row[4],
                            "purpose": row[5],
                            "code_snippet": row[6],
                            "documentation": row[7],
                            "complexity_score": row[8],
                            "importance_score": row[9],
                            "tags": row[10],
                            "metadata": row[11],
                            "keyword_score": float(row[12]) if row[12] else 0.0,
                        }
                    )

                return results

        except Exception as e:
            logger.error(f"[Hybrid Search] Error in keyword search: {e}", exc_info=True)
            return []

    def semantic_search(self, query: str, limit: int = 50) -> List[Dict]:
        """
        Perform semantic search using embeddings

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of knowledge entries with semantic similarity scores
        """
        try:
            # Generate query embedding
            query_embedding = self.embedding_generator.generate_embedding(query)

            if not query_embedding:
                print("[Hybrid Search] Failed to generate query embedding")
                return []

            # Get all entries with embeddings
            from tools.database import db
            import sqlalchemy

            sql_query = """
                SELECT
                    id,
                    knowledge_type,
                    entity_name,
                    file_path,
                    description,
                    purpose,
                    code_snippet,
                    documentation,
                    complexity_score,
                    importance_score,
                    tags,
                    metadata,
                    embedding
                FROM knowledge_base
                WHERE embedding IS NOT NULL
            """

            with db.engine.connect() as conn:
                result = conn.execute(sqlalchemy.text(sql_query))

                results = []
                for row in result:
                    try:
                        # Parse embedding
                        import json

                        embedding_data = row[12]

                        if isinstance(embedding_data, str):
                            entry_embedding = json.loads(embedding_data)
                        else:
                            entry_embedding = embedding_data

                        if not entry_embedding:
                            continue

                        # Calculate semantic similarity
                        similarity = self.embedding_generator.cosine_similarity(query_embedding, entry_embedding)

                        results.append(
                            {
                                "id": row[0],
                                "knowledge_type": row[1],
                                "entity_name": row[2],
                                "file_path": row[3],
                                "description": row[4],
                                "purpose": row[5],
                                "code_snippet": row[6],
                                "documentation": row[7],
                                "complexity_score": row[8],
                                "importance_score": row[9],
                                "tags": row[10],
                                "metadata": row[11],
                                "semantic_score": similarity,
                            }
                        )

                    except Exception as e:
                        print(f"[Hybrid Search] Error processing entry {row[0]}: {e}")
                        continue

                # Sort by semantic score
                results.sort(key=lambda x: x["semantic_score"], reverse=True)

                return results[:limit]

        except Exception as e:
            print(f"[Hybrid Search] Error in semantic search: {e}")
            return []

    def hybrid_search(self, query: str, limit: int = 10, min_score: float = 0.1) -> List[Dict]:
        """
        Perform hybrid search combining keyword and semantic approaches

        Args:
            query: Search query
            limit: Maximum results to return
            min_score: Minimum combined score threshold

        Returns:
            List of knowledge entries sorted by hybrid score
        """
        try:
            print(f"[Hybrid Search] Searching for: '{query}'")

            # Perform both searches
            keyword_results = self.keyword_search(query, limit=50)
            semantic_results = self.semantic_search(query, limit=50)

            print(f"[Hybrid Search] Keyword results: {len(keyword_results)}")
            print(f"[Hybrid Search] Semantic results: {len(semantic_results)}")

            # Normalize scores
            keyword_max = max([r["keyword_score"] for r in keyword_results], default=1.0)
            semantic_max = max([r["semantic_score"] for r in semantic_results], default=1.0)

            # Create combined results dict
            combined = {}

            # Add keyword results
            for result in keyword_results:
                entry_id = result["id"]
                normalized_keyword = result["keyword_score"] / keyword_max if keyword_max > 0 else 0

                combined[entry_id] = {
                    **result,
                    "keyword_score_normalized": normalized_keyword,
                    "semantic_score_normalized": 0.0,
                }

            # Add/merge semantic results
            for result in semantic_results:
                entry_id = result["id"]
                normalized_semantic = result["semantic_score"] / semantic_max if semantic_max > 0 else 0

                if entry_id in combined:
                    # Update existing entry
                    combined[entry_id]["semantic_score"] = result.get("semantic_score", 0)
                    combined[entry_id]["semantic_score_normalized"] = normalized_semantic
                else:
                    # Add new entry
                    combined[entry_id] = {
                        **result,
                        "keyword_score_normalized": 0.0,
                        "semantic_score_normalized": normalized_semantic,
                    }

            # Calculate hybrid scores
            for entry in combined.values():
                keyword_contrib = entry["keyword_score_normalized"] * self.keyword_weight
                semantic_contrib = entry["semantic_score_normalized"] * self.semantic_weight

                entry["hybrid_score"] = keyword_contrib + semantic_contrib

            # Filter by minimum score and sort
            results = [entry for entry in combined.values() if entry["hybrid_score"] >= min_score]

            results.sort(key=lambda x: x["hybrid_score"], reverse=True)

            # Return top results
            top_results = results[:limit]

            print(f"[Hybrid Search] Returning {len(top_results)} results")

            return top_results

        except Exception as e:
            print(f"[Hybrid Search] Error in hybrid search: {e}")
            import traceback

            traceback.print_exc()
            return []

    def _extract_search_terms(self, query: str) -> List[str]:
        """Extract meaningful search terms from query"""
        # Remove special characters and split
        cleaned = re.sub(r"[^\w\s]", " ", query.lower())
        terms = [term for term in cleaned.split() if len(term) > 2]
        return terms

    def search_by_category(self, query: str, knowledge_type: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Search within a specific knowledge type category

        Args:
            query: Search query
            knowledge_type: Filter by type (function, class, module, etc.)
            limit: Maximum results

        Returns:
            Filtered hybrid search results
        """
        results = self.hybrid_search(query, limit=limit * 2)

        if knowledge_type:
            results = [r for r in results if r.get("knowledge_type") == knowledge_type]

        return results[:limit]


# Convenience functions
def hybrid_search(query: str, limit: int = 10) -> List[Dict]:
    """Perform hybrid search on knowledge base"""
    searcher = KnowledgeHybridSearch()
    return searcher.hybrid_search(query, limit=limit)


def search_code_entities(query: str, entity_type: str = None, limit: int = 10) -> List[Dict]:
    """Search for specific code entities (functions, classes, etc.)"""
    searcher = KnowledgeHybridSearch()
    return searcher.search_by_category(query, knowledge_type=entity_type, limit=limit)
