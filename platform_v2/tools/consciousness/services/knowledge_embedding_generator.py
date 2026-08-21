"""
Knowledge Base Embedding Generator
Generates semantic embeddings for knowledge base articles using Ollama

Purpose:
- Create vector embeddings for semantic search
- Use Ollama's embedding models (no external API costs)
- Store embeddings as JSONB in PostgreSQL
- Enable hybrid search (keyword + semantic)

Author: A.R.C.H.I.E. Platform
Date: 2026-01-06
"""

import os
import json
import logging
import requests
from typing import Dict, List, Optional
import numpy as np

logger = logging.getLogger(__name__)


class KnowledgeEmbeddingGenerator:
    """Generates embeddings for knowledge base articles"""

    def __init__(
        self,
        ollama_url: str = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434"),
        model: str = "arctic-embed-cpu",
        dimension: int = 768,
    ):
        if ollama_url and not ollama_url.startswith("http"):
            ollama_url = "http://" + ollama_url
        self.ollama_url = ollama_url
        self.model = model
        self.dimension = dimension

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding vector for text using Ollama

        Args:
            text: Text to generate embedding for

        Returns:
            List of floats representing the embedding vector
        """
        try:
            # Use Ollama's embedding API
            response = requests.post(
                f"{self.ollama_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                embedding = data.get("embedding", [])

                if len(embedding) == 0:
                    logger.warning("[Embeddings] Warning: Empty embedding returned for text")
                    return None

                return embedding
            else:
                print(f"[Embeddings] Error: HTTP {response.status_code} from Ollama")
                return None

        except requests.exceptions.ConnectionError:
            print(f"[Embeddings] Error: Cannot connect to Ollama at {self.ollama_url}")
            return None
        except Exception as e:
            print(f"[Embeddings] Error generating embedding: {e}")
            return None

    def generate_embedding_for_article(self, article: Dict) -> Optional[List[float]]:
        """
        Generate embedding for a knowledge base article

        Combines title, description, and content for better semantic representation

        Args:
            article: Dictionary with 'title', 'description', 'content' fields

        Returns:
            Embedding vector
        """
        # Combine article fields for richer semantic representation
        text_parts = []

        if article.get("title"):
            text_parts.append(f"Title: {article['title']}")

        if article.get("description"):
            text_parts.append(f"Description: {article['description']}")

        if article.get("content"):
            # Limit content to first 2000 chars to avoid token limits
            content = article["content"][:2000]
            text_parts.append(f"Content: {content}")

        combined_text = "\n\n".join(text_parts)

        return self.generate_embedding(combined_text)

    def generate_embeddings_batch(self, articles: List[Dict]) -> Dict[int, List[float]]:
        """
        Generate embeddings for multiple articles

        Args:
            articles: List of article dictionaries with 'id' field

        Returns:
            Dictionary mapping article_id -> embedding vector
        """
        embeddings = {}

        for article in articles:
            article_id = article.get("id")
            if not article_id:
                continue

            print(f"[Embeddings] Generating for article #{article_id}: {article.get('title', 'Untitled')[:50]}...")

            embedding = self.generate_embedding_for_article(article)

            if embedding:
                embeddings[article_id] = embedding
                print(f"[Embeddings] ✓ Generated {len(embedding)}-dim vector")
            else:
                print(f"[Embeddings] ✗ Failed to generate embedding")

        return embeddings

    def update_article_embeddings(self, article_ids: Optional[List[int]] = None):
        """
        Update embeddings for knowledge base articles in database

        Args:
            article_ids: List of specific article IDs to update, or None for all
        """
        try:
            from tools.database import db
            import sqlalchemy

            # Get articles from database
            if article_ids:
                query = """
                    SELECT id, title, description, content
                    FROM knowledge_base
                    WHERE id = ANY(%s)
                """
                with db.engine.connect() as conn:
                    result = conn.execute(sqlalchemy.text(query), (article_ids,))
                    articles = [dict(row._mapping) for row in result]
            else:
                query = """
                    SELECT id, title, description, content
                    FROM knowledge_base
                    WHERE embedding IS NULL OR embedding = 'null'::jsonb
                    ORDER BY id
                    LIMIT 100
                """
                with db.engine.connect() as conn:
                    result = conn.execute(sqlalchemy.text(query))
                    articles = [dict(row._mapping) for row in result]

            if not articles:
                print("[Embeddings] No articles to process")
                return {"success": True, "updated": 0}

            print(f"[Embeddings] Processing {len(articles)} articles...")

            # Generate embeddings
            embeddings = self.generate_embeddings_batch(articles)

            # Update database
            updated_count = 0
            for article_id, embedding in embeddings.items():
                try:
                    update_query = """
                        UPDATE knowledge_base
                        SET embedding = %s::jsonb,
                            updated_at = NOW()
                        WHERE id = %s
                    """

                    with db.engine.connect() as conn:
                        conn.execute(
                            sqlalchemy.text(update_query),
                            (json.dumps(embedding), article_id),
                        )
                        conn.commit()

                    updated_count += 1

                except Exception as e:
                    print(f"[Embeddings] Error updating article #{article_id}: {e}")

            print(f"[Embeddings] ✓ Updated {updated_count} articles with embeddings")

            return {
                "success": True,
                "processed": len(articles),
                "updated": updated_count,
                "failed": len(articles) - updated_count,
            }

        except Exception as e:
            print(f"[Embeddings] Error in batch update: {e}")
            return {"success": False, "error": str(e)}

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors

        Args:
            vec1: First vector
            vec2: Second vector

        Returns:
            Similarity score between -1 and 1 (1 = identical, 0 = orthogonal, -1 = opposite)
        """
        try:
            # Convert to numpy arrays
            a = np.array(vec1)
            b = np.array(vec2)

            # Calculate cosine similarity
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            similarity = dot_product / (norm_a * norm_b)

            return float(similarity)

        except Exception as e:
            print(f"[Embeddings] Error calculating similarity: {e}")
            return 0.0

    def search_similar_articles(self, query_text: str, limit: int = 10, min_similarity: float = 0.3) -> List[Dict]:
        """
        Search for similar articles using semantic search

        Args:
            query_text: Search query
            limit: Maximum number of results
            min_similarity: Minimum similarity threshold (0-1)

        Returns:
            List of articles with similarity scores
        """
        try:
            # Generate embedding for query
            query_embedding = self.generate_embedding(query_text)

            if not query_embedding:
                print("[Embeddings] Failed to generate query embedding")
                return []

            # Get all articles with embeddings from database
            from tools.database import db
            import sqlalchemy

            query = """
                SELECT id, title, description, content, category, embedding
                FROM knowledge_base
                WHERE embedding IS NOT NULL
                  AND embedding != 'null'::jsonb
            """

            with db.engine.connect() as conn:
                result = conn.execute(sqlalchemy.text(query))
                articles = [dict(row._mapping) for row in result]

            # Calculate similarity scores
            scored_articles = []

            for article in articles:
                try:
                    # Parse embedding from JSONB
                    embedding_json = article.get("embedding")
                    if isinstance(embedding_json, str):
                        article_embedding = json.loads(embedding_json)
                    else:
                        article_embedding = embedding_json

                    if not article_embedding:
                        continue

                    # Calculate similarity
                    similarity = self.cosine_similarity(query_embedding, article_embedding)

                    if similarity >= min_similarity:
                        scored_articles.append(
                            {
                                "id": article["id"],
                                "title": article["title"],
                                "description": article["description"],
                                "content": article["content"],
                                "category": article["category"],
                                "similarity": similarity,
                            }
                        )

                except Exception as e:
                    print(f"[Embeddings] Error processing article #{article['id']}: {e}")
                    continue

            # Sort by similarity (highest first)
            scored_articles.sort(key=lambda x: x["similarity"], reverse=True)

            # Return top results
            return scored_articles[:limit]

        except Exception as e:
            print(f"[Embeddings] Error in semantic search: {e}")
            return []


# Convenience functions
def generate_embeddings_for_all_articles():
    """Generate embeddings for all articles missing embeddings"""
    generator = KnowledgeEmbeddingGenerator()
    return generator.update_article_embeddings()


def semantic_search(query: str, limit: int = 10) -> List[Dict]:
    """Search knowledge base using semantic similarity"""
    generator = KnowledgeEmbeddingGenerator()
    return generator.search_similar_articles(query, limit=limit)
