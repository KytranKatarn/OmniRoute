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

from datetime import datetime, timedelta
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
    if footprint.prefer_gpu and gpu_avail:
        if footprint.vram_gb > gpu_vram:
            return None
    else:
        # CPU path. extra_capabilities.max_model_gb (if set) is the
        # operator-declared ceiling; otherwise use ram_gb.
        cap = float(declared_cap) if declared_cap is not None else ram_gb
        required = max(footprint.vram_gb, footprint.ram_gb)
        if required > cap:
            return None

    score = 1.0

    # Tier match — reward routing prefer_gpu models to GPU nodes and
    # CPU-only models to CPU nodes.
    if footprint.prefer_gpu == gpu_avail:
        score += 1.0
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
            age = (datetime.utcnow() - last_hb).total_seconds()
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
    return (datetime.utcnow() - last_hb) > timedelta(seconds=seconds)


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
