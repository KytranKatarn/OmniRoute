"""
Fleet Command — Shared helpers and caches
==========================================
Merged from starbase/helpers.py and starship/helpers.py during Fleet migration.
"""

import json
import os
import time
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from database import get_db_cursor
import requests
from .services import fleet_hardware_capacity as _hardware_capacity
from .services import fleet_node_store as _node_store

# Preserve the legacy module reference used by hardware probes and test overrides.
subprocess = _hardware_capacity.subprocess

try:
    from ai_bridge import agent_performance_tracker as _performance_tracker

    # Explicit re-exports preserve the legacy helper API for external callers.
    get_agent_performance = _performance_tracker.get_agent_performance
    update_agent_performance = _performance_tracker.update_agent_performance
    get_top_performers = _performance_tracker.get_top_performers
    log_agent_action = _performance_tracker.log_agent_action

    _HAS_PERFORMANCE_TRACKER = True
except (ImportError, AttributeError):
    _HAS_PERFORMANCE_TRACKER = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Legacy station <-> department mappings (moved here from agent_routes.py)
# Other route files import these for backward-compatible rendering.
# ---------------------------------------------------------------------------
LEGACY_STATION_DEPARTMENT = {
    "COMMAND": ["Executive Office"],
    "ANALYTICS": ["Analytics & Intelligence", "Finance & Accounting"],
    "CREATIVE": ["Creative & Design", "Marketing & Communications", "Documentation & Knowledge"],
    "ENGINEERING": ["Engineering & Technology", "Security & Compliance", "Research & Development"],
    "COMMUNICATIONS": ["Marketing & Communications"],
    "RESEARCH": ["Research & Development"],
    "SECURITY": ["Security & Compliance"],
    "LOGISTICS": ["Logistics & Supply Chain"],
    "DIPLOMATIC": ["Diplomatic & External Relations"],
    "OPERATIONS": ["Operations & Infrastructure"],
}

DEPARTMENT_TO_STATION = {}
for _code, _depts in LEGACY_STATION_DEPARTMENT.items():
    for _dept in _depts:
        if _dept not in DEPARTMENT_TO_STATION:
            DEPARTMENT_TO_STATION[_dept] = _code

LEGACY_STATION_COLORS = {
    "COMMAND": "#00e5ff",
    "ANALYTICS": "#8b5cf6",
    "CREATIVE": "#f472b6",
    "ENGINEERING": "#fbbf24",
    "COMMUNICATIONS": "#22d3ee",
    "RESEARCH": "#10b981",
    "SECURITY": "#ef4444",
    "LOGISTICS": "#f97316",
    "DIPLOMATIC": "#818cf8",
    "OPERATIONS": "#a3e635",
}

# ---------------------------------------------------------------------------
# Centralised defaults — import these instead of repeating os.getenv() calls
# ---------------------------------------------------------------------------
OLLAMA_LOCAL_HOST = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
OLLAMA_DEFAULT_PORT = os.getenv("OLLAMA_LOCAL_PORT", "11434")
OLLAMA_LOCAL_URL = f"http://{OLLAMA_LOCAL_HOST}:{OLLAMA_DEFAULT_PORT}"
DEFAULT_NODE_PORT = 11434  # integer fallback for remote-node DB rows
DEFAULT_CLIENT_VERSION = "3.0.0"
LATEST_CLIENT_VERSION = "3.0.0"

# Canonical hub display label. The hub node carries several legacy aliases
# ("Archie Starbase" was the pre-cluster name; node_id is "archie-starbase").
# All of them collapse to ONE label for display so A.R.M.A.D.A. traffic/model
# panels don't show the hub as two separate nodes. Node *IDs* are NOT touched.
# Owner-chosen canonical label (#4342): the hub IS the Starbase, running A.R.C.H.I.E.
HUB_DISPLAY_LABEL = "Starbase - A.R.C.H.I.E."
_HUB_NODE_ALIASES = {"archie starbase", "archie-starbase", "archie-hub", "hub", "starbase - a.r.c.h.i.e."}


