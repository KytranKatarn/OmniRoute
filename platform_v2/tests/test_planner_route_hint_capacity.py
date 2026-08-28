"""The ModelQueuePlanner's route hint must never name a node that cannot hold the model.

WHY THIS EXISTS (2026-08-19, KB #291799, task #5809)
---------------------------------------------------
The planner writes PRIORITIES, never node assignments — node choice belongs to
BridgeDispatcher / model_dispatch, which enforce capacity themselves. But its log line
is what a human reads during an incident, and it used to print ``gpu_fleet[0]``
regardless of the model:

    [ModelQueuePlanner]   K.I.N. [gemma3:12b] x16 tasks -> priority 9 -> GPU fleet (USS-245)

USS-245 has 4GB VRAM / 11.7GB RAM and cannot hold a 12b under any policy. Acting on that
hint, an operator capped USS-245 — a node that was serving qwen2.5:7b at 50/50 and 32.4s
average, i.e. one of the healthiest in the fleet. The cap removed real working capacity
and was reverted the same hour.

A diagnostic that names an impossible node is worse than no diagnostic at all.
"""

# Real fleet shapes, measured 2026-08-19.
USS_245 = {  # RTX 3050, the node wrongly capped
    "node_name": "Starship - Runabout - USS-245",
    "gpu_available": True,
    "gpu_vram_gb": 4,
    "ram_gb": 11.7,
    "extra_capabilities": {},
}
USS_246 = {
    "node_name": "Starship - Defiant - USS-246",
    "gpu_available": True,
    "gpu_vram_gb": 8,
    "ram_gb": 29.4,
    "extra_capabilities": {"max_model_gb": 16},
}
HUB = {
    "node_name": "Archie Starbase",
    "gpu_available": True,
    "gpu_vram_gb": 12,
    "ram_gb": 128,
    "extra_capabilities": {},
}
OUTPOST = {
    "node_name": "Outpost - United States",
    "gpu_available": False,
    "gpu_vram_gb": None,
    "ram_gb": 7.8,
    "extra_capabilities": {"max_model_gb": 4},
}


def _fits():
    from tools.department_hq.jobs import _planner_node_fits

    return _planner_node_fits


def test_12b_is_not_offered_to_a_node_that_cannot_hold_it():
    """The exact regression: gemma3:12b requires 24GB; neither Starship can hold it."""
    fits = _fits()
    assert fits(USS_245, "gemma3:12b") is False
    assert fits(USS_246, "gemma3:12b") is False
    # ...but the hub genuinely can (CPU-demoted into 128GB), so it must NOT be excluded.
    assert fits(HUB, "gemma3:12b") is True


def test_the_route_hint_filter_excludes_the_incapable_node():
    """Composition test: the list-comprehension the planner actually runs.

    Mirrors `eligible = [n for n in candidates if _planner_node_fits(n, model)]`.
    Before the fix this list was not built at all and gpu_fleet[0] was printed blind.
    """
    fits = _fits()
    gpu_fleet = [USS_246, USS_245]  # order as the planner receives it
    eligible = [n for n in gpu_fleet if fits(n, "gemma3:12b")]
    assert eligible == [], "no Starship can hold a 12b — the hint must fall back to hub"

    eligible_7b = [n for n in gpu_fleet if fits(n, "qwen2.5:7b")]
    names = [n["node_name"] for n in eligible_7b]
    assert (
        "Starship - Runabout - USS-245" in names
    ), "USS-245 runs 7Bs at 100% (50/50 @ 32.4s) — it must NOT be filtered out"


def test_uncapped_starship_still_offered_7b():
    """Guards against over-correction: the fix must not disqualify working capacity."""
    fits = _fits()
    assert fits(USS_245, "qwen2.5:7b") is True
    assert fits(USS_245, "mistral:7b") is True
    assert fits(USS_246, "qwen2.5:7b") is True


def test_cpu_outpost_cap_blocks_oversized_but_allows_small():
    fits = _fits()
    assert fits(OUTPOST, "qwen2.5:1.5b") is True  # required 3.0 <= 4
    assert fits(OUTPOST, "llama3.2:3b") is False  # required 5.0 > 4  (the cap-of-4 trap)
    assert fits(OUTPOST, "qwen2.5:7b") is False  # required 8.0 > 4


def test_fails_OPEN_when_the_capacity_predicate_raises(monkeypatch):
    """A capacity lookup that blows up must never take the queue planner down.

    This only decorates a log line; an optimistic hint is the cheaper failure mode.
    """
    import services.fleet_resource_router as frr

    def _boom(*_a, **_k):
        raise RuntimeError("capacity lookup exploded")

    monkeypatch.setattr(frr, "can_node_run_model", _boom)
    assert _fits()(USS_245, "gemma3:12b") is True, "must fail OPEN, not raise"


def test_planner_source_still_applies_the_filter():
    """Structural guard: if someone drops the filter, the blind hint returns silently.

    Asserts the invariant (the filter is applied), not any particular wording.
    """
    import inspect

    from tools.department_hq import jobs

    src = inspect.getsource(jobs)
    assert "_planner_node_fits" in src, "the capacity filter was removed from the planner"
    # the pre-fix shape: an unconditional index into the fleet list for the hint
    assert (
        "f\"→ GPU fleet ({gpu_fleet[0]['node_name']})\"" not in src
    ), "route hint reverted to printing gpu_fleet[0] regardless of the model"
