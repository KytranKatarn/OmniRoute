"""Model size lookup for resource-aware fleet routing (#2516 Phase 1).

Maps Ollama / cloud model names to their resource footprint so the
dispatcher can choose a fleet node that actually fits the model. Owner of
truth for "how big is this model in VRAM and RAM" — used by
fleet_resource_router.score_node_for_model.

Phase 1 status: additive only. Nothing in the live dispatch path consumes
this yet. Phase 2 wires score_node_for_model into smart_router's fleet
tier behind FLEET_RESOURCE_ROUTING_ENABLED.

ADR-555.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelFootprint:
    vram_gb: float
    ram_gb: float
    prefer_gpu: bool


# Seeded from production Modelfiles on hub + Ollama defaults.
# vram_gb is what Ollama reports loaded with default num_ctx.
# ram_gb is process RSS for a CPU-tier load (or zero for GPU-only models).
# prefer_gpu=True means the model is unhappy on CPU even if it fits in RAM.
_TABLE: dict[str, ModelFootprint] = {
    # Tiny — fit anywhere
    "qwen2.5:0.5b": ModelFootprint(1.0, 2.0, False),
    "qwen25-classify": ModelFootprint(1.0, 2.0, False),
    "qwen2.5:1.5b": ModelFootprint(2.0, 3.0, False),
    "llama3.2:3b": ModelFootprint(3.0, 5.0, False),
    "phi3.5": ModelFootprint(3.0, 5.0, False),
    "phi3.5:latest": ModelFootprint(3.0, 5.0, False),
    # 7B/9B GPU class
    "qwen2.5:7b": ModelFootprint(5.5, 8.0, True),
    "mistral:7b": ModelFootprint(5.5, 8.0, True),
    "qwen2.5-coder:7b": ModelFootprint(5.5, 8.0, True),
    "gemma2:9b": ModelFootprint(7.0, 10.0, True),
    "llama3.1:8b": ModelFootprint(6.0, 9.0, True),
    "nomic-embed-text": ModelFootprint(0.5, 1.5, False),
    "arctic-embed:33m": ModelFootprint(0.3, 1.0, False),
    # CPU-tier (large RAM, no VRAM)
    "gemma2-cpu:latest": ModelFootprint(0.0, 16.0, False),
    "qwen3-coder-cpu": ModelFootprint(0.0, 55.0, False),
    "qwen3-coder-cpu:latest": ModelFootprint(0.0, 55.0, False),
    # Cloud (no local resources required — the router still needs a hit)
    "claude-haiku": ModelFootprint(0.0, 0.0, False),
    "claude-sonnet": ModelFootprint(0.0, 0.0, False),
    "claude-opus": ModelFootprint(0.0, 0.0, False),
    # ── MEASURED 2026-09-07 from `ollama list` on the hub's HOST ollama ──────
    # Derivation, applied uniformly: vram = disk + 1.0 (KV cache + activations),
    # ram = disk * 1.8, rounded to 0.5. Existing entries above are LEFT ALONE —
    # they predate this and are close enough; churning them buys nothing.
    #
    # WHY THIS BLOCK EXISTS: 21 of the 28 models in active use were falling
    # through to the `params * 1.3` regex below, which oversizes EVERY model by
    # ~2x — and `can_node_run_model()` reads these numbers to decide where work
    # runs. Measured consequences before this fix:
    #   arctic-embed-cpu   218MB real -> 8.0 guessed  = 37x, banned from CPU nodes
    #   gemma3:12b         8.1GB real -> 15.6 guessed = 2x,  CPU-demoted into
    #                      failure, which is what made translate look "broken"
    #   qwen3-coder:30b    18GB real  -> 39.0 guessed = 2x,  never dispatched
    #   deepseek-coder-v2  8.9GB real -> 20.8 guessed = 2x,  never dispatched
    #   engine/archie:7b   4.7GB real -> 9.1 guessed  = 2x,  excluded from Runabout
    # Two MoE coder models sat pulled-but-unusable for months because of this.
    #
    # ⚠️ A model NOT listed here still gets a fabricated footprint. The fallback
    # now logs a warning naming it — do not ignore that line, add an entry.
    # 7B/8B class
    "qwen3:8b": ModelFootprint(6.5, 9.5, True),
    "aya-expanse:8b": ModelFootprint(6.0, 9.0, True),
    "dolphin3": ModelFootprint(6.0, 9.0, True),
    "dolphin3:latest": ModelFootprint(6.0, 9.0, True),
    "dolphin3-8k:latest": ModelFootprint(6.0, 9.0, True),
    "vivid:latest": ModelFootprint(5.5, 8.0, True),
    "weave:latest": ModelFootprint(5.5, 8.0, True),
    # The archie-code engine model. Same base/size as qwen2.5-coder:7b (4.7GB).
    # lookup() splits on ":", so BOTH the bare path and the tagged form are needed.
    "archie": ModelFootprint(5.5, 8.0, True),
    "archie:7b": ModelFootprint(5.5, 8.0, True),
    "engine/archie": ModelFootprint(5.5, 8.0, True),
    "engine/archie:7b": ModelFootprint(5.5, 8.0, True),
    "alpernae/qwen2.5-auditor": ModelFootprint(5.5, 8.0, True),
    # 12B-16B class — all of these FIT the hub's 12GB TITAN X on one card
    "gemma3:12b": ModelFootprint(9.5, 14.5, True),
    "translategemma:4b": ModelFootprint(4.5, 6.0, True),
    "phi4:14b": ModelFootprint(10.0, 16.5, True),
    "deepseek-coder-v2:16b": ModelFootprint(10.0, 16.0, True),
    # 30B MoE — 18GB exceeds the 12GB largest single card, so it can only run
    # SPANNED across the M4000+TITAN (20GB total). Ollama does span (measured
    # GPULayers 49 split 31/18), but placement does not anticipate the double
    # headroom cost — see .claude/rules/fleet.md.
    "qwen3-coder:30b": ModelFootprint(19.0, 32.5, True),
    # Vision
    "qwen2.5vl:7b": ModelFootprint(7.0, 11.0, True),
    "minicpm-v": ModelFootprint(6.5, 10.0, True),
    "minicpm-v:latest": ModelFootprint(6.5, 10.0, True),
    "moondream": ModelFootprint(2.0, 3.0, False),
    "moondream:latest": ModelFootprint(2.0, 3.0, False),
    # Embeddings — arctic-embed-cpu is 218MB on disk. It was guessed at 8.0/16.0,
    # which is what the "cap of 12 silently kills embeddings" note in fleet.md was
    # built on. That note rests on a fabricated number.
    "arctic-embed-cpu": ModelFootprint(0.3, 1.0, False),
    "arctic-embed-cpu:latest": ModelFootprint(0.3, 1.0, False),
    # CPU-tier variants (no VRAM by construction)
    "mistral-cpu": ModelFootprint(0.0, 8.0, False),
    "mistral-cpu:latest": ModelFootprint(0.0, 8.0, False),
    "minicpm-v-cpu:latest": ModelFootprint(0.0, 10.0, False),
    # Cloud / sentinel model names seen in task_execution_log. Zero local cost —
    # without these they read as 8.0GB local models to anything that looks them up.
    "claude-fable-5": ModelFootprint(0.0, 0.0, False),
    "claude-fable-5-1": ModelFootprint(0.0, 0.0, False),
    "claude-opus-5": ModelFootprint(0.0, 0.0, False),
    "claude-opus-4-7": ModelFootprint(0.0, 0.0, False),
    "claude-opus-4-8": ModelFootprint(0.0, 0.0, False),
    "claude-sonnet-5": ModelFootprint(0.0, 0.0, False),
    "claude-haiku-4-5-20251001": ModelFootprint(0.0, 0.0, False),
    "gpt-5-codex": ModelFootprint(0.0, 0.0, False),
    "codex/gpt-5-codex": ModelFootprint(0.0, 0.0, False),
    "minimax-m2.5:cloud": ModelFootprint(0.0, 0.0, False),
    "qwen3-coder-next:cloud": ModelFootprint(0.0, 0.0, False),
    "bridge-managed": ModelFootprint(0.0, 0.0, False),
    "internal": ModelFootprint(0.0, 0.0, False),
    "batch": ModelFootprint(0.0, 0.0, False),
    "browser": ModelFootprint(0.0, 0.0, False),
}


def lookup(model: str) -> ModelFootprint:
    """Return the footprint for a model name.

    Falls back to a conservative GPU-leaning default for unknown models so
    they route to the hub instead of accidentally landing on outpost-us.
    """
    if not model:
        return ModelFootprint(8.0, 16.0, True)
    if model in _TABLE:
        return _TABLE[model]
    bare = model.split(":")[0]
    if bare in _TABLE:
        return _TABLE[bare]
    # Heuristic: ":Nb" suffix → estimate. bf16 ≈ 2 bytes/param.
    #
    # ⚠️ THIS BRANCH FABRICATES A NUMBER, and can_node_run_model() treats it as
    # a measurement. Measured 2026-09-07: it oversizes real models by ~2x
    # (gemma3:12b 8.1GB real -> 15.6 guessed) and by 37x when there is no ":Nb"
    # to parse at all (arctic-embed-cpu 218MB -> 8.0). That silently disqualified
    # models from nodes that could run them, including two MoE coders that sat
    # pulled-but-never-dispatched for months.
    #
    # It stays as a fail-safe — refusing to place an unknown model at all would
    # be worse — but it now announces itself. If you see this warning, add a
    # MEASURED entry to _TABLE (`ollama list` gives the on-disk size) rather
    # than letting the guess stand.
    m = re.search(r":(\d+(?:\.\d+)?)b", model.lower())
    if m:
        params_b = float(m.group(1))
        vram = round(params_b * 1.3, 1)  # quantized weight + activation overhead
        ram = round(params_b * 2.0, 1)
        logger.warning(
            "[model_sizes] NO MEASURED FOOTPRINT for %r — guessing %.1fGB VRAM / "
            "%.1fGB RAM from the ':%sb' suffix. Placement decisions are being made "
            "on this guess; add a measured _TABLE entry.",
            model,
            vram,
            ram,
            m.group(1),
        )
        return ModelFootprint(vram_gb=vram, ram_gb=ram, prefer_gpu=params_b >= 4)
    logger.warning(
        "[model_sizes] NO MEASURED FOOTPRINT and no parseable size for %r — "
        "defaulting to 8.0GB VRAM / 16.0GB RAM. This is the 37x-overstatement "
        "case (see arctic-embed-cpu); add a measured _TABLE entry.",
        model,
    )
    return ModelFootprint(8.0, 16.0, True)


def known_models() -> Iterable[str]:
    """Iterate model names with explicit entries in the table."""
    return _TABLE.keys()
