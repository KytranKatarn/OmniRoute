"""
model_service.py — Ollama model lifecycle manager for Department HQ.

Handles: load, unload, eviction cascade, RAM budgeting, job tracking.
Uses urllib.request (no requests lib) to match platform patterns.
"""

import json
import logging
import os
import socket  # for socket.timeout — distinguishing "we stopped waiting" from a real failure
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
# VRAM capacity. TWO numbers, because they answer two DIFFERENT questions (#5271).
#
#   _VRAM_TOTAL_GB        — how much VRAM the box has in AGGREGATE. Different models
#                           legitimately live on different cards, so residency budgets
#                           against the SUM.
#   _VRAM_LARGEST_GPU_GB  — the biggest SINGLE card, used as a deliberate SAFETY clamp for
#                           one-model-at-a-time sizing. Spanning IS possible — measured
#                           2026-08-15: Ollama split qwen layers 31/18 across the Quadro
#                           (CC 5.2) and TITAN (CC 6.1), 49/49 offloaded (fleet.md). But a
#                           spanning model consumes headroom on BOTH cards simultaneously
#                           (the #5623 saturation shape), so sizing each model against the
#                           largest single card stays the conservative, correct input.
#
# This replaced a single `_DEFAULT_VRAM_BUDGET_GB = 8.0  # Quadro M4000 full 8 GB`, written
# before the TITAN X 12 GB was installed 2026-07-25. For two days the platform believed it
# had 8 GB while sitting on 20 GB: get_available_vram() under-reported, the per-model fit
# below failed, and load_model() sent `options.num_gpu = 0` — actively FORCING CPU. Measured
# 2026-07-27: both GPUs completely idle while qwen2.5:7b ran 100% CPU with 12 GB free.
#
# Env-overridable so a hardware change is a config edit, not a code edit — a bare constant
# is exactly what went stale. Keep these in step with `remote_nodes.gpu_vram_gb` (largest
# single) and `extra_capabilities.gpu_vram_total_gb` for the hub row. See .claude/rules/fleet.md.
_VRAM_TOTAL_GB = float(os.getenv("ARCHIE_VRAM_TOTAL_GB", "20.0"))  # TITAN 12 + M4000 8
_VRAM_LARGEST_GPU_GB = float(os.getenv("ARCHIE_VRAM_LARGEST_GPU_GB", "12.0"))  # TITAN X

# Multiplier applied to a model's weight size before deciding it fits in free VRAM.
# Covers KV cache + runtime overhead, which the raw weight figure excludes. Deliberately
# generous: over-estimating costs a CPU load (slow but correct), while under-estimating
# means a partial offload or an eviction of the warm set (#5130).
_GPU_FIT_HEADROOM = 1.4

# CPU placement is a viable FALLBACK for small models and a GUARANTEED FAILURE for
# large ones on this box (#5623). The hub CPU is a Xeon E5-2658 v2 (Ivy Bridge,
# pre-AVX2, no FMA): a 7B there cannot finish inside the 240s dispatch deadline, so
# "degrade to CPU" is not degradation, it is a timeout with extra steps.
#
# Measured 2026-08-15: VRAM headroom hit 0.0 GB, qwen2.5:7b was placed on CPU for
# ~4 minutes, and EVERY fact_check dispatched in that window died on
# "timeout after 240s ... did not return for model=qwen2.5:7b" — 89% failure for the
# hour against a 12% 24h baseline. It recovered only when placement returned to GPU.
#
# The threshold sits between the models that genuinely run on CPU (qwen2.5:1.5b
# ~1.3 GB, llama3.2:3b ~2.6 GB — the whole CPU-outpost tier depends on this staying
# true) and the 7B+ class (~4.7 GB and up) that does not. Raw estimate_model_size,
# NOT the _GPU_FIT_HEADROOM-inflated figure — this is about compute, not fit.
_CPU_VIABLE_MAX_GB = float(os.getenv("ARCHIE_CPU_VIABLE_MAX_GB", "4.0"))

