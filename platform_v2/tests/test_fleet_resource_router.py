"""Unit tests for services.fleet_resource_router (#2516 / ADR-555 Phase 1)."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.fleet_resource_router import (
    can_node_run_model,
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


# ---------------------------------------------------------------------------
# Concurrent-heavy cap (latency-aware routing, refined-B slice 2)
# ---------------------------------------------------------------------------


def test_heavy_model_over_concurrency_cap_is_penalised():
    from services.fleet_resource_router import HEAVY_CONCURRENCY_CAP, HEAVY_OVERCAP_PENALTY

    base = score_node_for_model(HUB, "qwen2.5:7b")
    over = dict(HUB)
    over["_heavy_inflight"] = HEAVY_CONCURRENCY_CAP  # at/over cap
    over_score = score_node_for_model(over, "qwen2.5:7b")
    assert base is not None and over_score is not None
    assert abs(over_score - (base - HEAVY_OVERCAP_PENALTY)) < 1e-9


def test_heavy_model_under_cap_not_penalised():
    from services.fleet_resource_router import HEAVY_CONCURRENCY_CAP

    base = score_node_for_model(HUB, "qwen2.5:7b")
    under = dict(HUB)
    under["_heavy_inflight"] = HEAVY_CONCURRENCY_CAP - 1
    assert score_node_for_model(under, "qwen2.5:7b") == base


def test_small_cpu_model_not_subject_to_heavy_cap():
    # prefer_gpu=False models don't contend for the GPU → the cap never applies,
    # even with many heavy jobs in flight on the node.
    base = score_node_for_model(OUTPOST, "qwen2.5:1.5b")
    loaded = dict(OUTPOST)
    loaded["_heavy_inflight"] = 99
    assert score_node_for_model(loaded, "qwen2.5:1.5b") == base


def test_heavy_inflight_absent_is_unchanged():
    base = score_node_for_model(HUB, "qwen2.5:7b")
    n = dict(HUB)
    n.pop("_heavy_inflight", None)
    assert score_node_for_model(n, "qwen2.5:7b") == base


# ---------------------------------------------------------------------------
# Observed-latency signal (latency-aware routing, refined-B slice 3)
# ---------------------------------------------------------------------------


def test_observed_latency_adj_bounds_and_midpoint():
    from services.fleet_resource_router import (
        observed_latency_adj,
        LATENCY_FAST_BONUS,
        LATENCY_SLOW_PENALTY,
        LATENCY_SLOW_RATIO,
    )

    assert observed_latency_adj(None) == 0.0  # no data → no adjustment
    assert observed_latency_adj("abc") == 0.0  # invalid → no adjustment
    assert observed_latency_adj(1.0) == LATENCY_FAST_BONUS  # fastest node
    assert observed_latency_adj(0.5) == LATENCY_FAST_BONUS  # clamped at fastest
    assert observed_latency_adj(LATENCY_SLOW_RATIO) == -LATENCY_SLOW_PENALTY
    assert observed_latency_adj(LATENCY_SLOW_RATIO + 1) == -LATENCY_SLOW_PENALTY
    mid = 1.0 + (LATENCY_SLOW_RATIO - 1.0) / 2.0  # halfway → ~0
    assert abs(observed_latency_adj(mid)) < 1e-9


def test_fast_node_outscores_slow_node_by_latency():
    fast = dict(HUB)
    fast["_latency_ratio"] = 1.0
    slow = dict(HUB)
    slow["_latency_ratio"] = 2.0
    s_fast = score_node_for_model(fast, "qwen2.5:7b")
    s_slow = score_node_for_model(slow, "qwen2.5:7b")
    assert s_fast is not None and s_slow is not None
    assert s_fast > s_slow


def test_latency_ratio_absent_is_unchanged():
    base = score_node_for_model(HUB, "qwen2.5:7b")
    n = dict(HUB)
    n["_latency_ratio"] = None
    assert score_node_for_model(n, "qwen2.5:7b") == base


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


# ---------------------------------------------------------------------------
# Ingress-only node hard exclusion (2026-08-21 fleet rebalance) — Beacon has
# no Ollama and must NEVER be a dispatch candidate, even if a caller builds a
# node dict directly (bypassing find_best_node_for_model's SQL-level filter).
# ---------------------------------------------------------------------------


def test_ollama_unavailable_node_disqualified_even_when_capacity_fits():
    ingress_only = dict(HUB)
    ingress_only["ollama_available"] = False
    # Would otherwise fit easily (small model, huge RAM) — must still be excluded.
    assert can_node_run_model(ingress_only, "qwen2.5:1.5b") is False
    assert score_node_for_model(ingress_only, "qwen2.5:1.5b") is None


def test_ollama_available_absent_is_unaffected():
    # Fail-open: every existing test node omits this key — must stay unchanged.
    assert "ollama_available" not in HUB
    assert can_node_run_model(HUB, "qwen2.5:7b") is True
    assert score_node_for_model(HUB, "qwen2.5:7b") is not None


def test_ollama_available_true_is_unaffected():
    node = dict(HUB)
    node["ollama_available"] = True
    assert can_node_run_model(node, "qwen2.5:7b") is True
    assert score_node_for_model(node, "qwen2.5:7b") == score_node_for_model(HUB, "qwen2.5:7b")


# ---------------------------------------------------------------------------
# Fleet-wide model hardware blocklist (2026-08-21 fleet rebalance) — a model
# that fits NO node's GPU in this fleet (e.g. gemma3:12b: 15.6GB vs a 12GB
# largest card) should not be scheduled anywhere, not just penalised. Backed
# by a DB-cached, platform_settings-tunable accessor; tests monkeypatch the
# accessor directly so they never touch the live database.
# ---------------------------------------------------------------------------


def test_blocklisted_model_disqualifies_gpu_node(monkeypatch):
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "model_hardware_blocklist", lambda: frozenset({"gemma3:12b"}))
    assert can_node_run_model(HUB, "gemma3:12b") is False
    assert score_node_for_model(HUB, "gemma3:12b") is None


def test_blocklisted_model_disqualifies_cpu_outpost_too(monkeypatch):
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "model_hardware_blocklist", lambda: frozenset({"some-cpu-model:3b"}))
    assert can_node_run_model(OUTPOST, "some-cpu-model:3b") is False
    assert score_node_for_model(OUTPOST, "some-cpu-model:3b") is None


def test_blocklist_normalizes_the_latest_suffix(monkeypatch):
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "model_hardware_blocklist", lambda: frozenset({"gemma3:12b"}))
    assert can_node_run_model(HUB, "gemma3:12b:latest") is False


def test_empty_blocklist_changes_nothing(monkeypatch):
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "model_hardware_blocklist", lambda: frozenset())
    # gemma3:12b is CPU-demoted on the hub (128GB RAM) when nothing blocks it.
    assert score_node_for_model(HUB, "gemma3:12b") is not None


def test_unrelated_model_unaffected_by_blocklist(monkeypatch):
    import services.fleet_resource_router as frr

    monkeypatch.setattr(frr, "model_hardware_blocklist", lambda: frozenset({"gemma3:12b"}))
    assert score_node_for_model(HUB, "qwen2.5:7b") is not None


def test_model_hardware_blocklist_default_is_empty():
    # The compiled-in fallback is EMPTY on purpose. It briefly held gemma3:12b, justified
    # by a 56% FLEET-WIDE average — which split by node is hub 52% vs USS-246 95% over
    # 2,918 runs. A fleet-wide block therefore deleted the good path and kept the bad one.
    # A wrong block silently removes capacity, so an unproven blocklist must fail OPEN.
    import services.fleet_resource_router as frr

    assert frr._MODEL_BLOCKLIST_DEFAULT == frozenset()


# ---------------------------------------------------------------------------
# Per-node model allowlist (#6714)
#
# The FLEET-WIDE blocklist is the wrong tool for a per-node problem: mistral:7b
# and qwen2.5:7b both run fine on the hub, so blocking either there deletes the
# good path (the 2026-08-21 gemma3 reversal is the precedent). This is the
# per-node analogue, and it lives in can_node_run_model because that one
# function gates BOTH dispatch routing AND the warm-up drain — the two arms of
# the ratchet that put a removed model back on USS-246 within 45 minutes.
# ---------------------------------------------------------------------------

STARSHIP_246 = {
    "node_id": "starship_76583490e36955ab",
    "node_name": "Starship - Defiant - USS-246",
    "gpu_available": True,
    "gpu_vram_gb": 8.0,
    "ram_gb": 29.4,
    "current_load": 0,
    "max_concurrent": 4,
    "priority": 10,
    "last_heartbeat": _fresh_hb(),
    "extra_capabilities": {},
}


def _with_allowlist(node, allowlist):
    clone = dict(node)
    extra = dict(clone.get("extra_capabilities") or {})
    if allowlist is None:
        extra.pop("model_allowlist", None)
    else:
        extra["model_allowlist"] = allowlist
    clone["extra_capabilities"] = extra
    return clone


def test_absent_allowlist_restricts_nothing():
    """Fail-OPEN, like the fleet-wide blocklist. A node with no allowlist behaves
    exactly as before — this is what keeps the change inert for every other node."""
    node = _with_allowlist(STARSHIP_246, None)
    assert can_node_run_model(node, "qwen2.5:7b") is True
    assert can_node_run_model(node, "qwen2.5:1.5b") is True


def test_allowlisted_model_still_runs():
    node = _with_allowlist(STARSHIP_246, ["qwen2.5:7b"])
    assert can_node_run_model(node, "qwen2.5:7b") is True


def test_non_allowlisted_model_is_refused_even_though_it_physically_fits():
    """The whole point. qwen2.5:1.5b fits an 8GB card trivially, so capacity can
    never refuse it — the GPU branch returns True before max_model_gb is even
    read. Only the allowlist can express 'this node serves one model'."""
    node = _with_allowlist(STARSHIP_246, ["qwen2.5:7b"])
    assert can_node_run_model(_with_allowlist(STARSHIP_246, None), "qwen2.5:1.5b") is True
    assert can_node_run_model(node, "qwen2.5:1.5b") is False


def test_empty_allowlist_is_treated_as_unset_not_as_deny_all():
    """An empty list is far more likely to be a config accident than an intent to
    idle a GPU node, and a node that silently serves nothing is the expensive
    failure. Same fail-open reasoning as node_has_model's empty model list."""
    for empty in ([], (), ""):
        node = _with_allowlist(STARSHIP_246, empty)
        assert can_node_run_model(node, "qwen2.5:1.5b") is True


