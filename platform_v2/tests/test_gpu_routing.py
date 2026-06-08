"""GPU performance-aware routing tests (best-hardware, 2026-06-08).

The scorer treated two 8GB GPUs as equal, so a 7B model tied between the slow hub
Quadro M4000 (~130-235s observed) and a fast RTX 3070 (~15-24s) and 80%
home-colocation pinned it to the hub. Now `gpu_perf_weight` ranks by card type so
the fastest fitting GPU wins, next-fastest + hub as failover.
"""

from __future__ import annotations

import pytest

from services.fleet_resource_router import gpu_perf_weight, score_node_for_model


class TestGpuPerfWeight:
    def test_ranking_order(self):
        rtx3070 = gpu_perf_weight("NVIDIA GeForce RTX 3070")
        rtx3050 = gpu_perf_weight("NVIDIA GeForce RTX 3050 Laptop GPU")
        quadro = gpu_perf_weight("NVIDIA Quadro M4000")
        assert rtx3070 > rtx3050 > quadro, (rtx3070, rtx3050, quadro)
        assert quadro < 0.2  # old Maxwell is heavily dispreferred

    def test_3050_matches_before_generic_30series(self):
        # substring order must catch the weak laptop 3050 before generic "rtx 30"
        assert gpu_perf_weight("RTX 3050") == 0.45
        assert gpu_perf_weight("RTX 3070") == 1.0

    def test_unknown_gpu_modest(self):
        assert gpu_perf_weight(None) == 0.3
        assert gpu_perf_weight("") == 0.3
        assert gpu_perf_weight("Some Future Card") == 0.3


def _gpu_node(name, vram, model, **kw):
    n = {
        "node_name": name,
        "gpu_available": True,
        "gpu_vram_gb": vram,
        "gpu_model": model,
        "ram_gb": 32,
        "current_load": 0,
        "max_concurrent": 3,
        "priority": 10,
        "last_heartbeat": None,
    }
    n.update(kw)
    return n


class TestScoreFavoursFasterGpu:
    def test_7b_prefers_rtx_over_quadro(self):
        """Same 8GB VRAM, both fit 7B — the RTX must outscore the hub Quadro."""
        model = "qwen2.5:7b"
        rtx = score_node_for_model(_gpu_node("USS-246", 8, "NVIDIA GeForce RTX 3070"), model)
        quadro = score_node_for_model(_gpu_node("Hub", 8, "NVIDIA Quadro M4000"), model)
        assert rtx is not None and quadro is not None
        assert rtx > quadro, (rtx, quadro)
        # margin must beat the 80% home-colocation rule (home kept if >= 0.8*best)
        assert quadro < rtx * 0.80, f"Quadro {quadro} not below 80% of RTX {rtx} — colocation would pin hub"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
