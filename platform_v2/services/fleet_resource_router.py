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


# ── GPU performance weights (best-hardware routing) ──
# Relative inference-speed weight by video-card type (higher = faster). The scorer
# otherwise treats two 8GB GPUs as equal, so a 7B model tied between the slow hub
# Quadro M4000 (~130-235s observed for 7B fact_check) and a fast RTX 3070 (~15-24s)
# — colocation then pinned it to the hub. These weights let routing prefer the
# FASTEST card that fits, with the next-fastest then the hub as failover. Matched by
# substring of remote_nodes.gpu_model (most-specific first; first match wins).
# Tunable — refine from observed per-card latency over time.
_GPU_PERF_WEIGHTS = (
    ("h100", 2.0),
    ("a100", 1.8),
    ("rtx 50", 1.5),
    ("rtx 4090", 1.5),
    ("rtx 4080", 1.35),
    ("rtx 40", 1.3),
    ("rtx 3090", 1.4),
    ("rtx 3080", 1.2),
    ("rtx 3070", 1.0),
    ("rtx 3060", 0.7),
    ("rtx 3050", 0.45),  # laptop 3050 — much weaker than desktop 30-series
    ("rtx a", 1.1),  # workstation Ampere (A4000/A5000…)
    ("rtx 20", 0.7),
    ("gtx 16", 0.45),
    ("gtx 10", 0.35),
    ("quadro m", 0.12),
    ("tesla m", 0.12),  # old Maxwell (hub Quadro M4000) — slow
    ("quadro", 0.4),
    ("tesla", 0.5),
)


def gpu_perf_weight(gpu_model) -> float:
    """Relative inference-speed weight for a node's GPU (0 if no/unknown match)."""
    m = (str(gpu_model) if gpu_model else "").strip().lower()
    if not m:
        return 0.3  # GPU present but model unknown — modest, still beats no-GPU
    for key, weight in _GPU_PERF_WEIGHTS:
        if key in m:
            return weight
    return 0.3


def can_node_run_model(node: dict[str, Any], model: str) -> bool:
    """Capacity-only check: can this node physically hold *model*?

    This is the FIT predicate, deliberately independent of transient load /
    heartbeat freshness (unlike score_node_for_model, which folds those in for
    RANKING). Routing gates should use this so a noisy current_load counter can
    never wrongly disqualify a capable, idle node. Mirrors the disqualify branch
    of score_node_for_model: a prefer_gpu model fits if it lands on a big-enough
    GPU; otherwise it must fit the node's CPU ceiling (operator max_model_gb, else
    ram_gb).
    """
    if not node or not model:
        return False
    footprint = lookup(model)
    extra = node.get("extra_capabilities") or {}
    if not isinstance(extra, dict):
        extra = {}
    gpu_avail = bool(node.get("gpu_available"))
    gpu_vram = float(_safe(node.get("gpu_vram_gb"), 0))
    ram_gb = float(_safe(node.get("ram_gb"), 0))
    declared_cap = extra.get("max_model_gb")
    if footprint.prefer_gpu and gpu_avail and footprint.vram_gb <= gpu_vram:
        return True  # fits on GPU
    cap = float(declared_cap) if declared_cap is not None else ram_gb
    required = max(footprint.vram_gb, footprint.ram_gb)
    return required <= cap


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

    # Best-hardware: offload heavy (prefer_gpu) inference to a DEDICATED GPU node
    # (Starship, fast RTX) over the shared platform-core hub (slow Quadro M4000,
    # reserved for platform core + ComfyUI). The scorer otherwise treats two 8GB
    # GPUs as equal, so 7B work tied and the 80% home-colocation rule pinned it to
    # the hub (130-235s) instead of the RTX (~15-24s). The bonus is sized to beat
    # colocation; the hub still scores positively as a failover when no Starship is
    # online/viable (e.g. the 8PM-6AM hardware rest window). Mirrors the lines above
    # that keep small CPU models off the hub GPU. KB cluster-saturation diagnosis.
    if footprint.prefer_gpu and gpu_avail and footprint.vram_gb <= gpu_vram:
        # Rank by ACTUAL GPU performance so the fastest card that fits wins
        # (RTX 3070 ~1.2 > RTX 3050 ~0.54 > hub Quadro M4000 ~0.14), with the
        # next-fastest then the hub as failover. Sized to beat 80% home-colocation.
        score += 1.2 * gpu_perf_weight(node.get("gpu_model"))

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


