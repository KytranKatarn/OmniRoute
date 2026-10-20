"""
Fleet-aware batch dispatcher for LLM-heavy scheduled jobs.

Discovers online fleet nodes with capable, welfare-healthy agents (30s TTL cache),
claims work sub-batches atomically via FOR UPDATE SKIP LOCKED, then fans work out
to nodes in parallel via ThreadPoolExecutor.

Usage pattern:
    from services.fleet_batch_dispatcher import get_available_nodes, claim_sub_batches, fan_out

    nodes = get_available_nodes("analyze")
    with get_db_cursor(commit=True) as (conn, cur):
        sub_batches = claim_sub_batches(
            cur, table="profile_ingest_ledger",
            state_col="state", pending_val="triaged_important", claiming_val="extracting",
            id_col="id", n_nodes=len(nodes), batch_per_node=10, account_col="account_id",
        )
    results = fan_out(
        [(nodes[i]["node_name"], sub_batches[i]) for i in range(len(nodes))],
        my_dispatch_fn,
    )

All dispatch calls must remain local_only=True for privacy-sensitive work.
Fleet nodes (Headscale mesh) are "local" — local_only does NOT disable fleet routing.

DEFAULT OFF (task #7371). `_query_available_nodes` joined a relation `agent_welfare` that exists nowhere, so
for months it failed every 5 min (logged as a warning) and returned [] — the hub-only fallback. The query now
reads the real objects (v_agent_welfare for stress/energy/rest, agent_budgets for load), but a WORKING query would
switch fleet fan-out ON for the first time, so it is gated by platform_settings:

    fleet_batch_dispatch:enabled        'true' to enable (default: off; any read error also means off)
    fleet_batch_dispatch:allowed_nodes  optional CSV of remote_nodes.node_id; empty = every approved online node

⚠️ The only caller today is the Gmail memory-vault extract worker, so enabling this sends email-derived extraction
work to fleet nodes. Eligible nodes include the rented VPSs (Citadel, Outpost-US) — set `allowed_nodes` to the LAN
Starships unless the owner has accepted that.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

_CACHE_TTL = 30.0  # seconds — re-query after 30s to pick up new/failed nodes

_FLAG_ENABLED = "fleet_batch_dispatch:enabled"
_FLAG_ALLOWED_NODES = "fleet_batch_dispatch:allowed_nodes"

_cache_lock = threading.Lock()
_cache: dict = {}  # {capability: (monotonic_ts, [node_dicts])}

# Hub sentinel: node_name=None means dispatcher uses normal hub routing.
# Appended to every result list as the always-available fallback.
_HUB_FALLBACK: dict = {"node_name": None, "node_id": "hub", "agent_id": None, "score": 0.1}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_available_nodes(capability: str, min_score: float = 0.2) -> List[dict]:
    """
    Return a list of {node_name, node_id, agent_id, score} dicts for fleet nodes
    whose agents are online, capable (have `capability` skill), and welfare-healthy.
    Hub (node_name=None) is always appended as the final fallback.
    Results are cached for 30s to avoid repeated DB round-trips per batch cycle.
    """
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(capability)
        if cached and (now - cached[0]) < _CACHE_TTL:
            return cached[1]

    nodes = _query_available_nodes(capability, min_score)
    # Always have hub as last resort
    if not any(n.get("node_id") == "hub" for n in nodes):
        nodes.append(_HUB_FALLBACK.copy())

    with _cache_lock:
        _cache[capability] = (now, nodes)

    logger.debug("fleet_batch_dispatcher: %d nodes available for %s", len(nodes), capability)
    return nodes


def invalidate_cache(capability: Optional[str] = None) -> None:
    """Force a cache refresh. Call from check_fleet_health when a node comes online/offline."""
    with _cache_lock:
        if capability:
            _cache.pop(capability, None)
        else:
            _cache.clear()


def claim_sub_batches(
    cur,
    table: str,
    state_col: str,
    pending_val: str,
    claiming_val: str,
    id_col: str,
    n_nodes: int,
    batch_per_node: int,
    account_col: Optional[str] = None,
) -> List[List[int]]:
    """
    Atomically claim n_nodes × batch_per_node rows from `table` where
    state_col = pending_val, update them to claiming_val, and split the
    claimed IDs round-robin into N lists (one per node).

    Uses a two-step approach that is safe under concurrent workers:
      1. SELECT candidates (with optional account-fairness interleaving).
      2. UPDATE those specific IDs with FOR UPDATE SKIP LOCKED — rows already
         claimed by a racing worker are simply skipped without blocking.

    account_col: when set, ROW_NUMBER() OVER (PARTITION BY account_col) ensures
    fair interleaving across accounts (no single account monopolises the batch).

    Returns N lists of int IDs. Empty lists are valid (no work for that slot).
    Caller is responsible for committing the surrounding transaction.
    """
    total = n_nodes * batch_per_node
    empty = [[] for _ in range(n_nodes)]

    if account_col:
        cur.execute(
            f"SELECT {id_col} FROM ("
            f"  SELECT {id_col},"
            f"         ROW_NUMBER() OVER (PARTITION BY {account_col} ORDER BY {id_col}) AS rn"
            f"  FROM {table} WHERE {state_col} = %s"
            f") _interleaved ORDER BY rn, {id_col} LIMIT %s",
            (pending_val, total),
        )
    else:
        cur.execute(
            f"SELECT {id_col} FROM {table}" f" WHERE {state_col} = %s ORDER BY {id_col} LIMIT %s",
            (pending_val, total),
        )

    candidate_ids = [r[id_col] for r in cur.fetchall()]
    if not candidate_ids:
        return empty

    # Atomically claim; SKIP LOCKED silently drops rows taken by concurrent workers.
    cur.execute(
        f"WITH locked AS ("
        f"  SELECT {id_col} FROM {table}"
        f"  WHERE {id_col} = ANY(%s) AND {state_col} = %s"
        f"  ORDER BY {id_col} FOR UPDATE SKIP LOCKED"
        f")"
        f" UPDATE {table}"
        f" SET {state_col} = %s, claimed_at = now()"
        f" WHERE {id_col} IN (SELECT {id_col} FROM locked)"
        f" RETURNING {id_col}",
        (candidate_ids, pending_val, claiming_val),
    )
    claimed_ids = [r[id_col] for r in cur.fetchall()]
    if not claimed_ids:
        return empty

    # Round-robin split across node buckets
    buckets: List[List[int]] = [[] for _ in range(n_nodes)]
    for i, id_ in enumerate(claimed_ids):
        buckets[i % n_nodes].append(id_)
    return buckets


def fan_out(
    node_work: List[tuple],
    dispatch_fn: Callable,
    max_workers: int = 6,
) -> List[Optional[Any]]:
    """
    Run dispatch_fn(node_name, items) for each (node_name, items) pair concurrently.
    Results are aligned to input order; None for any thread that raises.

    node_name=None means hub routing (passed straight through to dispatch_fn).
    Exceptions in individual threads are logged but do not affect other threads.
    """
    n = len(node_work)
    if n == 0:
        return []

    if n == 1:
        node_name, items = node_work[0]
        try:
            return [dispatch_fn(node_name, items)]
        except Exception as exc:
            logger.error("fleet fan-out single-thread failed: %s", exc)
            return [None]

    results: List[Optional[Any]] = [None] * n
    effective_workers = min(max_workers, n)
    with ThreadPoolExecutor(max_workers=effective_workers) as pool:
        future_to_idx = {
            pool.submit(dispatch_fn, node_name, items): idx for idx, (node_name, items) in enumerate(node_work)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.error("fleet fan-out thread[%d] (node=%s) failed: %s", idx, node_work[idx][0], exc)
    return results


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _setting(key: str) -> Optional[str]:
    """platform_settings value, or None. FAIL CLOSED: any error reads as 'unset' (so the feature stays off)."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return None
        return row["value"] if hasattr(row, "keys") else row[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("fleet_batch_dispatcher: could not read setting %s (%s); treating as unset", key, exc)
        return None


def is_enabled() -> bool:
    return str(_setting(_FLAG_ENABLED) or "").strip().lower() in ("1", "true", "on", "yes")


def _allowed_nodes() -> List[str]:
    return [t.strip() for t in str(_setting(_FLAG_ALLOWED_NODES) or "").split(",") if t.strip()]


# One row per eligible (node, agent); the best-scoring agent per node is chosen in SQL.
# Welfare comes from v_agent_welfare (stress/energy/rest cycles), load from agent_budgets. There is no
# `agent_welfare` relation and v_agent_welfare has no utilization/is_resting columns, so utilization is
# current_task_count / task_queue_limit and "resting" is an open agent_rest_cycles row (active_rest_cycles > 0).
_NODE_QUERY = """
    WITH cand AS (
        SELECT rn.id AS rn_id, rn.node_name, rn.node_id, a.id AS agent_id,
               COALESCE(w.stress_level, 0.3)::float AS stress,
               COALESCE(w.energy_level, 0.7)::float AS energy,
               LEAST(1.0, COALESCE(ab.current_task_count, 0)::float
                          / GREATEST(COALESCE(ab.task_queue_limit, 50), 1)) AS util,
               COALESCE(sk.proficiency_level, 3) AS prof
        FROM remote_nodes rn
        JOIN node_agents  na ON na.node_id = rn.id
        JOIN agents       a  ON a.id = na.hub_agent_id
        JOIN agent_skills sk ON sk.agent_id = a.id AND sk.skill_name = %s
        LEFT JOIN v_agent_welfare w ON w.agent_id = a.id
        LEFT JOIN agent_budgets  ab ON ab.agent_id = a.id
        WHERE rn.last_heartbeat > now() - INTERVAL '3 minutes'
          AND rn.approval_status = 'approved'
          AND a.shift_state IN ('active', 'winding_down')
          AND COALESCE(w.active_rest_cycles, 0) = 0
          AND COALESCE(ab.current_task_count, 0) < COALESCE(ab.task_queue_limit, 50)
          AND (%s::text[] IS NULL OR rn.node_id = ANY(%s::text[]))
    )
    SELECT DISTINCT ON (rn_id) node_name, node_id, agent_id, stress, energy, util
    FROM cand
    WHERE util < 0.95
    ORDER BY rn_id, ((1 - stress) * 0.3 + energy * 0.2 - util * 0.5 + prof * 0.05) DESC
"""


def _query_available_nodes(capability: str, min_score: float) -> List[dict]:
    """
    Query DB for online fleet nodes (heartbeat < 3min) whose best-scoring agent
    has `capability` in agent_skills and passes K.I.N. welfare thresholds.
    Returns one entry per node (highest-scoring agent wins).

    DEFAULT OFF: returns [] (hub-only fallback) unless `fleet_batch_dispatch:enabled` is set.
    """
    if not is_enabled():
        return []
    allowed = _allowed_nodes() or None
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(_NODE_QUERY, (capability, allowed, allowed))
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("fleet_batch_dispatcher: node query failed (%s): %s", capability, exc)
        return []

    result = []
    for row in rows:
        stress = float(row["stress"] if row["stress"] is not None else 0.3)
        energy = float(row["energy"] if row["energy"] is not None else 0.7)
        util = float(row["util"] if row["util"] is not None else 0.2)
        score = (1 - stress) * 0.3 + energy * 0.2 - util * 0.5
        if score >= min_score:
            result.append(
                {
                    "node_name": row["node_name"],
                    "node_id": row["node_id"],
                    "agent_id": row["agent_id"],
                    "score": round(score, 3),
                }
            )
    return result
