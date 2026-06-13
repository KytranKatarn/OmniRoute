"""Regression: fleet node selection must be CAPACITY-WEIGHTED, not raw task-count.

Guards the 2026-06-13 cluster-saturation fix. `_find_fleet_agent_for_hub_agent`
(the stationed-agent "node_preferred" path, which is what actually routes the WTF
fact-check team) tie-broke between GPU fleet nodes by raw 5-minute task COUNT. That
handed the weak 1-stream RTX 3050 (Starship-245) the SAME task count as the strong
3-stream RTX 3070 (Starship-246) -> 245 saturated (~76% busy) while 246 idled (~19%)
and overflow spilled to the slow hub CPU. The tiebreak must divide the load by each
node's max_concurrent so a 3-stream node absorbs ~3x a 1-stream node before they tie.

`department_dispatcher.py` has import-time side effects, so (like
tests/test_capability_routing.py) we assert against the module source.
"""

import os

_DISPATCHER = os.path.join(
    os.path.dirname(__file__),
    "..",
    "tools",
    "department_hq",
    "services",
    "department_dispatcher.py",
)


def _source():
    with open(_DISPATCHER, "r", encoding="utf-8") as fh:
        return fh.read()


def test_node_selection_tiebreak_is_capacity_weighted():
    src = _source()
    assert (
        "COALESCE(load_5m.task_count, 0)::float / GREATEST(rn.max_concurrent, 1)" in src
    ), "fleet node-selection tiebreak must weight 5-min load by per-node max_concurrent"


def test_bare_taskcount_tiebreak_removed():
    src = _source()
    # The raw-count tiebreak that saturated the weak node must be gone.
    assert (
        "COALESCE(load_5m.task_count, 0) ASC" not in src
    ), "raw (non-capacity-weighted) task_count tiebreak reintroduced — re-saturates the weak node"
