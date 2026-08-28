"""Tests for expanded model_service (Phase 2).

Run: docker exec archie_platform python -m pytest services/tests/test_phase2_model_service.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import patch
from services.model_service import ModelService


def test_ensure_model_ready_returns_tier_dict():
    """ensure_model_ready should return dict with ready, tier, host, warm_boot_ms."""
    svc = ModelService(ollama_host="http://fake:11434")
    with patch.object(
        svc,
        "_fetch_ps",
        return_value=[{"name": "mistral:7b", "size_gb": 4.0, "size_vram": 4_000_000_000, "size": 4_000_000_000}],
    ):
        result = svc.ensure_model_ready("TestAgent", "mistral:7b")
    assert result["ready"] is True
    assert result["tier"] in ("gpu", "cpu")
    assert "host" in result
    assert "warm_boot_ms" in result


def test_ensure_model_ready_cold_model():
    """Cold model should attempt load and return tier='cold'."""
    svc = ModelService(ollama_host="http://fake:11434")
    with patch.object(svc, "_fetch_ps", return_value=[]):
        with patch.object(svc, "load_model", return_value=True):
            with patch.object(svc, "ensure_capacity", return_value=True):
                result = svc.ensure_model_ready("TestAgent", "phi3.5:latest")
    assert result["ready"] is True
    assert result["tier"] == "cold"


def test_ensure_model_ready_no_capacity():
    """If no capacity and eviction fails, return ready=False."""
    svc = ModelService(ollama_host="http://fake:11434", ram_budget_gb=4.0)
    with patch.object(svc, "_fetch_ps", return_value=[]):
        with patch.object(svc, "ensure_capacity", return_value=False):
            result = svc.ensure_model_ready("TestAgent", "phi4:14b")
    assert result["ready"] is False


def test_estimate_model_size_known():
    """Known model sizes should return correct estimates."""
    svc = ModelService(ollama_host="http://fake:11434")
    assert svc.estimate_model_size("mistral:7b") >= 3.0
    assert svc.estimate_model_size("mistral:7b") <= 8.0


def test_estimate_model_size_unknown_with_param_count():
    """Unknown model with parameter count in name should use heuristic."""
    svc = ModelService(ollama_host="http://fake:11434")
    size = svc.estimate_model_size("somemodel:13b")
    assert size == 13.0 * 0.6  # 7.8


def test_estimate_model_size_unknown_no_param():
    """Unknown model without parameter count should return default 4.0."""
    svc = ModelService(ollama_host="http://fake:11434")
    assert svc.estimate_model_size("mystery-model:latest") == 4.0


def test_ensure_model_ready_node_target():
    """Node target should use the node's host, not hub."""
    svc = ModelService(ollama_host="http://fake:11434")
    target = {"hostname": "192.168.1.246", "port": 11434}
    with patch.object(
        svc,
        "_fetch_ps",
        return_value=[{"name": "llama3.2:3b", "size_gb": 2.0, "size_vram": 2_000_000_000, "size": 2_000_000_000}],
    ):
        result = svc.ensure_model_ready("TestAgent", "llama3.2:3b", target_host=target)
    assert result["ready"] is True
    assert "192.168.1.246" in result["host"]


def test_ensure_model_ready_gpu_tier():
    """Model with >50% VRAM should be classified as GPU tier."""
    svc = ModelService(ollama_host="http://fake:11434")
    with patch.object(
        svc,
        "_fetch_ps",
        return_value=[{"name": "mistral:7b", "size_gb": 4.0, "size_vram": 4_000_000_000, "size": 4_000_000_000}],
    ):
        result = svc.ensure_model_ready("TestAgent", "mistral:7b")
    assert result["tier"] == "gpu"


def test_ensure_model_ready_cpu_tier():
    """Model with <50% VRAM should be classified as CPU tier."""
    svc = ModelService(ollama_host="http://fake:11434")
    with patch.object(
        svc,
        "_fetch_ps",
        return_value=[{"name": "mistral:7b", "size_gb": 4.0, "size_vram": 100_000, "size": 4_000_000_000}],
    ):
        result = svc.ensure_model_ready("TestAgent", "mistral:7b")
    assert result["tier"] == "cpu"
