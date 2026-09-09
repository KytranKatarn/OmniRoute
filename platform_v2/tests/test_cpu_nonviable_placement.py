"""#5623 — CPU is a real fallback for small models and a guaranteed timeout for big ones.

Measured 2026-08-15: VRAM headroom hit 0.0 GB, `qwen2.5:7b` was placed on the hub CPU
for ~4 minutes, and EVERY fact_check dispatched in that window died on
"timeout after 240s ... did not return for model=qwen2.5:7b" — 89% failure for the hour
against a 12% 24h baseline. The hub CPU is a Xeon E5-2658 v2 (Ivy Bridge, pre-AVX2), so a
7B there cannot finish inside the deadline. "Degrade to CPU" was a timeout with extra steps.

The fix refuses the load instead, so `ensure_model_ready` reports not-ready and the
dispatcher's EXISTING `model_not_ready=True` path escalates to a node that has a GPU.

⚠️ The load-bearing half of these tests is the NEGATIVE space: a small model must STILL
load on CPU. The entire CPU-outpost tier (qwen2.5:1.5b / llama3.2:3b, no GPU at all)
depends on that staying true — a blanket "never CPU" would take the outposts offline.
"""

import importlib
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, "/app")


@pytest.fixture()
def svc(monkeypatch):
    monkeypatch.setenv("ARCHIE_VRAM_TOTAL_GB", "20.0")
    monkeypatch.setenv("ARCHIE_VRAM_LARGEST_GPU_GB", "12.0")
    monkeypatch.setenv("ARCHIE_CPU_VIABLE_MAX_GB", "4.0")
    import services.model_service as ms

    importlib.reload(ms)
    s = ms.ModelService()
    s._loaded_cache = []
    monkeypatch.setattr(s, "_is_cache_fresh", lambda: True)
    return s, ms


def _load(gb: float) -> dict:
    return {"name": f"stub-{gb}", "size_vram": int(gb * (1024**3))}


# ---------------------------------------------------------------------------
# the predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["qwen2.5:7b", "mistral:7b", "gemma3:12b", "dolphin3:latest"])
def test_big_models_are_not_cpu_viable(svc, model):
    s, _ = svc
    assert s.cpu_placement_is_viable(model) is False


@pytest.mark.parametrize("model", ["qwen2.5:1.5b", "llama3.2:3b"])
def test_small_models_stay_cpu_viable(svc, model):
    """The CPU-outpost tier runs exactly these, with no GPU anywhere."""
    s, _ = svc
    assert s.cpu_placement_is_viable(model) is True


def test_unknown_size_fails_safe_to_viable(svc):
    """Refusing to load a model we cannot size is worse than trying it."""
    s, _ = svc
    with patch.object(s, "estimate_model_size", side_effect=RuntimeError("no idea")):
        assert s.cpu_placement_is_viable("some-new-model") is True
    with patch.object(s, "estimate_model_size", return_value=0):
        assert s.cpu_placement_is_viable("zero-size") is True


def test_threshold_is_env_tunable(monkeypatch):
    """A bigger CPU (or a smaller deadline) is a config change, not a code change."""
    monkeypatch.setenv("ARCHIE_CPU_VIABLE_MAX_GB", "99.0")
    import services.model_service as ms

    importlib.reload(ms)
    s = ms.ModelService()
    assert s.cpu_placement_is_viable("gemma3:12b") is True
    monkeypatch.setenv("ARCHIE_CPU_VIABLE_MAX_GB", "4.0")
    importlib.reload(ms)


# ---------------------------------------------------------------------------
# load_model behaviour — THE regression
# ---------------------------------------------------------------------------


def _tight_vram(s):
    """Leave worst-case largest-card free ≈ 1 GB so placement pins to CPU."""
    s._loaded_cache = [_load(11.0)]


def test_hub_refuses_to_load_a_big_model_onto_cpu(svc, monkeypatch):
    """THE #5623 case: old code loaded it and every dispatch timed out at 240s."""
    s, ms = svc
    monkeypatch.setattr(ms, "_comfyui_container_running", lambda: False)
    _tight_vram(s)
    assert s.gpu_placement_options("qwen2.5:7b") == {"num_gpu": 0}  # precondition

    with patch("urllib.request.urlopen") as urlopen:
        ok = s.load_model("qwen2.5:7b")

    assert ok is False, "must refuse, not load into a guaranteed timeout"
    urlopen.assert_not_called(), "must not even issue the load request"


