"""Unit tests for services.fleet_jobs._kin_fleet_warmth_policy (#3532-v2).

Verifies the K.I.N. demand + welfare + rest-aware warmth policy without a live
DB by stubbing get_db_cursor with a FakeCursor that returns canned rows per
query and records the INSERTs into dispatch_pending_queue.
"""

import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.fleet_jobs as fleet_jobs


class FakeCursor:
    """Minimal cursor: returns canned results by matching the SQL, records inserts."""

    def __init__(self, nodes, demand_by_node, welfare_by_node, inflight_node_ids=()):
        self.nodes = nodes
        self.demand_by_node = demand_by_node  # node_id -> [(model, count)]
        self.welfare_by_node = welfare_by_node  # node_id -> {assigned, on_shift}
        self.inflight = set(inflight_node_ids)
        self.inserts = []  # list of (model, node_id)
        self._mode = None
        self._params = None

    def execute(self, sql, params=None):
        self._params = params or ()
        s = " ".join(sql.split())
        if "FROM remote_nodes" in s:
            self._mode = "nodes"
        elif "FROM task_execution_log" in s:
            self._mode = "demand"
        elif "FROM node_agents" in s:
            self._mode = "welfare"
        elif "FROM dispatch_pending_queue" in s:
            self._mode = "dedup"
        elif "INSERT INTO dispatch_pending_queue" in s:
            # params = (model, node_id)
            self.inserts.append((params[0], params[1]))
            self._mode = "insert"
        elif "INSERT INTO governance_audit_log" in s:
            self._mode = "audit"
        else:
            self._mode = "other"

    def fetchall(self):
        if self._mode == "nodes":
            return [dict(n) for n in self.nodes]
        if self._mode == "demand":
            node_id = self._params[0]
            return [{"model_used": m, "n": c} for m, c in self.demand_by_node.get(node_id, [])]
        return []

    def fetchone(self):
        if self._mode == "welfare":
            node_id = self._params[0]
            return self.welfare_by_node.get(node_id, {"assigned": 0, "on_shift": 0})
        if self._mode == "dedup":
            node_id = self._params[0]
            return (1,) if node_id in self.inflight else None
        if self._mode == "audit":
            return None
        return None


def _patch(monkeypatch, cursor, rest_active):
    @contextmanager
    def fake_get_db_cursor(commit=False):
        yield (None, cursor)

    # _kin_fleet_warmth_policy does `from database import get_db_cursor`
    import database

    monkeypatch.setattr(database, "get_db_cursor", fake_get_db_cursor)
    # and `from tools.department_hq.fleet_helpers import is_fleet_rest_active`
    import tools.department_hq.fleet_helpers as fh

    monkeypatch.setattr(fh, "is_fleet_rest_active", lambda: rest_active)


# ⚠️ The hardware fields are LOAD-BEARING, not decoration (#5947).
# _kin_fleet_warmth_policy gates every candidate through
# fleet_resource_router.can_node_run_model(node, model), which reads gpu_available /
# gpu_vram_gb / ram_gb / extra_capabilities straight off these rows. A fixture without
# them presents as gpu 0 / ram 0, the predicate refuses EVERY model, and the policy
# queues nothing — which is exactly how these tests started failing: three assertions
# against an empty set, with the production code entirely correct.
# Values mirror the real fleet (see .claude/rules/fleet.md).
STARSHIP = {
    "id": 115,
    "node_name": "Starship-246",
    "deployment_mode": "starship",
    "models": ["qwen2.5:7b", "qwen2.5:1.5b"],
    "gpu_available": True,
    "gpu_vram_gb": 8.0,  # RTX 3070
    "ram_gb": 32.0,
    "ollama_available": True,
    "extra_capabilities": {},
}
OUTPOST = {
    "id": 93,
    "node_name": "outpost-us",
    "deployment_mode": "outpost",
    "models": ["qwen2.5:1.5b", "llama3.2:3b"],
    "gpu_available": False,  # CPU-only VPS
    "gpu_vram_gb": 0,
    "ram_gb": 7.8,
    "ollama_available": True,
    "extra_capabilities": {"max_model_gb": 4},
}


