"""GPU-aware Ollama options helper.

Decides `num_gpu` per-dispatch by probing model VRAM requirements against
the target node's available VRAM. See docs/superpowers/specs/
2026-04-19-dispatcher-gpu-awareness-design.md for the full design.

Phase 1: hub-only `build_options()` + `VramProbeCache`.
Phase 2a: hub-first `select_node()` with fleet fallback.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import logging
import re
import threading
from typing import Any

import requests

logger = logging.getLogger(__name__)

# Module-level tunable — safety headroom for Ollama internal buffers.
# Promoted to config if future tuning is needed.
VRAM_SAFETY_MARGIN_GB: float = 0.5

_PARAM_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([BMKTbmkt])\s*$")
_SIZE_MULT = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}

# TTLs
_FAILED_PROBE_TTL = _dt.timedelta(seconds=60)
_SOFT_TTL = _dt.timedelta(hours=24)

# Quantization → bytes per parameter (actual weight storage, not bits).
# Values are approximate GGUF averages; exact size varies ±5% per model
# because K-quants store some layers at higher precision. 1.3× runtime
# overhead in the formula accounts for KV cache headroom.
#
# Unknown quant → 4.0 (conservative fp32 fallback). If telemetry shows
# these under-estimate, tighten individual entries.
_BPP_TABLE: dict[str, float] = {
    # bits ≈ 2.6 → bytes ≈ 0.33
    "Q2_K": 0.33,
    # bits ≈ 3.35 / 3.74 / 4.27
    "Q3_K_S": 0.42,
    "Q3_K_M": 0.47,
    "Q3_K_L": 0.53,
    # Q4 family: ~4.5 bits → ~0.56 bytes
    "Q4_0": 0.56,
    "Q4_1": 0.59,
    "Q4_K_S": 0.54,
    "Q4_K_M": 0.56,
    # Q5 family: ~5.4 bits → ~0.68 bytes
    "Q5_0": 0.68,
    "Q5_1": 0.71,
    "Q5_K_S": 0.66,
    "Q5_K_M": 0.68,
    # Q6: ~6.5 bits → ~0.81 bytes
    "Q6_K": 0.81,
    # Q8: ~8.5 bits → ~1.07 bytes
    "Q8_0": 1.07,
    # Half-precision floats
    "F16": 2.0,
    "BF16": 2.0,
    # Full-precision float
    "F32": 4.0,
}
_RUNTIME_OVERHEAD = 1.3
_DEFAULT_CTX_OVERHEAD_MB_PER_TOKEN = 1.0  # conservative first-cut


def _bytes_per_param(quant: str) -> float:
    return _BPP_TABLE.get((quant or "").upper(), 4.0)


def _estimate_base_vram_gb(*, parameter_count: int, quantization: str) -> float:
    bpp = _bytes_per_param(quantization)
    # params × bytes-per-param × runtime overhead, then bytes → GB
    return (parameter_count * bpp * _RUNTIME_OVERHEAD) / (1024**3)


def _parse_parameter_size(raw: str | None) -> int:
    if not raw:
        return 0
    m = _PARAM_SIZE_RE.match(raw)
    if not m:
        return 0
    return int(float(m.group(1)) * _SIZE_MULT[m.group(2).upper()])


def _fetch_show(node, model: str, timeout_s: float = 5.0) -> dict[str, Any]:
    """Call POST /api/show on the target node. Separate for ease of mocking."""
    url = f"{node.host.rstrip('/')}/api/show"
    resp = requests.post(url, json={"name": model}, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


class NodeUnavailable(Exception):
    """Raised when the selected node can no longer serve the request.

    Caught by the dispatcher, which falls back to the hub (Phase 1) or to
    the next-fit node (Phase 2a).
    """


@dataclasses.dataclass
class ProbeEntry:
    """Cached VRAM profile for a (node, model) pair."""

    parameter_count: int
    quantization: str
    estimated_vram_base_gb: float
    context_overhead_per_token_mb: float
    probed_at: _dt.datetime
    probe_failed: bool = False
    raw_show_response: dict[str, Any] = dataclasses.field(default_factory=dict)


class VramProbeCache:
    """In-memory, heartbeat-invalidated probe cache keyed by (node_id, model)."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ProbeEntry] = {}
        self._lock = threading.Lock()

    def get_or_probe(self, node, model: str) -> ProbeEntry:
        key = (node.node_id, model)
        now = _dt.datetime.now(_dt.timezone.utc)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                age = now - existing.probed_at
                if existing.probe_failed and age < _FAILED_PROBE_TTL:
                    return existing
                if not existing.probe_failed and age < _SOFT_TTL:
                    return existing
        # Lock is intentionally released before _probe()'s HTTP call.
        # Two concurrent misses for the same (node, model) can produce a
        # harmless double-probe; both threads write the same upstream data.
        # Tightening the lock across HTTP would risk blocking unrelated
        # dispatches on a slow probe.
        entry = self._probe(node, model, now)
        with self._lock:
            self._entries[key] = entry
        return entry

    def invalidate_node(self, node_id: str) -> None:
        with self._lock:
            for key in list(self._entries.keys()):
                if key[0] == node_id:
                    del self._entries[key]

    def invalidate(self, node_id: str, model: str) -> None:
        with self._lock:
            self._entries.pop((node_id, model), None)

    def _probe(self, node, model: str, now: _dt.datetime) -> ProbeEntry:
        try:
            raw = _fetch_show(node, model)
        except Exception as exc:
            logger.warning("probe failed for %s on %s: %s", model, node.node_id, exc)
            return ProbeEntry(
                parameter_count=0,
                quantization="",
                estimated_vram_base_gb=0.0,
                context_overhead_per_token_mb=0.0,
                probed_at=now,
                probe_failed=True,
                raw_show_response={},
            )
        details = raw.get("details", {}) or {}
        params = _parse_parameter_size(details.get("parameter_size"))
        quant = str(details.get("quantization_level") or "")
        # VRAM estimate wired in by Task 3.
        return ProbeEntry(
            parameter_count=params,
            quantization=quant,
            estimated_vram_base_gb=_estimate_base_vram_gb(parameter_count=params, quantization=quant),
            context_overhead_per_token_mb=_DEFAULT_CTX_OVERHEAD_MB_PER_TOKEN,
            probed_at=now,
            probe_failed=False,
            raw_show_response=raw,
        )


