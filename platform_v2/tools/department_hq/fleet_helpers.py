"""
Fleet Command — Shared helpers and caches
==========================================
Merged from starbase/helpers.py and starship/helpers.py during Fleet migration.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import logging
from collections import deque
from datetime import datetime, timezone
from flask import jsonify, request
from flask_login import current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_cursor, check_fleet_model_unique
import requests

try:
    from ai_bridge.agent_performance_tracker import (
        get_agent_performance,
        update_agent_performance,
        get_top_performers,
        log_agent_action,
    )

    _HAS_PERFORMANCE_TRACKER = True
except ImportError:
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
        pm_size = round(pm.get("size", 0) / (1024**3), 1)
        pm_vram = pm.get("size_vram", 0)
        if pm_vram and pm_vram > 0:
            gpu_models.append({"name": pm_name, "size_gb": pm_size, "vram_gb": round(pm_vram / (1024**3), 1)})
        else:
            cpu_models.append({"name": pm_name, "size_gb": pm_size})

    # GPU info from nvidia-smi (may fail inside Docker without GPU passthrough)
    gpu_info = None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            if len(parts) >= 4:
                vram_total = round(float(parts[1]) / 1024, 1)
                vram_used = round(float(parts[2]) / 1024, 1)
                vram_free = round(float(parts[3]) / 1024, 1)
                gpu_info = {
                    "name": parts[0],
                    "vram_total_gb": vram_total,
                    "vram_used_gb": vram_used,
                    "vram_free_gb": vram_free,
                    "usage_pct": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                    "status": "red" if vram_free < 1.0 else ("amber" if vram_free < 2.0 else "green"),
                    "models": gpu_models,
                }
    except Exception as e:
        logger.warning("nvidia-smi query failed (expected in Docker without GPU passthrough): %s", e)

    # Fallback: build GPU info from Ollama VRAM data if nvidia-smi unavailable
    if gpu_info is None and gpu_models:
        vram_used = round(sum(m["vram_gb"] for m in gpu_models), 1)
        gpu_info = {
            "name": "GPU (via Ollama)",
            "vram_total_gb": 8.0,  # Quadro M4000
            "vram_used_gb": vram_used,
            "vram_free_gb": round(8.0 - vram_used, 1),
            "usage_pct": round(vram_used / 8.0 * 100, 1),
            "status": "red" if (8.0 - vram_used) < 1.0 else ("amber" if (8.0 - vram_used) < 2.0 else "green"),
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


def _compute_node_status(node):
    """Compute real status based on heartbeat freshness."""
    if not node.get("last_heartbeat"):
        return "offline"
    hb = node["last_heartbeat"]
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - hb).total_seconds()
    if age > HEARTBEAT_TIMEOUT_SECONDS:
        return "offline"
    return node.get("status", "online")


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
