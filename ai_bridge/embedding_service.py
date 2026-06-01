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
REQUEST_TIMEOUT = 30  # seconds — warm <1s, cold CPU load ~4-10s; fail over fast (#3525)

# Cluster-delegated embedding routing (#3525): instead of always hitting the
# contended hub GPU, route to online fleet nodes that have the embedding model
# loaded (CPU outposts), with failover, then the configured host as last resort.
_HOSTS_CACHE: dict = {"hosts": None, "ts": 0.0}
_HOSTS_CACHE_TTL = 30  # seconds — cap DB lookups during bulk KB indexing


def _resolve_embedding_hosts() -> list[str]:
    """Ordered list of embedding endpoints, tier-first: GPU/Starship fleet
    nodes, then CPU outposts, then OLLAMA_HOST (hub) as final fallback. Within
    a tier, least-loaded first. The embedder runs num_gpu:0 (CPU) on every
    node, so the GPU-first preference is about node tier / keeping the hub free
    for large models — not GPU acceleration of the embed itself.
    Fully defensive — any error returns just [OLLAMA_HOST]."""
    import time

    now = time.time()
    cached = _HOSTS_CACHE.get("hosts")
    if cached is not None and (now - _HOSTS_CACHE.get("ts", 0.0)) < _HOSTS_CACHE_TTL:
        return cached

    hosts: list[str] = []
    try:
        from database import get_db_cursor  # platform DB (RealDictCursor)

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT r.mesh_ip
                FROM node_ollama_models m
                JOIN remote_nodes r ON r.node_id = m.node_id
                WHERE m.model_name = %s
                  AND r.status = 'online'
                  AND r.is_active = TRUE
                  AND r.last_heartbeat > NOW() - INTERVAL '3 minutes'
                  AND r.mesh_ip IS NOT NULL
                  -- Exclude the hub (starbase) here — it is appended last as
                  -- the OLLAMA_HOST fallback, so the pool prefers fleet nodes
                  -- and keeps the hub free for large models.
                  AND r.deployment_mode IS DISTINCT FROM 'starbase'
                -- Tier-first (#3): GPU/Starship nodes before CPU outposts,
                -- least-loaded within a tier. Hub is appended last below.
                ORDER BY r.gpu_available DESC NULLS LAST,
                         r.current_load ASC NULLS LAST,
                         random()
                """,
                (EMBEDDING_MODEL,),
            )
            for row in cur.fetchall():
                ip = row["mesh_ip"] if isinstance(row, dict) else row[0]
                if ip:
                    url = f"http://{ip}:11434"
                    if url not in hosts:
                        hosts.append(url)
    except Exception as e:  # noqa: BLE001 — resolution must never break embeddings
        logger.debug("embedding host resolve failed (%s) — using default host", e)

    # Hub FIRST (#3524): embeddings are a LOCAL, CPU-only (num_gpu:0), latency-
    # sensitive op called thousands of times. The local hub (host.docker.internal,
    # 128 GB RAM, arctic-embed-cpu kept resident as a protected CONSCIOUSNESS_MODEL,
    # re-warmed every 25 min) answers a warm embed in <1s and never touches the GPU
    # — so the #3525 "keep the hub free for large GPU models" rationale does not
    # apply to a CPU embed. Routing fleet-first instead meant a single embed tried
    # up to 5 remote CPU VPS outposts over the mesh, serially at 30s each (~150s)
    # before reaching the hub — the >120s timeouts that broke KB search on boot.
    # Remote outposts stay as overflow/failover, capped so a slow tail can't stack
    # multiple 30s timeouts.
    ordered = [OLLAMA_HOST] + [h for h in hosts if h != OLLAMA_HOST]
    ordered = ordered[:3]  # hub + at most 2 failover nodes

    _HOSTS_CACHE["hosts"] = ordered
    _HOSTS_CACHE["ts"] = now
    return ordered


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

        # Cluster-delegated routing with failover: try each online fleet node
        # that has the embedding model, then the hub as last resort (#3525).
        hosts = _resolve_embedding_hosts()
        last_err = "no endpoints"
        for _idx, _host in enumerate(hosts):
            try:
                response = requests.post(
                    f"{_host}/api/embed",
                    json={
                    "model": self.model,
                    "input": text,
                    "keep_alive": "35m",
                    # Force CPU: on GPU nodes (hub) Ollama otherwise tries to
                    # load the embedder on the full 8GB GPU and times out. CPU
                    # keeps it in RAM beside the GPU chat models (#3525).
                    "options": {"num_gpu": 0},
                },
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()

                embeddings = data.get("embeddings", [])
                if not embeddings:
                    last_err = f"no embeddings in response @ {_host}"
                    continue

                embedding = embeddings[0]
                if len(embedding) != EMBEDDING_DIMENSIONS:
                    logger.warning(
                        f"Unexpected embedding dimensions: {len(embedding)} "
                        f"(expected {EMBEDDING_DIMENSIONS})"
                    )
                if _idx > 0:
                    logger.info(
                        f"embedding: failed over to {_host} (attempt {_idx + 1}/{len(hosts)})"
                    )
                token_count = len(text.split())
                return EmbeddingResult(
                    embedding=embedding, model=self.model, token_count=token_count
                )

            except requests.exceptions.Timeout:
                last_err = f"timeout >{REQUEST_TIMEOUT}s @ {_host}"
            except requests.exceptions.RequestException as e:
                last_err = f"{e} @ {_host}"
            except Exception as e:  # noqa: BLE001
                last_err = f"unexpected {e} @ {_host}"

        logger.error(f"Embedding failed on all {len(hosts)} endpoint(s): {last_err}")
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


def warm_all_nodes() -> dict:
    """Ping every node in the embedding pool with a tiny embed to refresh its
    keep_alive timer, so arctic-embed-cpu never cold-loads (#3525). Run by the
    keep-warm scheduled job more often than the 35m keep_alive. Bypasses the
    30s host cache so it always sees the current fleet."""
    _HOSTS_CACHE["hosts"] = None
    results: dict = {}
    for host in _resolve_embedding_hosts():
        try:
            resp = requests.post(
                f"{host}/api/embed",
                json={
                    "model": EMBEDDING_MODEL,
                    "input": "warm",
                    "keep_alive": "35m",
                    "options": {"num_gpu": 0},
                },
                timeout=20,
            )
            results[host] = "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
        except Exception as e:  # noqa: BLE001 — keep-warm must never raise
            results[host] = f"err_{type(e).__name__}"
    ok = sum(1 for v in results.values() if v == "ok")
    logger.info("embedding keep-warm: %d/%d nodes warm — %s", ok, len(results), results)
    return results


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
