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

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.model_sizes import lookup

STALE_HEARTBEAT_SECONDS = 180
STALE_HEARTBEAT_PENALTY = 1.0

# ── Fleet-wide model hardware blocklist (2026-08-21 fleet rebalance) ──
# Some models fit NO GPU anywhere in this fleet regardless of which node is asked —
# that is an owner-decided hardware-fit exclusion, not a per-node capacity gap, so it
# belongs here rather than in any one node's extra_capabilities.max_model_gb.
#
# SEEDED EMPTY, DELIBERATELY. This was seeded with gemma3:12b on the reasoning that its
# 15.6GB footprint exceeds every card in the fleet, so it "only ever runs CPU-demoted —
# 56% success fleet-wide". That 56% is a FLEET-WIDE AVERAGE and it hides the answer:
# split by node over 30 days it is hub 12,103 runs / 52% and USS-246 2,918 runs / 95%
# (avg 38.4s). The model is not unfit for the hardware; it is unfit for THE HUB. Blocking
# it fleet-wide removed the 95% path and left the 52% one untouched, because this
# blocklist binds FLEET placement and the hub does not consult it — exactly backwards.
#
# So: a model belongs here only when it fails on EVERY node, proven per-node, never from
# an aggregate. Populate via platform_settings 'dispatch:model_blocklist' (comma-separated;
# an explicit empty string clears it) once you have that per-node evidence. DB-unreachable
# or unset -> this compiled-in default, which is empty: the fail-safe direction for an
# unproven blocklist is to allow, since a wrong block silently deletes capacity.
_MODEL_BLOCKLIST_DEFAULT: frozenset = frozenset()
_model_blocklist_cache: Optional[frozenset] = None
_model_blocklist_cache_time = 0.0
_MODEL_BLOCKLIST_CACHE_TTL = 60.0


