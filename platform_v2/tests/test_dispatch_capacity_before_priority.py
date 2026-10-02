"""Dispatch must prefer a node that has ROOM over a node that merely outranks it.

Starbase - A.R.C.H.I.E. is the hub (remote_nodes.mesh_ip = 'host.docker.internal',
deployment_mode 'starbase', node_role 'agent'), not a fleet member, and carries the
highest bridge_priority (100 vs 50). Two ranking paths therefore handed it work
whether it was idle or pinned at max_concurrent:

  1. _get_warm_models_nodes took the FIRST row per model, ordered only by
     `bridge_priority DESC` -- no load term at all.
  2. score_node_for_model folded load in as `-0.5 * (cur_load / max_conc)`, a 0.5
     penalty at full saturation, which the +1.2 GPU-perf bonus outweighs.

Work then queued behind a saturated GPU and hit the 600s dispatch timeout --
94 of 200 code_review timeouts in the 7 days to 2026-10-02 were on that host.

The rule under test: capacity is a GATE, priority only breaks ties among nodes
that have room. Deliberately soft -- a saturated node is deprioritised, never
disqualified, because if every node is full the queue still has to go somewhere.
"""

from __future__ import annotations

import re
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
DISPATCH = PLATFORM / "services" / "model_dispatch_service.py"
ROUTER = PLATFORM / "services" / "fleet_resource_router.py"


def _node(load: int, cap: int, **over) -> dict:
    n = {
        "gpu_available": True,
        "gpu_vram_gb": 12.0,
        "ram_gb": 32.0,
        "current_load": load,
        "max_concurrent": cap,
        "priority": 10,
        "last_heartbeat": None,
        "extra_capabilities": {},
    }
    n.update(over)
    return n


class TestScorerWasAlreadyCapacityAware:
    """score_node_for_model already drops saturated nodes — assert it KEEPS doing so.

    Measured while building this: a -1.5 saturation penalty was tried there and made
    load=5/5 score -0.44, which `return score if score > 0 else None` turned into a
    hard None. That is the opposite of the 'penalty only, never disqualify' the
    surrounding comments promise, and it would starve the queue when every node is
    full. The real gap is the SQL ordering below, not the scorer.
    """

    def _score(self, load: int, cap: int = 5) -> float:
        import sys

        sys.path.insert(0, str(PLATFORM))
        from services.fleet_resource_router import score_node_for_model

        node = {
            "gpu_available": True,
            "gpu_vram_gb": 12.0,
            "ram_gb": 32.0,
            "current_load": load,
            "max_concurrent": cap,
            "priority": 10,
            "last_heartbeat": None,
            "extra_capabilities": {},
        }
        s = score_node_for_model(node, "qwen2.5:7b")
        assert s is not None, f"load={load}/{cap} disqualified; that is not this rule"
        return s

    def test_score_falls_monotonically_with_load(self):
        scores = [self._score(l) for l in range(5)]
        assert scores == sorted(scores, reverse=True), f"not monotonic: {scores}"

    def test_a_fully_loaded_node_stays_eligible(self):
        """The scorer must never hard-None on load alone — the queue needs a target."""
        assert self._score(5) > 0, "saturated node scored <= 0 and would be disqualified"

    def test_no_saturation_penalty_was_left_in_the_scorer(self):
        """Pin the reverted attempt so it cannot be reintroduced by 'improvement'."""
        src = ROUTER.read_text()
        assert "if cur_load >= max_conc:" not in src, "a saturation gate belongs in the SQL ordering, not the scorer"


class TestWarmModelOrdering:
    def _sql_orderings(self) -> list[str]:
        src = DISPATCH.read_text()
        return re.findall(r"ORDER BY[^)]*?rn\.bridge_priority", src, re.S)

    def test_both_queries_put_capacity_before_priority(self):
        src = DISPATCH.read_text()
        orderings = re.findall(r"ORDER BY\s*\(rn\.current_load >= rn\.max_concurrent\)[^;]*", src)
        assert len(orderings) >= 2, f"expected the capacity key in both warm-model queries, found {len(orderings)}"
        for o in orderings:
            sat = o.index("(rn.current_load >= rn.max_concurrent)")
            pri = o.index("rn.bridge_priority")
            assert sat < pri, f"capacity must sort BEFORE bridge_priority: {o!r}"

    def test_saturated_nodes_are_not_filtered_out(self):
        """Soft gate: the boolean reorders, it must not remove rows from the result."""
        src = DISPATCH.read_text()
        assert (
            "AND rn.current_load < rn.max_concurrent" not in src
        ), "a hard capacity filter would starve the queue when every node is full"


class TestRealFleetShape:
    """The ordering must express the intended rule against the actual fleet."""

    def test_starbase_outranks_nodes_only_while_it_has_room(self):
        src = DISPATCH.read_text()
        assert re.search(
            r"ORDER BY\s*\(rn\.current_load >= rn\.max_concurrent\)\s*ASC,\s*" r"rn\.bridge_priority DESC",
            src,
        ), "capacity-first ordering not found in the expected shape"
