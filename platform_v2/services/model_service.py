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
_DEFAULT_VRAM_BUDGET_GB = 8.0  # Quadro M4000 full 8 GB

# Models required by the Consciousness / embedding pipeline — never evict first
CONSCIOUSNESS_MODELS = {"arctic-embed-cpu:latest", "mistral:7b"}

# Global serialisation lock — only one GPU model loads at a time.
# Concurrent loads cause CUDA graph_reserve failures (compute buffer fragmentation).
# Acquired by ensure_model_ready() regardless of caller (dispatcher, warmup, queue worker).
import threading as _threading

_MODEL_LOAD_LOCK = _threading.Lock()


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

    def _fetch_ps(self, ollama_url: Optional[str] = None) -> List[Dict]:
        """Hit /api/ps and return parsed model list.

        Parameters
        ----------
        ollama_url : str, optional
            Override base URL (used for node routing). Defaults to self.ollama_host.
        """
        base = ollama_url or self.ollama_host
        try:
            url = f"{base}/api/ps"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read())
            models = data.get("models", [])
            return [
                {
                    "name": m["name"],
                    "size_gb": m.get("size", 0) / (1024**3),
                    "size_vram": m.get("size_vram", 0),
                    "size": m.get("size", 0),
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

    def get_available_vram(self) -> float:
        """Return GB of GPU VRAM still free."""
        if not self._is_cache_fresh():
            self._refresh_cache()
        used = sum(m.get("size_vram", 0) / (1024**3) for m in self._loaded_cache)
        return max(0.0, _DEFAULT_VRAM_BUDGET_GB - used)

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
        Free enough RAM and VRAM for *needed_gb* by evicting low-priority models.

        Checks both RAM budget and VRAM budget (GPU). Models with active size_vram
        occupy GPU; they must be evicted when a new GPU model needs to load.

        Eviction order:
          1. LOWEST / LOW priority first (GPU models evicted before RAM-only models
             when VRAM is the bottleneck)
          2. MEDIUM priority if still not enough
          3. Returns False if PROTECTED / HIGH models block eviction
        """

        def _capacity_ok() -> bool:
            ram_ok = self.get_available_ram() >= needed_gb
            # For VRAM: we need 90% of GPU budget free to safely load a large model.
            # We use budget threshold rather than needed_gb because needed_gb is a RAM
            # estimate — actual VRAM footprint for quantized models is different.
            # Small models (<= 4 GB) typically run on CPU; skip the VRAM check.
            vram_threshold = _DEFAULT_VRAM_BUDGET_GB * 0.9
            vram_ok = needed_gb <= 4.0 or self.get_available_vram() >= vram_threshold
            return ram_ok and vram_ok

        if _capacity_ok():
            return True

        if not self._is_cache_fresh():
            self._refresh_cache()

        # Sort loaded models by priority ascending (cheapest to evict first).
        # Within the same priority, prefer evicting GPU models first when VRAM
        # is the binding constraint — they free both VRAM and RAM.
        vram_tight = self.get_available_vram() < needed_gb
        candidates = sorted(
            self._loaded_cache,
            key=lambda m: (
                self.get_model_priority(m["name"]),
                # GPU models get a slight eviction preference when VRAM is tight
                0 if (vram_tight and m.get("size_vram", 0) > 0) else 1,
            ),
        )

        for model_info in candidates:
            name = model_info["name"]
            if self.get_model_priority(name) >= ModelPriority.PROTECTED:
                continue
            self.unload_model(name)
            if _capacity_ok():
                return True

        return _capacity_ok()

    def load_model(self, model: str) -> bool:
        """Load *model* via /api/generate with keep_alive=5m."""
        try:
            url = f"{self.ollama_host}/api/generate"
            payload = json.dumps({"model": model, "keep_alive": "5m", "prompt": ""}).encode()
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
    # Model size estimation
    # ------------------------------------------------------------------

    # Known model size estimates (GB in RAM)
    _MODEL_SIZE_ESTIMATES = {
        "mistral:7b": 4.1,
        "llama3.2:3b": 2.0,
        "phi3.5:latest": 5.5,
        "phi4:14b": 8.5,
        "gemma2:9b": 5.5,
        "gemma3:12b": 7.2,
        "qwen2.5-coder:7b": 4.5,
        "qwen2.5:1.5b": 1.0,
        "dolphin3:latest": 4.8,
        "deepseek-coder-v2:16b": 9.5,
        "qwen2.5vl:7b": 4.5,
        "arctic-embed-cpu:latest": 0.3,
        "smollm2:1.7b": 1.2,
        "qwen3-coder-cpu:latest": 55.0,
    }

    def estimate_model_size(self, model: str) -> float:
        """Estimate model RAM usage in GB. Falls back to parameter-count heuristic."""
        if model in self._MODEL_SIZE_ESTIMATES:
            return self._MODEL_SIZE_ESTIMATES[model]
        import re

        match = re.search(r"(\d+(?:\.\d+)?)b", model.lower())
        if match:
            params = float(match.group(1))
            return params * 0.6
        return 4.0

    # ------------------------------------------------------------------
    # 3-tier warm boot
    # ------------------------------------------------------------------

    def ensure_model_ready(
        self,
        agent_name: str,
        model: str,
        target_host: Optional[Dict] = None,
    ) -> Dict:
        """Ensure model is loaded and ready for inference.

        3-tier strategy:
            1. GPU (VRAM) -- already loaded with VRAM allocation
            2. CPU (RAM)  -- loaded but no/partial VRAM
            3. Cold (disk) -- not loaded, needs warm boot

        Args:
            agent_name: Agent requesting the model (for logging).
            model: Ollama model tag.
            target_host: {"hostname": str, "port": int} for node, None for hub.

        Returns:
            {"ready": bool, "tier": "gpu"|"cpu"|"cold", "host": str, "warm_boot_ms": int}
        """
        import time as _time

        start_ms = _time.time() * 1000

        # Serialise GPU loads — wait up to 150s for any concurrent load to finish.
        # Prevents CUDA graph_reserve fragmentation when warmup / multiple jobs race.
        if not _MODEL_LOAD_LOCK.acquire(timeout=150):
            logger.warning("model_service: model_load_lock timeout waiting to load %s", model)
            return {"ready": False, "tier": "cold", "host": str(target_host), "warm_boot_ms": 150000}

        try:
            return self._ensure_model_ready_locked(agent_name, model, target_host, start_ms)
        finally:
            _MODEL_LOAD_LOCK.release()

    def _ensure_model_ready_locked(self, agent_name, model, target_host, start_ms):
        """Actual ensure_model_ready logic — called while _MODEL_LOAD_LOCK is held."""
        import time as _time

        if target_host:
            host = target_host.get("hostname", "unknown")
            port = target_host.get("port", 11434)
            ollama_url = f"http://{host}:{port}"
        else:
            ollama_url = self.ollama_host
            host = ollama_url.replace("http://", "").replace("https://", "")
            port = 11434

        host_label = f"{host}:{port}" if ":" not in host else host

        # Step 1: Check if already loaded
        try:
            loaded = self._fetch_ps(ollama_url)
        except Exception as exc:
            logger.error("[ModelService] _fetch_ps failed on %s: %s", host_label, exc)
            return {
                "ready": False,
                "tier": "cold",
                "host": host_label,
                "warm_boot_ms": 0,
            }

        for m in loaded:
            if m.get("name") == model:
                size_vram = m.get("size_vram", 0)
                size_total = m.get("size", 0)
                if size_vram > 0 and size_total > 0 and size_vram >= size_total * 0.5:
                    tier = "gpu"
                else:
                    tier = "cpu"
                self._last_used[model] = _time.time()
                logger.info("[ModelService] %s hot on %s @ %s", model, tier, host_label)
                return {
                    "ready": True,
                    "tier": tier,
                    "host": host_label,
                    "warm_boot_ms": 0,
                }

        # Step 2: Model is cold -- check capacity
        needed_gb = self.estimate_model_size(model)
        if not self.ensure_capacity(needed_gb):
            logger.warning(
                "[ModelService] Not enough RAM for %s on %s (need %.1fGB)",
                model,
                host_label,
                needed_gb,
            )
            return {
                "ready": False,
                "tier": "cold",
                "host": host_label,
                "warm_boot_ms": int(_time.time() * 1000 - start_ms),
            }

        # Step 3: Load the model
        if self.load_model(model):
            elapsed_ms = int(_time.time() * 1000 - start_ms)
            logger.info(
                "[ModelService] %s cold-loaded on %s in %dms",
                model,
                host_label,
                elapsed_ms,
            )
            return {
                "ready": True,
                "tier": "cold",
                "host": host_label,
                "warm_boot_ms": elapsed_ms,
            }

        return {
            "ready": False,
            "tier": "cold",
            "host": host_label,
            "warm_boot_ms": int(_time.time() * 1000 - start_ms),
        }

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
