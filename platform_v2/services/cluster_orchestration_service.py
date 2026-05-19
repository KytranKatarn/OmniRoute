"""Cluster Orchestration Service — score engine, config hierarchy, state cache.

Imported by:
  cluster_orchestration_worker (jobs.py) — writes agent_overflow_state each cycle
  department_coordinator.select_agent() — reads overflow cache for +0.4 score bonus
"""

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_overflow_cache: dict = {}
_cache_lock = threading.Lock()
_cache_built_at: float = 0.0
_CACHE_TTL_SECONDS = 90


def compute_overflow_score(
    idle_minutes: float,
    util_pct: float,
    queue_depth: int,
    config: dict,
) -> float:
    """Return 0.0-1.0 overflow score from three normalised signals."""
    idle_thresh = max(1, config["idle_threshold_minutes"])
    util_thresh = max(1.0, config["utilization_threshold_pct"])
    queue_thresh = max(1, config["queue_pressure_threshold"])

    idle_score = min(1.0, idle_minutes / idle_thresh)
    util_score = max(0.0, 1.0 - util_pct / util_thresh)
    queue_score = min(1.0, queue_depth / queue_thresh)

    return (
        config["idle_weight"] * idle_score
        + config["utilization_weight"] * util_score
        + config["queue_pressure_weight"] * queue_score
    )


CONFIG_KEYS = frozenset(
    {
        "idle_threshold_minutes",
        "utilization_threshold_pct",
        "queue_pressure_threshold",
        "idle_weight",
        "utilization_weight",
        "queue_pressure_weight",
        "overflow_enabled",
        "overflow_paused",
        "priority_boost",
        "max_overflow_concurrent",
    }
)


def resolve_config(
    all_configs: list,
    agent_id: Optional[int],
    capability: Optional[str],
    node_id: Optional[int],
) -> dict:
    """Merge config rows by scope priority: node > agent > capability > global.
    Only config payload keys are copied — scope discriminators are excluded.
    """
    PRIORITY = {"global": 0, "capability": 1, "agent": 2, "node": 3}
    result: dict = {}
    for row in sorted(all_configs, key=lambda r: PRIORITY.get(r["scope"], 0)):
        scope = row["scope"]
        matches = (
            scope == "global"
            or (scope == "capability" and row.get("capability") == capability)
            or (scope == "agent" and row.get("agent_id") == agent_id)
            or (scope == "node" and row.get("node_id") == node_id)
        )
        if matches:
            result.update({k: v for k, v in row.items() if k in CONFIG_KEYS})
    return result


def update_overflow_cache(states: list) -> None:
    """Replace the module-level cache atomically. Called by the worker each cycle."""
    global _overflow_cache, _cache_built_at
    new_cache: dict = {}
    for s in states:
        try:
            key = (s["agent_id"], s["capability"])
            new_cache[key] = {
                "is_active": s["is_active"],
                "score": s["overflow_score"],
            }
        except KeyError as exc:
            logger.warning("Skipping malformed overflow state row (missing key %s): %s", exc, s)
    with _cache_lock:
        _overflow_cache = new_cache
        _cache_built_at = time.monotonic()


def get_overflow_bonus(agent_id: int, capability: str) -> float:
    """Return +0.4 if agent is in active overflow for this capability, else 0.
    Zero DB queries — reads only the in-memory cache.
    """
    with _cache_lock:
        stale = (time.monotonic() - _cache_built_at) > _CACHE_TTL_SECONDS
        if stale:
            return 0.0
        entry = _overflow_cache.get((agent_id, capability), {})
    return 0.4 if entry.get("is_active") else 0.0


def get_full_cache_snapshot() -> list:
    """All current overflow state entries — used by the status API endpoint."""
    with _cache_lock:
        return [{"agent_id": aid, "capability": cap, **data} for (aid, cap), data in _overflow_cache.items()]
