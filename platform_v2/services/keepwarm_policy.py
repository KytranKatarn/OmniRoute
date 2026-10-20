"""Which hub keep-warm job may touch a model's placement (#7352).

Ollama treats a request with different options as a DIFFERENT runner: ``num_gpu: 0`` is a CPU runner,
not "the same runner, warmed". ``_keep_cockpit_model_warm`` (every 30 min, #4270, written when the
hub's 7B lived on CPU) POSTs A.R.C.H.I.E.'s model with ``num_gpu: 0`` and so REPLACES the GPU runner of
``qwen2.5:7b`` with a CPU one. On this pre-AVX2 Xeon a 7B on CPU is a guaranteed timeout, and the
placement-aware migrate-stranded keep-warm needs two 4-minute strikes to put it back, so the busiest
model spent ~8 min of every 30 on CPU (residency 4.59 GB -> 0.00 GB at 20:38 EDT 2026-10-19, the cockpit
load 17.7s at 20:39:04). It is the #5276 defect again, in the one job that was never fixed.

``_keep_cluster_models_warm`` (every 4 min) already warms these models with the placement decided per
cycle by ``model_service`` (#5276/#5328), so for them the cockpit CPU pin is redundant AND harmful.
"""

from __future__ import annotations

# Hub models the placement-aware cluster keep-warm owns (agent_loop._keep_cluster_models_warm registry).
CLUSTER_WARMED_HUB_MODELS = frozenset({"qwen2.5:7b", "mistral:7b"})


def cockpit_cpu_pin_allowed(model: str) -> bool:
    """False when *model* is owned by the placement-aware cluster keep-warm: the cockpit job must not
    CPU-pin it. Any other cockpit model keeps the legacy behaviour. Never raises."""
    return (model or "").replace(":latest", "") not in CLUSTER_WARMED_HUB_MODELS
