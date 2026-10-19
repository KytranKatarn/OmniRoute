"""Startup warm-up must not evict healthy resident models (#7329, #6106)."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.warmup_eviction import parse_expires_at, plan_evictions

NOW = datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc)
APP = Path(__file__).resolve().parents[1] / "app.py"


def _m(name, *, vram=4_000_000_000, size=5_000_000_000, expires="2026-10-19T14:50:00.123456789-04:00"):
    return {"name": name, "size_vram": vram, "size": size, "expires_at": expires}


def _plan(models, pinned=()):
    return plan_evictions(models, now=NOW, is_cpu_pinned=lambda n: n in pinned)


def test_healthy_gpu_resident_is_kept():
    evict, keep = _plan([_m("qwen2.5:7b")])
    assert evict == []
    assert keep == [("qwen2.5:7b", "resident_on_gpu")]


def test_infinite_keep_alive_is_evicted():
    evict, _ = _plan([_m("old:7b", expires="2318-03-01T11:22:33.123456789-04:00")])
    assert evict == [("old:7b", "stale_keep_alive")]


def test_unparseable_expiry_falls_back_to_old_behaviour():
    evict, _ = _plan([_m("x:1b", expires="garbage"), _m("y:1b", expires=None)])
    assert {n for n, _ in evict} == {"x:1b", "y:1b"}


def test_cpu_stranded_gpu_model_is_evicted():
    evict, _ = _plan([_m("qwen2.5:7b", vram=0)])
    assert evict == [("qwen2.5:7b", "stranded")]


def test_modelfile_cpu_pin_is_kept_not_stranded():
    evict, keep = _plan([_m("qwen25-classify:latest", vram=0)], pinned={"qwen25-classify:latest"})
    assert evict == []
    assert keep == [("qwen25-classify:latest", "cpu_by_design")]


def test_zero_size_runner_is_not_called_stranded():
    evict, _ = _plan([_m("ghost:1b", vram=0, size=0)])
    assert evict == []


def test_expiry_just_inside_the_window_is_kept():
    ok = (NOW + timedelta(minutes=119)).isoformat()
    evict, _ = _plan([_m("a:7b", expires=ok)])
    assert evict == []


def test_nanosecond_timestamps_parse():
    dt = parse_expires_at("2026-10-19T15:03:07.633739665-04:00")
    assert dt is not None and dt.tzinfo is not None
    assert parse_expires_at("2026-10-19T15:03:07Z") is not None


def test_warmup_no_longer_evicts_every_loaded_model():
    """`app` runs the warm-up at import, so read the source: the unconditional loop is gone."""
    tree = ast.parse(APP.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_warmup_ollama_models")
    src = ast.get_source_segment(APP.read_text(), fn)
    assert "plan_evictions(" in src
    assert "for model_name in loaded_before" not in src
