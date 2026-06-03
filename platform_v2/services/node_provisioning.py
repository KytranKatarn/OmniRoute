"""Hardware-aware node provisioning recommendation (#3731, project #371).

The engine behind the +Add Node wizard: given a node's hardware profile
(CPU/RAM/GPU/VRAM), recommend which Ollama + ComfyUI models it CAN run and which
to download — "what you can, what you can't, what to pull." Pure + testable;
builds on services.model_sizes for footprints and the ComfyUI VRAM tiers
recovered from KB #240991 (_select_best_model_for_node).

Nothing here downloads anything — it returns a plan. The +Add Node flow / OTA
model-pull consumes the plan to actually fetch models (next slice).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.model_sizes import lookup

# Reserve RAM for the OS + node_api + sync containers before sizing models.
HOST_RESERVE_GB = 1.5
# Leave VRAM headroom for KV cache / activations on top of the weight size.
GPU_HEADROOM_GB = 0.7

# Ollama candidates we consider for a node, best→smallest. footprints come from
# services.model_sizes.lookup(). The recommender keeps the best that FIT.
_OLLAMA_AGENT_CANDIDATES = [
    "qwen2.5:7b",  # GPU 7B mid-tier
    "mistral:7b",
    "llama3.1:8b",
    "llama3.2:3b",  # small, CPU-friendly
    "qwen2.5:1.5b",
    "qwen2.5:0.5b",
]
_OLLAMA_EMBED = "nomic-embed-text"  # every node gets embeddings
_OLLAMA_TINY = "qwen2.5:1.5b"  # every node gets a tiny fast agent model
_OLLAMA_CPU_SECONDARY = "llama3.2:3b"  # second model on CPU-only outposts

# ComfyUI checkpoint by FREE VRAM (KB #240991 / _select_best_model_for_node).
_COMFYUI_TIERS = [
    (12.0, "flux1-dev-fp8.safetensors"),
    (8.0, "sd_xl_base_1.0.safetensors"),
    (4.0, "v1-5-pruned-emaonly.ckpt"),
]


@dataclass
class NodeRecommendation:
    tier: str
    can_run_ollama: list = field(default_factory=list)
    cannot_run_ollama: list = field(default_factory=list)
    recommended_ollama: list = field(default_factory=list)
    recommended_comfyui: str | None = None
    notes: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tier": self.tier,
            "can_run_ollama": list(self.can_run_ollama),
            "cannot_run_ollama": list(self.cannot_run_ollama),
            "recommended_ollama": list(self.recommended_ollama),
            "recommended_comfyui": self.recommended_comfyui,
            "notes": list(self.notes),
        }


def _fits(model: str, gpu_available: bool, gpu_vram_gb: float, avail_ram_gb: float) -> bool:
    """Can this node run *model* at all (on GPU or CPU)?"""
    fp = lookup(model)
    gpu_ok = gpu_available and fp.vram_gb > 0 and gpu_vram_gb >= fp.vram_gb + GPU_HEADROOM_GB
    if fp.prefer_gpu:
        return gpu_ok  # 7B+ class is unhappy on CPU — require GPU
    if gpu_ok:
        return True
    return avail_ram_gb >= fp.ram_gb  # CPU-runnable: must fit in RAM


def _classify_tier(gpu_available: bool, gpu_vram_gb: float, ram_gb: float) -> str:
    if gpu_available and gpu_vram_gb >= 12:
        return "gpu-large"
    if gpu_available and gpu_vram_gb >= 8:
        return "gpu-mid"
    if gpu_available and gpu_vram_gb >= 4:
        return "gpu-small"
    if ram_gb >= 24:
        return "cpu-large"
    return "cpu-outpost"


def _comfyui_for(gpu_available: bool, gpu_vram_gb: float) -> str | None:
    if not gpu_available:
        return None
    for threshold, ckpt in _COMFYUI_TIERS:
        if gpu_vram_gb >= threshold:
            return ckpt
    return None


def recommend(
    cpu_cores: int = 0,
    ram_gb: float = 0.0,
    gpu_available: bool = False,
    gpu_vram_gb: float = 0.0,
    gpu_model: str = "",
) -> NodeRecommendation:
    """Return a hardware-aware model plan for a node.

    Splits every Ollama candidate into can/cannot-run, picks a sensible WARM SET
    to pull (a tiny agent + embeddings always; the best-fitting 7B if there's a
    GPU; a CPU secondary on RAM-only outposts), and the right ComfyUI checkpoint
    for the GPU's VRAM (or None for CPU-only).
    """
    ram_gb = float(ram_gb or 0.0)
    gpu_vram_gb = float(gpu_vram_gb or 0.0)
    avail_ram = max(0.0, ram_gb - HOST_RESERVE_GB)
    tier = _classify_tier(gpu_available, gpu_vram_gb, ram_gb)
    rec = NodeRecommendation(tier=tier)

    for m in _OLLAMA_AGENT_CANDIDATES + [_OLLAMA_EMBED]:
        if _fits(m, gpu_available, gpu_vram_gb, avail_ram):
            rec.can_run_ollama.append(m)
        else:
            rec.cannot_run_ollama.append(m)

    # WARM SET: tiny agent + embeddings if they fit (they're small enough for any node).
    warm: list[str] = []
    if _OLLAMA_TINY in rec.can_run_ollama:
        warm.append(_OLLAMA_TINY)
    if _OLLAMA_EMBED in rec.can_run_ollama:
        warm.append(_OLLAMA_EMBED)
    # Best agent model that actually fits (first in best-first order).
    best_agent = next((m for m in _OLLAMA_AGENT_CANDIDATES if m in rec.can_run_ollama), None)
    if best_agent and best_agent not in warm:
        warm.insert(0, best_agent)
    # CPU-only outpost with room: add a 3B secondary for a bit more capability.
    if not gpu_available and _OLLAMA_CPU_SECONDARY in rec.can_run_ollama and _OLLAMA_CPU_SECONDARY not in warm:
        warm.append(_OLLAMA_CPU_SECONDARY)
    rec.recommended_ollama = warm

    rec.recommended_comfyui = _comfyui_for(gpu_available, gpu_vram_gb)

    # Human-readable notes for the wizard UI.
    if not warm:
        rec.notes.append(f"Insufficient RAM ({ram_gb:.0f}GB) — node can't host even a tiny model.")
    if gpu_available:
        rec.notes.append(f"GPU {gpu_model or '?'} {gpu_vram_gb:.0f}GB → tier '{tier}'.")
        if rec.recommended_comfyui:
            rec.notes.append(f"Image gen: pull {rec.recommended_comfyui}.")
        else:
            rec.notes.append("GPU VRAM < 4GB — no ComfyUI checkpoint fits; text-only.")
    else:
        rec.notes.append(f"CPU-only ({cpu_cores}c / {ram_gb:.0f}GB) → tier '{tier}', small models only, no image gen.")
    return rec


def recommend_from_node_row(row: dict) -> NodeRecommendation:
    """Convenience: build a recommendation from a remote_nodes row dict
    (columns: cpu_cores, ram_gb, gpu_available, gpu_vram_gb, gpu_model)."""
    return recommend(
        cpu_cores=int(row.get("cpu_cores") or 0),
        ram_gb=float(row.get("ram_gb") or 0.0),
        gpu_available=bool(row.get("gpu_available")),
        gpu_vram_gb=float(row.get("gpu_vram_gb") or 0.0),
        gpu_model=str(row.get("gpu_model") or ""),
    )