# Module-level default cache so callers that don't pass `cache=` share one.
_DEFAULT_CACHE = VramProbeCache()


def _resolve_target_node(target_node):
    """Phase 1: None → hub via fleet_service. Phase 2a (Task 12) will swap
    in select_node() for topology-aware selection.

    Raises NodeUnavailable if fleet_service is not importable or the hub
    node cannot be resolved — callers must pass an explicit `target_node`
    to bypass this.
    """
    if target_node is not None:
        return target_node
    # Import lazily to avoid circulars during module init.
    try:
        from .fleet_service import get_hub_node

        return get_hub_node()
    except (ImportError, AttributeError) as exc:
        raise NodeUnavailable(f"cannot resolve hub node; fleet_service.get_hub_node is unavailable: {exc}") from exc


def build_options(
    *,
    model: str,
    target_node: Any | None = None,
    agent: Any | None = None,
    prompt_tokens_hint: int = 0,
    keep_alive: str = "5m",
    cache: "VramProbeCache | None" = None,
) -> dict[str, Any]:
    """Decide GPU vs CPU placement for a model on a target node.

    Phase 1 (strategy A): if the model's estimated VRAM fits within
    `node.gpu_vram_gb - VRAM_SAFETY_MARGIN_GB - currently_loaded_other_models`,
    omit `num_gpu` (let Ollama auto-place on GPU). Otherwise set
    `num_gpu=0` to force CPU.

    Returns a dict with keys: model, options (dict, may contain num_gpu),
    keep_alive, target_node_id, placement ('gpu'|'cpu'), reason (short str).

    The `cache` parameter lets callers inject a VramProbeCache (primarily
    for test isolation — the module-level _DEFAULT_CACHE is shared by
    default). The `agent` parameter is reserved for per-agent VRAM budget
    rules in a later phase; it is currently unused.

    Raises:
        ValueError: model is empty or non-string, prompt_tokens_hint < 0.
        NodeUnavailable: target_node is None and fleet_service is missing.
    """
    if not model or not isinstance(model, str):
        raise ValueError(f"model must be a non-empty string, got {model!r}")
    if prompt_tokens_hint < 0:
        raise ValueError(f"prompt_tokens_hint must be >= 0, got {prompt_tokens_hint}")

    cache = cache or _DEFAULT_CACHE

    if target_node is None:
        node = select_node(
            capability=getattr(agent, "capability", "") if agent else "",
            model=model,
            prompt_tokens_hint=prompt_tokens_hint,
            fallback_cpu_ok=True,
            cache=cache,
        )
    else:
        node = target_node
    entry = cache.get_or_probe(node, model)

    gpu_vram_gb = float(getattr(node, "gpu_vram_gb", 0) or 0)
    gpu_available = bool(getattr(node, "gpu_available", False))

    placement: str
    reason: str

    if entry.probe_failed:
        placement, reason = "cpu", "probe_failed"
    elif not gpu_available or gpu_vram_gb <= 0:
        placement, reason = "cpu", "no_gpu_on_node"
    else:
        ctx_gb = (prompt_tokens_hint * entry.context_overhead_per_token_mb) / 1024.0
        required = entry.estimated_vram_base_gb + ctx_gb
        loaded_other = get_loaded_vram_gb(node, exclude_model=model)
        available = gpu_vram_gb - VRAM_SAFETY_MARGIN_GB - loaded_other
        if required > available:
            placement, reason = "cpu", "insufficient_vram_too_big"
        else:
            placement, reason = "gpu", "fits"

    options: dict[str, Any] = {}
    if placement == "cpu":
        options["num_gpu"] = 0

    _record_placement_event(
        {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "node_id": node.node_id,
            "model": model,
            "placement": placement,
            "reason": reason,
            "prompt_tokens_hint": prompt_tokens_hint,
        }
    )

    return {
        "model": model,
        "options": options,
        "keep_alive": keep_alive,
        "target_node_id": node.node_id,
        "placement": placement,
        "reason": reason,
    }