def test_rest_gate_skips_starship_keeps_outpost(monkeypatch):
    """During the rest window, starships get NO warmth; always-on outposts still do."""
    cur = FakeCursor(
        nodes=[STARSHIP, OUTPOST],
        demand_by_node={93: [("qwen2.5:1.5b", 243)], 115: [("qwen2.5:7b", 122)]},
        welfare_by_node={},
    )
    _patch(monkeypatch, cur, rest_active=True)
    fleet_jobs._kin_fleet_warmth_policy()

    node_ids = {nid for _, nid in cur.inserts}
    assert 115 not in node_ids, "resting starship must not be warmed"
    assert 93 in node_ids, "always-on outpost must still be warmed"


def test_demand_picks_top_model(monkeypatch):
    """A node warms its top recently-dispatched model, not a blanket smallest pilot."""
    cur = FakeCursor(
        nodes=[STARSHIP],
        demand_by_node={115: [("qwen2.5:7b", 122), ("mistral:7b", 17)]},
        welfare_by_node={},
    )
    _patch(monkeypatch, cur, rest_active=False)
    fleet_jobs._kin_fleet_warmth_policy()

    models = [m for m, _ in cur.inserts]
    assert "qwen2.5:7b" in models, "top-demanded model should be warmed"
    # dedup breaks after the first enqueue per node, so only the #1 model lands
    assert cur.inserts[0] == ("qwen2.5:7b", 115)


def test_zero_demand_applies_pilot_floor(monkeypatch):
    """No recent demand but on-shift agents → smallest-model pilot floor fires."""
    cur = FakeCursor(
        nodes=[OUTPOST],
        demand_by_node={},  # no demand
        welfare_by_node={93: {"assigned": 44, "on_shift": 39}},
    )
    _patch(monkeypatch, cur, rest_active=False)
    fleet_jobs._kin_fleet_warmth_policy()

    assert cur.inserts == [("qwen2.5:1.5b", 93)], "smallest available model as pilot floor"


def test_zero_demand_all_rested_roster_skips(monkeypatch):
    """No demand AND every assigned agent rested → node left cold (welfare gate)."""
    cur = FakeCursor(
        nodes=[OUTPOST],
        demand_by_node={},
        welfare_by_node={93: {"assigned": 12, "on_shift": 0}},
    )
    _patch(monkeypatch, cur, rest_active=False)
    fleet_jobs._kin_fleet_warmth_policy()

    assert cur.inserts == [], "fully-rested roster with no demand gets no warmth"


def test_dedup_skips_node_with_inflight_warmth(monkeypatch):
    """An already-queued kin_warmth task suppresses a duplicate enqueue."""
    cur = FakeCursor(
        nodes=[OUTPOST],
        demand_by_node={93: [("qwen2.5:1.5b", 243)]},
        welfare_by_node={},
        inflight_node_ids=(93,),
    )
    _patch(monkeypatch, cur, rest_active=False)
    fleet_jobs._kin_fleet_warmth_policy()

    assert cur.inserts == [], "no enqueue when a warmth task is already in flight"


def test_a_node_that_cannot_FIT_the_model_is_not_warmed(monkeypatch):
    """The capacity gate (#5947) must still bind — pinned so the fixture update above
    cannot silently disable it.

    Adding the hardware fields to STARSHIP/OUTPOST is what made these tests pass again;
    without this test, a future fixture that quietly satisfies everything would hide a
    regression in the gate itself. Here the node is real but TOO SMALL for the model it
    demands, so nothing may be queued for it.
    """
    tiny = {
        "id": 120,
        "node_name": "Starship-245",
        "deployment_mode": "starship",
        "models": ["qwen2.5:7b"],
        "gpu_available": True,
        "gpu_vram_gb": 4.0,  # RTX 3050 — cannot hold a 7B
        "ram_gb": 3.0,  # and no room to CPU-demote either
        "ollama_available": True,
        "extra_capabilities": {"max_model_gb": 4},
    }
    cur = FakeCursor(
        nodes=[tiny],
        demand_by_node={120: [("qwen2.5:7b", 99)]},
        welfare_by_node={},
    )
    _patch(monkeypatch, cur, rest_active=False)
    fleet_jobs._kin_fleet_warmth_policy()

    assert cur.inserts == [], "a node that cannot fit the model must not be warmed for it"


def test_the_capacity_predicate_is_actually_consulted():
    """Wiring, not intent: the gate must be CALLED from the warm path.

    `can_node_run_model` existed and was correct long before anything in warm-up called
    it — the #5194/#5862/#5863 shape. This asserts the call site still exists.
    """
    import inspect

    src = inspect.getsource(fleet_jobs)
    assert "can_node_run_model" in src, "warm-up must consult the capacity predicate"