def node_has_model(node: dict[str, Any], model: str) -> bool:
    """True if *node* actually has *model* pulled (per its reported ollama_models).

    can_node_run_model() is capacity-only — it checks the node COULD hold a model
    of this size, NOT that this exact model is present. Routing a hub-only / custom
    model (e.g. qwen25-classify, codex-cli, phi3.5) to a capable-but-doesn't-have-it
    node 404s its Ollama (#4272). Fail-OPEN: when the node reports no model list we
    can't disqualify it (the hub fallback, which has every model, covers a rare
    miss); fail-CLOSED only when the list is known and the model is absent.
    """
    if not node or not model:
        return False
    extra = node.get("extra_capabilities") or {}
    if not isinstance(extra, dict):
        return True
    names = extra.get("ollama_models")
    if not isinstance(names, list) or not names:
        return True  # unknown list — don't disqualify; hub fallback covers a miss

    def _norm(m: str) -> str:
        return m[:-7] if isinstance(m, str) and m.endswith(":latest") else m

    nm = _norm(model)
    return nm in names or any(_norm(x) == nm for x in names)


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
                       gpu_model, ram_gb, current_load, max_concurrent, priority,
                       last_heartbeat, extra_capabilities, deployment_mode
                FROM remote_nodes
                WHERE is_active = TRUE
                  AND status = 'online'
                  -- Exclude ingress / no-Ollama nodes (e.g. Beacon, ollama_available=f):
                  -- they cannot serve inference, so scoring them as dispatch candidates
                  -- routes jobs to a dead Ollama port → ConnectionError storm (#4272).
                  -- COALESCE → a NULL flag is treated as available (fail-open).
                  AND COALESCE(ollama_available, TRUE) = TRUE
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
        # P2a (#3802): admission = the FIT predicate (capacity-only, load-
        # independent), matching the async queue gate, so the sync path can't
        # disqualify a capable IDLE node via the noisy current_load/heartbeat
        # terms score_node_for_model folds in. score is used ONLY to rank.
        if not can_node_run_model(node, model):
            continue
        # Capacity-fit (above) only proves the node COULD hold a model of this
        # size — not that THIS model is actually pulled there. Skip nodes whose
        # reported model list lacks it, so a hub-only / custom model never routes
        # to a node that 404s on it (#4272); the hub fallback serves it instead.
        if not node_has_model(node, model):
            continue
        score = score_node_for_model(node, model)
        if score is None:
            score = 0.001  # admitted by fit; rank last rather than disqualify
        # AGENT MOBILITY PROFILE bias — tiebreak only, consistent with the
        # dispatcher's routing block 1a. Never un-disqualifies (fit gate above).
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


def score_node_for_egress(
    node: dict[str, Any],
    preferred_region: Optional[str] = None,
    *,
    prefer_residential: bool = True,
) -> Optional[float]:
    """Score a fleet node as an HTTP egress proxy for external_fetch requests.

    Returns float (higher = better) or None to disqualify.
    Residential IPs score highest for gov-API scraping (datacenter IPs are blocked).
    Region match adds a strong bonus for geo-diverse egress.
    """
    if not node or is_stale(node):
        return None

    egress = node.get("egress_metadata") or {}
    if not isinstance(egress, dict):
        egress = {}

    egress_regions = egress.get("egress_regions") or []
    residential = bool(egress.get("residential", False))

    score = 1.0

    if prefer_residential:
        score += 2.0 if residential else -0.5

    if preferred_region and egress_regions:
        pref = preferred_region.upper()
        if pref in egress_regions:
            score += 1.5
        elif any(pref[:2] == r[:2] for r in egress_regions):
            score += 0.5  # partial match (e.g. "GB" ~ "EU")

    max_conc = max(int(_safe(node.get("max_concurrent"), 1)), 1)
    cur_load = max(int(_safe(node.get("current_load"), 0)), 0)
    score -= 0.3 * (cur_load / max_conc)

    return score if score > 0 else None


def find_best_egress_node(
    preferred_region: Optional[str] = None,
    *,
    prefer_residential: bool = True,
) -> int:
    """Return the DB id of the best online node for an external_fetch request.

    Scores all active nodes using egress_metadata. Falls back to hub (id=68)
    when no node qualifies — hub's residential CA/US IP is the safe default.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, current_load, max_concurrent, last_heartbeat, egress_metadata
                FROM remote_nodes
                WHERE is_active = TRUE
                  AND status = 'online'
                  AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                ORDER BY priority DESC NULLS LAST
                """
            )
            nodes = [dict(r) for r in cur.fetchall()]
    except Exception:
        return 68  # hub fallback

    best_id: Optional[int] = None
    best_score: Optional[float] = None

    for node in nodes:
        score = score_node_for_egress(node, preferred_region, prefer_residential=prefer_residential)
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_id = node["id"]

    return best_id if best_id is not None else 68


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
