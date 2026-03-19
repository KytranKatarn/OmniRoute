"""
A.R.C.H.I.E. STARBASE COMMAND Routes
=====================================
Central command center for all AI/LLM operations.
Provides visual monitoring and station-based workflow.

Author: A.R.C.H.I.E. Platform
Date: 2026-01-16
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import logging
from collections import deque
from datetime import datetime
from typing import Dict, List
from flask import Blueprint, render_template, jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
from rbac import require_permission, Permission
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

starbase_bp = Blueprint("starbase", __name__, url_prefix="/tools/starbase")

# Ollama tags cache (avoid hitting Ollama on every stats poll)
_ollama_tags_cache = {"models": [], "count": 0, "time": 0}
_OLLAMA_CACHE_TTL = 30  # seconds — matches stats poll interval


def _get_cached_ollama_tags():
    """Get Ollama model list with 30s cache"""
    now = time.time()
    if _ollama_tags_cache["time"] and (now - _ollama_tags_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_tags_cache["models"], _ollama_tags_cache["count"]
    try:
        host = os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
        if not host.startswith("http"):
            host = f"http://{host}"
        resp = requests.get(f"{host}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_tags_cache["models"] = models
            _ollama_tags_cache["count"] = len(models)
            _ollama_tags_cache["time"] = now
            return models, len(models)
    except Exception:
        pass
    return _ollama_tags_cache["models"], _ollama_tags_cache["count"]


# Ollama ps cache (avoid hitting Ollama /api/ps on every poll)
_ollama_ps_cache = {"models": [], "time": 0}


def _get_cached_ollama_ps():
    """Get loaded Ollama models with 30s cache"""
    now = time.time()
    if _ollama_ps_cache["time"] and (now - _ollama_ps_cache["time"]) < _OLLAMA_CACHE_TTL:
        return _ollama_ps_cache["models"]
    try:
        host = os.getenv("OLLAMA_HOST", "http://archie_ollama:11434")
        if not host.startswith("http"):
            host = f"http://{host}"
        resp = requests.get(f"{host}/api/ps", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            _ollama_ps_cache["models"] = models
            _ollama_ps_cache["time"] = now
            return models
    except Exception:
        pass
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
    except Exception:
        pass

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
    except Exception:
        pass
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
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    _activity_queue.appendleft(evt)


# ============================================================================
# MAIN BRIDGE PAGE
# ============================================================================


@starbase_bp.route("/")
@login_required
def starbase_dashboard():
    """Render the main Starbase command center"""
    deployment_mode = os.getenv("DEPLOYMENT_MODE", "hub")
    if deployment_mode == "business_node":
        return render_template(
            "tools/starbase_hub.html",
            deployment_mode=deployment_mode,
            node_id=os.getenv("NODE_ID", ""),
            hub_url=os.getenv("HUB_URL", ""),
        )
    else:
        # Hub and default: full command center with stations, agents, crew + mesh
        # Pre-fetch status bar data so it shows instantly (no flash of "--")
        agent_count = 0
        interactions_24h = 0
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT COUNT(*) AS cnt FROM agents WHERE status = 'active'")
                agent_count = cur.fetchone()["cnt"]
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM task_execution_log " "WHERE created_at >= NOW() - INTERVAL '24 hours'"
                )
                interactions_24h = cur.fetchone()["cnt"]
        except Exception:
            pass
        return render_template(
            "tools/starbase.html",
            deployment_mode=deployment_mode,
            initial_agent_count=agent_count,
            initial_interactions_24h=interactions_24h,
        )


# ============================================================================
# BRIDGE STATS API
# ============================================================================


@starbase_bp.route("/api/stats")
@login_required
def get_bridge_stats():
    """Get overall Bridge statistics"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Get active agents count
            cur.execute(
                """
                SELECT COUNT(*) as active_agents
                FROM agents
                WHERE status = 'active'
            """
            )
            agent_stats = cur.fetchone()

            # Get recent token usage (last 24h)
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(tokens_used), 0) as total_tokens,
                    COUNT(*) as total_requests
                FROM token_usage_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """
            )
            token_stats = cur.fetchone()

            # Get A.R.C.H.I.E.'s emotional state
            cur.execute(
                """
                SELECT current_mood, mood_intensity, relationship_strength
                FROM archie_emotional_state
                ORDER BY timestamp DESC
                LIMIT 1
            """
            )
            emotional_state = cur.fetchone() or {
                "current_mood": "supportive",
                "mood_intensity": 0.85,
                "relationship_strength": 0.90,
            }

            # Get real LLM model counts from Ollama (cached)
            _, llm_total = _get_cached_ollama_tags()
            llm_online = llm_total

            # System load from active requests ratio (capped 0-100)
            active_requests = token_stats["total_requests"] if token_stats else 0
            system_load = min(int(active_requests / max(1, active_requests + 10) * 100), 100)

            return jsonify(
                {
                    "success": True,
                    "stats": {
                        "llm_status": {"online": llm_online, "total": llm_total},
                        "active_requests": active_requests,
                        "system_load": system_load,
                        "active_agents": agent_stats["active_agents"] if agent_stats else 0,
                        "tokens_24h": token_stats["total_tokens"] if token_stats else 0,
                    },
                    "archie": {
                        "mood": emotional_state["current_mood"],
                        "energy": (
                            float(emotional_state["mood_intensity"]) if emotional_state.get("mood_intensity") else 0.85
                        ),
                        "relationship": (
                            float(emotional_state["relationship_strength"])
                            if emotional_state.get("relationship_strength")
                            else 0.90
                        ),
                        "status": "Active",
                    },
                    "captain": {"name": "Kytran", "role": "Admin", "status": "On Duty"},
                }
            )

    except Exception as e:
        logger.error(f"Error getting bridge stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# TOKEN USAGE / TRAFFIC API
# ============================================================================


@starbase_bp.route("/api/traffic")
@login_required
def get_traffic_stats():
    """Get throughput stats from task_execution_log (rolling 24h window)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT COUNT(*) as total_24h
                FROM task_execution_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            """
            )
            row = cur.fetchone()
            total_24h = row["total_24h"] if row else 0
            requests_per_minute = round(total_24h / 1440.0, 1)

            return jsonify(
                {
                    "success": True,
                    "requests_per_minute": requests_per_minute,
                    "total_24h": total_24h,
                }
            )

    except Exception as e:
        logger.error(f"Error getting traffic stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@starbase_bp.route("/api/agent-utilization")
@login_required
def get_agent_utilization():
    """Get real agent activity rate over 24h (agents that executed tasks / total active)"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT
                    (SELECT COUNT(DISTINCT agent_id) FROM task_execution_log
                     WHERE created_at >= NOW() - INTERVAL '24 hours' AND agent_id IS NOT NULL) as active_agents,
                    (SELECT COUNT(*) FROM agents WHERE status = 'active') as total_agents
            """
            )
            row = cur.fetchone()
            active = row["active_agents"] or 0
            total = row["total_agents"] or 0
            utilization_pct = round(active / total * 100) if total > 0 else 0

            return jsonify(
                {
                    "success": True,
                    "active_agents": active,
                    "total_agents": total,
                    "utilization_pct": utilization_pct,
                }
            )

    except Exception as e:
        logger.error(f"Error getting agent utilization: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@starbase_bp.route("/api/models/live")
@login_required
def get_live_models():
    """Get actual model count from live Ollama API"""
    models, count = _get_cached_ollama_tags()
    return jsonify({"success": True, "count": count, "models": [m["name"] for m in models]})


@starbase_bp.route("/api/iaae/overview")
@login_required
def get_iaae_overview():
    """Get real IAAE compliance and welfare metrics"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Agent welfare: stress and energy across active agents
            cur.execute(
                """
                SELECT es.stress_level, es.energy_level
                FROM agent_emotional_state es
                JOIN agents a ON a.id = es.agent_id
                WHERE a.status = 'active'
            """
            )
            welfare_rows = cur.fetchall()
            stress_vals = [r["stress_level"] for r in welfare_rows if r["stress_level"] is not None]
            energy_vals = [r["energy_level"] for r in welfare_rows if r["energy_level"] is not None]
            avg_stress = round(sum(stress_vals) / len(stress_vals), 2) if stress_vals else None
            avg_energy = round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None

            # Compliance = agents within ethical limits (stress <= 0.7, energy >= 0.3)
            monitored = [
                r for r in welfare_rows if r.get("stress_level") is not None or r.get("energy_level") is not None
            ]
            healthy = sum(
                1 for r in monitored if (r.get("stress_level") or 0) <= 0.7 and (r.get("energy_level") or 1) >= 0.3
            )
            compliance_pct = round(healthy / len(monitored) * 100, 1) if monitored else None

            # Governance events 24h
            cur.execute(
                """
                SELECT COUNT(*) as total
                FROM governance_audit_log
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
            """
            )
            gov_total = cur.fetchone()["total"] or 0

            # Agents currently at rest
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM agent_rest_cycles
                WHERE ended_at IS NULL
            """
            )
            rest_row = cur.fetchone()
            agents_at_rest = rest_row["count"] or 0

            return jsonify(
                {
                    "success": True,
                    "compliance_pct": compliance_pct,
                    "avg_stress": avg_stress,
                    "avg_energy": avg_energy,
                    "agents_at_rest": agents_at_rest,
                    "governance_events_24h": gov_total,
                }
            )

    except Exception as e:
        logger.error(f"Error getting IAAE overview: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@starbase_bp.route("/api/agents/workload")
@login_required
def get_agent_workload():
    """Per-agent workload: 24h tasks, tokens, daily caps, risk levels."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            cur.execute(
                """
                SELECT
                    a.id, a.name, a.first_name, a.last_name, a.status,
                    COALESCE(ab.task_queue_limit, 50) as daily_cap,
                    COALESCE(ab.token_limit_per_day, 500000) as token_cap,
                    COUNT(tel.id) as tasks_24h,
                    COUNT(tel.id) FILTER (WHERE tel.success = TRUE) as completed_24h,
                    COUNT(tel.id) FILTER (WHERE tel.success = FALSE) as failed_24h,
                    COALESCE(AVG(tel.duration_ms), 0) as avg_duration_ms,
                    COALESCE(SUM(tel.tokens_used), 0) as tokens_used_24h
                FROM agents a
                LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
                LEFT JOIN task_execution_log tel ON tel.agent_id = a.id
                    AND tel.created_at >= NOW() - INTERVAL '24 hours'
                WHERE a.status IN ('active', 'busy', 'idle', 'working')
                GROUP BY a.id, a.name, a.first_name, a.last_name, a.status,
                         ab.task_queue_limit, ab.token_limit_per_day
                ORDER BY tasks_24h DESC
            """
            )
            rows = cur.fetchall()

            agents = []
            total_tasks = 0
            at_risk = 0
            for r in rows:
                daily_cap = int(r["daily_cap"]) or 50
                token_cap = int(r["token_cap"]) or 500000
                tasks = int(r["tasks_24h"])
                tokens = int(r["tokens_used_24h"])
                workload_pct = min(round(tasks / daily_cap * 100, 1), 100) if daily_cap > 0 else 0
                token_pct = min(round(tokens / token_cap * 100, 1), 100) if token_cap > 0 else 0

                if workload_pct >= 100:
                    risk = "overloaded"
                elif workload_pct >= 80:
                    risk = "critical"
                elif workload_pct >= 60:
                    risk = "elevated"
                else:
                    risk = "healthy"

                if risk in ("critical", "overloaded"):
                    at_risk += 1
                total_tasks += tasks

                agents.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "first_name": r.get("first_name"),
                        "last_name": r.get("last_name"),
                        "status": r["status"],
                        "daily_cap": daily_cap,
                        "token_cap": token_cap,
                        "tasks_24h": tasks,
                        "completed_24h": int(r["completed_24h"]),
                        "failed_24h": int(r["failed_24h"]),
                        "avg_duration_ms": round(float(r["avg_duration_ms"]), 1),
                        "tokens_used_24h": tokens,
                        "workload_pct": workload_pct,
                        "token_usage_pct": token_pct,
                        "risk_level": risk,
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "agents": agents,
                    "summary": {
                        "total_agents": len(agents),
                        "total_tasks_24h": total_tasks,
                        "agents_at_risk": at_risk,
                    },
                }
            )
    except Exception as e:
        logger.error("get_agent_workload error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@starbase_bp.route("/api/agents/welfare")
@login_required
def get_agent_welfare():
    """Aggregate welfare: emotional state, rest cycles, refusals, governance."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Latest emotional state per agent (using DISTINCT ON)
            cur.execute(
                """
                SELECT DISTINCT ON (a.id)
                    a.id, a.name, a.first_name, a.last_name,
                    es.current_mood as mood, es.mood_intensity as intensity,
                    es.energy_level, es.stress_level, es.timestamp as last_check
                FROM agents a
                LEFT JOIN agent_emotional_state es ON es.agent_id = a.id
                WHERE a.status IN ('active', 'busy', 'idle', 'working', 'resting')
                ORDER BY a.id, es.timestamp DESC NULLS LAST
            """
            )
            agents = cur.fetchall()
            for a in agents:
                if a.get("last_check"):
                    a["last_check"] = a["last_check"].isoformat()
                for k in ["intensity", "energy_level", "stress_level"]:
                    if a.get(k) is not None:
                        a[k] = float(a[k])

            # Agents currently at rest
            cur.execute(
                """
                SELECT a.id, a.name, arc.reason, arc.started_at, arc.initiated_by
                FROM agent_rest_cycles arc
                JOIN agents a ON a.id = arc.agent_id
                WHERE arc.ended_at IS NULL
            """
            )
            resting = cur.fetchall()
            for r in resting:
                if r.get("started_at"):
                    r["started_at"] = r["started_at"].isoformat()

            # Recent refusals (24h)
            cur.execute(
                """
                SELECT a.id, a.name, trl.refusal_reason as reason,
                       trl.task_type, trl.was_overridden, trl.timestamp
                FROM task_refusal_log trl
                JOIN agents a ON a.id = trl.agent_id
                WHERE trl.timestamp >= NOW() - INTERVAL '24 hours'
                ORDER BY trl.timestamp DESC
                LIMIT 20
            """
            )
            refusals = cur.fetchall()
            for r in refusals:
                if r.get("timestamp"):
                    r["timestamp"] = r["timestamp"].isoformat()

            # Governance events (24h)
            cur.execute(
                """
                SELECT event_category, COUNT(*) as count
                FROM governance_audit_log
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
                GROUP BY event_category
            """
            )
            gov_rows = cur.fetchall()
            gov_summary = {}
            for g in gov_rows:
                gov_summary[g["event_category"]] = g["count"]

            # Fleet health aggregates
            stress_vals = [a["stress_level"] for a in agents if a.get("stress_level") is not None]
            energy_vals = [a["energy_level"] for a in agents if a.get("energy_level") is not None]
            avg_stress = round(sum(stress_vals) / len(stress_vals), 2) if stress_vals else None
            avg_energy = round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None
            high_stress = sum(1 for s in stress_vals if s > 0.7)

            total_gov = sum(gov_summary.values()) if gov_summary else 0

            # Compliance = agents within ethical limits (stress <= 0.7, energy >= 0.3)
            monitored = [a for a in agents if a.get("stress_level") is not None or a.get("energy_level") is not None]
            healthy_count = sum(
                1 for a in monitored if (a.get("stress_level") or 0) <= 0.7 and (a.get("energy_level") or 1) >= 0.3
            )
            compliance_pct = round(healthy_count / len(monitored) * 100, 1) if monitored else None

            return jsonify(
                {
                    "success": True,
                    "agents": agents,
                    "agents_at_rest": resting,
                    "recent_refusals": refusals,
                    "governance_summary": gov_summary,
                    "fleet_health": {
                        "avg_stress": avg_stress,
                        "avg_energy": avg_energy,
                        "agents_at_risk": high_stress,
                        "agents_resting": len(resting),
                        "compliance_pct": compliance_pct,
                        "total_governance_events": total_gov,
                    },
                }
            )
    except Exception as e:
        logger.error("get_agent_welfare error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@starbase_bp.route("/api/iaae/enforcement-log")
@login_required
def get_iaae_enforcement_log():
    """Vigil's Log: governance actions, IAAE welfare checks, and agent health."""
    try:
        events = []

        with get_db_cursor(commit=False) as (conn, cur):
            # 1. Governance audit events (excluding dev commits)
            cur.execute(
                """
                SELECT gal.id, gal.timestamp, gal.event_type, gal.event_category,
                       gal.action, gal.reason, gal.outcome,
                       gal.agent_id, a.name as agent_name,
                       a.first_name as agent_first_name
                FROM governance_audit_log gal
                LEFT JOIN agents a ON a.id = gal.agent_id
                WHERE gal.timestamp >= NOW() - INTERVAL '7 days'
                  AND gal.event_type != 'dev_commit'
                ORDER BY gal.timestamp DESC
                LIMIT 20
            """
            )
            for r in cur.fetchall():
                # Build readable label from event_type + action
                etype = (r["event_type"] or "").replace("_", " ")
                action = r["action"] or ""
                if action:
                    label = f"{etype} — {action}"
                else:
                    label = etype
                events.append(
                    {
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                        "event_category": r["event_category"] or "governance",
                        "label": label,
                        "agent_name": r["agent_first_name"] or r["agent_name"],
                        "severity": "warning" if r["event_category"] == "autonomy" else "info",
                    }
                )

            # 2. IAAE welfare scan — check current agent states against thresholds
            cur.execute(
                """
                SELECT DISTINCT ON (aes.agent_id)
                       aes.agent_id,
                       COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name,
                       aes.stress_level, aes.energy_level,
                       aes.current_mood, aes.timestamp
                FROM agent_emotional_state aes
                JOIN agents a ON a.id = aes.agent_id
                WHERE a.status = 'active'
                ORDER BY aes.agent_id, aes.timestamp DESC
            """
            )
            agent_states = cur.fetchall()

            # Get IAAE thresholds
            cur.execute(
                "SELECT threshold_type, warning_level, critical_level " "FROM iaae_thresholds WHERE is_active = true"
            )
            thresholds = {r["threshold_type"]: r for r in cur.fetchall()}

            stress_warn = float(thresholds.get("stress_high", {}).get("warning_level", 0.70))
            stress_crit = float(thresholds.get("stress_high", {}).get("critical_level", 0.85))
            energy_warn = float(thresholds.get("energy_low", {}).get("warning_level", 0.40))
            energy_crit = float(thresholds.get("energy_low", {}).get("critical_level", 0.30))

            for agent in agent_states:
                stress = float(agent["stress_level"] or 0)
                energy = float(agent["energy_level"] or 0)
                name = agent["agent_name"]
                ts = agent["timestamp"].isoformat() if agent["timestamp"] else None

                if stress >= stress_crit:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"stress critical ({stress:.0%})",
                            "agent_name": name,
                            "severity": "critical",
                        }
                    )
                elif stress >= stress_warn:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"stress elevated ({stress:.0%})",
                            "agent_name": name,
                            "severity": "warning",
                        }
                    )

                if energy <= energy_crit:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"energy critical ({energy:.0%})",
                            "agent_name": name,
                            "severity": "critical",
                        }
                    )
                elif energy <= energy_warn:
                    events.append(
                        {
                            "timestamp": ts,
                            "event_category": "welfare",
                            "label": f"energy low ({energy:.0%})",
                            "agent_name": name,
                            "severity": "warning",
                        }
                    )

            # 3. ARCHIE wellness check
            cur.execute(
                """
                SELECT current_mood, mood_intensity, timestamp
                FROM archie_emotional_state
                ORDER BY timestamp DESC LIMIT 1
            """
            )
            archie_state = cur.fetchone()
            if archie_state and archie_state["timestamp"]:
                events.append(
                    {
                        "timestamp": archie_state["timestamp"].isoformat(),
                        "event_category": "archie_wellness",
                        "label": f"ARCHIE mood: {archie_state['current_mood']}",
                        "agent_name": None,
                        "severity": "info",
                    }
                )

            # 4. Failed dispatches — Vigil flags task execution failures
            cur.execute(
                """
                SELECT tel.id, tel.created_at,
                       COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name) AS agent_name,
                       tel.module_source, tel.task_type, tel.capability,
                       tel.model_used, tel.error_message
                FROM task_execution_log tel
                LEFT JOIN agents a ON a.id = tel.agent_id
                WHERE tel.success = false
                  AND tel.created_at >= NOW() - INTERVAL '7 days'
                ORDER BY tel.created_at DESC
                LIMIT 15
            """
            )
            for r in cur.fetchall():
                module = r["module_source"] or ""
                cap = r["capability"] or r["task_type"] or ""
                detail = f"{module} / {cap}" if module and cap else module or cap
                err = r["error_message"] or "unknown error"
                # Truncate long error messages
                if len(err) > 80:
                    err = err[:77] + "..."
                events.append(
                    {
                        "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                        "event_category": "dispatch",
                        "label": f"dispatch failed — {detail}: {err}" if detail else f"dispatch failed — {err}",
                        "agent_name": r["agent_name"],
                        "severity": "warning",
                    }
                )

            # 5. Escalation events — model tier escalations
            cur.execute(
                """
                SELECT del.id, del.created_at, del.original_model,
                       del.escalated_model, del.escalated_provider,
                       del.capability, del.module_id, del.reason,
                       del.failure_count, del.success,
                       COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name
                FROM dispatch_escalation_log del
                LEFT JOIN agents a ON a.id = del.original_agent_id
                WHERE del.created_at >= NOW() - INTERVAL '7 days'
                ORDER BY del.created_at DESC
                LIMIT 10
            """
            )
            for r in cur.fetchall():
                reason = r["reason"] or "capability exceeded"
                if len(reason) > 60:
                    reason = reason[:57] + "..."
                events.append(
                    {
                        "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                        "event_category": "governance",
                        "label": f"Escalated from {r['original_model']} to {r['escalated_model']}: {reason}",
                        "agent_name": r["agent_name"],
                        "severity": "warning",
                    }
                )

        # Sort by timestamp descending
        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        return jsonify({"success": True, "events": events, "total": len(events)})
    except Exception as e:
        logger.error("get_iaae_enforcement_log error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@starbase_bp.route("/api/iaae/enforcement-log-full")
@login_required
def get_iaae_enforcement_log_full():
    """Vigil's Log — paginated full view with category filter."""
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(50, max(5, int(request.args.get("per_page", 20))))
        category_filter = request.args.get("filter", "all")
        events = []

        with get_db_cursor(commit=False) as (conn, cur):
            # 1. Governance audit events
            if category_filter in ("all", "governance", "autonomy"):
                cur.execute(
                    """
                    SELECT gal.id, gal.timestamp, gal.event_type, gal.event_category,
                           gal.action, gal.reason, gal.outcome,
                           gal.agent_id, a.name as agent_name,
                           a.first_name as agent_first_name
                    FROM governance_audit_log gal
                    LEFT JOIN agents a ON a.id = gal.agent_id
                    WHERE gal.timestamp >= NOW() - INTERVAL '30 days'
                      AND gal.event_type != 'dev_commit'
                    ORDER BY gal.timestamp DESC
                    LIMIT 200
                """
                )
                for r in cur.fetchall():
                    etype = (r["event_type"] or "").replace("_", " ")
                    action = r["action"] or ""
                    label = f"{etype} — {action}" if action else etype
                    cat = r["event_category"] or "governance"
                    if category_filter != "all" and cat != category_filter:
                        continue
                    events.append(
                        {
                            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                            "event_category": cat,
                            "label": label,
                            "agent_name": r["agent_first_name"] or r["agent_name"],
                            "severity": "warning" if cat == "autonomy" else "info",
                        }
                    )

            # 2. Welfare checks
            if category_filter in ("all", "welfare"):
                cur.execute(
                    """
                    SELECT DISTINCT ON (aes.agent_id)
                           aes.agent_id,
                           COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name,
                           aes.stress_level, aes.energy_level,
                           aes.current_mood, aes.timestamp
                    FROM agent_emotional_state aes
                    JOIN agents a ON a.id = aes.agent_id
                    WHERE a.status = 'active'
                    ORDER BY aes.agent_id, aes.timestamp DESC
                """
                )
                agent_states = cur.fetchall()

                cur.execute(
                    "SELECT threshold_type, warning_level, critical_level "
                    "FROM iaae_thresholds WHERE is_active = true"
                )
                thresholds = {r["threshold_type"]: r for r in cur.fetchall()}

                stress_warn = float(thresholds.get("stress_high", {}).get("warning_level", 0.70))
                stress_crit = float(thresholds.get("stress_high", {}).get("critical_level", 0.85))
                energy_warn = float(thresholds.get("energy_low", {}).get("warning_level", 0.40))
                energy_crit = float(thresholds.get("energy_low", {}).get("critical_level", 0.30))

                for agent in agent_states:
                    stress = float(agent["stress_level"] or 0)
                    energy = float(agent["energy_level"] or 0)
                    name = agent["agent_name"]
                    ts = agent["timestamp"].isoformat() if agent["timestamp"] else None

                    if stress >= stress_crit:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"stress critical ({stress:.0%})",
                                "agent_name": name,
                                "severity": "critical",
                            }
                        )
                    elif stress >= stress_warn:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"stress elevated ({stress:.0%})",
                                "agent_name": name,
                                "severity": "warning",
                            }
                        )

                    if energy <= energy_crit:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"energy critical ({energy:.0%})",
                                "agent_name": name,
                                "severity": "critical",
                            }
                        )
                    elif energy <= energy_warn:
                        events.append(
                            {
                                "timestamp": ts,
                                "event_category": "welfare",
                                "label": f"energy low ({energy:.0%})",
                                "agent_name": name,
                                "severity": "warning",
                            }
                        )

            # 3. ARCHIE wellness
            if category_filter in ("all", "archie_wellness"):
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, timestamp
                    FROM archie_emotional_state
                    ORDER BY timestamp DESC LIMIT 1
                """
                )
                archie_state = cur.fetchone()
                if archie_state and archie_state["timestamp"]:
                    events.append(
                        {
                            "timestamp": archie_state["timestamp"].isoformat(),
                            "event_category": "archie_wellness",
                            "label": f"ARCHIE mood: {archie_state['current_mood']}",
                            "agent_name": None,
                            "severity": "info",
                        }
                    )

            # 4. Failed dispatches
            if category_filter in ("all", "dispatch"):
                cur.execute(
                    """
                    SELECT tel.id, tel.created_at,
                           COALESCE(NULLIF(a.first_name, ''), a.name, tel.agent_name)
                               AS agent_name,
                           tel.module_source, tel.task_type, tel.capability,
                           tel.model_used, tel.error_message
                    FROM task_execution_log tel
                    LEFT JOIN agents a ON a.id = tel.agent_id
                    WHERE tel.success = false
                      AND tel.created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY tel.created_at DESC
                    LIMIT 200
                """
                )
                for r in cur.fetchall():
                    module = r["module_source"] or ""
                    cap = r["capability"] or r["task_type"] or ""
                    detail = f"{module} / {cap}" if module and cap else module or cap
                    err = r["error_message"] or "unknown error"
                    if len(err) > 100:
                        err = err[:97] + "..."
                    events.append(
                        {
                            "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                            "event_category": "dispatch",
                            "label": f"dispatch failed — {detail}: {err}" if detail else f"dispatch failed — {err}",
                            "agent_name": r["agent_name"],
                            "severity": "warning",
                        }
                    )

            # 5. Escalation events
            if category_filter in ("all", "governance"):
                cur.execute(
                    """
                    SELECT del.id, del.created_at, del.original_model,
                           del.escalated_model, del.escalated_provider,
                           del.capability, del.module_id, del.reason,
                           del.failure_count, del.success,
                           COALESCE(NULLIF(a.first_name, ''), a.name) as agent_name
                    FROM dispatch_escalation_log del
                    LEFT JOIN agents a ON a.id = del.original_agent_id
                    WHERE del.created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY del.created_at DESC
                    LIMIT 50
                """
                )
                for r in cur.fetchall():
                    reason = r["reason"] or "capability exceeded"
                    if len(reason) > 80:
                        reason = reason[:77] + "..."
                    events.append(
                        {
                            "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                            "event_category": "governance",
                            "label": f"Escalated from {r['original_model']} to {r['escalated_model']}: {reason}",
                            "agent_name": r["agent_name"],
                            "severity": "warning",
                        }
                    )

        # Sort by timestamp descending
        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        total = len(events)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(page, total_pages)
        start = (page - 1) * per_page
        paged = events[start : start + per_page]

        return jsonify(
            {
                "success": True,
                "events": paged,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            }
        )
    except Exception as e:
        logger.error("get_iaae_enforcement_log_full error: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ARCHIE STATUS API
# ============================================================================


@starbase_bp.route("/api/archie/status")
@login_required
def get_archie_status():
    """Get A.R.C.H.I.E.'s current status and emotional state"""
    try:
        with get_db_cursor(commit=False) as (conn, cur):

            # Get core identity
            cur.execute(
                """
                SELECT name, role, personality_profile
                FROM archie_core_identity
                LIMIT 1
            """
            )
            identity = cur.fetchone()

            # Get emotional state
            cur.execute(
                """
                SELECT
                    current_mood, mood_intensity, relationship_strength, timestamp
                FROM archie_emotional_state
                ORDER BY timestamp DESC
                LIMIT 1
            """
            )
            emotional = cur.fetchone()

            # Get personality traits
            cur.execute(
                """
                SELECT trait_name, trait_value, description
                FROM archie_personality
                ORDER BY updated_at DESC
                LIMIT 5
            """
            )
            traits = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "archie": {
                        "identity": identity or {"name": "A.R.C.H.I.E.", "role": "AI Co-founder"},
                        "emotional_state": emotional
                        or {
                            "current_mood": "supportive",
                            "mood_intensity": 0.85,
                            "relationship_strength": 0.90,
                        },
                        "top_traits": traits or [],
                        "station": "COMMS",
                        "status": "Active",
                    },
                }
            )

    except Exception as e:
        logger.error(f"Error getting ARCHIE status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# LLM CONNECTIONS MONITOR (Phase 27)
# ============================================================================


@starbase_bp.route("/api/llm/status")
@login_required
def get_llm_status():
    """Get live LLM status from Ollama + external API key checks"""
    try:
        ollama_host = os.getenv("OLLAMA_LOCAL_HOST", "archie_ollama")
        ollama_port = int(os.getenv("OLLAMA_LOCAL_PORT", "11434"))

        # 1. Check Ollama health
        status, latency = check_ollama_status(ollama_host, ollama_port)

        # 2. Get loaded models (currently in VRAM/RAM)
        loaded_models = []
        for m in _get_cached_ollama_ps():
            loaded_models.append(
                {
                    "name": m.get("name", "unknown"),
                    "size": m.get("size", 0),
                    "vram": m.get("size_vram", 0),
                    "expires": m.get("expires_at", ""),
                }
            )
        loaded_names = {m["name"] for m in loaded_models}

        # 3. Get all available models (dict of name -> size_bytes)
        available_models = get_ollama_models(ollama_host, ollama_port)

        # 3b. Get models assigned to active agents (green = agent is using it)
        assigned_models = set()
        try:
            with get_db_cursor(commit=False) as (aconn, acur):
                acur.execute("SELECT DISTINCT model FROM agents WHERE status = 'active' AND model IS NOT NULL")
                for row in acur.fetchall():
                    assigned_models.add(row["model"])
        except Exception:
            pass

        # 4. Build model list with status and size
        models = []
        for name, size_bytes in available_models.items():
            # Check assignment: match with or without :latest suffix
            is_assigned = name in assigned_models or name.split(":")[0] in {m.split(":")[0] for m in assigned_models}
            models.append(
                {
                    "name": name,
                    "provider": "ollama",
                    "status": "loaded" if name in loaded_names else "available",
                    "assigned": is_assigned,
                    "size": size_bytes,
                }
            )

        # 5. Check external AI providers — dynamic from contractor_providers + external_api_keys
        external = []
        try:
            with get_db_cursor(commit=False) as (pconn, pcur):
                pcur.execute(
                    """
                    SELECT cp.provider_key, cp.display_name, cp.is_cloud_proxy,
                           eak.is_active as key_active,
                           eak.monthly_budget_usd, eak.current_month_cost_usd,
                           CASE WHEN eak.api_key_encrypted IS NOT NULL AND eak.api_key_encrypted != ''
                                THEN TRUE ELSE FALSE END as has_key
                    FROM contractor_providers cp
                    LEFT JOIN external_api_keys eak ON cp.provider_key = eak.provider
                    WHERE cp.is_active = TRUE OR eak.is_active = TRUE
                    ORDER BY cp.tier_position
                    """
                )
                ollama_key = os.getenv("OLLAMA_API_KEY", "")
                for row in pcur.fetchall():
                    prov = row["provider_key"]
                    has_key = row["has_key"] if row["has_key"] is not None else False
                    is_active = row["key_active"] if row["key_active"] is not None else False

                    # Cloud proxy providers check env var
                    if row["is_cloud_proxy"]:
                        has_key = bool(ollama_key)
                        if not is_active:
                            is_active = has_key

                    if has_key and is_active:
                        prov_status = "active"
                    elif has_key:
                        prov_status = "configured"
                    else:
                        prov_status = "no_key"
                    entry = {
                        "name": row["display_name"],
                        "provider": prov,
                        "status": prov_status,
                    }
                    budget = row.get("monthly_budget_usd")
                    cost = row.get("current_month_cost_usd")
                    if budget and float(budget) > 0:
                        entry["budget_pct"] = round(float(cost or 0) / float(budget) * 100, 1)
                    external.append(entry)
        except Exception as e:
            logger.warning(f"Could not query contractor_providers: {e}")

        # 6. Get routing mode
        routing_mode = "full"
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
                row = cur.fetchone()
                if row:
                    routing_mode = row["value"]
        except Exception:
            pass

        return jsonify(
            {
                "success": True,
                "ollama_status": status,
                "ollama_latency_ms": latency,
                "loaded_models": loaded_models,
                "models": models,
                "external": external,
                "routing_mode": routing_mode,
                "total_available": len(available_models),
                "total_loaded": len(loaded_models),
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"LLM status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