def test_hub_still_loads_a_small_model_on_cpu(svc, monkeypatch):
    """NEGATIVE SPACE — a blanket 'never CPU' would kill the CPU-outpost tier."""
    s, ms = svc
    monkeypatch.setattr(ms, "_comfyui_container_running", lambda: False)
    _tight_vram(s)
    monkeypatch.setattr(s, "_HUB_CPU_TIER", {"qwen2.5:1.5b"}, raising=False)

    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        ok = s.load_model("qwen2.5:1.5b")

    assert ok is True
    assert urlopen.called


def test_gpu_placement_is_never_refused(svc, monkeypatch):
    """When the model fits the GPU there is nothing to defer."""
    s, ms = svc
    monkeypatch.setattr(ms, "_comfyui_container_running", lambda: False)
    assert s.gpu_placement_options("qwen2.5:7b") == {}  # roomy box

    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        assert s.load_model("qwen2.5:7b") is True


def test_resident_model_is_never_refused(svc, monkeypatch):
    """A model already holding VRAM refreshes in place — refusing would evict it."""
    s, ms = svc
    monkeypatch.setattr(ms, "_comfyui_container_running", lambda: False)
    s._loaded_cache = [{"name": "qwen2.5:7b", "size_vram": int(5.0 * (1024**3))}]

    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        assert s.load_model("qwen2.5:7b") is True


def test_remote_node_loads_are_untouched(svc, monkeypatch):
    """Nodes manage their own placement; the hub CPU verdict must not follow them.
    Starship-246 has a real GPU — refusing there would strand the escalation target
    this fix depends on."""
    s, ms = svc
    monkeypatch.setattr(ms, "_comfyui_container_running", lambda: False)
    _tight_vram(s)

    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"{}"
        ok = s.load_model("qwen2.5:7b", ollama_url="http://100.64.0.3:11434")

    assert ok is True
    assert urlopen.called


# ---------------------------------------------------------------------------
# #5623 RESIDUAL HALF — a model ALREADY resident CPU-only on the hub
#
# The original fix guards the LOAD path. When the model is already resident nothing
# is loading, so that guard never runs: `ensure_model_ready` reported "hot on cpu",
# the dispatcher served it, and the request died on the 240s deadline. Measured
# 2026-08-16 as `qwen2.5:7b hot on cpu` -> `timed out for cap=code_review`.
# ---------------------------------------------------------------------------


def _ps(name: str, vram_gb: float, total_gb: float) -> dict:
    """An /api/ps entry. vram_gb == 0 is the stranded CPU-only case."""
    return {
        "name": name,
        "size_vram": int(vram_gb * (1024**3)),
        "size": int(total_gb * (1024**3)),
    }


def _ready(s, ms, monkeypatch, entry, *, target_host=None):
    monkeypatch.setattr(s, "_fetch_ps", lambda *a, **k: [entry], raising=False)
    return s.ensure_model_ready("_test", entry["name"], target_host)


def test_cpu_resident_big_model_on_hub_reports_not_ready(svc, monkeypatch):
    """Resident CPU-only 7B that CANNOT be migrated to the TITAN (GPU held by
    protected work) falls back to the original not-ready/escalate path (#5623)."""
    s, ms = svc
    monkeypatch.setattr(s, "_try_migrate_cpu_resident_to_gpu", lambda m: False)
    out = _ready(s, ms, monkeypatch, _ps("qwen2.5:7b", 0.0, 5.0))
    assert out["ready"] is False
    assert out["tier"] == "cpu_nonviable"


def test_cpu_resident_small_model_on_hub_stays_ready(svc, monkeypatch):
    """NEGATIVE SPACE: a small model on CPU is a real, working placement."""
    s, ms = svc
    out = _ready(s, ms, monkeypatch, _ps("qwen2.5:1.5b", 0.0, 1.3))
    assert out["ready"] is True
    assert out["tier"] == "cpu"


def test_gpu_resident_big_model_stays_ready(svc, monkeypatch):
    """Only the CPU tier is refused — a 7B on the GPU is exactly what we want."""
    s, ms = svc
    out = _ready(s, ms, monkeypatch, _ps("qwen2.5:7b", 5.0, 5.0))
    assert out["ready"] is True
    assert out["tier"] == "gpu"


def test_node_cpu_resident_big_model_is_NOT_refused(svc, monkeypatch):
    """SCOPING GUARANTEE. Starship-246 deliberately keeps qwen2.5:7b warm on ITS cpu,
    which is not the hub's pre-AVX2 Xeon. Refusing that would break a working node —
    the same shape as the hub-RAM check that once 'wrongly gated node warm-boots'."""
    s, ms = svc
    # target_host is a node RECORD (dict), not a string — `ensure_model_ready` reads
    # `target_host["hostname"]`. Passing a str raised AttributeError and is what caught
    # this test's own bug; the production guard keys off `target_host is None`, which
    # discriminates hub (None) from node (dict) correctly either way.
    out = _ready(
        s,
        ms,
        monkeypatch,
        _ps("qwen2.5:7b", 0.0, 5.0),
        target_host={"hostname": "100.64.0.3", "node_name": "Starship - Defiant - USS-246"},
    )
    assert out["ready"] is True
    assert out["tier"] == "cpu"


