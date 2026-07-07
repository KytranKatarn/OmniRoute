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

import re
from dataclasses import dataclass
from typing import Iterable


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
    m = re.search(r":(\d+(?:\.\d+)?)b", model.lower())
    if m:
        params_b = float(m.group(1))
        vram = round(params_b * 1.3, 1)  # quantized weight + activation overhead
        ram = round(params_b * 2.0, 1)
        return ModelFootprint(vram_gb=vram, ram_gb=ram, prefer_gpu=params_b >= 4)
    return ModelFootprint(8.0, 16.0, True)


def known_models() -> Iterable[str]:
    """Iterate model names with explicit entries in the table."""
    return _TABLE.keys()
