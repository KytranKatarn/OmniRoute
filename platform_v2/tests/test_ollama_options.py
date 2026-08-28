# platform_v2/tests/test_ollama_options.py
"""Unit tests for ollama_options helper (Phase 1 + 2a)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_module_exports_expected_public_api():
    from tools.department_hq.services import ollama_options as oo

    # Public surface exported for callers and tests.
    assert hasattr(oo, "build_options")
    assert hasattr(oo, "VramProbeCache")
    assert hasattr(oo, "ProbeEntry")
    assert hasattr(oo, "NodeUnavailable")
    assert hasattr(oo, "VRAM_SAFETY_MARGIN_GB")


def test_probe_entry_is_a_dataclass_with_expected_fields():
    from tools.department_hq.services.ollama_options import ProbeEntry
    import dataclasses

    assert dataclasses.is_dataclass(ProbeEntry)
    names = {f.name for f in dataclasses.fields(ProbeEntry)}
    # >= allows Task 2+ to extend fields without breaking this test
    assert names >= {
        "parameter_count",
        "quantization",
        "estimated_vram_base_gb",
        "context_overhead_per_token_mb",
        "probed_at",
        "probe_failed",
        "raw_show_response",
    }


def test_node_unavailable_is_an_exception():
    from tools.department_hq.services.ollama_options import NodeUnavailable

    assert issubclass(NodeUnavailable, Exception)


class _FakeNode:
    def __init__(self, node_id="hub", host="http://archie_ollama:11434", status="online"):
        self.node_id = node_id
        self.host = host
        self.status = status


def _make_show_response(parameter_size="3B", quant="Q4_K_M"):
    return {
        "modelfile": "",
        "parameters": "",
        "template": "",
        "details": {
            "parameter_size": parameter_size,
            "quantization_level": quant,
            "family": "llama",
            "format": "gguf",
        },
    }


def test_cache_probes_once_and_reuses_entry():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response(),
    ) as mocked:
        e1 = cache.get_or_probe(node, "llama3.2:3b")
        e2 = cache.get_or_probe(node, "llama3.2:3b")
    assert e1 is e2
    assert mocked.call_count == 1
    assert e1.parameter_count == 3_000_000_000
    assert e1.quantization == "Q4_K_M"
    assert e1.probe_failed is False


def test_cache_invalidate_node_drops_all_entries_for_node():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response(),
    ):
        cache.get_or_probe(node, "llama3.2:3b")
        cache.get_or_probe(node, "mistral:7b")
    cache.invalidate_node(node.node_id)
    assert cache._entries == {}


def test_cache_probe_failure_marks_entry_and_caches_for_short_window():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        side_effect=RuntimeError("boom"),
    ) as mocked:
        first = cache.get_or_probe(node, "mystery:7b")
        second = cache.get_or_probe(node, "mystery:7b")
    assert first.probe_failed is True
    assert first.parameter_count == 0
    # Second call within the 60s failed-probe TTL reuses the cached entry
    # — _fetch_show is NOT called again.
    assert first is second
    assert mocked.call_count == 1


# ---------------------------------------------------------------------------
# Task 3: quantization → bytes-per-param table + VRAM estimator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quant,expected_bpp",
    [
        ("Q2_K", 0.33),
        ("Q3_K_M", 0.47),
        ("Q4_K_M", 0.56),
        ("Q5_K_M", 0.68),
        ("Q6_K", 0.81),
        ("Q8_0", 1.07),
        ("F16", 2.0),
        ("UNKNOWN", 4.0),  # worst-case fp32 fallback
        ("", 4.0),
    ],
)
def test_bytes_per_param_table(quant, expected_bpp):
    from tools.department_hq.services.ollama_options import _bytes_per_param

    assert _bytes_per_param(quant) == pytest.approx(expected_bpp, rel=1e-3)


def test_estimate_base_vram_3b_q4():
    # 3B × 0.56 bytes × 1.3 overhead / 1024³ ≈ 2.03 GB
    from tools.department_hq.services.ollama_options import _estimate_base_vram_gb

    gb = _estimate_base_vram_gb(parameter_count=3_000_000_000, quantization="Q4_K_M")
    assert 1.8 < gb < 2.3


def test_cache_probe_populates_vram_estimate():
    from tools.department_hq.services.ollama_options import VramProbeCache

    cache = VramProbeCache()
    node = _FakeNode()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("7B", "Q4_K_M"),
    ):
        entry = cache.get_or_probe(node, "mistral:7b")
    # 7B × 0.56 bytes × 1.3 / 1024³ ≈ 4.75 GB (matches empirical ~4.4 GB for
    # mistral:7b-instruct-q4_K_M; accept a ±0.5 GB tolerance for run-to-run drift)
    assert 4.3 < entry.estimated_vram_base_gb < 5.3
    assert entry.context_overhead_per_token_mb > 0


def _make_ps_response(models_with_sizes):
    # size_vram is bytes per Ollama docs
    return {"models": [{"name": name, "size_vram": sz, "size": sz} for name, sz in models_with_sizes]}


def test_loaded_vram_sums_size_vram_across_models():
    from tools.department_hq.services.ollama_options import get_loaded_vram_gb, _loaded_vram_cache

    _loaded_vram_cache.clear()
    node = _FakeNode()
    ps = _make_ps_response([("a:latest", 1 * 1024**3), ("b:latest", 2 * 1024**3)])
    with patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=ps,
    ):
        gb = get_loaded_vram_gb(node, exclude_model=None)
    assert 2.99 < gb < 3.01


def test_loaded_vram_excludes_named_model():
    from tools.department_hq.services.ollama_options import get_loaded_vram_gb, _loaded_vram_cache

    _loaded_vram_cache.clear()
    node = _FakeNode()
    ps = _make_ps_response([("target:latest", 4 * 1024**3), ("other:latest", 1 * 1024**3)])
    with patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=ps,
    ):
        gb = get_loaded_vram_gb(node, exclude_model="target:latest")
    assert 0.99 < gb < 1.01


def test_loaded_vram_caches_for_five_seconds():
    from tools.department_hq.services.ollama_options import (
        get_loaded_vram_gb,
        _loaded_vram_cache,
    )

    _loaded_vram_cache.clear()
    node = _FakeNode()
    ps = _make_ps_response([("a:latest", 1 * 1024**3)])
    with patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=ps,
    ) as mocked:
        get_loaded_vram_gb(node, exclude_model=None)
        get_loaded_vram_gb(node, exclude_model=None)
    assert mocked.call_count == 1


# ---------------------------------------------------------------------------
# Task 5: build_options() strategy A
# ---------------------------------------------------------------------------


def _hub(gpu_vram_gb=8.0):
    node = _FakeNode()
    node.gpu_vram_gb = gpu_vram_gb
    node.gpu_available = True
    node.status = "online"
    return node


def test_build_options_gpu_placement_when_model_fits():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.2:3b", target_node=hub)
    assert result["placement"] == "gpu"
    assert "num_gpu" not in result["options"]
    assert result["target_node_id"] == "hub"
    assert result["model"] == "llama3.2:3b"
    assert result["keep_alive"] == "5m"


def test_build_options_cpu_placement_when_model_too_big():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("13B", "Q4_K_M"),  # ~8.8 GB, exceeds 8-0.5=7.5
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.1:13b", target_node=hub)
    assert result["placement"] == "cpu"
    assert result["options"]["num_gpu"] == 0
    assert "insufficient" in result["reason"] or "too_big" in result["reason"]


def test_build_options_cpu_placement_when_probe_failed():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        side_effect=RuntimeError("boom"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="mystery:7b", target_node=hub)
    assert result["placement"] == "cpu"
    assert result["options"]["num_gpu"] == 0
    assert result["reason"] == "probe_failed"


def test_build_options_prompt_tokens_push_past_vram_threshold():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    # 7B Q4_K_M base ~4.75 GB; with 4096 prompt tokens × ~1 MB/token = 4 GB ctx,
    # total ~8.75 GB > available (8 - 0.5 margin = 7.5 GB). Expect CPU fallback.
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("7B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="mistral:7b", target_node=hub, prompt_tokens_hint=4096)
    assert result["placement"] == "cpu"


def test_build_options_currently_loaded_models_reduce_headroom():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    # 3B Q4_K_M ~2 GB; but another model already takes 6 GB → 8 - 0.5 - 6 = 1.5 GB
    # headroom, so 2 GB model doesn't fit → CPU fallback.
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([("other:latest", 6 * 1024**3)]),
    ):
        result = build_options(model="llama3.2:3b", target_node=hub)
    assert result["placement"] == "cpu"


def test_build_options_respects_keep_alive_override():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.2:3b", target_node=hub, keep_alive="15m")
    assert result["keep_alive"] == "15m"


def test_build_options_raises_on_empty_model():
    from tools.department_hq.services.ollama_options import build_options
    import pytest

    with pytest.raises(ValueError):
        build_options(model="", target_node=_hub())


def test_build_options_raises_on_negative_tokens_hint():
    from tools.department_hq.services.ollama_options import build_options
    import pytest

    with pytest.raises(ValueError):
        build_options(model="llama3.2:3b", target_node=_hub(), prompt_tokens_hint=-1)


def test_build_options_cpu_when_node_has_no_gpu():
    from tools.department_hq.services.ollama_options import build_options, _loaded_vram_cache

    _loaded_vram_cache.clear()
    node = _FakeNode(node_id="cpu-node")
    node.gpu_available = False
    node.gpu_vram_gb = 0.0
    node.status = "online"
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = build_options(model="llama3.2:3b", target_node=node)
    assert result["placement"] == "cpu"
    assert result["reason"] == "no_gpu_on_node"


def test_drain_placement_events_returns_and_resets():
    from tools.department_hq.services.ollama_options import (
        _record_placement_event,
        drain_placement_events,
    )

    drain_placement_events()  # reset any leftover
    _record_placement_event({"placement": "gpu", "reason": "fits"})
    _record_placement_event({"placement": "cpu", "reason": "probe_failed"})
    events = drain_placement_events()
    assert len(events) == 2
    # Second drain is empty.
    assert drain_placement_events() == []


def test_build_options_records_placement_event():
    from tools.department_hq.services.ollama_options import (
        build_options,
        drain_placement_events,
        _loaded_vram_cache,
    )

    _loaded_vram_cache.clear()
    drain_placement_events()  # reset
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        build_options(model="llama3.2:3b", target_node=hub)
    events = drain_placement_events()
    assert len(events) == 1
    event = events[0]
    assert event["model"] == "llama3.2:3b"
    assert event["placement"] == "gpu"
    assert event["reason"] == "fits"
    assert event["node_id"] == "hub"
    assert "ts" in event


def test_placement_event_buffer_is_bounded():
    """Verify the bounded buffer sheds oldest events when overflowing."""
    from tools.department_hq.services.ollama_options import (
        _record_placement_event,
        drain_placement_events,
        _PLACEMENT_WINDOW_MAX,
    )

    drain_placement_events()
    # Flood past the buffer cap.
    for i in range(_PLACEMENT_WINDOW_MAX + 500):
        _record_placement_event({"placement": "gpu", "reason": "fits", "i": i})
    events = drain_placement_events()
    # Buffer should have dropped some oldest events; total must be <= cap.
    assert len(events) <= _PLACEMENT_WINDOW_MAX
    # Latest events should be preserved.
    assert events[-1]["i"] == _PLACEMENT_WINDOW_MAX + 499


def test_select_node_returns_hub_when_hub_fits():
    from tools.department_hq.services.ollama_options import select_node, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        chosen = select_node(capability="conversation", model="llama3.2:3b")
    assert chosen.node_id == "hub"


def test_select_node_falls_to_fleet_when_hub_full():
    from tools.department_hq.services.ollama_options import select_node, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    fleet = _FakeNode(node_id="uss-kytran", host="http://100.64.0.2:11434")
    fleet.gpu_vram_gb = 8.0
    fleet.gpu_available = True
    fleet.status = "online"
    fleet.current_load = 0
    fleet.max_concurrent = 5

    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[fleet],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        side_effect=lambda n, timeout_s=5.0: _make_ps_response(
            [("big:latest", 7 * 1024**3)] if n.node_id == hub.node_id else []
        ),
    ):
        chosen = select_node(capability="conversation", model="llama3.2:3b")
    assert chosen.node_id == "uss-kytran"


def test_select_node_returns_hub_cpu_when_no_gpu_node_fits():
    from tools.department_hq.services.ollama_options import select_node, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("70B", "Q4_K_M"),  # ~47 GB, doesn't fit anywhere
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        chosen = select_node(capability="conversation", model="big:70b")
    # Nothing fits → still return hub; caller sees placement=cpu from build_options.
    assert chosen.node_id == "hub"


def test_select_node_skips_nodes_at_max_concurrent():
    from tools.department_hq.services.ollama_options import select_node, _loaded_vram_cache

    _loaded_vram_cache.clear()
    hub = _hub()
    fleet = _FakeNode(node_id="busy-node", host="http://busy:11434")
    fleet.gpu_vram_gb = 8.0
    fleet.gpu_available = True
    fleet.status = "online"
    fleet.current_load = 5
    fleet.max_concurrent = 5

    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[fleet],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        side_effect=lambda n, timeout_s=5.0: _make_ps_response(
            [("big:latest", 7 * 1024**3)] if n.node_id == hub.node_id else []
        ),
    ):
        chosen = select_node(capability="conversation", model="llama3.2:3b")
    # Hub full, fleet at max_concurrent → fall back to hub (CPU).
    assert chosen.node_id == "hub"


def test_select_node_raises_when_fallback_cpu_ok_false_and_nothing_fits():
    from tools.department_hq.services.ollama_options import (
        select_node,
        NodeUnavailable,
        _loaded_vram_cache,
    )
    import pytest

    _loaded_vram_cache.clear()
    hub = _hub()
    with patch(
        "tools.department_hq.services.ollama_options._resolve_target_node",
        return_value=hub,
    ), patch(
        "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
        return_value=[],
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("70B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        with pytest.raises(NodeUnavailable):
            select_node(
                capability="conversation",
                model="big:70b",
                fallback_cpu_ok=False,
            )


def test_build_options_with_none_target_node_uses_select_node():
    from tools.department_hq.services import ollama_options as oo

    oo._loaded_vram_cache.clear()

    fleet = _FakeNode(node_id="uss-kytran", host="http://100.64.0.2:11434")
    fleet.gpu_vram_gb = 8.0
    fleet.gpu_available = True

    with patch(
        "tools.department_hq.services.ollama_options.select_node",
        return_value=fleet,
    ) as mocked_select, patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = oo.build_options(model="llama3.2:3b", target_node=None)
    mocked_select.assert_called_once()
    assert result["target_node_id"] == "uss-kytran"


def test_build_options_with_explicit_target_node_bypasses_select_node():
    from tools.department_hq.services import ollama_options as oo

    oo._loaded_vram_cache.clear()
    hub = _hub()

    with patch(
        "tools.department_hq.services.ollama_options.select_node",
    ) as mocked_select, patch(
        "tools.department_hq.services.ollama_options._fetch_show",
        return_value=_make_show_response("3B", "Q4_K_M"),
    ), patch(
        "tools.department_hq.services.ollama_options._fetch_ps",
        return_value=_make_ps_response([]),
    ):
        result = oo.build_options(model="llama3.2:3b", target_node=hub)
    # Explicit target_node must NOT call select_node
    mocked_select.assert_not_called()
    assert result["target_node_id"] == "hub"
