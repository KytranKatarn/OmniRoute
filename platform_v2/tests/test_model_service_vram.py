"""
VRAM budgeting regression tests — task #5271.

The hub gained a TITAN X 12 GB on 2026-07-25, taking it to 20 GB (TITAN 12 +
Quadro M4000 8). model_service kept a single hardcoded
`_DEFAULT_VRAM_BUDGET_GB = 8.0  # Quadro M4000 full 8 GB`, so for two days:

    get_available_vram()          -> 5.44   (measured live, TITAN invisible)
    qwen2.5:7b needs 4.2 * 1.4    -> 5.88
    5.44 >= 5.88                  -> False  -> pin_to_cpu -> options.num_gpu = 0

i.e. the platform ACTIVELY forced CPU while both GPUs sat idle. These tests pin
the two properties that fix requires, and would both FAIL against the old
single-constant implementation.
"""

import importlib
import sys

import pytest

sys.path.insert(0, "/app")


@pytest.fixture()
def svc(monkeypatch):
    """A ModelService with a stubbed loaded-model cache (no Ollama contact)."""
    monkeypatch.setenv("ARCHIE_VRAM_TOTAL_GB", "20.0")
    monkeypatch.setenv("ARCHIE_VRAM_LARGEST_GPU_GB", "12.0")
    import services.model_service as ms

    importlib.reload(ms)  # re-read the env-driven constants

    s = ms.ModelService()
    s._loaded_cache = []
    monkeypatch.setattr(s, "_is_cache_fresh", lambda: True)
    return s, ms


def _load(gb: float) -> dict:
    return {"name": f"stub-{gb}", "size_vram": int(gb * (1024**3))}


def test_aggregate_vram_counts_both_cards(svc):
    """An empty box reports the SUM, not just the Quadro. Old code said 8.0."""
    s, _ = svc
    assert s.get_available_vram() == pytest.approx(20.0)


def test_single_model_budget_is_capped_by_largest_card(svc):
    """
    20 GB free aggregate does NOT mean one model may use 20 GB — it cannot span
    cards (compute capability 6.1 vs 5.2). The per-model budget is the biggest
    single device.
    """
    s, _ = svc
    assert s.get_available_vram() == pytest.approx(20.0)
    assert s.get_gpu_fit_budget() == pytest.approx(12.0)


def test_single_model_budget_respects_vram_already_held(svc):
    """
    14 GB resident leaves 6 GB aggregate. The per-model budget must be LOWER
    still (0.0 here): worst case the largest card absorbed 12 of those 14, so no
    single card can be assumed to have room. Guards against a fix that only ever
    returns the card size.
    """
    s, _ = svc
    s._loaded_cache = [_load(14.0)]
    assert s.get_available_vram() == pytest.approx(6.0)
    assert s.get_gpu_fit_budget() == pytest.approx(0.0)


def test_budget_assumes_worst_case_card_concentration(svc):
    """
    F.O.R.G.E.'s REQUEST CHANGES on PR #2500, made concrete.

    /api/ps never says WHICH card holds a model. With 8 GB resident, subtracting
    only from the aggregate yields min(12, 12) = 12 GB — but if all 8 GB sit on
    the TITAN it has just 4 GB free, so a ~10 GB model would be told it fits when
    NEITHER card can hold it (partial offload / warm-set eviction).

    Budget must therefore assume the pessimal distribution: 12 - 8 = 4.
    """
    s, _ = svc
    s._loaded_cache = [_load(8.0)]
    assert s.get_available_vram() == pytest.approx(12.0)  # aggregate is still 12
    assert s.get_gpu_fit_budget() == pytest.approx(4.0)  # but ONE model gets 4
    assert s.get_gpu_fit_budget() < 10.0, "a 10 GB model must NOT look loadable"


def test_seven_b_is_gpu_eligible_on_an_idle_box(svc):
    """
    THE REGRESSION. qwen2.5:7b is ~4.2 GB estimated; with _GPU_FIT_HEADROOM=1.4
    it needs 5.88 GB. Under the old 8 GB constant with ~2.7 GB resident the
    budget was 5.44 -> pinned to CPU. It must now be GPU-eligible.
    """
    s, ms = svc
    s._loaded_cache = [_load(2.7)]
    needed = s.estimate_model_size("qwen2.5:7b") * ms._GPU_FIT_HEADROOM
    assert s.get_gpu_fit_budget() >= needed, (
        f"qwen2.5:7b needs {needed:.2f} GB but budget is " f"{s.get_gpu_fit_budget():.2f} GB — still pinning to CPU"
    )


def test_model_larger_than_any_single_card_is_not_gpu_eligible(svc):
    """
    The safety half: aggregate 20 GB must never make a 13 GB model look loadable
    when the largest card is 12 GB. Writing the SUM into a per-model check is the
    documented footgun in .claude/rules/fleet.md.
    """
    s, _ = svc
    assert s.get_gpu_fit_budget() < 13.0 * 1.0


def test_capacity_numbers_are_env_overridable(monkeypatch):
    """A hardware change must be a config edit, not a code edit — a bare constant
    is what went stale for two days."""
    monkeypatch.setenv("ARCHIE_VRAM_TOTAL_GB", "48.0")
    monkeypatch.setenv("ARCHIE_VRAM_LARGEST_GPU_GB", "24.0")
    import services.model_service as ms

    importlib.reload(ms)
    try:
        assert ms._VRAM_TOTAL_GB == pytest.approx(48.0)
        assert ms._VRAM_LARGEST_GPU_GB == pytest.approx(24.0)
    finally:
        monkeypatch.delenv("ARCHIE_VRAM_TOTAL_GB", raising=False)
        monkeypatch.delenv("ARCHIE_VRAM_LARGEST_GPU_GB", raising=False)
        importlib.reload(ms)
