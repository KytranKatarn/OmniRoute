"""Shared cluster-slot admission helper (#4343 P1c).

ONE source of truth for "does the fleet have room for more BATCH work right now?", so
every batch producer (WTF backlogs, fleet_backlog_runner, delegate_task_worker,
consciousness analysis/embedding, engine autopull) can throttle at the SOURCE instead of
each hard-coding its own scalar.

Why it exists: the old `jobs.py:_wtf_cluster_slots` counted ONLY the cold
`dispatch_pending_queue` (so it was blind to the warm GPU dispatches that actually saturate
the Starships) and compared against a hard-coded `_FLEET_SLOTS=6`. This derives slots live
from `remote_nodes.max_concurrent`, counts warm in-flight from a recent `task_execution_log`
window, tracks the GPU subcluster separately, and reserves interactive headroom.

Relationship to P1a/P1b: the per-node concurrency cap + interactive reserve in
`department_dispatcher` already protect the interactive lane AT DISPATCH TIME. This helper is
the complementary SOURCE-SIDE throttle: batch producers admit fewer workers when the fleet
(or the GPU subcluster) is already hot, so less work spills onto the hub in the first place.

STRICTLY READ-ONLY + FAIL-OPEN: every function swallows DB errors and returns a permissive
result (admit=True / large free count) — it can never block or drop a dispatch. It is
advisory; it governs only the batch producers that choose to consult it.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# GPU subcluster node_ids (mirror of department_dispatcher._GPU_CLUSTER). Kept local to
# avoid a dept_hq->services import on the hot path; assert_cluster_invariants() checks it
# still matches the dispatcher's list so drift is caught, not silently tolerated.
GPU_CLUSTER_NODE_IDS = ("starship_76583490e36955ab", "starship_5501c2766526e746")

# Heavy models that run on the GPU subcluster — a batch of one of these is gpu_bound.
GPU_MODELS = {
    "gemma3:12b",
    "qwen2.5:7b",
    "mistral:7b",
    "dolphin3:latest",
    "qwen2.5-coder:7b",
    "qwen2.5vl:7b",
}

# Defaults (overridable via platform_settings cluster:slots:* — no deploy to tune).
_DEFAULTS = {
    "cluster:slots:headroom": 1,  # cluster-wide interactive reservation
    "cluster:slots:gpu_headroom": 1,  # GPU-subcluster interactive reservation
    "cluster:slots:warm_window_s": 90,  # task_execution_log recency proxy for warm in-flight
}


def _setting_int(cur, key: str) -> int:
    """Read an int platform_setting, fail-open to the module default."""
    default = _DEFAULTS[key]
    try:
        cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        if not row:
            return default
        val = row["value"] if isinstance(row, dict) else row[0]
        return int(str(val).strip())
    except Exception:
        return default


def _run(cur, fn):
    """Run fn(cur) with an injected cursor or a fresh one (agent_load_service pattern)."""
    if cur is not None:
        return fn(cur)
    from database import get_db_cursor

    with get_db_cursor() as (_conn, c):
        return fn(c)


def get_cluster_slots(cur=None) -> dict:
    """Live free-slot accounting for the online+approved fleet.

    Returns a dict: total_slots / total_inflight / cluster_free, gpu_slots / gpu_inflight /
    gpu_free, and by_node {node_id: {db_id,name,max,warm,free}}. Warm in-flight is a recent
    task_execution_log proxy (the table logs on completion, so this lags — same inherent
    limit as the dispatcher's 5-min balancer, narrowed to ~90s). Cold queued/running work is
    counted cluster-wide (dispatch_pending_queue rows carry no reliable node hint). Fail-open
    to a permissive (all-free) view on any error.
    """

    def _q(c):
        win = _setting_int(c, "cluster:slots:warm_window_s")
        c.execute(
            """
            WITH nodes AS (
                SELECT id, node_id, node_name, max_concurrent
                FROM remote_nodes
                WHERE status = 'online' AND approval_status = 'approved'
            ),
            warm AS (
                -- Concurrency ESTIMATE, not a raw completion count: busy-time over the window
                -- = SUM(duration_ms)/window_ms ≈ avg streams busy. A raw COUNT over-counts a
                -- node that churned many short tasks (verified: 129 completions in 90s on a
                -- 35-slot fleet that was actually near-idle). CEIL so any activity reads >=1.
                SELECT node_used_id AS nid,
                       CEIL(SUM(COALESCE(duration_ms, 0))::float / (%s * 1000.0)) AS n
                FROM task_execution_log
                WHERE created_at > NOW() - make_interval(secs => %s)
                  AND node_used_id IS NOT NULL
                GROUP BY node_used_id
            )
            SELECT n.node_id, n.id AS db_id, n.node_name, n.max_concurrent,
                   COALESCE(w.n, 0) AS warm
            FROM nodes n
            LEFT JOIN warm w ON w.nid = n.id
            """,
            (win, win),
        )
        rows = c.fetchall() or []
        # Cluster-wide cold work OCCUPYING a stream = status='running' only. 'queued' rows are
        # waiting backlog (not consuming a slot) — counting them over-throttled the gate.
        c.execute("SELECT COUNT(*) AS n FROM dispatch_pending_queue WHERE status = 'running'")
        cr = c.fetchone()
        total_cold = int((cr["n"] if isinstance(cr, dict) else cr[0]) or 0)
        return rows, total_cold

    try:
        rows, total_cold = _run(cur, _q)
    except Exception as exc:  # fail-open: pretend the fleet is wide open
        logger.debug("cluster_slots.get_cluster_slots failed (fail-open): %s", exc)
        return {
            "total_slots": 999,
            "total_inflight": 0,
            "cluster_free": 999,
            "gpu_slots": 999,
            "gpu_inflight": 0,
            "gpu_free": 999,
            "by_node": {},
            "degraded": True,
        }

    by_node = {}
    total_slots = total_warm = 0
    gpu_slots = gpu_warm = 0
    for r in rows:
        nid = r["node_id"]
        mx = int(r["max_concurrent"] or 0)
        # Cap the duration-based estimate at the node's stream count: one long-running task
        # that just completed within the window can't mean more concurrency than max streams.
        warm = min(mx, int(r["warm"] or 0))
        by_node[nid] = {
            "db_id": r["db_id"],
            "name": r["node_name"],
            "max": mx,
            "warm": warm,
            "free": max(0, mx - warm),
        }
        total_slots += mx
        total_warm += warm
        if nid in GPU_CLUSTER_NODE_IDS:
            gpu_slots += mx
            gpu_warm += warm

    total_inflight = total_warm + total_cold
    return {
        "total_slots": total_slots,
        "total_inflight": total_inflight,
        "cluster_free": max(0, total_slots - total_inflight),
        "gpu_slots": gpu_slots,
        "gpu_inflight": gpu_warm,  # cold has no node hint; GPU warm is the live signal
        "gpu_free": max(0, gpu_slots - gpu_warm),
        "by_node": by_node,
        "degraded": False,
    }


def should_admit_batch(
    target_model: Optional[str] = None,
    *,
    want: int = 1,
    gpu_bound: Optional[bool] = None,
    cur=None,
) -> Tuple[bool, int, dict]:
    """Decide whether a batch producer may fire, and how many workers to admit.

    Returns (admit, recommended_workers, slots). The relevant free pool (GPU subcluster when
    the work is gpu_bound, else the whole cluster) must exceed the matching interactive
    headroom; recommended_workers = clamp(free - headroom, 0, want). Fail-open to
    (True, want, {}) on any error so a measurement bug never stalls a producer.
    """
    try:
        slots = get_cluster_slots(cur=cur)
        if slots.get("degraded"):
            return True, want, slots
        is_gpu = gpu_bound
        if is_gpu is None:
            is_gpu = bool(target_model) and target_model in GPU_MODELS

        def _hd(c):
            key = "cluster:slots:gpu_headroom" if is_gpu else "cluster:slots:headroom"
            return _setting_int(c, key)

        headroom = _run(cur, _hd)
        free = slots["gpu_free"] if is_gpu else slots["cluster_free"]
        recommended = max(0, min(want, free - headroom))
        return (recommended > 0, recommended, slots)
    except Exception as exc:
        logger.debug("cluster_slots.should_admit_batch failed (fail-open): %s", exc)
        return True, want, {}


def assert_cluster_invariants(cur=None) -> list:
    """Drift guard (advisory): returns a list of warning strings (empty = healthy).

    Catches the recurring fleet traps (fleet.md): a GPU_CLUSTER_NODE_ID that no longer maps
    to a remote_nodes row, and divergence from department_dispatcher._GPU_CLUSTER. NEVER
    raises into a caller — returns warnings to be logged/notified by an observer job.
    """
    warnings: list = []
    try:

        def _q(c):
            c.execute("SELECT node_id FROM remote_nodes")
            return {(r["node_id"] if isinstance(r, dict) else r[0]) for r in (c.fetchall() or [])}

        known = _run(cur, _q)
        for nid in GPU_CLUSTER_NODE_IDS:
            if nid not in known:
                warnings.append(f"GPU_CLUSTER node_id {nid!r} not found in remote_nodes")
        try:
            from tools.department_hq.services.department_dispatcher import _GPU_CLUSTER

            if set(_GPU_CLUSTER) != set(GPU_CLUSTER_NODE_IDS):
                warnings.append(
                    f"GPU cluster drift: cluster_slots={set(GPU_CLUSTER_NODE_IDS)} != "
                    f"dispatcher._GPU_CLUSTER={set(_GPU_CLUSTER)}"
                )
        except Exception as exc:
            warnings.append(f"could not compare dispatcher._GPU_CLUSTER: {exc}")
    except Exception as exc:
        logger.debug("cluster_slots.assert_cluster_invariants failed: %s", exc)
    return warnings
