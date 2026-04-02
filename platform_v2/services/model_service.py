"""
model_service.py — Ollama model lifecycle manager for Department HQ.

Handles: load, unload, eviction cascade, RAM budgeting, job tracking.
Uses urllib.request (no requests lib) to match platform patterns.
"""

import json
import logging
import os
import time
import urllib.request
from enum import IntEnum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_OLLAMA_HOST = "host.docker.internal:11434"
_CACHE_TTL_SECONDS = 30
_DEFAULT_RAM_BUDGET_GB = 102.4  # 80% of 128 GB

# Models required by the Consciousness / embedding pipeline — never evict first
CONSCIOUSNESS_MODELS = {"arctic-embed-cpu:latest", "mistral:7b"}


# ---------------------------------------------------------------------------
# Priority enum
# ---------------------------------------------------------------------------
class ModelPriority(IntEnum):
    LOWEST = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    PROTECTED = 4


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class ModelService:
    """
    Manages Ollama model lifecycle: load, unload, eviction, capacity planning.

    Attributes
    ----------
    ollama_host : str
        Base URL for the Ollama REST API (with scheme).
    ram_budget_gb : float
        Maximum RAM to allocate to loaded models.
    """

    def __init__(
        self,
        ollama_host: Optional[str] = None,
        ram_budget_gb: float = _DEFAULT_RAM_BUDGET_GB,
    ) -> None:
        raw_host = ollama_host or os.getenv("OLLAMA_HOST", _DEFAULT_OLLAMA_HOST)
        if not raw_host.startswith(("http://", "https://")):
            raw_host = f"http://{raw_host}"
        self.ollama_host = raw_host.rstrip("/")
        self.ram_budget_gb = ram_budget_gb

        # Internal state
        self._loaded_cache: List[Dict] = []
        self._cache_time: float = 0.0
        self._active_jobs: Dict[str, List] = {}  # model → [job_id, ...]
        self._last_used: Dict[str, float] = {}  # model → timestamp

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    def _is_cache_fresh(self) -> bool:
        return (time.time() - self._cache_time) < _CACHE_TTL_SECONDS

    def _refresh_cache(self) -> None:
        self._loaded_cache = self._fetch_ps()
        self._cache_time = time.time()

    def _fetch_ps(self) -> List[Dict]:
        """Hit /api/ps and return parsed model list."""
        try:
            url = f"{self.ollama_host}/api/ps"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            models = data.get("models", [])
            return [
                {
                    "name": m["name"],
                    "size_gb": m.get("size", 0) / (1024**3),
                }
                for m in models
            ]
        except Exception as exc:
            logger.warning("model_service: /api/ps failed — %s", exc)
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def check_loaded_models(self) -> List[Dict]:
        """Return list of currently loaded models with name + size_gb."""
        result = self._fetch_ps()
        self._loaded_cache = result
        self._cache_time = time.time()
        return result

    def get_available_ram(self) -> float:
        """Return GB of RAM still available under budget."""
        if not self._is_cache_fresh():
            self._refresh_cache()
        used = sum(m.get("size_gb", 0.0) for m in self._loaded_cache)
        return self.ram_budget_gb - used

    def is_model_loaded(self, model: str) -> bool:
        """Return True if *model* is currently loaded."""
        if not self._is_cache_fresh():
            self._refresh_cache()
        return any(m["name"] == model for m in self._loaded_cache)

    def get_model_priority(self, model: str) -> ModelPriority:
        """
        Determine eviction priority for *model*.

        PROTECTED  — has active jobs
        HIGH       — consciousness/embedding model
        MEDIUM     — used within the last hour
        LOW        — everything else
        """
        if self._active_jobs.get(model):
            return ModelPriority.PROTECTED
        if model in CONSCIOUSNESS_MODELS:
            return ModelPriority.HIGH
        last = self._last_used.get(model)
        if last and (time.time() - last) < 3600:
            return ModelPriority.MEDIUM
        return ModelPriority.LOW

    def ensure_capacity(self, needed_gb: float) -> bool:
        """
        Free enough RAM for *needed_gb* by evicting low-priority models.

        Eviction order:
          1. LOWEST / LOW priority first
          2. MEDIUM priority if still not enough
          3. Returns False if PROTECTED / HIGH models block eviction
        """
        if self.get_available_ram() >= needed_gb:
            return True

        if not self._is_cache_fresh():
            self._refresh_cache()

        # Sort loaded models by priority ascending (cheapest to evict first)
        candidates = sorted(
            self._loaded_cache,
            key=lambda m: self.get_model_priority(m["name"]),
        )

        for model_info in candidates:
            name = model_info["name"]
            priority = self.get_model_priority(name)
            if priority >= ModelPriority.PROTECTED:
                continue  # cannot evict
            self.unload_model(name)
            if self.get_available_ram() >= needed_gb:
                return True

        return self.get_available_ram() >= needed_gb

    def load_model(self, model: str) -> bool:
        """Load *model* via /api/generate with keep_alive=24h."""
        try:
            url = f"{self.ollama_host}/api/generate"
            payload = json.dumps({"model": model, "keep_alive": "24h", "prompt": ""}).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                resp.read()
            self._last_used[model] = time.time()
            self._cache_time = 0.0  # invalidate cache
            logger.info("model_service: loaded %s", model)
            return True
        except Exception as exc:
            logger.error("model_service: load %s failed — %s", model, exc)
            return False

    def unload_model(self, model: str) -> bool:
        """Unload *model* via /api/generate with keep_alive=0."""
        try:
            url = f"{self.ollama_host}/api/generate"
            payload = json.dumps({"model": model, "keep_alive": 0, "prompt": ""}).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            self._cache_time = 0.0  # invalidate cache
            logger.info("model_service: unloaded %s", model)
            return True
        except Exception as exc:
            logger.error("model_service: unload %s failed — %s", model, exc)
            return False

    def ensure_ready(self, model: str, needed_gb: float = 8.0) -> bool:
        """
        Ensure *model* is loaded and ready.

        Steps: check loaded → ensure capacity → load.
        Returns True on success.
        """
        if self.is_model_loaded(model):
            self._last_used[model] = time.time()
            return True
        if not self.ensure_capacity(needed_gb):
            logger.warning("model_service: not enough RAM for %s (need %.1f GB)", model, needed_gb)
            return False
        return self.load_model(model)

    # ------------------------------------------------------------------
    # Job tracking
    # ------------------------------------------------------------------
    def register_job(self, model: str, job_id) -> None:
        """Mark *job_id* as actively using *model*."""
        self._active_jobs.setdefault(model, [])
        if job_id not in self._active_jobs[model]:
            self._active_jobs[model].append(job_id)
        self._last_used[model] = time.time()

    def unregister_job(self, model: str, job_id) -> None:
        """Remove *job_id* from active users of *model*."""
        jobs = self._active_jobs.get(model, [])
        if job_id in jobs:
            jobs.remove(job_id)
        if not jobs:
            self._active_jobs.pop(model, None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_model_service_instance: Optional[ModelService] = None


def get_model_service() -> ModelService:
    """Return the global ModelService singleton."""
    global _model_service_instance
    if _model_service_instance is None:
        _model_service_instance = ModelService()
    return _model_service_instance