def test_a_malformed_allowlist_never_disqualifies():
    """A string or dict where a list belongs must not silently deny everything."""
    for junk in ("qwen2.5:7b", {"qwen2.5:7b": True}, 7):
        node = _with_allowlist(STARSHIP_246, junk)
        assert can_node_run_model(node, "qwen2.5:1.5b") is True


def test_allowlist_tolerates_the_latest_tag_on_either_side():
    """node_has_model normalises ':latest'; an allowlist that did not would refuse
    a model the node genuinely serves."""
    node = _with_allowlist(STARSHIP_246, ["dolphin3"])
    assert can_node_run_model(node, "dolphin3:latest") is True
    node2 = _with_allowlist(STARSHIP_246, ["dolphin3:latest"])
    assert can_node_run_model(node2, "dolphin3") is True


def test_allowlist_does_not_override_a_hard_capacity_refusal():
    """Allowlisting is a NARROWING filter, never a grant. Listing a model that
    cannot fit must not make it fit."""
    tiny = dict(STARSHIP_246)
    tiny["gpu_available"] = False
    tiny["gpu_vram_gb"] = None
    tiny["ram_gb"] = 4.0
    tiny["extra_capabilities"] = {"max_model_gb": 4, "model_allowlist": ["gemma3:12b"]}
    assert can_node_run_model(tiny, "gemma3:12b") is False
