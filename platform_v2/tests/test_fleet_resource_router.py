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


def test_oversized_gpu_model_disqualifies_undersized_node():
    # 14B model needs ~18GB VRAM; hub only has 8GB.
    big = dict(HUB)
    big["gpu_vram_gb"] = 4.0
    assert score_node_for_model(big, "custom:14b") is None


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
