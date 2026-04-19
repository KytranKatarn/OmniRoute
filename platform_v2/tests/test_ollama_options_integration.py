"""Integration tests — require RUN_INTEGRATION=1 and a live hub Ollama.

These are skipped in CI by default. Run manually after retrofit:
    RUN_INTEGRATION=1 pytest tests/test_ollama_options_integration.py -v

Prerequisites:
- The A.R.C.H.I.E. hub is reachable at OLLAMA_HOST (default 192.168.1.200:11434)
- At least one small model is pullable (e.g., llama3.2:3b)
- The hub has a working GPU (Quadro M4000 8GB in the canonical setup)
"""

from __future__ import annotations

import os
import time
import requests

import pytest

_INTEGRATION_SKIP = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1",
    reason="integration tests gated by RUN_INTEGRATION=1",
)

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")


class _LiveNode:
    """Lightweight node stub that mirrors the attributes build_options reads."""

    node_id = "archie-starbase"
    host = OLLAMA_HOST
    gpu_vram_gb = 8.0
    gpu_available = True
    status = "online"


def _is_loaded_on_gpu(model: str) -> bool:
    """Check /api/ps for a loaded model with size_vram > 0."""
    resp = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=10)
    resp.raise_for_status()
    for m in resp.json().get("models", []):
        if m.get("name", "").startswith(model) and int(m.get("size_vram", 0) or 0) > 0:
            return True
    return False


def _model_is_available(model: str) -> bool:
    """Check /api/tags for the model's presence (pulled, not necessarily loaded)."""
    resp = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
    resp.raise_for_status()
    for m in resp.json().get("models", []):
        if m.get("name", "").startswith(model):
            return True
    return False


@_INTEGRATION_SKIP
def test_small_model_places_on_gpu():
    """llama3.2:3b should land on GPU via build_options decision."""
    from tools.department_hq.services.ollama_options import (
        build_options,
        VramProbeCache,
    )

    model = "llama3.2:3b"
    if not _model_is_available(model):
        pytest.skip(f"{model} not pulled on hub; pull it first: ollama pull {model}")

    cache = VramProbeCache()  # fresh cache — don't inherit module default state
    result = build_options(model=model, target_node=_LiveNode(), cache=cache)
    assert result["placement"] == "gpu", f"Expected GPU placement for {model} (base ~2 GB vs 8 GB VRAM); got {result}"

    # Trigger actual inference to verify the decision is honoured by Ollama.
    resp = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": model,
            "prompt": "hi",
            "stream": False,
            "options": {**result["options"], "num_predict": 1},
            "keep_alive": result["keep_alive"],
        },
        timeout=120,
    )
    assert resp.status_code == 200

    # Wait briefly for /api/ps to report the model.
    time.sleep(0.5)
    assert _is_loaded_on_gpu(model), f"{model} should be loaded on GPU per /api/ps after dispatch"


@_INTEGRATION_SKIP
def test_oversized_model_places_on_cpu():
    """A model exceeding 8 GB VRAM should be routed CPU-only."""
    from tools.department_hq.services.ollama_options import (
        build_options,
        VramProbeCache,
    )

    # Try common oversized models in priority order; skip if none are available.
    candidates = [
        "qwen3-coder-cpu:latest",
        "llama3.1:70b",
        "mixtral:8x7b",
        "llama3.3:70b",
    ]
    available = [m for m in candidates if _model_is_available(m)]
    if not available:
        pytest.skip(
            f"No oversized model available on hub from candidates: {candidates}. "
            f"Pull one first: ollama pull qwen3-coder-cpu"
        )
    model = available[0]

    cache = VramProbeCache()
    result = build_options(model=model, target_node=_LiveNode(), cache=cache)
    assert result["placement"] == "cpu", f"Expected CPU placement for oversized model {model}; got {result}"
    assert result["options"].get("num_gpu") == 0, f"num_gpu should be 0 for CPU placement; got {result['options']}"


@_INTEGRATION_SKIP
def test_placement_event_is_emitted_on_live_dispatch():
    """Each build_options call should push one event into the telemetry buffer."""
    from tools.department_hq.services.ollama_options import (
        build_options,
        VramProbeCache,
        drain_placement_events,
    )

    model = "llama3.2:3b"
    if not _model_is_available(model):
        pytest.skip(f"{model} not pulled on hub")

    drain_placement_events()  # reset window
    cache = VramProbeCache()
    build_options(model=model, target_node=_LiveNode(), cache=cache)
    events = drain_placement_events()
    assert len(events) >= 1, "build_options must emit exactly one placement event"
    assert events[-1]["model"] == model
    assert events[-1]["placement"] in ("gpu", "cpu")


