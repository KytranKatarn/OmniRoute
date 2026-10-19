"""Keep-warm stranded-migration guards (#6106).

The keep-warm unloads a live runner when it reads resident-with-0-VRAM. Measured
2026-10-19: 72 unloads/24h for qwen2.5:7b and 54 for qwen25-classify, the latter a
model whose Modelfile pins `num_gpu 0` (always 0 VRAM by design, ~850 dispatches/day,
one warm took 339s). These tests pin the two guards: skip CPU-by-Modelfile models,
and require consecutive zero-VRAM readings.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.model_service import ModelService  # noqa: E402


def _svc(vram_by_model):
    svc = object.__new__(ModelService)
    svc.ollama_host = "http://test-host:1"
    svc.resident_vram_gb = lambda m: vram_by_model.get(m)  # type: ignore[method-assign]
    return svc


def _show(parameters):
    body = json.dumps({"parameters": parameters}).encode()
    return mock.patch("urllib.request.urlopen", return_value=io.BytesIO(body))


class TestModelfilePin:
    def test_num_gpu_zero_is_pinned(self):
        svc = _svc({})
        with _show("num_ctx                        2048\nnum_gpu                        0"):
            assert svc.is_cpu_pinned_by_modelfile("qwen25-classify:latest") is True

    def test_no_parameters_is_not_pinned(self):
        svc = _svc({})
        with _show(None):
            assert svc.is_cpu_pinned_by_modelfile("qwen2.5:7b") is False

    def test_nonzero_num_gpu_is_not_pinned(self):
        svc = _svc({})
        with _show("num_gpu 20"):
            assert svc.is_cpu_pinned_by_modelfile("m") is False

    def test_num_gpu_10_is_not_confused_with_zero(self):
        svc = _svc({})
        with _show("num_gpu 10"):
            assert svc.is_cpu_pinned_by_modelfile("m") is False

    def test_show_failure_fails_toward_pinned_and_is_not_cached(self):
        svc = _svc({})
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            assert svc.is_cpu_pinned_by_modelfile("m") is True
        with _show("num_ctx 4096"):  # recovers on the next call: the error was not cached
            assert svc.is_cpu_pinned_by_modelfile("m") is False

    def test_result_is_cached(self):
        svc = _svc({})
        with _show("num_gpu 0") as up:
            svc.is_cpu_pinned_by_modelfile("m")
            svc.is_cpu_pinned_by_modelfile("m")
        assert up.call_count == 1


class TestStrandedStrikes:
    def test_single_zero_reading_does_not_migrate(self):
        svc = _svc({"qwen2.5:7b": 0.0})
        with _show(None):
            assert svc.should_migrate_stranded("qwen2.5:7b") is False

    def test_two_consecutive_zero_readings_migrate_then_reset(self):
        svc = _svc({"qwen2.5:7b": 0.0})
        with _show(None):
            assert svc.should_migrate_stranded("qwen2.5:7b") is False
            assert svc.should_migrate_stranded("qwen2.5:7b") is True
            assert svc.should_migrate_stranded("qwen2.5:7b") is False  # counter reset after acting

    def test_healthy_reading_between_zeros_resets_the_count(self):
        vram = {"qwen2.5:7b": 0.0}
        svc = _svc(vram)
        with _show(None):
            assert svc.should_migrate_stranded("qwen2.5:7b") is False
            vram["qwen2.5:7b"] = 4.6
            assert svc.should_migrate_stranded("qwen2.5:7b") is False
            vram["qwen2.5:7b"] = 0.0
            assert svc.should_migrate_stranded("qwen2.5:7b") is False  # first strike again

    def test_not_resident_never_migrates(self):
        svc = _svc({})
        with _show(None):
            for _ in range(5):
                assert svc.should_migrate_stranded("qwen2.5:7b") is False

    def test_modelfile_pinned_model_never_migrates(self):
        """The qwen25-classify regression: 0 VRAM forever, must never be unloaded."""
        svc = _svc({"qwen25-classify": 0.0})
        with _show("num_gpu 0"):
            for _ in range(10):
                assert svc.should_migrate_stranded("qwen25-classify") is False


def test_agent_loop_uses_the_guarded_check():
    """Source-level (AgentLoop cannot be unit-booted): the keep-warm must call the guard,
    not the bare `resident_vram_gb(model) == 0.0` it replaced."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "ai_bridge" / "agent_loop.py").exists():
            src = (parent / "ai_bridge" / "agent_loop.py").read_text()
            break
    else:
        src = Path("/mnt/archie_brain/ai_bridge/agent_loop.py").read_text()
    body = src.split("def _keep_cluster_models_warm", 1)[1].split("def _forge_review_path_observer", 1)[0]
    assert "svc.should_migrate_stranded(model)" in body
    assert "resident_vram_gb(model) == 0.0" not in body