_PS_CACHE_TTL_S = 5
_loaded_vram_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
_loaded_vram_lock = threading.Lock()


def _fetch_ps(node, timeout_s: float = 5.0) -> dict[str, Any]:
    """Call GET /api/ps on the target node. Separate for ease of mocking."""
    url = f"{node.host.rstrip('/')}/api/ps"
    resp = requests.get(url, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def _get_ps_models(node) -> list[dict[str, Any]]:
    """Return /api/ps `models` list, using a 5-second per-(node_id, host) cache."""
    key = (node.node_id, node.host)
    with _loaded_vram_lock:
        cached = _loaded_vram_cache.get(key)
        now = _dt.datetime.now(_dt.timezone.utc).timestamp()
        if cached and now - cached[0] < _PS_CACHE_TTL_S:
            return cached[1]
    try:
        ps = _fetch_ps(node)
    except Exception as exc:
        logger.warning("ps fetch failed on %s: %s", node.node_id, exc)
        return []
    # Refresh `now` AFTER the HTTP call so the cache entry reflects when
    # we actually received the data (prevents stale-cache-at-birth if the
    # fetch took most of the TTL window).
    now = _dt.datetime.now(_dt.timezone.utc).timestamp()
    models = ps.get("models", []) or []
    with _loaded_vram_lock:
        _loaded_vram_cache[key] = (now, models)
    return models


def get_loaded_vram_gb(node, *, exclude_model: str | None) -> float:
    """Sum `size_vram` across every model currently loaded on the node.

    `exclude_model` is an exact-string match against Ollama's `name` field
    (typically includes a tag, e.g. ``"llama3:latest"``). Callers must pass
    the fully-qualified name; no normalization is performed.

    Returns 0.0 if `_fetch_ps` fails (treats node as having no visible
    loaded models rather than raising).
    """
    total_bytes = 0
    for m in _get_ps_models(node):
        if exclude_model and m.get("name") == exclude_model:
            continue
        total_bytes += int(m.get("size_vram", 0) or 0)
    return total_bytes / (1024**3)


# ---- Placement telemetry ---------------------------------------------------
# Simple bounded in-memory rolling window. The observer in agent_loop drains
# this every 5 min and writes one autonomy_loop_log row per tick. Bounded
# memory is better than unbounded list under a possible QPS spike.

_PLACEMENT_WINDOW_MAX = 10_000
_placement_events: list[dict[str, Any]] = []
_placement_lock = threading.Lock()


def _record_placement_event(event: dict[str, Any]) -> None:
    """Append a placement-decision event to the bounded rolling window."""
    with _placement_lock:
        if len(_placement_events) >= _PLACEMENT_WINDOW_MAX:
            # Drop the oldest 1000 to amortize list-slicing cost.
            del _placement_events[:1000]
        _placement_events.append(event)


def drain_placement_events() -> list[dict[str, Any]]:
    """Return + clear the current placement-event window. Observer-only API."""
    with _placement_lock:
        events = list(_placement_events)
        _placement_events.clear()
        return events


# ---- Phase 2a: hub-first node selection with fleet fallback ----------------


def _list_online_fleet_nodes() -> list:
    """Query remote_nodes for online, GPU-capable, Ollama-capable fleet nodes.

    Returns a list of node-like objects (dicts from fleet_service, or adapted
    via _dict_to_node). Priority-sorted ASC, then current_load ASC.

    Returns [] if fleet_service is unavailable (Phase 2a fallback to hub-only).
    """
    try:
        from .fleet_service import list_nodes
    except ImportError:
        return []

    rows = list_nodes() or []
    out: list = []
    for r in rows:
        # Accept either dicts or objects; normalize reads via getattr/get.
        def _get(attr: str, default=None):
            if hasattr(r, attr):
                return getattr(r, attr)
            if isinstance(r, dict):
                return r.get(attr, default)
            return default

        node_id = _get("node_id")
        if node_id in ("hub", "archie-starbase"):
            continue
        if _get("status") != "online":
            continue
        if not _get("gpu_available"):
            continue
        if not _get("ollama_available"):
            continue
        out.append(r)

    def _priority(r):
        return (
            int(r.get("priority", 10)) if isinstance(r, dict) else int(getattr(r, "priority", 10) or 10),
            int(r.get("current_load", 0)) if isinstance(r, dict) else int(getattr(r, "current_load", 0) or 0),
        )

    out.sort(key=_priority)
    return out


def _dict_to_node(row: dict[str, Any]):
    """Light adapter for fleet_service rows that come back as dicts."""

    class _NodeView:
        pass

    n = _NodeView()
    n.node_id = row.get("node_id")
    n.host = f"http://{row.get('vpn_ip')}:{row.get('port', 11434)}"
    n.gpu_vram_gb = float(row.get("gpu_vram_gb") or 0)
    n.gpu_available = bool(row.get("gpu_available"))
    n.current_load = int(row.get("current_load") or 0)
    n.max_concurrent = int(row.get("max_concurrent") or 0)
    n.status = row.get("status") or "offline"
    return n


def _fits_on_node(
    node,
    model: str,
    prompt_tokens_hint: int,
    cache: "VramProbeCache",
) -> bool:
    """Return True if (model + context) fits on node's currently-available GPU."""
    gpu_vram_gb = float(getattr(node, "gpu_vram_gb", 0) or 0)
    if gpu_vram_gb <= 0:
        return False
    if not getattr(node, "gpu_available", False):
        return False
    entry = cache.get_or_probe(node, model)
    if entry.probe_failed:
        return False
    ctx_gb = (prompt_tokens_hint * entry.context_overhead_per_token_mb) / 1024.0
    required = entry.estimated_vram_base_gb + ctx_gb
    loaded_other = get_loaded_vram_gb(node, exclude_model=model)
    available = gpu_vram_gb - VRAM_SAFETY_MARGIN_GB - loaded_other
    return required <= available


def select_node(
    *,
    capability: str,
    model: str,
    prompt_tokens_hint: int = 0,
    fallback_cpu_ok: bool = True,
    cache: "VramProbeCache | None" = None,
):
    """Hub-first locality selection with fleet fallback.

    Phase 2a behaviour:
    1. If the model fits on the hub GPU, return the hub.
    2. Else scan online fleet GPU nodes (priority-sorted, skipping nodes at
       max_concurrent). Return the first one the model fits on.
    3. Else return the hub (caller gets CPU placement via build_options),
       UNLESS fallback_cpu_ok=False, in which case raise NodeUnavailable.

    `capability` is currently unused but reserved for Phase 2b scoring
    (department affinity / agent specialization bonuses).
    """
    cache = cache or _DEFAULT_CACHE
    hub = _resolve_target_node(None)

    if _fits_on_node(hub, model, prompt_tokens_hint, cache):
        return hub

    for node in _list_online_fleet_nodes():
        load = int(
            getattr(node, "current_load", None) or (node.get("current_load", 0) if isinstance(node, dict) else 0)
        )
        maxc = int(
            getattr(node, "max_concurrent", None) or (node.get("max_concurrent", 0) if isinstance(node, dict) else 0)
        )
        if maxc and load >= maxc:
            continue
        node_obj = node if hasattr(node, "node_id") else _dict_to_node(node)
        if _fits_on_node(node_obj, model, prompt_tokens_hint, cache):
            return node_obj

    if fallback_cpu_ok:
        return hub
    raise NodeUnavailable(f"no node can fit {model} and fallback_cpu_ok=False")