# ---------------------------------------------------------------------------
# Mocked fleet — always runs (no RUN_INTEGRATION gate).
# Uses the `responses` library to stand up fake hub+fleet Ollama endpoints
# and verify select_node routes to fleet when hub GPU is full.
# ---------------------------------------------------------------------------

from unittest.mock import patch as _unittest_patch

# Ensure /tmp/pip_pkgs is on sys.path so `responses` can be found when
# the container filesystem is read-only (pip installs there as a fallback).
import os as _os
import sys as _sys

if _os.path.isdir("/tmp/pip_pkgs") and "/tmp/pip_pkgs" not in _sys.path:
    _sys.path.insert(0, "/tmp/pip_pkgs")

try:
    import responses as _responses

    _HAS_RESPONSES = True
except ImportError:
    _HAS_RESPONSES = False


@pytest.mark.skipif(not _HAS_RESPONSES, reason="responses library not installed")
def test_mocked_two_node_fleet_hub_full_routes_to_fleet():
    """End-to-end: hub has no room (7 GB loaded vs 8 GB), fleet has room.
    select_node should pick the fleet node.
    """
    from tools.department_hq.services import ollama_options as oo

    oo._loaded_vram_cache.clear()
    oo._DEFAULT_CACHE = oo.VramProbeCache()  # fresh probe cache

    hub_url = "http://archie_ollama:11434"
    fleet_url = "http://100.64.0.2:11434"

    class _HubNode:
        node_id = "archie-starbase"
        host = hub_url
        gpu_vram_gb = 8.0
        gpu_available = True
        status = "online"

    class _FleetNode:
        node_id = "uss-kytran"
        host = fleet_url
        gpu_vram_gb = 8.0
        gpu_available = True
        current_load = 0
        max_concurrent = 5
        status = "online"

    with _responses.RequestsMock() as rsps:
        rsps.add(
            rsps.POST,
            f"{hub_url}/api/show",
            json={
                "details": {
                    "parameter_size": "3B",
                    "quantization_level": "Q4_K_M",
                }
            },
        )
        rsps.add(
            rsps.POST,
            f"{fleet_url}/api/show",
            json={
                "details": {
                    "parameter_size": "3B",
                    "quantization_level": "Q4_K_M",
                }
            },
        )
        # Hub has 7 GB loaded → no room for a 3B Q4 model (~2 GB) given
        # safety margin reduces headroom to ~0.5 GB.
        rsps.add(
            rsps.GET,
            f"{hub_url}/api/ps",
            json={"models": [{"name": "big:latest", "size_vram": 7 * 1024**3}]},
        )
        rsps.add(
            rsps.GET,
            f"{fleet_url}/api/ps",
            json={"models": []},
        )

        with _unittest_patch(
            "tools.department_hq.services.ollama_options._resolve_target_node",
            return_value=_HubNode(),
        ), _unittest_patch(
            "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
            return_value=[_FleetNode()],
        ):
            chosen = oo.select_node(capability="conversation", model="llama3.2:3b")

    assert chosen.node_id == "uss-kytran"


@pytest.mark.skipif(not _HAS_RESPONSES, reason="responses library not installed")
def test_mocked_two_node_fleet_hub_empty_routes_to_hub():
    """Sanity check: when both hub and fleet are empty, hub is preferred."""
    from tools.department_hq.services import ollama_options as oo

    oo._loaded_vram_cache.clear()
    oo._DEFAULT_CACHE = oo.VramProbeCache()

    hub_url = "http://archie_ollama:11434"
    fleet_url = "http://100.64.0.2:11434"

    class _HubNode:
        node_id = "archie-starbase"
        host = hub_url
        gpu_vram_gb = 8.0
        gpu_available = True
        status = "online"

    class _FleetNode:
        node_id = "uss-kytran"
        host = fleet_url
        gpu_vram_gb = 8.0
        gpu_available = True
        current_load = 0
        max_concurrent = 5
        status = "online"

    with _responses.RequestsMock() as rsps:
        rsps.add(
            rsps.POST,
            f"{hub_url}/api/show",
            json={"details": {"parameter_size": "3B", "quantization_level": "Q4_K_M"}},
        )
        # Only hub /api/ps gets called because the hub check passes.
        rsps.add(rsps.GET, f"{hub_url}/api/ps", json={"models": []})

        with _unittest_patch(
            "tools.department_hq.services.ollama_options._resolve_target_node",
            return_value=_HubNode(),
        ), _unittest_patch(
            "tools.department_hq.services.ollama_options._list_online_fleet_nodes",
            return_value=[_FleetNode()],
        ):
            chosen = oo.select_node(capability="conversation", model="llama3.2:3b")

    assert chosen.node_id == "archie-starbase"
