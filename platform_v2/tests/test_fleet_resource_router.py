"""Unit tests for services.fleet_resource_router (#2516 / ADR-555 Phase 1)."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.fleet_resource_router import (
    is_stale,
    score_node_for_model,
    utilization_pct,
    STALE_HEARTBEAT_SECONDS,
)


def _fresh_hb():
    return datetime.now(timezone.utc) - timedelta(seconds=10)


def _stale_hb():
    return datetime.now(timezone.utc) - timedelta(seconds=STALE_HEARTBEAT_SECONDS + 60)


HUB = {
    "node_id": "archie-starbase",
    "node_name": "Archie Starbase",
    "gpu_available": True,
    "gpu_vram_gb": 8.0,
    "ram_gb": 128.0,
    "current_load": 0,
    "max_concurrent": 5,
    "priority": 10,
    "last_heartbeat": _fresh_hb(),
    "extra_capabilities": {},
}

OUTPOST = {
    "node_id": "outpost_us_001",
    "node_name": "outpost-us",
    "gpu_available": False,
    "gpu_vram_gb": None,
    "ram_gb": 7.8,
    "current_load": 1,
    "max_concurrent": 5,
    "priority": 10,
    "last_heartbeat": _fresh_hb(),
    "extra_capabilities": {
        "max_model_gb": 4,
        "inference_type": "cpu",
        "recommended_models": ["qwen2.5:1.5b"],
    },
}


def test_oversized_gpu_model_disqualifies_when_ram_too_small():
    # 14B won't fit a 4GB GPU AND won't fit a small-RAM node → disqualified.
    # (e.g. a 7.8GB outpost-class node; RAM-gate via ram_gb / max_model_gb.)
    tiny = dict(HUB)
    tiny["gpu_vram_gb"] = 4.0
    tiny["ram_gb"] = 8.0
    assert score_node_for_model(tiny, "custom:14b") is None


def test_oversized_gpu_model_cpu_fallback_when_ram_fits():
    # 14B won't fit a 4GB GPU, but the node has ample RAM (hub 128GB / 29GB
    # Starship) → allowed on CPU (cpu_demoted), not disqualified. KB #270009.
    roomy = dict(HUB)
    roomy["gpu_vram_gb"] = 4.0  # too small for 14B VRAM
    demoted = score_node_for_model(roomy, "custom:14b")
    assert demoted is not None and demoted > 0
    # A node that can actually GPU-fit the model must outscore the CPU-demoted one.
    gpu_fits = dict(HUB)
    gpu_fits["gpu_vram_gb"] = 48.0
    assert score_node_for_model(gpu_fits, "custom:14b") > demoted


def test_small_model_fits_outpost_cpu_path():
    # 1.5B model is well under outpost's max_model_gb=4.
    score = score_node_for_model(OUTPOST, "qwen2.5:1.5b")
    assert score is not None and score > 0


def test_large_model_disqualifies_outpost_via_max_model_gb_cap():
    # 7B model needs >5GB; outpost max_model_gb=4 disqualifies it.
    assert score_node_for_model(OUTPOST, "qwen2.5:7b") is None


def test_small_model_scores_outpost_higher_than_hub():
    # CPU-tier model should prefer the CPU node (tier match) — hub is allowed
    # but penalised.
    s_outpost = score_node_for_model(OUTPOST, "qwen2.5:1.5b")
    s_hub = score_node_for_model(HUB, "qwen2.5:1.5b")
    assert s_outpost is not None
    # Hub is GPU node and prefer_gpu=False for 1.5b → tier mismatch.
    if s_hub is not None:
        assert s_outpost > s_hub


def test_large_gpu_model_scores_hub_higher_than_outpost():
    # 7B GPU model fits hub's 8GB VRAM and prefer_gpu=True.
    s_hub = score_node_for_model(HUB, "qwen2.5:7b")
    s_outpost = score_node_for_model(OUTPOST, "qwen2.5:7b")
    assert s_hub is not None and s_hub > 0
    assert s_outpost is None  # outpost cap=4 blocks it


def test_stale_heartbeat_penalised():
    stale = dict(HUB)
    stale["last_heartbeat"] = _stale_hb()
    fresh = score_node_for_model(HUB, "qwen2.5:7b")
    stale_score = score_node_for_model(stale, "qwen2.5:7b")
    assert fresh is not None
    if stale_score is not None:
        assert stale_score < fresh
    # Either way, the stale node should be lower-ranked or disqualified.


def test_loaded_node_scores_lower_than_idle():
    busy = dict(HUB)
    busy["current_load"] = 5  # at capacity
    idle = score_node_for_model(HUB, "qwen2.5:7b")
    busy_score = score_node_for_model(busy, "qwen2.5:7b")
    assert idle is not None
    if busy_score is not None:
        assert busy_score < idle


def test_higher_priority_node_scores_higher():
    high = dict(HUB)
    high["priority"] = 10
    low = dict(HUB)
    low["priority"] = 1
    s_high = score_node_for_model(high, "qwen2.5:7b")
    s_low = score_node_for_model(low, "qwen2.5:7b")
    assert s_high is not None and s_low is not None
    assert s_high > s_low


# ---------------------------------------------------------------------------
# Warm-resident preference (latency-aware routing, refined-B / KB #278809)
# ---------------------------------------------------------------------------


def test_warm_resident_model_scores_higher_by_the_bonus():
    from services.fleet_resource_router import WARM_MODEL_BONUS

    cold = score_node_for_model(HUB, "qwen2.5:7b")
    warm_node = dict(HUB)
    warm_node["_model_warm"] = True
    warm = score_node_for_model(warm_node, "qwen2.5:7b")
    assert cold is not None and warm is not None
    assert warm == cold + WARM_MODEL_BONUS


def test_warm_flag_absent_or_false_is_unchanged():
    # No/False flag → byte-for-byte the old score (backward compat for other callers).
    base = score_node_for_model(HUB, "qwen2.5:7b")
    false_node = dict(HUB)
    false_node["_model_warm"] = False
    assert score_node_for_model(false_node, "qwen2.5:7b") == base


def test_warm_model_can_outrank_a_faster_cold_gpu():
    # A warm model on an RTX 3070 should beat the SAME model COLD on a faster RTX 4090 —
    # the cold-load cost exceeds the per-card speed delta between adjacent tiers.
    fast_cold = dict(HUB)
    fast_cold["gpu_model"] = "RTX 4090"
    warm_slower = dict(HUB)
    warm_slower["gpu_model"] = "RTX 3070"
    warm_slower["_model_warm"] = True
    s_fast_cold = score_node_for_model(fast_cold, "qwen2.5:7b")
    s_warm = score_node_for_model(warm_slower, "qwen2.5:7b")
    assert s_fast_cold is not None and s_warm is not None
    assert s_warm > s_fast_cold


def test_iso_string_heartbeat_is_parsed():
    node = dict(HUB)
    node["last_heartbeat"] = _fresh_hb().isoformat()
    score = score_node_for_model(node, "qwen2.5:7b")
    assert score is not None and score > 0


def test_garbage_heartbeat_string_treated_as_missing():
    node = dict(HUB)
    node["last_heartbeat"] = "not-a-timestamp"
    # is_stale → True, score function should still penalise but not crash.
    assert is_stale(node) is True


def test_empty_inputs_return_none():
    assert score_node_for_model({}, "qwen2.5:7b") is None
    assert score_node_for_model(HUB, "") is None
    assert score_node_for_model(None, "qwen2.5:7b") is None


def test_utilization_pct_zero_load():
    n = dict(HUB)
    n["current_load"] = 0
    n["max_concurrent"] = 5
    assert utilization_pct(n) == 0.0


def test_utilization_pct_at_capacity():
    n = dict(HUB)
    n["current_load"] = 5
    n["max_concurrent"] = 5
    assert utilization_pct(n) == 100.0


def test_utilization_pct_handles_zero_max_concurrent():
    n = dict(HUB)
    n["max_concurrent"] = 0  # avoid div-by-zero
    n["current_load"] = 1
    # Helper guards against zero — should not crash.
    assert utilization_pct(n) == 100.0


def test_is_stale_with_fresh_heartbeat():
    assert is_stale(HUB) is False


def test_is_stale_with_old_heartbeat():
    n = dict(HUB)
    n["last_heartbeat"] = _stale_hb()
    assert is_stale(n) is True


def test_is_stale_with_no_heartbeat():
    n = dict(HUB)
    n["last_heartbeat"] = None
    assert is_stale(n) is True


# ---------------------------------------------------------------------------
# should_dispatch_to_node — Phase 2 wire-in guard
# ---------------------------------------------------------------------------


def test_should_dispatch_allows_well_matched_dispatch():
    from services.fleet_resource_router import should_dispatch_to_node

    allowed, reason = should_dispatch_to_node(HUB, "qwen2.5:7b", enforce=True)
    assert allowed is True
    assert "score=" in reason


def test_should_dispatch_blocks_mismatch_when_enforce_true():
    from services.fleet_resource_router import should_dispatch_to_node

    allowed, reason = should_dispatch_to_node(OUTPOST, "qwen2.5:7b", enforce=True)
    assert allowed is False
    assert "capacity-mismatch" in reason
    assert "qwen2.5:7b" in reason


def test_should_dispatch_warns_but_allows_mismatch_when_enforce_false():
    from services.fleet_resource_router import should_dispatch_to_node

    # Same mismatch, but flag off — proceed with a logged reason.
    allowed, reason = should_dispatch_to_node(OUTPOST, "qwen2.5:7b", enforce=False)
    assert allowed is True
    assert "capacity-mismatch" in reason


def test_should_dispatch_reason_includes_node_label():
    from services.fleet_resource_router import should_dispatch_to_node

    _, reason = should_dispatch_to_node(OUTPOST, "qwen2.5:7b", enforce=True)
    assert "outpost-us" in reason


def test_should_dispatch_unnamed_node_falls_back_to_node_id():
    from services.fleet_resource_router import should_dispatch_to_node

    node = dict(OUTPOST)
    node.pop("node_name")
    _, reason = should_dispatch_to_node(node, "qwen2.5:7b", enforce=True)
    assert "outpost_us_001" in reason
