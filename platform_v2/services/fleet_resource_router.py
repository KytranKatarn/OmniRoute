"""Resource-aware fleet routing helpers (#2516 Phase 1).

Pure-function module. Given a candidate node row from `remote_nodes` and a
model name, score whether the node should run that model. Higher score =
better fit; ``None`` means disqualify.

Phase 1 ships this as an *additive* helper — nothing in the live dispatch
path calls it yet. Phase 2 (separate PR) wires it into smart_router's
fleet tier behind ``FLEET_RESOURCE_ROUTING_ENABLED``.

Inputs use the column names from ``remote_nodes`` so the function is
trivial to call from a DictRow without re-mapping.

ADR-555.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.model_sizes import lookup

STALE_HEARTBEAT_SECONDS = 180
STALE_HEARTBEAT_PENALTY = 1.0


def _safe(value, default=0):
    return value if value is not None else default


def score_node_for_model(node: dict[str, Any], model: str) -> Optional[float]:
    """Score a fleet node for a given model.

    Returns a float (higher = better fit). Returns ``None`` to disqualify
    the node — caller should skip it and try the next candidate or
    escalate to the next tier.

    Required ``node`` keys (subset of ``remote_nodes``):
        gpu_available, gpu_vram_gb, ram_gb, current_load,
        max_concurrent, priority, last_heartbeat, extra_capabilities
    Missing keys default to safe values rather than raising.
    """
    if not node or not model:
        return None

    footprint = lookup(model)
    extra = node.get("extra_capabilities") or {}
    if not isinstance(extra, dict):
        extra = {}

    gpu_avail = bool(node.get("gpu_available"))
    gpu_vram = float(_safe(node.get("gpu_vram_gb"), 0))
    ram_gb = float(_safe(node.get("ram_gb"), 0))
    declared_cap = extra.get("max_model_gb")

    # Capacity check — disqualify if the model can't fit at all.
    # cpu_demoted: a prefer_gpu model that won't fit THIS node's VRAM but can
    # still run on CPU using the node's RAM (e.g. gemma3:12b on a 29GB Starship
    # whose 8GB GPU is too small, or on the 128GB hub). Allowed but penalised
    # below so a node that can truly GPU-fit it ranks higher. RAM-gated: the
    # 7.8GB outposts still disqualify (footprint.ram_gb 24 > 7.8). KB #270009.
    cpu_demoted = False
    if footprint.prefer_gpu and gpu_avail and footprint.vram_gb <= gpu_vram:
        pass  # fits on GPU
    else:
        # CPU path: no GPU, a CPU-preferred model, OR a prefer_gpu model too big
        # for this node's VRAM. extra_capabilities.max_model_gb (if set) is the
        # operator-declared ceiling; otherwise use ram_gb.
        cap = float(declared_cap) if declared_cap is not None else ram_gb
        required = max(footprint.vram_gb, footprint.ram_gb)
        if required > cap:
            return None
        cpu_demoted = footprint.prefer_gpu and gpu_avail

    score = 1.0

    # Tier match — reward routing prefer_gpu models to GPU nodes and
    # CPU-only models to CPU nodes.
    if cpu_demoted:
        # prefer_gpu model demoted to CPU (node VRAM too small) — allowed where
        # RAM permits but dispreferred vs a node that can actually GPU-fit it.
        score -= 0.5
    elif footprint.prefer_gpu == gpu_avail:
        score += 1.0
        # Small CPU-only model on a dedicated CPU-only node is the IDEAL
        # placement — it frees hub GPU for prefer_gpu workloads. Without
        # this nudge, hub (which has BOTH CPU and GPU) often outscores
        # outpost-tier nodes via load balancing alone, so qwen2.5:1.5b
        # ends up on the same hub that should be running 7B+ inference.
        if not footprint.prefer_gpu and not gpu_avail:
            score += 0.7
    else:
        # Allowed but not ideal (e.g. small model on hub GPU).
        score -= 0.3

    # Load pressure — softer when the node is idle.
    max_conc = max(int(_safe(node.get("max_concurrent"), 1)), 1)
    cur_load = max(int(_safe(node.get("current_load"), 0)), 0)
    score -= 0.5 * (cur_load / max_conc)

    # Priority — node operators set priority 1-10 to influence routing.
    priority = int(_safe(node.get("priority"), 10))
    score += 0.1 * (priority / 10.0)

    # Heartbeat freshness — penalise nodes that haven't checked in.
    last_hb = node.get("last_heartbeat")
    if last_hb is not None:
        if isinstance(last_hb, str):
            try:
                last_hb = datetime.fromisoformat(last_hb)
            except ValueError:
                last_hb = None
        if last_hb is not None:
            if last_hb.tzinfo is None:
                last_hb = last_hb.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last_hb).total_seconds()
            if age > STALE_HEARTBEAT_SECONDS:
                score -= STALE_HEARTBEAT_PENALTY
    else:
        # Never heartbeated — heavy penalty but still allow if no other
        # node fits.
        score -= STALE_HEARTBEAT_PENALTY

    return score if score > 0 else None


def utilization_pct(node: dict[str, Any]) -> float:
    """Return load percentage 0-100 for a node row. Used by reporting."""
    max_conc = max(int(_safe(node.get("max_concurrent"), 1)), 1)
    cur_load = max(int(_safe(node.get("current_load"), 0)), 0)
    return round(100.0 * cur_load / max_conc, 1)


def is_stale(node: dict[str, Any], seconds: int = STALE_HEARTBEAT_SECONDS) -> bool:
    """True if last_heartbeat is older than ``seconds`` (or missing)."""
    last_hb = node.get("last_heartbeat")
    if last_hb is None:
        return True
    if isinstance(last_hb, str):
        try:
            last_hb = datetime.fromisoformat(last_hb)
        except ValueError:
            return True
    if last_hb.tzinfo is None:
        last_hb = last_hb.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last_hb) > timedelta(seconds=seconds)


def find_best_node_for_model(
    model: str, home_node_db_id: Optional[int] = None, *, profile_pref: Optional[str] = None
) -> Optional[int]:
    """Find the best online fleet node for a given model.

    Scores all online nodes against the model. If a node scores significantly
    better than the agent's home node (e.g. GPU Starship vs CPU VPS), escalate
    there instead — enabling bi-directional cluster dispatch.

    Colocation preference: if home node scores within 80% of best, keep home.
    This ensures news-team VPS agents stay on VPS for 1.5b models (GPU nodes
    score lower for CPU-preferred small models anyway).

    ``profile_pref`` (AGENT MOBILITY PROFILE, optional): ``'gpu'`` nudges a
    profile-prioritised agent's model toward GPU nodes (platform mode);
    ``'cpu'`` nudges toward CPU/outpost nodes (news mode). Tiebreak only —
    keeps the score-based path consistent with the dispatcher's routing block
    1a. ``None`` (default) = byte-for-byte unchanged for every existing caller.

    Returns the integer DB id of the best node, or ``home_node_db_id`` if no
    improvement is found. Returns ``None`` only when there are no online nodes.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, node_id, node_name, gpu_available, gpu_vram_gb,
                       ram_gb, current_load, max_concurrent, priority,
                       last_heartbeat, extra_capabilities, deployment_mode
                FROM remote_nodes
                WHERE is_active = TRUE
                  AND status = 'online'
                  AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                ORDER BY priority DESC NULLS LAST
                """,
            )
            nodes = [dict(r) for r in cur.fetchall()]
    except Exception:
        return home_node_db_id

    # Suppress starship nodes during the hardware rest window (8PM–6AM).
    _rest_active = False
    try:
        from tools.department_hq.fleet_helpers import is_fleet_rest_active

        _rest_active = is_fleet_rest_active()
    except Exception:
        pass

    best_db_id = home_node_db_id
    best_score: Optional[float] = None
    home_score: Optional[float] = None

    for node in nodes:
        if node.get("deployment_mode") == "starship" and _rest_active:
            continue
        score = score_node_for_model(node, model)
        if score is None:
            continue
        # AGENT MOBILITY PROFILE bias — tiebreak only, consistent with the
        # dispatcher's routing block 1a. Never un-disqualifies (None skips above).
        if profile_pref == "gpu" and node.get("gpu_available"):
            score += 0.5
        elif profile_pref == "cpu" and not node.get("gpu_available"):
            score += 0.5
        if node["id"] == home_node_db_id:
            home_score = score
        if best_score is None or score > best_score:
            best_score = score
            best_db_id = node["id"]

    # Keep home node when it's within 80% of the best score — colocation wins
    if home_score is not None and best_score is not None and best_score > 0:
        if home_score >= best_score * 0.80:
            return home_node_db_id

    return best_db_id


def should_dispatch_to_node(node: dict[str, Any], model: str, enforce: bool) -> tuple[bool, str]:
    """Pre-dispatch capacity guard.

    Returns ``(allowed, reason)``. The reason string is always populated
    so callers can log it regardless of outcome — useful for soft-warn
    mode (``enforce=False``) where the dispatch proceeds anyway.

    When ``enforce=False`` (default — flag off): returns ``allowed=True``
    even if the node would be disqualified, but the reason explains the
    mismatch so it shows up in logs.

    When ``enforce=True`` (FLEET_RESOURCE_ROUTING_ENABLED=true): a None
    score from ``score_node_for_model`` returns ``allowed=False``,
    causing the caller to refuse the dispatch.

    Phase 2 of #2516. ADR-555.
    """
    score = score_node_for_model(node, model)
    if score is None:
        node_label = node.get("node_name") or node.get("node_id") or "<unknown>"
        reason = f"capacity-mismatch: model={model!r} disqualifies node={node_label!r}"
        return (not enforce, reason)
    return (True, f"score={round(score, 2)}")
