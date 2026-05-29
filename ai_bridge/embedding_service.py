"""
Embedding Service for ARCHIE Consciousness Intelligence

Generates semantic embeddings using Ollama's arctic-embed-cpu model (768 dimensions).
Used for vector similarity search in knowledge retrieval.

Note: This service calls Ollama /api/embed directly (ADR-013 exception).
Embeddings are a utility operation (vector generation), not chat/completion inference.
Routing through Bridge dispatch would add overhead with no routing/escalation benefit.
Called thousands of times during KB indexing — direct call is intentional.

Usage:
    from ai_bridge.embedding_service import generate_embedding, get_embedding_service

    # Single embedding
    embedding = generate_embedding("Your text here")

    # Batch embeddings
    service = get_embedding_service()
    embeddings = service.generate_batch(["text1", "text2", "text3"])
"""

import os
import logging
import requests
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Configuration
# Embedding model runs on ARCHIE's local Ollama instance (CPU, kept loaded via MAX_LOADED_MODELS=3).
# arctic-embed-cpu — 768-dim, better retrieval quality than nomic-embed-text.
# Use OLLAMA_EMBEDDING_HOST if set, otherwise OLLAMA_PRIMARY, then host.docker.internal.
_embedding_host = os.getenv("OLLAMA_EMBEDDING_HOST", "")
if not _embedding_host:
    _embedding_host = os.getenv("OLLAMA_PRIMARY", "host.docker.internal:11434")

# Ensure http:// prefix
if not _embedding_host.startswith("http"):
    _embedding_host = f"http://{_embedding_host}"
OLLAMA_HOST = _embedding_host
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "arctic-embed-cpu")
EMBEDDING_DIMENSIONS = 768
REQUEST_TIMEOUT = 120  # seconds — 2 min for arctic-embed-cpu cold-start load


@dataclass
class EmbeddingResult:
    """Result of an embedding operation"""

    embedding: list[float]
    model: str
    token_count: int


class EmbeddingService:
    """Service for generating embeddings via Ollama"""

    def __init__(self, host: str = OLLAMA_HOST, model: str = EMBEDDING_MODEL):
        self.host = host.rstrip("/")
        self.model = model
        self.endpoint = f"{self.host}/api/embed"
        self._healthy: Optional[bool] = None

    def health_check(self) -> dict:
        """Check if embedding service is available"""
        try:
            # Test with a simple embedding
            response = requests.post(
                self.endpoint,
                json={"model": self.model, "input": "health check", "keep_alive": "35m"},
                timeout=60,
            )
            if response.status_code == 200:
                data = response.json()
                embeddings = data.get("embeddings", [[]])
                if embeddings and len(embeddings[0]) == EMBEDDING_DIMENSIONS:
                    self._healthy = True
                    return {
                        "status": "healthy",
                        "model": self.model,
                        "dimensions": len(embeddings[0]),
                        "host": self.host,
                    }

            self._healthy = False
            return {
                "status": "unhealthy",
                "error": f"Unexpected response: {response.status_code}",
                "host": self.host,
            }
        except requests.exceptions.RequestException as e:
            self._healthy = False
            return {"status": "unhealthy", "error": str(e), "host": self.host}

    def generate(self, text: str) -> Optional[EmbeddingResult]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed (will be truncated if too long)

        Returns:
            EmbeddingResult with embedding vector, or None on failure
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for embedding")
            return None

        # Truncate to fit model context window (arctic-embed-cpu: 512 tokens ≈ 1500 chars)
        # Use 1000 chars to leave room for dense text and CJK characters
        max_chars = 1000
        if len(text) > max_chars:
            text = text[:max_chars]
            logger.debug(f"Truncated text to {max_chars} chars for embedding")

        try:
            response = requests.post(
                self.endpoint,
                json={"model": self.model, "input": text, "keep_alive": "35m"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()

            embeddings = data.get("embeddings", [])
            if not embeddings:
                logger.error("No embeddings in response")
                return None

            embedding = embeddings[0]
            if len(embedding) != EMBEDDING_DIMENSIONS:
                logger.warning(
                    f"Unexpected embedding dimensions: {len(embedding)} "
                    f"(expected {EMBEDDING_DIMENSIONS})"
                )

            # Estimate token count (rough approximation)
            token_count = len(text.split())

            return EmbeddingResult(
                embedding=embedding, model=self.model, token_count=token_count
            )

        except requests.exceptions.Timeout:
            logger.error(f"Timeout generating embedding (>{REQUEST_TIMEOUT}s)")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error generating embedding: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in embedding generation: {e}")
            return None

    def generate_batch(
        self, texts: list[str], skip_empty: bool = True
    ) -> list[Optional[EmbeddingResult]]:
        """
        Generate embeddings for multiple texts.

        Note: Ollama doesn't support true batch embedding, so this iterates.
        Consider parallel processing for large batches.

        Args:
            texts: List of texts to embed
            skip_empty: If True, return None for empty texts instead of failing

        Returns:
            List of EmbeddingResults (None for failures)
        """
        results = []
        for i, text in enumerate(texts):
            if skip_empty and (not text or not text.strip()):
                results.append(None)
                continue

            result = self.generate(text)
            results.append(result)

            # Log progress for large batches
            if (i + 1) % 50 == 0:
                logger.info(f"Generated {i + 1}/{len(texts)} embeddings")

        return results

    @property
    def is_healthy(self) -> bool:
        """Check if service was last known to be healthy"""
        if self._healthy is None:
            self.health_check()
        return self._healthy or False


# Singleton instance
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create singleton embedding service instance"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def generate_embedding(text: str) -> Optional[list[float]]:
    """
    Convenience function to generate a single embedding.

    Args:
        text: Text to embed

    Returns:
        768-dimension embedding vector, or None on failure
    """
    service = get_embedding_service()
    result = service.generate(text)
    return result.embedding if result else None


def embedding_health_check() -> dict:
    """Convenience function for health check"""
    service = get_embedding_service()
    return service.health_check()


if __name__ == "__main__":
    # Test when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing Embedding Service...")
    print("-" * 40)

    # Health check
    health = embedding_health_check()
    print(f"Health: {health}")

    if health["status"] == "healthy":
        # Test single embedding
        test_text = "Docker networking bridge mode vs host mode"
        embedding = generate_embedding(test_text)
        if embedding:
            print(f"\nTest embedding generated:")
            print(f"  Text: '{test_text}'")
            print(f"  Dimensions: {len(embedding)}")
            print(f"  First 5 values: {embedding[:5]}")
        else:
            print("Failed to generate test embedding")
    else:
        print("Service unhealthy, skipping embedding test")