# ---------------------------------------------------------------------------
# TITAN migration (#6662) — a CPU-stranded 7B is moved onto the hub GPU rather
# than escalating, because the hub HAS a 12GB TITAN X. Fail-safe to the #5623
# not-ready path (test above) when the card cannot be freed.
# ---------------------------------------------------------------------------


def test_cpu_resident_big_model_migrates_to_gpu(svc, monkeypatch):
    """When the TITAN can be freed, ensure_model_ready migrates in line and
    reports ready:gpu instead of deferring to the async keep-warm."""
    s, ms = svc
    monkeypatch.setattr(s, "_try_migrate_cpu_resident_to_gpu", lambda m: True)
    out = _ready(s, ms, monkeypatch, _ps("qwen2.5:7b", 0.0, 5.0))
    assert out["ready"] is True
    assert out["tier"] == "gpu"
    assert out.get("migrated") is True


def _wire_migration(s, ms, monkeypatch, *, evict=True, load=True, vram_after=5.0, comfyui=False, size=5.9):
    calls = {"unloaded": [], "loaded": []}
    monkeypatch.setattr(ms, "_comfyui_container_running", lambda: comfyui)
    monkeypatch.setattr(s, "estimate_model_size", lambda m: size)
    monkeypatch.setattr(s, "unload_model", lambda m: calls["unloaded"].append(m) or True)
    monkeypatch.setattr(s, "ensure_capacity", lambda gb: evict)
    monkeypatch.setattr(s, "load_model", lambda m, *a, **k: calls["loaded"].append(m) or load)
    monkeypatch.setattr(s, "resident_vram_gb", lambda m: vram_after)
    return calls


def test_migration_helper_success_evicts_then_loads_on_gpu(svc, monkeypatch):
    s, ms = svc
    calls = _wire_migration(s, ms, monkeypatch)
    assert s._try_migrate_cpu_resident_to_gpu("qwen2.5:7b") is True
    assert calls["unloaded"] == ["qwen2.5:7b"]  # stranded runner dropped first (#5328)
    assert calls["loaded"] == ["qwen2.5:7b"]


def test_migration_helper_refuses_hub_cpu_tier_models(svc, monkeypatch):
    """gemma3:12b / mistral:7b etc. are DELIBERATELY CPU-pinned — never migrate them."""
    s, ms = svc
    calls = _wire_migration(s, ms, monkeypatch)
    assert s._try_migrate_cpu_resident_to_gpu("gemma3:12b") is False
    assert calls["unloaded"] == []  # nothing touched


def test_migration_helper_refuses_model_too_big_for_titan(svc, monkeypatch):
    """A model whose fit-inflated size exceeds the largest single card can't go on GPU."""
    s, ms = svc
    calls = _wire_migration(s, ms, monkeypatch, size=10.0)  # 10 * 1.4 = 14 > 12
    assert s._try_migrate_cpu_resident_to_gpu("bespoke-9b") is False
    assert calls["unloaded"] == []


def test_migration_helper_refuses_when_model_has_active_jobs(svc, monkeypatch):
    """Don't yank a runner that is actively serving."""
    s, ms = svc
    calls = _wire_migration(s, ms, monkeypatch)
    s._active_jobs["qwen2.5:7b"] = ["job-1"]
    assert s._try_migrate_cpu_resident_to_gpu("qwen2.5:7b") is False
    assert calls["unloaded"] == []


def test_migration_helper_false_when_eviction_blocked(svc, monkeypatch):
    """HIGH/PROTECTED models hold the card — ensure_capacity fails, so do we (no load)."""
    s, ms = svc
    calls = _wire_migration(s, ms, monkeypatch, evict=False)
    assert s._try_migrate_cpu_resident_to_gpu("qwen2.5:7b") is False
    assert calls["loaded"] == []  # never attempted the reload


def test_migration_helper_false_when_still_cpu_after_reload(svc, monkeypatch):
    """Reload happened but Ollama still placed it on CPU — report failure, not success."""
    s, ms = svc
    _wire_migration(s, ms, monkeypatch, vram_after=0.0)
    assert s._try_migrate_cpu_resident_to_gpu("qwen2.5:7b") is False
