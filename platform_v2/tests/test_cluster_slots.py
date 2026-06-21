"""Unit tests for services.cluster_slots (#4343 P1c).

Pure-logic tests via a SQL-routing fake cursor — no live DB needed. Covers the slot math
(warm/cold accounting, GPU subcluster split), should_admit_batch decisions (cluster vs
gpu_bound, headroom, want clamp), and the fail-open contract.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from services import cluster_slots  # noqa: E402


class FakeCursor:
    """Routes execute() by SQL fragment and returns canned rows.

    nodes: list of dicts {node_id, db_id, node_name, max_concurrent, warm_ms}
    cold_running: int (dispatch_pending_queue status='running' count)
    settings: {key: value} overrides for platform_settings reads
    raise_on: substring that, if present in a SQL, raises (to exercise fail-open)
    """

    def __init__(self, nodes, cold_running=0, settings=None, raise_on=None):
        self._nodes = nodes
        self._cold = cold_running
        self._settings = settings or {}
        self._raise_on = raise_on
        self._last = None

    def execute(self, sql, params=None):
        if self._raise_on and self._raise_on in sql:
            raise RuntimeError("simulated DB failure")
        self._last = (sql, params)

    def fetchone(self):
        sql = self._last[0]
        if "platform_settings" in sql:
            key = self._last[1][0]
            if key in self._settings:
                return {"value": str(self._settings[key])}
            return None  # → helper falls back to its module default
        if "dispatch_pending_queue" in sql:
            return {"n": self._cold}
        if "remote_nodes" in sql:  # assert_cluster_invariants node_id set fetch path
            return None
        return None

    def fetchall(self):
        sql = self._last[0]
        if "WITH nodes" in sql:
            # window seconds is params[0]; warm n = CEIL(warm_ms / (win*1000))
            win = float(self._last[1][0])
            import math

            out = []
            for n in self._nodes:
                warm_n = math.ceil(n.get("warm_ms", 0) / (win * 1000.0)) if n.get("warm_ms") else 0
                out.append(
                    {
                        "node_id": n["node_id"],
                        "db_id": n["db_id"],
                        "node_name": n["node_name"],
                        "max_concurrent": n["max_concurrent"],
                        "warm": warm_n,
                    }
                )
            return out
        if "remote_nodes" in sql:  # invariants: distinct node_id set
            return [{"node_id": n["node_id"]} for n in self._nodes]
        return []


GPU_A = cluster_slots.GPU_CLUSTER_NODE_IDS[0]
GPU_B = cluster_slots.GPU_CLUSTER_NODE_IDS[1]


def _nodes_idle_fleet():
    # hub busy (5/5), one outpost idle, one GPU node idle, one GPU node busy.
    return [
        {"node_id": "archie-starbase", "db_id": 68, "node_name": "hub", "max_concurrent": 5, "warm_ms": 5 * 90 * 1000},
        {"node_id": "outpost_us", "db_id": 93, "node_name": "us", "max_concurrent": 5, "warm_ms": 0},
        {"node_id": GPU_A, "db_id": 115, "node_name": "USS-246", "max_concurrent": 3, "warm_ms": 0},
        {"node_id": GPU_B, "db_id": 120, "node_name": "USS-245", "max_concurrent": 1, "warm_ms": 90 * 1000},
    ]


def test_get_cluster_slots_math():
    cur = FakeCursor(_nodes_idle_fleet(), cold_running=0)
    s = cluster_slots.get_cluster_slots(cur=cur)
    assert s["degraded"] is False
    assert s["total_slots"] == 14  # 5+5+3+1
    # hub warm capped at 5, USS-245 warm=1 → total warm 6; cold 0 → inflight 6
    assert s["total_inflight"] == 6
    assert s["cluster_free"] == 8
    assert s["gpu_slots"] == 4  # 3 + 1
    assert s["gpu_inflight"] == 1  # only USS-245 busy
    assert s["gpu_free"] == 3


def test_warm_estimate_caps_at_max_concurrent():
    # A single very long completed task (10 min) on a 3-stream node must not exceed 3.
    nodes = [{"node_id": GPU_A, "db_id": 115, "node_name": "USS-246", "max_concurrent": 3, "warm_ms": 600 * 1000}]
    cur = FakeCursor(nodes)
    s = cluster_slots.get_cluster_slots(cur=cur)
    assert s["by_node"][GPU_A]["warm"] == 3  # capped, not 6.67
    assert s["by_node"][GPU_A]["free"] == 0


def test_cold_running_counts_against_cluster():
    cur = FakeCursor(_nodes_idle_fleet(), cold_running=4)
    s = cluster_slots.get_cluster_slots(cur=cur)
    assert s["total_inflight"] == 10  # warm 6 + cold 4
    assert s["cluster_free"] == 4


def test_should_admit_generic_admits_when_room():
    cur = FakeCursor(_nodes_idle_fleet(), cold_running=0)
    admit, rec, _ = cluster_slots.should_admit_batch("llama3.2:3b", want=3, cur=cur)
    # cluster_free 8, headroom 1 → recommend min(3, 7) = 3
    assert admit is True
    assert rec == 3


def test_should_admit_gpu_defers_when_subcluster_full():
    # GPU subcluster saturated: both GPU nodes fully warm.
    nodes = [
        {"node_id": GPU_A, "db_id": 115, "node_name": "USS-246", "max_concurrent": 3, "warm_ms": 3 * 90 * 1000},
        {"node_id": GPU_B, "db_id": 120, "node_name": "USS-245", "max_concurrent": 1, "warm_ms": 90 * 1000},
        {"node_id": "outpost_us", "db_id": 93, "node_name": "us", "max_concurrent": 5, "warm_ms": 0},
    ]
    cur = FakeCursor(nodes)
    admit, rec, _ = cluster_slots.should_admit_batch("gemma3:12b", want=2, cur=cur)
    assert admit is False  # gpu_free 0 <= headroom 1
    assert rec == 0


def test_should_admit_gpu_bound_inferred_from_model():
    # gemma3:12b is in GPU_MODELS → treated as gpu_bound even without the flag.
    nodes = [
        {"node_id": GPU_A, "db_id": 115, "node_name": "USS-246", "max_concurrent": 3, "warm_ms": 0},
        {"node_id": GPU_B, "db_id": 120, "node_name": "USS-245", "max_concurrent": 1, "warm_ms": 0},
    ]
    cur = FakeCursor(nodes)
    admit, rec, _ = cluster_slots.should_admit_batch("gemma3:12b", want=5, cur=cur)
    # gpu_free 4, headroom 1 → recommend min(5,3)=3
    assert admit is True
    assert rec == 3


def test_fail_open_on_db_error():
    cur = FakeCursor(_nodes_idle_fleet(), raise_on="WITH nodes")
    s = cluster_slots.get_cluster_slots(cur=cur)
    assert s["degraded"] is True
    assert s["cluster_free"] >= 999
    # should_admit_batch must also stay permissive when slots are degraded
    admit, rec, _ = cluster_slots.should_admit_batch("gemma3:12b", want=2, cur=cur)
    assert admit is True
    assert rec == 2


def test_headroom_setting_override():
    cur = FakeCursor(_nodes_idle_fleet(), settings={"cluster:slots:headroom": 5})
    admit, rec, _ = cluster_slots.should_admit_batch("llama3.2:3b", want=10, cur=cur)
    # cluster_free 8, headroom 5 → recommend 3
    assert rec == 3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
