"""
Fleet Command — Shared helpers and caches
==========================================
Merged from starbase/helpers.py and starship/helpers.py during Fleet migration.
"""

import json
import os
import subprocess
import time
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from database import get_db_cursor
import requests

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
    """Get hardware capacity info with 30s cache (GPU, RAM, model breakdown)."""
    now = time.time()
    if _hw_capacity_cache["data"] and (now - _hw_capacity_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _hw_capacity_cache["data"]

    import psutil

    mem = psutil.virtual_memory()
    total_gb = round(mem.total / (1024**3), 1)
    available_gb = round(mem.available / (1024**3), 1)
    usage_pct = round(mem.percent, 1)
    # RAM budget: 70% LLM / 15% host / 15% security services (ADR-078 updated)
    reserve_gb = round(total_gb * 0.15, 1)  # 15% host reserve (OS, Docker, platform, DB)
    security_gb = round(total_gb * 0.15, 1)  # 15% security services (Frigate, CrowdSec, Suricata, etc.)

    # Ollama loaded models — categorize GPU vs CPU
    ps_models = _get_cached_ollama_ps()
    models_loaded = len(ps_models)
    models_ram_gb = round(sum(m.get("size", 0) for m in ps_models) / (1024**3), 1)
    gpu_models = []
    cpu_models = []
    for pm in ps_models:
        pm_name = pm.get("name", "").replace(":latest", "")
        pm_total = pm.get("size", 0) or 0
        pm_size = round(pm_total / (1024**3), 1)
        pm_vram = pm.get("size_vram", 0) or 0
        # `size` vs `size_vram` is exactly what `ollama ps` uses to compute its
        # PROCESSOR column, so the GPU/CPU split is derivable here and needs no
        # second source. It was being discarded: the panel printed a GB figure
        # when vram>0 and the bare word "CPU" otherwise, so GPU residency was
        # implied by the PRESENCE of a number and never actually stated.
        if pm_vram <= 0:
            processor, gpu_pct = "cpu", 0
        elif pm_vram >= pm_total:
            processor, gpu_pct = "gpu", 100
        else:
            processor, gpu_pct = "split", int(round(pm_vram / pm_total * 100)) if pm_total else 0
        entry = {
            "name": pm_name,
            "size_gb": pm_size,
            "vram_gb": round(pm_vram / (1024**3), 1),
            "processor": processor,
            "gpu_pct": gpu_pct,
        }
        (gpu_models if pm_vram > 0 else cpu_models).append(entry)

    # GPU info from nvidia-smi (may fail inside Docker without GPU passthrough)
    gpu_info = None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                # uuid is the JOIN KEY to --query-compute-apps, which is the only
                # way to say which card carries which model (/api/ps does not say).
                # Index is NOT usable for that join and is misleading besides: the
                # TITAN is index 1, not 0, and ai-bridge.md warns to identify these
                # cards by UUID precisely because an index assumption was wrong once.
                "--query-gpu=name,memory.total,memory.used,memory.free,uuid",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # ONE LINE PER GPU. Splitting the whole payload on "," merged the rows:
            # measured 2026-09-20 on the hub, parts became
            #   ['Quadro M4000','8192','4','8116\nNVIDIA TITAN X (Pascal)','12288',...]
            # so parts[1]/parts[2] described GPU 0 ALONE -> the platform reported a
            # single 8GB card with 0.0GB used while a 12GB TITAN held 4.9GB. The
            # identical bug was found and fixed in scripts/host_monitor.py (KSO's
            # collector) on 2026-07-26; this copy was never fixed.
            cards = []
            for line in result.stdout.strip().splitlines():
                parts = [c.strip() for c in line.split(",")]
                if len(parts) < 4:
                    continue
                try:
                    c_total = round(float(parts[1]) / 1024, 1)
                    c_used = round(float(parts[2]) / 1024, 1)
                    c_free = round(float(parts[3]) / 1024, 1)
                except ValueError:
                    continue
                cards.append(
                    {
                        "index": len(cards),
                        "name": parts[0],
                        # Absent on older nvidia-smi builds; consumers must treat a
                        # missing uuid as "cannot join", not as a blank that matches.
                        "uuid": parts[4] if len(parts) > 4 else None,
                        "vram_total_gb": c_total,
                        "vram_used_gb": c_used,
                        "vram_free_gb": c_free,
                        "usage_pct": round(c_used / c_total * 100, 1) if c_total > 0 else 0,
                    }
                )
            if cards:
                vram_total = round(sum(c["vram_total_gb"] for c in cards), 1)
                vram_used = round(sum(c["vram_used_gb"] for c in cards), 1)
                vram_free = round(sum(c["vram_free_gb"] for c in cards), 1)
                largest_free = max(c["vram_free_gb"] for c in cards)
                gpu_info = {
                    "name": " + ".join(c["name"] for c in cards),
                    "gpus": cards,
                    "gpu_count": len(cards),
                    "vram_total_gb": vram_total,
                    "vram_used_gb": vram_used,
                    "vram_free_gb": vram_free,
                    "largest_free_gb": largest_free,
                    "total_known": True,
                    "usage_pct": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                    # Keyed on the LARGEST SINGLE card, not the sum: a model has to
                    # fit on one card, so 2GB free spread over two cards is not 2GB
                    # of capacity. Same rule as remote_nodes.gpu_vram_gb (fleet.md).
                    "status": "red" if largest_free < 1.0 else ("amber" if largest_free < 2.0 else "green"),
                    "models": gpu_models,
                }
    except Exception as e:
        logger.warning("nvidia-smi query failed (expected in Docker without GPU passthrough): %s", e)

    # Fallback: build GPU info from Ollama VRAM data if nvidia-smi unavailable
    if gpu_info is None and gpu_models:
        vram_used = round(sum(m["vram_gb"] for m in gpu_models), 1)
        # No nvidia-smi: we know what Ollama placed on a GPU but NOT how much VRAM
        # exists, so the total is reported as unknown rather than assumed. This
        # previously hardcoded 8.0 ("Quadro M4000") and computed a usage percentage
        # against it -- on a 20GB two-card host that is a confident wrong number.
        # An unknown capacity is reported as unknown (ADR-017).
        gpu_info = {
            "name": "GPU (via Ollama)",
            "gpus": [],
            "gpu_count": 0,
            "vram_total_gb": None,
            "vram_used_gb": vram_used,
            "vram_free_gb": None,
            "largest_free_gb": None,
            "total_known": False,
            "usage_pct": None,
            "status": "unknown",
            "models": gpu_models,
        }

    # ComfyUI VRAM usage (loads SDXL on-demand, torch_vram_total > 0 when active)
    comfyui_vram_gb = 0
    comfyui_status = "idle"
    comfyui_reserved_gb = 0
    try:
        comfyui_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
        _cfu_resp = requests.get(f"{comfyui_host}/system_stats", timeout=3)
        if _cfu_resp.status_code == 200:
            for dev in _cfu_resp.json().get("devices", []):
                if dev.get("type") == "cuda":
                    torch_vram = dev.get("torch_vram_total", 0)
                    comfyui_vram_gb = round(torch_vram / (1024**3), 1)
                    comfyui_status = "loaded" if torch_vram > 0 else "idle"
    except Exception as e:
        logger.warning("ComfyUI system_stats fetch failed: %s", e)
    # Estimate reserved VRAM for the configured checkpoint (SDXL ~6.5GB)
    if comfyui_status == "idle":
        try:
            with get_db_cursor(commit=False) as (_cconn, _ccur):
                _ccur.execute(
                    "SELECT image_model FROM agents WHERE image_model IS NOT NULL AND status = 'active' LIMIT 1"
                )
                _crow = _ccur.fetchone()
                if _crow:
                    ckpt = _crow["image_model"]
                    # Estimate VRAM from checkpoint name
                    if "xl" in ckpt.lower():
                        comfyui_reserved_gb = 6.5
                    else:
                        comfyui_reserved_gb = 4.0
        except Exception:
            comfyui_reserved_gb = 6.5  # Default SDXL estimate
    if gpu_info:
        gpu_info["comfyui_vram_gb"] = comfyui_vram_gb
        gpu_info["comfyui_status"] = comfyui_status
        gpu_info["comfyui_reserved_gb"] = comfyui_reserved_gb

    llm_budget_gb = round(total_gb * 0.70, 1)  # 70% for LLM agents
    agent_budget_gb = round(llm_budget_gb * 0.90, 1)  # 90% of LLM budget for active agents
    swap_buffer_gb = round(llm_budget_gb * 0.10, 1)  # 10% swap buffer for model rotation
    # Status: red if eating into reserve+security, amber if swap depleted, green if within budget
    swap_used_gb = max(0, models_ram_gb - agent_budget_gb)
    min_free = reserve_gb + security_gb  # Total non-LLM allocation
    if available_gb <= reserve_gb:
        ram_status = "red"
    elif available_gb <= min_free or swap_used_gb >= swap_buffer_gb:
        ram_status = "amber"
    else:
        ram_status = "green"

    capacity = {
        "ram": {
            "total_gb": total_gb,
            "available_gb": available_gb,
            "usage_pct": usage_pct,
            "reserve_gb": reserve_gb,
            "security_gb": security_gb,
            "llm_budget_gb": llm_budget_gb,
            "agent_budget_gb": agent_budget_gb,
            "swap_buffer_gb": swap_buffer_gb,
            "status": ram_status,
        },
        "gpu": gpu_info,
        "models_loaded": models_loaded,
        "models_ram_gb": models_ram_gb,
        "gpu_models": gpu_models,
        "cpu_models": cpu_models,
    }
    _hw_capacity_cache["data"] = capacity
    _hw_capacity_cache["time"] = now
    return capacity


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
    """Get all starship nodes owned by or visible to this user.
    Admins see all nodes. Nodes with NULL registered_by are visible to all."""
    with get_db_cursor() as (conn, cur):
        if is_admin:
            cur.execute(
                """
                SELECT id, node_id, node_name, deployment_mode, hostname, port,
                       status, is_active, bridge_enabled, bridge_priority,
                       gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                       approval_status, last_heartbeat, client_version,
                       -- #5218: node_role + mesh_status are what let the caller tell
                       -- "an agent phoned home" apart from "this node is reachable".
                       -- Without them _compute_node_health() degrades to the old
                       -- heartbeat-only verdict.
                       COALESCE(node_role, 'agent') AS node_role,
                       mesh_status, mesh_last_seen, mesh_latency_ms, reachable_port,
                       COALESCE(privacy_settings, '{}'::jsonb) as privacy_settings
                FROM remote_nodes
                ORDER BY bridge_priority DESC, node_name
                """
            )
        else:
            cur.execute(
                """
                SELECT id, node_id, node_name, deployment_mode, hostname, port,
                       status, is_active, bridge_enabled, bridge_priority,
                       gpu_model, gpu_vram_gb, cpu_model, cpu_cores, ram_gb, disk_gb,
                       approval_status, last_heartbeat, client_version,
                       -- #5218: node_role + mesh_status are what let the caller tell
                       -- "an agent phoned home" apart from "this node is reachable".
                       -- Without them _compute_node_health() degrades to the old
                       -- heartbeat-only verdict.
                       COALESCE(node_role, 'agent') AS node_role,
                       mesh_status, mesh_last_seen, mesh_latency_ms, reachable_port,
                       COALESCE(privacy_settings, '{}'::jsonb) as privacy_settings
                FROM remote_nodes
                WHERE registered_by = %s OR registered_by IS NULL
                ORDER BY bridge_priority DESC, node_name
                """,
                (user_id,),
            )
        return cur.fetchall()


def _get_node_for_user(node_id, user_id, require_owner=True):
    """Get a specific node, verifying ownership.
    Nodes with NULL registered_by are atomically claimed on first access."""
    with get_db_cursor(commit=True) as (conn, cur):
        if require_owner:
            # Try to claim orphan nodes atomically
            cur.execute(
                """UPDATE remote_nodes SET registered_by = %s
                   WHERE node_id = %s AND registered_by IS NULL""",
                (user_id, node_id),
            )
            cur.execute(
                """SELECT * FROM remote_nodes
                   WHERE node_id = %s AND registered_by = %s""",
                (node_id, user_id),
            )
        else:
            cur.execute("SELECT * FROM remote_nodes WHERE node_id = %s", (node_id,))
        return cur.fetchone()


def _get_node_for_user_by_int_id(int_id, user_id):
    """Get a node by its integer DB id, verifying ownership."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Claim orphan if needed
        cur.execute(
            """UPDATE remote_nodes SET registered_by = %s
               WHERE id = %s AND registered_by IS NULL""",
            (user_id, int_id),
        )
        cur.execute(
            """SELECT * FROM remote_nodes
               WHERE id = %s AND registered_by = %s""",
            (int_id, user_id),
        )
        return cur.fetchone()


def auto_assign_agents_for_model(node_id_str: str, model_name: str) -> int:
    """Auto-assign hub AI agents whose model matches to a fleet node.

    Called after a model becomes available on a node (heartbeat model sync or
    OTA model_pull ack). Inserts into node_agents with auto_assigned=TRUE.
    Skips agents already assigned to this node. Returns count assigned.
    """
    import logging

    logger = logging.getLogger(__name__)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO node_agents
                    (node_id, source_agent_id, hub_agent_id, name, display_name,
                     model, department, status, auto_assigned)
                SELECT
                    rn.id,
                    a.id, a.id,
                    a.name, COALESCE(a.display_name, a.name),
                    a.model, a.department,
                    'active', TRUE
                FROM agents a
                JOIN remote_nodes rn ON rn.node_id = %s
                WHERE a.model = %s
                  AND a.worker_type = 'ai'
                  AND a.shift_state IN ('active', 'barracked')
                  AND NOT EXISTS (
                      SELECT 1 FROM node_agents na2
                      WHERE na2.hub_agent_id = a.id
                        AND na2.node_id = rn.id
                  )
                ON CONFLICT (node_id, name)
                DO UPDATE SET status = 'active', auto_assigned = TRUE
                RETURNING id
                """,
                (node_id_str, model_name),
            )
            count = len(cur.fetchall())
            if count:
                logger.info(
                    "fleet: auto-assigned %d agent(s) with model %s to node %s",
                    count,
                    model_name,
                    node_id_str,
                )
            return count
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "auto_assign_agents_for_model failed for %s/%s: %s", node_id_str, model_name, exc
        )
        return 0


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
