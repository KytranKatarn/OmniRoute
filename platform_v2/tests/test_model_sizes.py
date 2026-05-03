"""Unit tests for services.model_sizes (#2516 / ADR-555 Phase 1)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.model_sizes import ModelFootprint, lookup, known_models


def test_known_model_returns_explicit_entry():
    fp = lookup("qwen2.5:7b")
    assert isinstance(fp, ModelFootprint)
    assert fp.vram_gb == 5.5
    assert fp.ram_gb == 8.0
    assert fp.prefer_gpu is True


def test_cpu_tier_model_has_zero_vram_and_no_gpu_preference():
    fp = lookup("qwen3-coder-cpu")
    assert fp.vram_gb == 0.0
    assert fp.ram_gb == 55.0
    assert fp.prefer_gpu is False


def test_tiny_model_does_not_prefer_gpu():
    fp = lookup("qwen2.5:0.5b")
    assert fp.prefer_gpu is False
    assert fp.vram_gb < 2


def test_unknown_model_falls_back_to_safe_default():
    fp = lookup("never-heard-of-this-model")
    # Safe default routes to hub: high VRAM, GPU-preferring.
    assert fp.prefer_gpu is True
    assert fp.vram_gb >= 4
    assert fp.ram_gb >= 8


def test_unknown_model_with_size_suffix_uses_heuristic():
    fp = lookup("custom-model:13b")
    # 13b * 1.3 = 16.9 vram, 13 * 2 = 26 ram, prefer_gpu since >=4
    assert fp.prefer_gpu is True
    assert 14 <= fp.vram_gb <= 18
    assert fp.ram_gb >= 20


def test_empty_or_none_model_returns_default():
    assert lookup("").prefer_gpu is True
    assert lookup(None).prefer_gpu is True


def test_known_models_includes_seed_entries():
    names = list(known_models())
    assert "qwen2.5:7b" in names
    assert "mistral:7b" in names
    assert "qwen2.5:1.5b" in names
    assert "gemma2-cpu:latest" in names


def test_bare_name_match_when_tag_unknown():
    # phi3.5 and phi3.5:latest both seeded
    assert lookup("phi3.5").vram_gb == 3.0
    assert lookup("phi3.5:latest").vram_gb == 3.0


def test_cloud_models_have_zero_local_footprint():
    for name in ("claude-haiku", "claude-sonnet", "claude-opus"):
        fp = lookup(name)
        assert fp.vram_gb == 0.0
        assert fp.ram_gb == 0.0