def normalize_node_label(node_name):
    """Map any hub alias to the canonical 'Hub' display label; pass other
    node names through unchanged. Safe on None/empty."""
    if not node_name:
        return node_name
    return HUB_DISPLAY_LABEL if str(node_name).strip().lower() in _HUB_NODE_ALIASES else node_name


# ---------------------------------------------------------------------------
# Starship node constants (from starship/helpers.py)
# ---------------------------------------------------------------------------
# 3 minutes — outposts heartbeat every 60s, starships every 30s
HEARTBEAT_TIMEOUT_SECONDS = 180

# Current node package version (update this when releasing new packages)
LATEST_NODE_VERSION = "3.0.0"

# Ollama tags cache (avoid hitting Ollama on every stats poll)
_ollama_tags_cache = {"models": [], "count": 0, "time": 0}
_OLLAMA_CACHE_TTL = 30  # seconds — matches stats poll interval


def _get_cached_ollama_tags():
    """Get Ollama model list with 30s cache"""
    now = time.time()
    if _ollama_tags_cache["time"] and (now - _ollama_tags_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_tags_cache["models"], _ollama_tags_cache["count"]
    try:
        host = os.getenv("OLLAMA_HOST", OLLAMA_LOCAL_URL)
        if not host.startswith("http"):
            host = f"http://{host}"
        resp = requests.get(f"{host}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_tags_cache["models"] = models
            _ollama_tags_cache["count"] = len(models)
            _ollama_tags_cache["time"] = now
            return models, len(models)
    except Exception as e:
        logger.warning("Ollama tags cache miss: %s", e)
    return _ollama_tags_cache["models"], _ollama_tags_cache["count"]


# Ollama ps cache (avoid hitting Ollama /api/ps on every poll)
_ollama_ps_cache = {"models": [], "time": 0}


def _get_cached_ollama_ps():
    """Get loaded Ollama models with 30s cache"""
    now = time.time()
    if _ollama_ps_cache["time"] and (now - _ollama_ps_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_ps_cache["models"]
    try:
        host = os.getenv("OLLAMA_HOST", OLLAMA_LOCAL_URL)
        if not host.startswith("http"):
            host = f"http://{host}"
        resp = requests.get(f"{host}/api/ps", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_ps_cache["models"] = models
            _ollama_ps_cache["time"] = now
            return models
    except Exception as e:
        logger.warning("Ollama ps cache miss: %s", e)
    return _ollama_ps_cache["models"]


# Hardware capacity cache (nvidia-smi + psutil + Ollama model categories)
_hw_capacity_cache = {"data": None, "time": 0}


def _get_cached_hw_capacity():
    """Get hardware capacity with the existing shared 30-second cache."""
    return _hardware_capacity.get_cached_capacity(
        _get_cached_ollama_ps, get_db_cursor, cache=_hw_capacity_cache, ttl=_OLLAMA_CACHE_TTL
    )


# --- SSE Activity Event Queue ---
_activity_queue = deque(maxlen=200)


def push_agent_event(event_type, agent_id=None, data=None):
    """Push an event to the in-memory SSE queue."""
    evt = {
        "event_type": event_type,
        "agent_id": agent_id,
        "data": data or {},
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
    }
    _activity_queue.appendleft(evt)


# ============================================================================
# OLLAMA STATUS HELPERS (extracted from station_routes for shared use)
# ============================================================================


def node_inter_cluster_host(node, fallback=None):
    """Pick the host string for inter-cluster traffic to a remote_nodes row.

    Order: mesh_ip → vpn_ip → hostname → fallback. Mesh IP wins because
    hub↔node traffic must traverse Headscale per the DHQ mesh-routing
    mandate (KB #263641, ADR-008). Hostname is a last resort — heartbeats
    have been seen to write the node's Docker container ID into it, which
    is unresolvable from the hub.
    """
    if node is None:
        return fallback
    getter = node.get if hasattr(node, "get") else lambda k, d=None: node[k] if k in node else d
    return getter("mesh_ip") or getter("vpn_ip") or getter("hostname") or fallback


def validate_mesh_ip(ip: str) -> bool:
    """Return True if *ip* is within the Headscale mesh range 100.64.0.0/10.

    Used by api/request-node, update_mesh_ip, and the heartbeat handler to
    reject IPs that could never be reachable via our Headscale overlay.
    """
    import ipaddress

    HEADSCALE_NETWORK = ipaddress.ip_network("100.64.0.0/10")
    try:
        return ipaddress.ip_address(ip.strip()) in HEADSCALE_NETWORK
    except ValueError:
        return False


def check_ollama_status(host, port):
    """Check if Ollama is running and responsive"""
    try:
        start = time.time()
        response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
        latency = int((time.time() - start) * 1000)

        if response.status_code == 200:
            return "online", latency
        else:
            return "degraded", latency
    except requests.exceptions.Timeout:
        return "timeout", None
    except requests.exceptions.ConnectionError:
        return "offline", None
    except Exception as e:
        logger.error(f"Error checking Ollama: {e}")
        return "error", None


def get_ollama_models(host, port):
    """Get list of available Ollama models with sizes"""
    try:
        response = requests.get(f"http://{host}:{port}/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {model["name"]: model.get("size", 0) for model in data.get("models", [])}
    except Exception as e:
        logger.error(f"Error getting Ollama models: {e}")
    return {}


# ============================================================================
# STARSHIP NODE DETECTION
# ============================================================================


def get_starship_node_for_user(user_id):
    """Check if the current user is a starship node operator."""
    if not user_id:
        return None
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT node_id, node_name, deployment_mode, hostname, port,
                       status, bridge_priority, gpu_model, gpu_vram_gb,
                       cpu_model, cpu_cores, ram_gb, disk_gb
                FROM remote_nodes
                WHERE registered_by = %s AND deployment_mode = 'starship' AND is_active = true
                LIMIT 1
            """,
                (user_id,),
            )
            return cur.fetchone()
    except Exception:
        return None


# ============================================================================
# STARSHIP NODE HELPERS (from starship/helpers.py)
# ============================================================================


def _heartbeat_fresh(node):
    """True/False if a heartbeat exists, None when the caller did not select it."""
    hb = node.get("last_heartbeat")
    if hb is None:
        return None
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - hb).total_seconds() <= HEARTBEAT_TIMEOUT_SECONDS


def _mesh_reachable(node):
    """Tri-state mesh reachability; None when mesh_status was not selected."""
    ms = node.get("mesh_status")
    if ms is None:
        return None
    return ms == "connected"


def _compute_node_status(node):
    """Compute node status. BACKWARD-COMPATIBLE: only ever 'online' or 'offline'.

    Callers (and the Fleet tab JS) treat this as a two-state field, so it stays
    two-state. The richer picture is in _compute_node_health().

    The one BEHAVIOUR change is for ingress nodes (#5218): they run no node agent,
    so heartbeat freshness is meaningless for them and this function used to return
    'offline' unconditionally — Beacon rendered offline in the Fleet tab while it
    was serving every public request the platform receives. For those nodes,
    reachability is the answer.
    """
    role = node.get("node_role") or "agent"
    if role == "ingress":
        reachable = _mesh_reachable(node)
        if reachable is None:
            # No mesh signal selected — fall back to the stored status rather than
            # asserting 'offline' from a signal this node cannot produce.
            return node.get("status") or "unknown"
        return "online" if reachable else "offline"

    if not node.get("last_heartbeat"):
        return "offline"
    if not _heartbeat_fresh(node):
        return "offline"
    return node.get("status", "online")


def _compute_node_health(node):
    """Honest combined health label — 'the path the traffic actually uses'.

    Distinguishes the two ways a node lies about itself (#5218):
      unreachable  agent heartbeats (often over the LAN) but the MESH path is dead,
                   so dispatch cannot land. Both Starships looked green like this
                   on 2026-07-26 while unable to receive any work.
      agent_down   host reachable, node agent not reporting.

    Requires the caller to have selected mesh_status + node_role; degrades to the
    plain heartbeat verdict when they are absent.
    """
    from services.node_reachability import describe_status

    return describe_status(
        node.get("node_role"),
        _heartbeat_fresh(node),
        _mesh_reachable(node),
    )


def _get_user_nodes(user_id, is_admin=False):
    """Compatibility entry point; retain the caller's database override."""
    return _node_store.get_user_nodes(user_id, is_admin, db_cursor=get_db_cursor)


def _get_node_for_user(node_id, user_id, require_owner=True):
    """Compatibility entry point; retain the caller's database override."""
    return _node_store.get_node_for_user(node_id, user_id, require_owner, db_cursor=get_db_cursor)


def _get_node_for_user_by_int_id(int_id, user_id):
    """Compatibility entry point; retain the caller's database override."""
    return _node_store.get_node_for_user_by_int_id(int_id, user_id, db_cursor=get_db_cursor)


def auto_assign_agents_for_model(node_id_str: str, model_name: str) -> int:
    """Compatibility entry point; retain the caller's database override."""
    return _node_store.auto_assign_agents_for_model(node_id_str, model_name, db_cursor=get_db_cursor)


# ── Hardware Rest Mode ────────────────────────────────────────────────────────


def get_fleet_rest_config() -> dict:
    """Return rest config from system_config. Defaults: enabled=False, start=20, end=6."""
    try:
        with get_db_cursor(commit=False) as (_, cur):
            cur.execute("SELECT value FROM system_config WHERE key = 'fleet_hardware_rest'")
            row = cur.fetchone()
        if row:
            return json.loads(row["value"])
    except Exception:
        pass
    return {"enabled": False, "start_hour": 20, "end_hour": 6}


def set_fleet_rest_config(enabled: bool, start_hour: int = 20, end_hour: int = 6) -> None:
    """Persist rest config to system_config."""

    value = json.dumps({"enabled": enabled, "start_hour": start_hour, "end_hour": end_hour})
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """INSERT INTO system_config (key, value, updated_at)
               VALUES ('fleet_hardware_rest', %s, NOW())
               ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
            (value,),
        )


def is_fleet_rest_active() -> bool:
    """True if rest mode enabled AND current time is inside the rest window (America/Toronto)."""
    import pytz

    cfg = get_fleet_rest_config()
    if not cfg.get("enabled"):
        return False
    tz = pytz.timezone("America/Toronto")
    hour = datetime.now(tz).hour
    start, end = int(cfg.get("start_hour", 20)), int(cfg.get("end_hour", 6))
    if start > end:  # crosses midnight
        return hour >= start or hour < end
    return start <= hour < end


# ── Force undock (#5332) ─────────────────────────────────────────────────────
# "UNDOCKED = leave the ships alone" (owner, 2026-07-28). The schedule above
# only ever gated TWO call sites (candidate selection + warm-set) — pinned
# dispatches, ComfyUI routing, node keep-warms and model-control all still
# reached a resting Starship. This section adds (a) a manual force-undock that
# detaches the ships NOW, auto-expiring at the next rest-window END boundary so
# a manual force can never permanently strand a node, and (b) ONE shared
# predicate — is_starships_undocked() — that every gate consults, so the answer
# cannot drift between call sites the way the beacon/fleet lists once did.

FORCE_UNDOCK_KEY = "fleet_force_undock"


def next_rest_end_boundary(now=None) -> datetime:
    """Next occurrence of the rest window's end_hour (America/Toronto), within 24h.

    Used as the force-undock expiry: "auto-expiry at the window boundary".
    Works whether or not the schedule is enabled — the WINDOW defines the
    boundary; the toggle only says if it fires nightly on its own.
    """
    import pytz

    tz = pytz.timezone("America/Toronto")
    if now is None:
        now = datetime.now(tz)
    end = int(get_fleet_rest_config().get("end_hour", 6))
    candidate = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def force_undock_until(now=None):
    """The force-undock expiry datetime while ACTIVE, else None. Fail-open:
    any read/parse problem answers None (docked) — a DB hiccup must never
    silently un-route the fleet."""
    import pytz

    try:
        with get_db_cursor(commit=False) as (_, cur):
            cur.execute("SELECT value FROM system_config WHERE key = %s", (FORCE_UNDOCK_KEY,))
            row = cur.fetchone()
        if not row:
            return None
        until = datetime.fromisoformat(json.loads(row["value"]).get("until"))
        tz = pytz.timezone("America/Toronto")
        if now is None:
            now = datetime.now(tz)
        return until if until > now else None
    except Exception:
        return None


def set_force_undock(now=None) -> dict:
    """Arm force-undock NOW. Expiry = next rest-window end boundary (<24h away)."""
    until = next_rest_end_boundary(now)
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute(
            """INSERT INTO system_config (key, value, updated_at)
               VALUES (%s, %s, NOW())
               ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
            (FORCE_UNDOCK_KEY, json.dumps({"until": until.isoformat()})),
        )
    return {"until": until.isoformat()}


def clear_force_undock() -> None:
    """Redock early: drop the force flag (the schedule still applies on its own)."""
    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("DELETE FROM system_config WHERE key = %s", (FORCE_UNDOCK_KEY,))


def is_starships_undocked() -> bool:
    """#5332 — THE dock predicate. True when the Starships must be left alone:
    scheduled hardware rest is active OR a manual force-undock is armed.
    Every gate (candidate selection, preferred_node pins, ComfyUI routing,
    keep-warm jobs, model-control, queued-pin claims) consults THIS, never the
    schedule directly."""
    try:
        return is_fleet_rest_active() or force_undock_until() is not None
    except Exception:
        return False  # fail-open: never un-route the fleet on an internal error


def rest_status_snapshot(cfg: dict = None, now=None) -> dict:
    """#5321: ONE dict with everything the A.R.M.A.D.A. cluster strip needs
    about the hardware-rest schedule. The schedule lived only in a
    system_config JSON blob — invisible, which produced two real wrong
    beliefs in one day (a UTC/ET mix-up at 16:00 ET, and treating the
    20:00-06:00 window as armed while the toggle was actually OFF).

    Pure given (cfg, now) so it is testable; both default to live values.
    ``in_window`` is computed from the WINDOW alone — the strip must be able
    to say "window now, but rest is DISABLED" instead of lying either way.
    ``next_transition`` is likewise window-based (what WOULD happen / when).
    """
    import pytz

    if cfg is None:
        cfg = get_fleet_rest_config()
    tz = pytz.timezone("America/Toronto")
    if now is None:
        now = datetime.now(tz)
    start, end = int(cfg.get("start_hour", 20)), int(cfg.get("end_hour", 6))
    hour = now.hour
    if start > end:  # crosses midnight
        in_window = hour >= start or hour < end
    else:
        in_window = start <= hour < end
    enabled = bool(cfg.get("enabled"))

    # Nearest future window boundary: today's/tomorrow's start and end at :00.
    boundaries = []
    for base_hour, kind in ((start, "rest_start"), (end, "rest_end")):
        for day_offset in (0, 1):
            candidate = now.replace(hour=base_hour, minute=0, second=0, microsecond=0) + timedelta(days=day_offset)
            if candidate > now:
                boundaries.append((candidate, kind))
    boundaries.sort(key=lambda pair: pair[0])
    next_at, next_kind = boundaries[0]
    # In-window means the next boundary is the window END, and vice versa —
    # pick the first boundary of the expected kind to survive equal-hour edge cases.
    expected_kind = "rest_end" if in_window else "rest_start"
    for candidate, kind in boundaries:
        if kind == expected_kind:
            next_at, next_kind = candidate, kind
            break

    return {
        "enabled": enabled,
        "in_window": in_window,
        "active": enabled and in_window,
        "start_hour": start,
        "end_hour": end,
        "window_label": f"{start:02d}:00–{end:02d}:00 ET",
        "now_et": now.strftime("%H:%M ET"),
        "next_transition": {
            "kind": next_kind,
            "at": next_at.strftime("%H:%M ET"),
            "in_minutes": int((next_at - now).total_seconds() // 60),
        },
    }