def _load_model_blocklist() -> frozenset:
    """DB read behind model_hardware_blocklist()'s cache. Fail-safe -> the compiled-in
    default on any error (missing table, no DB, connection issue)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'dispatch:model_blocklist'")
            row = cur.fetchone()
        if row is None:
            return _MODEL_BLOCKLIST_DEFAULT
        raw = row["value"] if isinstance(row, dict) else row[0]
        raw = raw or ""
        return frozenset(m.strip() for m in raw.split(",") if m.strip())
    except Exception:
        return _MODEL_BLOCKLIST_DEFAULT


def model_hardware_blocklist() -> frozenset:
    """Cached (~60s) accessor for the fleet-wide model blocklist. Tests monkeypatch
    this function directly rather than exercising the DB. See module docstring above
    for semantics."""
    global _model_blocklist_cache, _model_blocklist_cache_time
    now = time.time()
    if _model_blocklist_cache is None or (now - _model_blocklist_cache_time) >= _MODEL_BLOCKLIST_CACHE_TTL:
        _model_blocklist_cache = _load_model_blocklist()
        _model_blocklist_cache_time = now
    return _model_blocklist_cache


def _is_model_blocked(model: str) -> bool:
    if not model:
        return False
    blocked = model_hardware_blocklist()
    if not blocked:
        return False
    m = model.strip()
    m_norm = m[:-7] if m.endswith(":latest") else m
    return m in blocked or m_norm in blocked


# Latency-aware routing (refined-B / K.I.N.-advises): a node that already has the
# model LOADED (warm-resident, per model_load_state) skips a multi-GB cold-load —
# the dominant dispatch latency (the 3-13 min / warmup-thrash we measured; KB #278809).
# Additive bonus so a warm node beats a cold one and can outrank a somewhat-faster
# COLD card. find_best_node_for_model precomputes node["_model_warm"]; other callers
# omit it → byte-for-byte unchanged. Tunable.
WARM_MODEL_BONUS = 1.0
# Freshness window for a model_load_state row to count as "still warm". The state
# save job refreshes ~every 5m and KEEP_ALIVE is 60m, so 15m = 3 cycles of tolerance.
WARM_STATE_WINDOW_MINUTES = 15

# Concurrent-heavy cap (refined-B slice 2): with NUM_PARALLEL=1 a node serves one
# request per model at a time, so stacking heavy (prefer_gpu / 7B+) jobs on one node
# SERIALIZES them — the Nth waits for N-1 to finish. When a node already has this many
# heavy jobs in flight, deprioritize it for ANOTHER heavy job so the work spreads across
# GPU nodes. Absolute (not scaled by max_concurrent — heavy work is GPU-bound). The
# penalty deprioritizes, never disqualifies (fail-open: all-saturated still routes to the
# least-bad). ``_heavy_inflight`` is precomputed by find_best_node_for_model. Tunable.
HEAVY_CONCURRENCY_CAP = 2
HEAVY_OVERCAP_PENALTY = 1.5

# Hub (starbase) 7B de-preference (#375): the hub Quadro M4000 runs 7B at ~100s (an
# old Maxwell card) — slower than even the RTX-3050 laptop's CPU (~67s). Its GPU-fit
# path scores it ABOVE the faster Starship-245 for 7B overflow, so 7B spills onto the
# slow hub when Starship-246 hits its heavy cap. Penalize the hub for prefer_gpu
# (7B+) models so overflow prefers a Starship; sized to drop the hub below the
# RTX-3050's cpu-demoted score while staying a positive LAST-RESORT failover (rest
# window / all Starships offline). See score_node_for_model. Tunable.
HUB_HEAVY_PENALTY = 1.5

# Observed-latency signal (refined-B slice 3): refine the STATIC gpu_perf_weight guess
# with MEASURED recent latency. find_best_node_for_model computes node["_latency_ratio"]
# = (this node's recent avg latency for the model) / (the fastest node's), from
# dispatch_pending_queue done rows in the last LATENCY_WINDOW_MINUTES (>= LATENCY_MIN_SAMPLES
# each). A node empirically FAST for this model gets +LATENCY_FAST_BONUS; a SLOW one
# (>= LATENCY_SLOW_RATIO x the fastest) gets -LATENCY_SLOW_PENALTY; linear between. Bounded
# small so it refines, never overrides tier/warm/cap. Absent ratio → 0 (fail-open). Tunable.
LATENCY_WINDOW_MINUTES = 30
LATENCY_MIN_SAMPLES = 2
LATENCY_FAST_BONUS = 0.3
LATENCY_SLOW_PENALTY = 0.3
LATENCY_SLOW_RATIO = 2.0


def observed_latency_adj(ratio) -> float:
    """Bounded routing adjustment from a node's recent-latency RATIO (its avg / the fastest
    node's avg for the same model). 1.0 = fastest → +LATENCY_FAST_BONUS; >= LATENCY_SLOW_RATIO
    → -LATENCY_SLOW_PENALTY; linear between. None/invalid → 0.0 (no data → no adjustment)."""
    if ratio is None:
        return 0.0
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return 0.0
    if r <= 1.0:
        return LATENCY_FAST_BONUS
    if r >= LATENCY_SLOW_RATIO:
        return -LATENCY_SLOW_PENALTY
    frac = (r - 1.0) / (LATENCY_SLOW_RATIO - 1.0)
    return LATENCY_FAST_BONUS - frac * (LATENCY_FAST_BONUS + LATENCY_SLOW_PENALTY)


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


def _canon_tag(name: str) -> str:
    """Drop a trailing ':latest' so both spellings of one model compare equal.

    Mirrors node_has_model's _norm — a node reports 'dolphin3:latest' via /api/tags
    while an operator writing an allowlist by hand will type 'dolphin3'.
    """
    if isinstance(name, str) and name.endswith(":latest"):
        return name[:-7]
    return name


def _node_allows_model(extra: dict[str, Any], model: str) -> bool:
    """Per-node pin: when `extra_capabilities.model_allowlist` names models, only
    those may run on this node.

    WHY THIS EXISTS. The fleet-wide `model_hardware_blocklist()` is the wrong tool
    for a per-node problem: qwen2.5:7b and qwen2.5:1.5b both run fine on the hub, so
    blocking either fleet-wide deletes the good path (the 2026-08-21 gemma3 reversal
    is the precedent). And capacity CANNOT express it — `can_node_run_model`'s GPU
    branch returns True for any prefer_gpu model that fits the card, before
    `max_model_gb` is even read, so a 1.4GB model can never be refused from an 8GB
    node on size.

    WHY HERE. This one function gates BOTH dispatch routing AND the warm-up drain
    (#5862 / PR #2738). USS-246's 8GB card holds one model in practice, and the
    failure always follows whichever model is NOT resident — a switch costs 37s+ or
    hangs outright, and each hang ties up the hub's single-instance
    model_dispatch_worker. Removing the model from the node does not hold: the
    warm-up path re-pulls it and the reconciler then recreates its registry row from
    the live node (KB #315652). Gating here stops both arms.

    FAILS OPEN in every uncertain direction — absent, empty, or malformed all mean
    "no restriction". A node that silently serves nothing is far more expensive than
    one that serves too much, and this mirrors node_has_model's empty-list rule.
    It NARROWS only: allowlisting a model never makes it fit, because the capacity
    checks still run afterwards.
    """
    allow = extra.get("model_allowlist")
    if not isinstance(allow, (list, tuple, set)) or not allow:
        return True
    wanted = _canon_tag(model)
    return any(_canon_tag(m) == wanted for m in allow if isinstance(m, str))


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
    if _is_model_blocked(model):
        return False  # fleet-wide hardware-fit exclusion — see model_hardware_blocklist()
    if node.get("ollama_available") is False:
        return False  # ingress-only node (e.g. Beacon) — never a dispatch candidate
    footprint = lookup(model)
    extra = node.get("extra_capabilities") or {}
    if not isinstance(extra, dict):
        extra = {}
    if not _node_allows_model(extra, model):
        return False  # per-node pin — see _node_allows_model()
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
    if _is_model_blocked(model):
        return None  # fleet-wide hardware-fit exclusion — see model_hardware_blocklist()
    if node.get("ollama_available") is False:
        return None  # ingress-only node (e.g. Beacon) — never a dispatch candidate

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

    # Hub 7B de-preference (#375): keep the slow hub M4000 as a LAST-RESORT failover
    # for 7B+ — its GPU-fit path above otherwise outscores the faster Starship-245
    # (confirmed live: hub 1.94 > 245 0.60 for qwen2.5:7b, yet the hub runs it at
    # ~100s vs 245's ~67s). Penalize prefer_gpu models on the starbase so overflow
    # prefers a Starship (246's queue, then 245); the hub stays positive so it still
    # serves 7B when every Starship is offline/asleep. Small CPU models untouched.
    if footprint.prefer_gpu and str(node.get("deployment_mode") or "") == "starbase":
        score -= HUB_HEAVY_PENALTY

    # Warm-resident preference (latency): the model is ALREADY loaded on this node,
    # so this dispatch skips the cold-load. ``_model_warm`` is precomputed by
    # find_best_node_for_model from model_load_state; absent for other callers (no-op).
    if node.get("_model_warm"):
        score += WARM_MODEL_BONUS

    # Observed-latency refinement (measured): nudge toward nodes empirically FAST for this
    # model recently, tempering the STATIC per-card gpu_perf_weight guess. Bounded ±small.
    # ``_latency_ratio`` precomputed by find_best_node_for_model; absent → 0 (no-op).
    score += observed_latency_adj(node.get("_latency_ratio"))

    # Load pressure — softer when the node is idle.
    max_conc = max(int(_safe(node.get("max_concurrent"), 1)), 1)
    cur_load = max(int(_safe(node.get("current_load"), 0)), 0)
    score -= 0.5 * (cur_load / max_conc)

    # Concurrent-heavy cap (latency): a node already running >= HEAVY_CONCURRENCY_CAP
    # heavy jobs would SERIALIZE another one behind them (NUM_PARALLEL=1). Firmly
    # deprioritize so heavy work spreads to a less-loaded GPU node — penalty only, never
    # disqualify. Only for prefer_gpu models; small CPU models don't contend for the GPU.
    # ``_heavy_inflight`` precomputed by find_best_node_for_model; absent → no-op.
    if footprint.prefer_gpu and node.get("_heavy_inflight", 0) >= HEAVY_CONCURRENCY_CAP:
        score -= HEAVY_OVERCAP_PENALTY

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
            # Warm-resident set: nodes with the model currently LOADED (model_load_state,
            # keyed by node_db_id = remote_nodes.id). Preferring these skips the multi-GB
            # cold-load. Fail-safe: any error → empty set → routing byte-for-byte unchanged.
            # :latest is normalized on both sides (e.g. dolphin3 vs dolphin3:latest).
            warm_ids: set = set()
            try:
                cur.execute(
                    """
                    SELECT DISTINCT node_db_id FROM model_load_state
                    WHERE host_type = 'node' AND node_db_id IS NOT NULL
                      AND saved_at > NOW() - make_interval(mins => %s)
                      AND regexp_replace(model_name, ':latest$', '')
                          = regexp_replace(%s, ':latest$', '')
                    """,
                    (WARM_STATE_WINDOW_MINUTES, model),
                )
                warm_ids = {r["node_db_id"] for r in cur.fetchall() if r.get("node_db_id") is not None}
            except Exception:
                warm_ids = set()
            # Heavy-inflight per node: count in-flight (queued/running) dispatch rows whose
            # model is prefer_gpu (GPU-bound, classified via model_sizes.lookup). With
            # NUM_PARALLEL=1 these serialize on the node, so the scorer deprioritizes a node
            # at/over HEAVY_CONCURRENCY_CAP for another heavy job. Fail-safe → empty on error.
            heavy_inflight: dict = {}
            try:
                cur.execute(
                    """
                    SELECT COALESCE(result_node_id, preferred_node_id) AS nid, model_needed
                    FROM dispatch_pending_queue
                    WHERE status IN ('queued', 'running')
                      AND queued_at > NOW() - INTERVAL '10 minutes'
                      AND COALESCE(result_node_id, preferred_node_id) IS NOT NULL
                    """,
                )
                for r in cur.fetchall():
                    nid, mdl = r["nid"], r.get("model_needed")
                    if nid is None or not mdl:
                        continue
                    try:
                        if lookup(mdl).prefer_gpu:
                            heavy_inflight[nid] = heavy_inflight.get(nid, 0) + 1
                    except Exception:
                        continue
            except Exception:
                heavy_inflight = {}
            # Observed-latency per node: recent avg execution time for THIS model (done rows,
            # last LATENCY_WINDOW_MINUTES, >= LATENCY_MIN_SAMPLES each) → ratio vs the fastest
            # node, so the scorer nudges toward empirically-fast nodes. Fail-safe → {} on error.
            latency_ratio: dict = {}
            try:
                cur.execute(
                    """
                    SELECT COALESCE(result_node_id, preferred_node_id) AS nid,
                           AVG(EXTRACT(EPOCH FROM (completed_at - claimed_at))) AS avg_s,
                           COUNT(*) AS n
                    FROM dispatch_pending_queue
                    WHERE status = 'done'
                      AND completed_at IS NOT NULL AND claimed_at IS NOT NULL
                      AND queued_at > NOW() - make_interval(mins => %s)
                      AND COALESCE(result_node_id, preferred_node_id) IS NOT NULL
                      AND regexp_replace(model_needed, ':latest$', '')
                          = regexp_replace(%s, ':latest$', '')
                    GROUP BY 1
                    HAVING COUNT(*) >= %s
                    """,
                    (LATENCY_WINDOW_MINUTES, model, LATENCY_MIN_SAMPLES),
                )
                _avgs = {
                    r["nid"]: float(r["avg_s"])
                    for r in cur.fetchall()
                    if r.get("nid") is not None and r.get("avg_s") is not None and float(r["avg_s"]) > 0
                }
                _fastest = min(_avgs.values()) if _avgs else None
                if _fastest and _fastest > 0:
                    latency_ratio = {nid: v / _fastest for nid, v in _avgs.items()}
            except Exception:
                latency_ratio = {}
    except Exception:
        return home_node_db_id

    # Suppress starship nodes while UNDOCKED (#5332): scheduled hardware rest
    # OR a manual force-undock. ONE predicate for every gate — see fleet_helpers.
    _rest_active = False
    try:
        from tools.department_hq.fleet_helpers import is_starships_undocked

        _rest_active = is_starships_undocked()
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
        # Warm-resident flag → the scorer adds WARM_MODEL_BONUS (skip the cold-load).
        node["_model_warm"] = node["id"] in warm_ids
        node["_heavy_inflight"] = heavy_inflight.get(node["id"], 0)
        node["_latency_ratio"] = latency_ratio.get(node["id"])
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