# Models required by the Consciousness / embedding pipeline — never evict first
CONSCIOUSNESS_MODELS = {"arctic-embed-cpu:latest", "mistral:7b"}

# Per-HOST model-load serialisation. The original SINGLE global lock serialised
# EVERY warm-boot fleet-wide, so one slow remote cold-load (e.g. ~84s on a CPU
# node) blocked the hub + every Starship — the systemic dispatch stall. The only
# invariant that must serialise is "one concurrent load per physical device"
# (CUDA graph_reserve fragmentation on the hub's single GPU); that is per-HOST,
# not global. Separate hosts (hub / each Starship / each outpost / Citadel) now
# load concurrently. Keyed by the SAME host_label ensure_model_ready computes.
import threading as _threading

_MODEL_LOAD_LOCKS: dict = {}
_MODEL_LOAD_LOCKS_GUARD = _threading.Lock()


def _get_model_load_lock(host_label):
    """Return (creating on first use) the per-host model-load lock for *host_label*."""
    lk = _MODEL_LOAD_LOCKS.get(host_label)
    if lk is None:
        with _MODEL_LOAD_LOCKS_GUARD:
            lk = _MODEL_LOAD_LOCKS.get(host_label)
            if lk is None:
                lk = _threading.Lock()
                _MODEL_LOAD_LOCKS[host_label] = lk
    return lk


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
        # Env-var fallback chain — OLLAMA_HOST is canonical for this module,
        # but OLLAMA_URL/OLLAMA_PRIMARY are the names used in .mcp.json and
        # platform docs. Accept all three so a host-process consumer (MCP
        # server) doesn't silently fall through to the Docker-only default.
        # Per-node dispatch (orchestration → remote_nodes) passes target_host
        # explicitly to ensure_model_ready() and bypasses this fallback.
        raw_host = (
            ollama_host
            or os.getenv("OLLAMA_HOST")
            or os.getenv("OLLAMA_URL")
            or os.getenv("OLLAMA_PRIMARY")
            or _DEFAULT_OLLAMA_HOST
        )
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
        """Return GB of GPU VRAM still free, AGGREGATED across every card."""
        if not self._is_cache_fresh():
            self._refresh_cache()
        used = sum(m.get("size_vram", 0) / (1024**3) for m in self._loaded_cache)
        return max(0.0, _VRAM_TOTAL_GB - used)

    def get_gpu_fit_budget(self) -> float:
        """
        GB of VRAM a SINGLE model may occupy right now (#5271).

        Two independent ceilings, so take the lower:
          * aggregate free  — cannot use VRAM that other models already hold
          * largest card    — a deliberate safety clamp for one-model-at-a-time
                              sizing. Spanning across the mixed-CC 6.1/5.2 cards
                              IS possible (proven 2026-08-15: Ollama split 31/18
                              layers across Quadro+TITAN), but a spanning model
                              eats headroom on BOTH cards at once — the #5623
                              saturation shape — so clamping each model to the
                              biggest device remains the conservative input.

        Using aggregate alone would claim a 16 GB model fits on a 12 GB card.
        Using the largest card alone would ignore VRAM already consumed.

        WORST-CASE PLACEMENT (F.O.R.G.E. review of PR #2500). Ollama's /api/ps
        reports size_vram per MODEL but never says WHICH card holds it, so the
        residents' distribution is unknowable here. Naively subtracting only
        from the aggregate over-reports whenever they are concentrated on the
        big card: TITAN 12 + Quadro 8 with 8 GB resident ON THE TITAN gives
        aggregate free 12 and would hand out a 12 GB budget, while the TITAN
        actually has 4 GB free and the Quadro 8 — so a 10 GB model would be told
        it fits when NEITHER card can hold it.

        So assume the pessimal distribution: every resident byte sits on the
        largest card. This deliberately UNDER-reports when they are really on
        the smaller card, and that is the correct direction to be wrong in —
        per _GPU_FIT_HEADROOM above, over-estimating costs a CPU load (slow but
        correct) whereas under-estimating means a partial offload or an eviction
        of the warm set.

        Removing the guesswork needs real per-card telemetry — task #5273.
        """
        used = max(0.0, _VRAM_TOTAL_GB - self.get_available_vram())
        largest_card_free = max(0.0, _VRAM_LARGEST_GPU_GB - used)
        return min(self.get_available_vram(), largest_card_free)

    @staticmethod
    def _record_placement(**kw) -> None:
        """Best-effort persistence of a placement decision (#5273 Phase 1).

        Deliberately a LAZY import: this module imports no DB machinery (json,
        logging, os, socket, time, urllib only) and must keep it that way — it is
        a low-level Ollama HTTP client, and a module-level `from database import`
        here would both add a dependency it has never had and invite an import
        cycle. `services.placement_telemetry.record_placement` owns the write and
        never raises; this wrapper only guards the IMPORT.

        Telemetry must never break placement — but it must not go quiet either,
        so an import failure warns rather than passing silently (the same reason
        the sink warns instead of using logger.debug: an observer that fails
        invisibly is 'unmonitored while APPEARING monitored').
        """
        try:
            from services.placement_telemetry import record_placement

            record_placement(**kw)
        except Exception as exc:  # never break placement
            logger.warning("model_service: placement telemetry unavailable: %s", exc)

    def gpu_placement_options(self, model: str) -> Dict:
        """Ollama ``options`` fragment placing *model* on the HUB: ``{}`` lets
        Ollama use the GPUs, ``{"num_gpu": 0}`` pins it to CPU.

        THE single placement decision point, with one log line per call
        (#5276). load_model and the agent-loop keep-warm each hardcoded their
        own answer before this; the 4-minute cluster keep-warm's unconditional
        ``num_gpu=0`` overrode every correct placement with a fresh 30m CPU
        keep-alive — measured 2026-07-27 18:40: both GPUs at ~0 MiB while
        qwen2.5:7b AND mistral:7b sat 100% CPU with fresh keep-alives.

        Rules, in order:
          1. Already resident holding VRAM → ``{}`` (refresh in place). Without
             this, two GPU-resident 7Bs would each shrink the OTHER's fit
             budget below threshold and the pin would demote them in
             oscillation. Evictions stay owned by the ComfyUI VRAM swap.
          2. ComfyUI container running → CPU. Its SDXL VRAM is a separate
             process that /api/ps cannot see, so the fit budget over-reports
             the whole time image gen is awake. (The old unconditional pin
             protected this by accident; this keeps it deliberate.)
          3. Fits the dual-card budget (``get_gpu_fit_budget``) → GPU.
          4. Otherwise, or on ANY error → CPU. Warmth is preserved either way.

        RECOVERY CAVEAT (#5328, measured 2026-07-27 20:02-20:10): a FRESH load
        with ``{}`` auto-places on GPU, but Ollama does NOT reload a LIVE
        runner when a warm request merely OMITS num_gpu — three gpu-eligible
        decisions in a row left qwen2.5:7b at 100% CPU because its dispatch
        volume never lets the runner expire. A stranded runner must be
        explicitly unloaded first; the keep-warm does that (see
        ``resident_vram_gb`` + the stranded-migration branch in
        ``_keep_cluster_models_warm``).
        """
        try:
            if not self._is_cache_fresh():
                self._refresh_cache()
            resident_vram_gb = 0.0
            for m in self._loaded_cache:
                if m.get("name") in (model, f"{model}:latest"):
                    resident_vram_gb = m.get("size_vram", 0) / (1024**3)
                    break
            if resident_vram_gb > 0:
                logger.info(
                    "model_service: placement %s -> gpu (already resident, %.1f GB VRAM)",
                    model,
                    resident_vram_gb,
                )
                self._record_placement(
                    model=model,
                    decision="gpu",
                    reason="resident",
                    resident_vram_gb=round(resident_vram_gb, 2),
                )
                return {}
            if _comfyui_container_running():
                logger.info(
                    "model_service: placement %s -> cpu (ComfyUI awake — GPUs reserved for image gen)",
                    model,
                )
                self._record_placement(model=model, decision="cpu", reason="comfyui_reserved")
                return {"num_gpu": 0}
            needed = self.estimate_model_size(model) * _GPU_FIT_HEADROOM
            budget = self.get_gpu_fit_budget()
            if budget >= needed:
                logger.info(
                    "model_service: placement %s -> gpu (budget %.1f GB >= needed %.1f GB)",
                    model,
                    budget,
                    needed,
                )
                self._record_placement(
                    model=model,
                    decision="gpu",
                    reason="budget_fit",
                    budget_gb=round(budget, 2),
                    needed_gb=round(needed, 2),
                )
                return {}
            logger.info(
                "model_service: placement %s -> cpu (budget %.1f GB < needed %.1f GB)",
                model,
                budget,
                needed,
            )
            self._record_placement(
                model=model,
                decision="cpu",
                reason="budget_short",
                budget_gb=round(budget, 2),
                needed_gb=round(needed, 2),
            )
            return {"num_gpu": 0}
        except Exception as exc:
            logger.warning("model_service: placement %s -> cpu (VRAM state unknown: %s)", model, exc)
            # The fail-open branch, and the highest-value row in the table: an
            # exception-driven CPU demotion is indistinguishable from a deliberate
            # one in the logs, and for a 7B on this pre-AVX2 Xeon CPU is a
            # GUARANTEED deadline failure, not a degraded path (#5623).
            self._record_placement(model=model, decision="cpu", reason="vram_unknown", detail=str(exc)[:500])
            return {"num_gpu": 0}

    def cpu_placement_is_viable(self, model: str) -> bool:
        """Can *model* actually SERVE from the hub CPU, or is CPU a guaranteed timeout?

        `gpu_placement_options` answers "where does this go" and falls back to CPU on
        every uncertain input — correct, because for a small model CPU is a real
        degraded path and warmth is preserved. For a 7B+ on this pre-AVX2 Xeon it is
        not degradation at all: the dispatch cannot finish inside 240s, so the work is
        dead the moment it is placed (#5623).

        This is deliberately about COMPUTE, not fit: it uses the raw size estimate,
        not the `_GPU_FIT_HEADROOM`-inflated figure that `get_gpu_fit_budget` compares.
        Fail-safe VIABLE on an unknown size — refusing to load a model we cannot size
        would be a worse failure than trying it.
        """
        try:
            size_gb = self.estimate_model_size(model)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("model_service: size unknown for %s (%s) — treating CPU as viable", model, exc)
            return True
        if not size_gb:
            return True
        return size_gb <= _CPU_VIABLE_MAX_GB

    def resident_vram_gb(self, model: str) -> Optional[float]:
        """VRAM held by *model* in GB, or None if it is not resident at all.

        ``0.0`` means resident but fully on CPU — the stranded case the
        keep-warm migrates (#5328). Matches Ollama names with or without the
        ``:latest`` tag, same as gpu_placement_options.
        """
        if not self._is_cache_fresh():
            self._refresh_cache()
        for m in self._loaded_cache:
            if m.get("name") in (model, f"{model}:latest"):
                return m.get("size_vram", 0) / (1024**3)
        return None

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
            # #5271: ask whether THIS model fits, not whether the GPU is nearly empty.
            # The old rule was `available >= budget * 0.9`, which scales with the budget:
            # correcting 8 -> 20 GB would have raised the bar to 18 GB free and pinned
            # even MORE work to CPU. A proportional threshold can never express "a 4.2 GB
            # model fits in 12 GB while a 3 GB model is already resident".
            vram_ok = needed_gb <= 4.0 or self.get_gpu_fit_budget() >= needed_gb * _GPU_FIT_HEADROOM
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

    # Hub big-model tier: models too large to co-reside on the 8GB GPU alongside
    # the GPU hot model (qwen2.5:7b). On the HUB these are pinned to CPU
    # (options.num_gpu=0) so they load into the 128GB RAM instead of fighting for
    # ~3GB of free VRAM and failing ("no result"/cold-tier timeouts). Demand-driven:
    # they load on dispatch when the owning agent is working and drain via
    # keep_alive when idle. NOTE: load_model() is HUB-only (uses self.ollama_host),
    # so Outpost/Starship node loads are unaffected — those keep their GPU placement.
    # qwen2.5:7b is intentionally EXCLUDED (it is the GPU hot model). KB #270009.
    _HUB_CPU_TIER = {
        "mistral:7b",
        "gemma3:12b",
        "dolphin3:latest",
        "qwen2.5-coder:7b",
        "phi4:14b",
        "deepseek-coder-v2:16b",
        "qwen3-coder-cpu:latest",
        "qwen2.5vl:7b",
    }

    def load_model(self, model: str, ollama_url: Optional[str] = None) -> bool:
        """Warm-boot *model* (sanctioned model-lifecycle path, called by
        ``ensure_model_ready`` — the warmboot orchestrator, ADR-013 exception).

        Warms the HUB by default, or a REMOTE NODE when *ollama_url* is given.
        Warming the actual target node is the fix for the node cold-load bug:
        a queued dispatch routed to a node must hit a warm model, else it
        cold-loads inside the dispatch call and times out as 'no result'.
        Previously this only ever warmed the hub, so node targets stayed cold.

        Hub big-model tier (``_HUB_CPU_TIER``) is pinned to CPU via
        ``options.num_gpu=0`` so it loads into RAM rather than evicting / failing
        to fit on the 8GB GPU. Nodes manage their own placement, so the pin is
        hub-only.
        """
        base = ollama_url or self.ollama_host
        try:
            url = f"{base}/api/" + "generate"
            body = {"model": model, "keep_alive": "10m", "prompt": ""}
            if ollama_url is None:
                # Conditional CPU pin: big models yield the GPUs when VRAM is
                # tight (the unconditional pin starved code_review on a busy
                # CPU beside an idle GPU, #5130) but are no longer forced off
                # an idle card. Decision + telemetry are centralised in
                # gpu_placement_options (#5276), shared with the agent-loop
                # keep-warm so no caller can override another's placement.
                placement = self.gpu_placement_options(model)

                # #5623 — REFUSE rather than load a big model onto a CPU that cannot
                # serve it. placement == {"num_gpu": 0} means the GPU had no room;
                # for a 7B+ on this pre-AVX2 Xeon that is not a degraded path, it is a
                # guaranteed 240s timeout for every dispatch until VRAM frees.
                # Returning False makes ensure_model_ready report not-ready, which the
                # dispatcher ALREADY turns into model_not_ready=True → immediate
                # escalation to the next tier (a fleet node that HAS the GPU). Reusing
                # that existing signal is the whole fix; no new plumbing.
                #
                # ⚠️ This check is deliberately OUTSIDE the `_HUB_CPU_TIER` test. The
                # model that actually caused the #5623 outage — qwen2.5:7b — is NOT in
                # that set, so a guard nested inside it would never have fired for the
                # very incident it was written for. The tier governs whether the CPU
                # PIN is carried through (unchanged below); viability governs whether
                # we are willing to load at all.
                if placement.get("num_gpu") == 0 and not self.cpu_placement_is_viable(model):
                    logger.warning(
                        "model_service: REFUSING hub CPU load of %s — too large to serve on a "
                        "pre-AVX2 CPU (>%.1f GB); deferring so the caller escalates/queues (#5623)",
                        model,
                        _CPU_VIABLE_MAX_GB,
                    )
                    return False

                # Unchanged: only the big-model tier carries the pin into the request.
                if placement and model in self._HUB_CPU_TIER:
                    body["options"] = placement
            payload = json.dumps(body).encode()
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
            logger.info("model_service: loaded %s on %s", model, base)
            return True
        except Exception as exc:
            # A TIMEOUT MEANS WE STOPPED WAITING — NOT THAT THE LOAD FAILED.
            #
            # Ollama serialises per model (NUM_PARALLEL=1), so a warm request issued
            # while the host is mid-dispatch queues behind it. On a node averaging
            # ~116s per dispatch that wait can exceed our bound and expire client-side
            # while the load goes on to succeed moments later.
            #
            # Reporting that as "failed" makes a HEALTHY node look broken: it is exactly
            # what produced the (wrong) "node 246 cannot load qwen2.5:7b" conclusion,
            # when the model was in fact resident on its GPU and the node had served
            # 33/33 dispatches on it (#5133). Same status-misreports-a-healthy-system
            # shape this module keeps hitting.
            #
            # So on timeout, ask the host what is ACTUALLY resident before judging —
            # via the existing _fetch_ps helper, no new call path.
            if isinstance(exc, socket.timeout) or "timed out" in str(exc).lower():
                try:
                    loaded = self._fetch_ps(base) or []
                    if any(m.get("name") == model for m in loaded):
                        self._last_used[model] = time.time()
                        self._cache_time = 0.0
                        logger.info(
                            "model_service: %s on %s exceeded the load wait but IS resident — "
                            "reporting success (client timeout, not a load failure)",
                            model,
                            base,
                        )
                        return True
                except Exception:
                    pass  # cannot confirm -> fall through to the honest 'not ready'
                logger.warning(
                    "model_service: load %s on %s exceeded the wait and is NOT yet resident — "
                    "it may still be loading; treating as not-ready (NOT a node failure)",
                    model,
                    base,
                )
                return False
            logger.error("model_service: load %s on %s failed — %s", model, base, exc)
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

    def ensure_ready(self, model: str, needed_gb: float = None) -> bool:
        """
        Ensure *model* is loaded and ready.

        Steps: check loaded → ensure capacity → load.
        Returns True on success.

        ``needed_gb`` defaults to the model's estimated RAM size (e.g.
        arctic-embed-cpu = 0.3 GB) rather than a flat 8 GB — otherwise tiny
        models like the CPU embedder get RAM-gated off the 8 GB outposts.
        """
        if self.is_model_loaded(model):
            self._last_used[model] = time.time()
            return True
        if needed_gb is None:
            needed_gb = self.estimate_model_size(model)
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

        # Per-HOST serialisation (not global): only loads on the SAME physical
        # device serialise. The hub's single GPU still loads one model at a time
        # (CUDA graph_reserve), but a slow remote cold-load no longer blocks the
        # hub or other nodes. host_label MUST match _ensure_model_ready_locked.
        if target_host:
            _h = target_host.get("hostname", "unknown")
            _p = target_host.get("port", 11434)
        else:
            _h = self.ollama_host.replace("http://", "").replace("https://", "")
            _p = 11434
        host_label = f"{_h}:{_p}" if ":" not in str(_h) else str(_h)
        load_lock = _get_model_load_lock(host_label)

        # Wait up to 150s for any concurrent load ON THIS HOST to finish.
        if not load_lock.acquire(timeout=150):
            logger.warning("model_service: model_load_lock timeout waiting to load %s on %s", model, host_label)
            return {"ready": False, "tier": "cold", "host": str(target_host), "warm_boot_ms": 150000}

        try:
            return self._ensure_model_ready_locked(agent_name, model, target_host, start_ms)
        finally:
            load_lock.release()

    def _ensure_model_ready_locked(self, agent_name, model, target_host, start_ms):
        """Actual ensure_model_ready logic — called while the per-host load lock is held."""
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

                # #5623 — THE RESIDUAL HALF. The load-path guard (see gpu_placement_options
                # / the `cpu_placement_is_viable` check in the load request) refuses to LOAD
                # a big model onto the hub CPU. It says nothing about one that is ALREADY
                # resident there, and in that case nothing is loading, so that guard never
                # runs: the model is reported "hot", the dispatcher serves it, and every
                # request dies on the 240s deadline.
                #
                # Measured 2026-08-16 while reviewing PR #2614:
                #   [ModelService] qwen2.5:7b hot on cpu @ host.docker.internal:11434
                #   [BridgeDispatcher] model qwen2.5:7b timed out for cap=code_review
                # i.e. the exact #5623 outage signature, reached by a path the original
                # fix did not cover. A stranded CPU-resident 7B is migrated back by the
                # keep-warm (#5328); until it is, serving from it is a guaranteed failure,
                # so we report not-ready and let the caller escalate to a node that has a
                # GPU — reusing `model_not_ready`, no new plumbing (same as the load guard).
                #
                # ⚠️ HUB ONLY (`target_host is None`), mirroring the load guard's
                # `ollama_url is None` scoping. Starship-246 DELIBERATELY keeps qwen2.5:7b
                # warm on its own CPU, and that is not the hub's pre-AVX2 Xeon E5-2658 v2.
                # An unscoped check would refuse a placement that works fine — the same
                # shape as the hub-RAM check below that "wrongly gated node warm-boots".
                if target_host is None and tier == "cpu" and not self.cpu_placement_is_viable(model):
                    logger.warning(
                        "[ModelService] %s is resident but CPU-ONLY on the hub — reporting "
                        "NOT ready. A >%.1f GB model cannot finish inside the dispatch "
                        "deadline on a pre-AVX2 CPU, so serving it is a timeout with extra "
                        "steps (#5623). Caller escalates/queues; keep-warm migrates it back.",
                        model,
                        _CPU_VIABLE_MAX_GB,
                    )
                    return {
                        "ready": False,
                        "tier": "cpu_nonviable",
                        "host": host_label,
                        "warm_boot_ms": 0,
                    }

                logger.info("[ModelService] %s hot on %s @ %s", model, tier, host_label)
                return {
                    "ready": True,
                    "tier": tier,
                    "host": host_label,
                    "warm_boot_ms": 0,
                }

        # Step 2: Model is cold -- check capacity. Hub-only: ensure_capacity
        # inspects the HUB's RAM, which is meaningless for a remote node. A node
        # self-manages its own memory and will simply fail the load below if it
        # can't fit the model (-> ready=False -> bounded re-queue). Running the
        # hub check for a node target wrongly gated node warm-boots.
        if target_host is None:
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

        # Step 3: Warm-boot the model ON THE TARGET HOST (the node when
        # target_host is set, else the hub). Loading on the hub for a node
        # target would leave the node cold -> dispatch then fails 'no result'.
        if self.load_model(model, ollama_url if target_host else None):
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


def _comfyui_container_running() -> bool:
    """True when the archie_comfyui container is up.

    Used by gpu_placement_options: ComfyUI's SDXL VRAM lives in a separate
    process /api/ps cannot see, so while the container is running the GPUs are
    treated as claimed by image generation and no new LLM is admitted onto
    them. False on ANY doubt — a docker hiccup must not permanently pin the
    hot models to CPU (the idle-stop observer reaps ComfyUI within its idle
    window, bounding the contention the other way).
    """
    try:
        from services.comfyui_lifecycle import _get_container

        container = _get_container()
        if container is None:
            return False
        container.reload()
        return getattr(container, "status", "") == "running"
    except Exception:
        return False


def hub_gpu_placement(model: str) -> Dict:
    """Module-level convenience for out-of-process callers (the agent-loop
    keep-warm jobs): the singleton's placement decision for *model* on the hub."""
    return get_model_service().gpu_placement_options(model)
