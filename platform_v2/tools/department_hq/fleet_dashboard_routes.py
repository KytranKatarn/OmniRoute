"""
A.R.C.H.I.E. FLEET COMMAND Routes
===================================
Central command center for all AI/LLM operations + fleet node management.
Merged from starbase/routes.py and starship/routes.py during Fleet migration.

Author: A.R.C.H.I.E. Platform
Date: 2026-04-08
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
from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from rbac import require_permission, Permission
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_cursor, check_fleet_model_unique
from services.fleet_resource_router import is_stale, utilization_pct
import requests

from .fleet_helpers import (
    OLLAMA_LOCAL_URL,
    OLLAMA_LOCAL_HOST,
    OLLAMA_DEFAULT_PORT,
    _get_cached_ollama_tags,
    _get_cached_ollama_ps,
    _get_cached_hw_capacity,
    check_ollama_status,
    get_ollama_models,
    _get_user_nodes,
    _compute_node_status,
    push_agent_event,
)

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

fleet_bp = Blueprint("fleet", __name__, url_prefix="/tools/fleet", template_folder="templates")


# ============================================================================
# MAIN FLEET DASHBOARD PAGE
# ============================================================================


@fleet_bp.route("/")
@login_required
def fleet_dashboard():
    """Redirect to Department HQ Fleet tab — all fleet UI lives there now."""
    from flask import redirect

    return redirect("/tools/department-hq/#fleet", code=302)


# ============================================================================
# ADR-045: register_dashboard_routes - all API endpoints
# ============================================================================


def register_dashboard_routes(bp, auth_decorator):
    """Register all Fleet dashboard API routes (ADR-045 pattern)."""

    # ========================================================================
    # BRIDGE STATS API (from starbase)
    # ========================================================================

    @bp.route("/api/stats")
    @auth_decorator
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
                                float(emotional_state["mood_intensity"])
                                if emotional_state.get("mood_intensity")
                                else 0.85
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # TOKEN USAGE / TRAFFIC API (from starbase)
    # ========================================================================

    @bp.route("/api/traffic")
    @auth_decorator
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent-utilization")
    @auth_decorator
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/node-utilization")
    @auth_decorator
    def get_node_utilization():
        """Per-node capacity + live state for resource-aware routing (#2516, ADR-555).

        Returns one row per active fleet node with load %, fail rate, and a
        stale-heartbeat flag. Used by the dispatch tab and by the
        fleet_capacity_report agent_loop job that recommends upgrades when
        a node sustains high utilisation.
        """
        try:
            nodes = []
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT node_id, node_name, status, last_heartbeat,
                           gpu_available, gpu_model, gpu_vram_gb,
                           cpu_model, cpu_cores, ram_gb,
                           current_load, max_concurrent,
                           total_requests, successful_requests, failed_requests,
                           avg_latency_ms,
                           ollama_available, comfyui_available, foocus_available,
                           extra_capabilities, priority
                      FROM remote_nodes
                     WHERE is_active = TRUE
                  ORDER BY priority DESC, node_name
                    """
                )
                for row in cur.fetchall():
                    node = dict(row)
                    total = node.get("total_requests") or 0
                    failed = node.get("failed_requests") or 0
                    last_hb = node.get("last_heartbeat")
                    nodes.append(
                        {
                            **node,
                            "last_heartbeat": last_hb.isoformat() if last_hb else None,
                            "load_pct": utilization_pct(node),
                            "fail_rate": round(100 * failed / total, 2) if total else 0.0,
                            "stale": is_stale(node),
                        }
                    )

            online = sum(1 for n in nodes if n["status"] == "online" and not n["stale"])
            return jsonify(
                {
                    "success": True,
                    "nodes": nodes,
                    "online_count": online,
                    "total_count": len(nodes),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as e:
            logger.error(f"Error getting node utilization: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/models/live")
    @auth_decorator
    def get_live_models():
        """Get actual model count from live Ollama API"""
        models, count = _get_cached_ollama_tags()
        return jsonify({"success": True, "count": count, "models": [m["name"] for m in models]})

    @bp.route("/api/creed/overview")
    @auth_decorator
    def get_creed_overview():
        """Get real C.R.E.E.D. compliance and welfare metrics"""
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
            logger.error(f"Error getting C.R.E.E.D. overview: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/workload")
    @auth_decorator
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/welfare")
    @auth_decorator
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
                monitored = [
                    a for a in agents if a.get("stress_level") is not None or a.get("energy_level") is not None
                ]
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # C.R.E.E.D. ENFORCEMENT LOG (from starbase)
    # ========================================================================

    @bp.route("/api/creed/enforcement-log")
    @auth_decorator
    def get_creed_enforcement_log():
        """Vigil's Log: governance actions, C.R.E.E.D. welfare checks, and agent health."""
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

                # 2. C.R.E.E.D. welfare scan
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
                            "label": f"A.R.C.H.I.E. mood: {archie_state['current_mood']}",
                            "agent_name": None,
                            "severity": "info",
                        }
                    )

                # 4. Failed dispatches
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
                    if len(err) > 80:
                        err = err[:77] + "..."
                    events.append(
                        {
                            "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                            "event_category": "dispatch",
                            "label": (f"dispatch failed — {detail}: {err}" if detail else f"dispatch failed — {err}"),
                            "agent_name": r["agent_name"],
                            "severity": "warning",
                        }
                    )

                # 5. Escalation events
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
            logger.error("get_creed_enforcement_log error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/creed/enforcement-log-full")
    @auth_decorator
    def get_creed_enforcement_log_full():
        """Vigil's Log -- paginated full view with category filter."""
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
                                "label": f"A.R.C.H.I.E. mood: {archie_state['current_mood']}",
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
                                "label": (
                                    f"dispatch failed — {detail}: {err}" if detail else f"dispatch failed — {err}"
                                ),
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
                                "label": (
                                    f"Escalated from {r['original_model']} to " f"{r['escalated_model']}: {reason}"
                                ),
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
            logger.error("get_creed_enforcement_log_full error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # ARCHIE STATUS API (from starbase)
    # ========================================================================

    @bp.route("/api/archie/status")
    @auth_decorator
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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # LLM CONNECTIONS MONITOR (from starbase)
    # ========================================================================

    @bp.route("/api/llm/status")
    @auth_decorator
    def get_llm_status():
        """Get live LLM status from Ollama + external API key checks"""
        try:
            ollama_host = OLLAMA_LOCAL_HOST
            ollama_port = int(OLLAMA_DEFAULT_PORT)

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
            except Exception as e:
                logger.warning("Failed to fetch assigned models: %s", e)

            # 4. Build model list with status and size
            models = []
            for name, size_bytes in available_models.items():
                # Check assignment: match with or without :latest suffix
                is_assigned = name in assigned_models or name.split(":")[0] in {
                    m.split(":")[0] for m in assigned_models
                }
                models.append(
                    {
                        "name": name,
                        "provider": "ollama",
                        "status": "loaded" if name in loaded_names else "available",
                        "assigned": is_assigned,
                        "size": size_bytes,
                    }
                )

            # 5. Check external AI providers
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
            except Exception as e:
                logger.warning("Failed to fetch routing_mode setting: %s", e)

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
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # FLEET NODE ENDPOINTS (from starship/routes.py)
    # ========================================================================

    @bp.route("/api/nodes")
    @auth_decorator
    def api_list_nodes():
        """List all nodes owned by current user."""
        user_id = current_user.id
        try:
            nodes = _get_user_nodes(user_id)
            result = []
            for n in nodes:
                result.append(
                    {
                        "node_id": n["node_id"],
                        "node_name": n["node_name"],
                        "deployment_mode": n["deployment_mode"],
                        "hostname": n["hostname"],
                        "status": _compute_node_status(n),
                        "is_active": n["is_active"],
                        "bridge_enabled": n["bridge_enabled"],
                        "bridge_priority": n["bridge_priority"],
                        "approval_status": n["approval_status"],
                        "gpu_model": n["gpu_model"],
                        "gpu_vram_gb": float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else None,
                        "cpu_model": n["cpu_model"],
                        "cpu_cores": n["cpu_cores"],
                        "ram_gb": float(n["ram_gb"]) if n["ram_gb"] else None,
                        "disk_gb": float(n["disk_gb"]) if n["disk_gb"] else None,
                        "last_heartbeat": (n["last_heartbeat"].isoformat() if n["last_heartbeat"] else None),
                        "privacy_settings": n["privacy_settings"],
                    }
                )
            return jsonify({"success": True, "nodes": result})
        except Exception as e:
            logger.exception("Failed to list nodes")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/fleet-agents")
    @auth_decorator
    def api_fleet_agents():
        """Public endpoint -- agent counts + live VRAM/RAM per node for docked fleet strip."""
        try:
            import requests as _req

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT rn.id, rn.node_id, rn.hostname, rn.port,
                              rn.gpu_vram_gb, rn.ram_gb, rn.cpu_cores, rn.deployment_mode,
                              rn.last_heartbeat,
                              hb.cpu_usage, hb.memory_usage, hb.details AS hb_details,
                              (SELECT COUNT(*) FROM node_agents na
                               WHERE na.node_id = rn.id AND na.status = 'active') as agent_count
                       FROM remote_nodes rn
                       LEFT JOIN LATERAL (
                           SELECT cpu_usage, memory_usage, details
                           FROM node_heartbeats nh
                           WHERE nh.node_id = rn.id
                           ORDER BY nh.created_at DESC LIMIT 1
                       ) hb ON true
                       WHERE rn.is_active = true AND rn.deployment_mode != 'starbase'"""
                )
                nodes = []
                for r in cur.fetchall():
                    hb_details = r.get("hb_details") or {}
                    uptime_secs = hb_details.get("uptime", 0)
                    services_count = sum(1 for v in hb_details.values() if v is True)
                    node = {
                        "node_id": r["node_id"],
                        "deployment_mode": r["deployment_mode"],
                        "agent_count": r["agent_count"],
                        "vram_total": float(r["gpu_vram_gb"] or 0),
                        "vram_used": 0,
                        "ram_total": float(r["ram_gb"] or 0),
                        "ram_used": 0,
                        "models_loaded": 0,
                        "cpu_usage": round(float(r["cpu_usage"] or 0), 1),
                        "cpu_cores": r["cpu_cores"] or 0,
                        "mem_usage": round(float(r["memory_usage"] or 0), 1),
                        "uptime_secs": uptime_secs,
                        "services_count": services_count,
                    }
                    # Live usage from node Ollama /api/ps (skip for outposts)
                    if r["deployment_mode"] != "outpost":
                        try:
                            ps = _req.get(f"http://{r['hostname']}:{r['port']}/api/ps", timeout=3)
                            if ps.status_code == 200:
                                models = ps.json().get("models", [])
                                node["models_loaded"] = len(models)
                                node["vram_used"] = round(sum(m.get("size_vram", 0) for m in models) / 1e9, 1)
                                node["ram_used"] = round(
                                    sum(m.get("size", 0) - m.get("size_vram", 0) for m in models) / 1e9,
                                    1,
                                )
                        except Exception:
                            pass
                    nodes.append(node)
            return jsonify({"success": True, "nodes": nodes})
        except Exception as e:
            logger.exception("Failed to get fleet agents")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/starbase-stats")
    @auth_decorator
    def api_starbase_stats():
        """Hero Starbase stats -- real data from dispatcher + DB."""
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            manifest = dispatcher.get_crew_manifest()

            hub_agents = [a for a in manifest if not a.get("name", "").startswith("fleet:")]
            active_agents = sum(1 for a in hub_agents if a.get("shift_state") == "active")
            deployed_agents = sum(1 for a in hub_agents if a.get("shift_state") == "deployed")
            barracked_agents = sum(1 for a in hub_agents if a.get("shift_state") == "barracked")
            loaded_models = sum(1 for a in manifest if a.get("llm_status") == "loaded")
            active_jobs = sum(1 for a in manifest if a.get("current_job"))

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT COUNT(*) as cnt FROM remote_nodes WHERE is_active = true")
                node_count = cur.fetchone()["cnt"]

                cur.execute(
                    """SELECT COUNT(*) as cnt FROM remote_nodes
                       WHERE is_active = true
                       AND (last_heartbeat > NOW() - INTERVAL '30 seconds'
                            OR deployment_mode = 'starbase')"""
                )
                online_count = cur.fetchone()["cnt"]

            return jsonify(
                {
                    "success": True,
                    "total_agents": len(hub_agents),
                    "active_agents": active_agents,
                    "deployed_agents": deployed_agents,
                    "barracked_agents": barracked_agents,
                    "loaded_models": loaded_models,
                    "active_jobs": active_jobs,
                    "total_nodes": node_count,
                    "online_nodes": online_count,
                }
            )
        except Exception as e:
            logger.error(f"Starbase stats error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/creed/workload-scores")
    @auth_decorator
    def api_creed_workload_scores():
        """Token-based workload scoring per department for C.R.E.E.D. enforcement."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT department,
                           COUNT(*) as agent_count,
                           COUNT(*) FILTER (WHERE shift_state = 'active') as active_count,
                           COALESCE(AVG(stress_level), 0) as avg_stress,
                           COALESCE(AVG(energy_level), 0.5) as avg_energy,
                           COALESCE(SUM(total_tokens_used), 0) as total_tokens,
                           COALESCE(AVG(total_tokens_used), 0) as avg_tokens_per_agent
                    FROM agents
                    GROUP BY department
                    ORDER BY SUM(total_tokens_used) DESC NULLS LAST
                    """
                )
                departments = []
                for row in cur.fetchall():
                    dept = row["department"]
                    count = row["agent_count"]
                    active = row["active_count"]
                    stress = float(row["avg_stress"])
                    energy = float(row["avg_energy"])
                    total_tok = float(row["total_tokens"])
                    avg_tok = float(row["avg_tokens_per_agent"])

                    stress_score = stress * 40
                    energy_score = (1 - energy) * 30
                    token_score = min(30, avg_tok / 10000 * 30) if avg_tok else 0
                    workload = round(stress_score + energy_score + token_score, 1)

                    if workload > 70:
                        status = "critical"
                    elif workload > 50:
                        status = "warning"
                    elif workload > 30:
                        status = "moderate"
                    else:
                        status = "healthy"

                    departments.append(
                        {
                            "department": dept,
                            "agent_count": count,
                            "active_count": active,
                            "avg_stress": round(stress, 3),
                            "avg_energy": round(energy, 3),
                            "total_tokens": int(total_tok),
                            "avg_tokens_per_agent": int(avg_tok),
                            "workload_score": workload,
                            "status": status,
                        }
                    )

                cur.execute(
                    """
                    SELECT id, name, display_name, department,
                           stress_level, energy_level, total_tokens_used
                    FROM agents
                    WHERE shift_state = 'active'
                    ORDER BY stress_level DESC, energy_level ASC
                    LIMIT 5
                    """
                )
                overworked = []
                for row in cur.fetchall():
                    overworked.append(
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "display_name": row["display_name"],
                            "department": row["department"],
                            "stress": round(float(row["stress_level"] or 0), 3),
                            "energy": round(float(row["energy_level"] or 0.5), 3),
                            "tokens_used": int(row["total_tokens_used"] or 0),
                        }
                    )

            return jsonify(success=True, departments=departments, overworked_agents=overworked)
        except Exception as e:
            logger.error(f"Workload scores error: {e}")
            return jsonify(success=False, error=str(e)[:200]), 500

    @bp.route("/api/fleet/queue-status")
    @auth_decorator
    def api_fleet_queue_status():
        """Dispatch queue depth by model + live loaded models on hub Ollama."""
        import json as _json
        import urllib.request as _ureq

        try:
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute(
                    """
                    SELECT model_needed, capability, status, COUNT(*) AS cnt,
                           MIN(queued_at) AS oldest
                    FROM dispatch_pending_queue
                    WHERE status IN ('queued', 'running')
                    GROUP BY model_needed, capability, status
                    ORDER BY status DESC, cnt DESC
                    """
                )
                items = [
                    {
                        "model": r["model_needed"],
                        "capability": r["capability"],
                        "status": r["status"],
                        "count": r["cnt"],
                        "oldest": r["oldest"].isoformat() if r["oldest"] else None,
                    }
                    for r in cur.fetchall()
                ]
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS cnt
                    FROM dispatch_pending_queue
                    WHERE status IN ('queued', 'running')
                    GROUP BY status
                    """
                )
                totals = {r["status"]: r["cnt"] for r in cur.fetchall()}

            loaded = []
            try:
                resp = _ureq.urlopen("http://192.168.1.200:11434/api/ps", timeout=3)
                for m in _json.loads(resp.read()).get("models", []):
                    loaded.append({"name": m["name"], "vram_gb": round(m.get("size_vram", 0) / 1e9, 1)})
            except Exception:
                pass

            return jsonify(
                success=True,
                queued=totals.get("queued", 0),
                running=totals.get("running", 0),
                items=items,
                loaded=loaded,
            )
        except Exception as exc:
            logger.error("api_fleet_queue_status: %s", exc)
            return jsonify(success=False, error=str(exc)[:200]), 500

    @bp.route("/api/fleet/routing-enabled")
    @auth_decorator
    def api_fleet_routing_enabled():
        """Return current agent mobility toggle state."""
        try:
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute("SELECT value FROM system_config WHERE key='fleet_node_routing_enabled'")
                row = cur.fetchone()
                enabled = (row["value"] if row else "true").lower() != "false"
            return jsonify({"success": True, "enabled": enabled})
        except Exception as exc:
            logger.error("api_fleet_routing_enabled: %s", exc)
            return jsonify({"success": False, "enabled": True})

    @bp.route("/api/fleet/routing-toggle", methods=["POST"])
    @auth_decorator
    def api_fleet_routing_toggle():
        """Toggle agent mobility on/off via system_config."""
        try:
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled", True))
            with get_db_cursor(commit=True) as (_, cur):
                cur.execute(
                    """INSERT INTO system_config (key, value, updated_at)
                       VALUES ('fleet_node_routing_enabled', %s, NOW())
                       ON CONFLICT (key) DO UPDATE
                         SET value=EXCLUDED.value, updated_at=NOW()""",
                    (str(enabled).lower(),),
                )
            return jsonify({"success": True, "enabled": enabled})
        except Exception as exc:
            logger.error("api_fleet_routing_toggle: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fleet/cluster-activity")
    @auth_decorator
    def api_fleet_cluster_activity():
        """Live cluster activity — tasks per node + recent dispatch log."""
        try:
            with get_db_cursor(commit=False) as (_, cur):
                # Per-node active task breakdown
                cur.execute(
                    """
                    SELECT
                        COALESCE(rn.node_name, 'Hub')   AS node_name,
                        COALESCE(rn.node_id, 'hub')     AS node_id,
                        COALESCE(rn.status, 'online')   AS node_status,
                        COALESCE(rn.mesh_ip, '')        AS mesh_ip,
                        rn.gpu_available,
                        COUNT(*) FILTER (WHERE dpq.status = 'queued')  AS queued,
                        COUNT(*) FILTER (WHERE dpq.status = 'running') AS running,
                        json_agg(
                            json_build_object(
                                'id',         dpq.id,
                                'agent',      dpq.agent_name,
                                'capability', dpq.capability,
                                'model',      dpq.model_needed,
                                'status',     dpq.status,
                                'source',     dpq.source_product,
                                'queued_at',  dpq.queued_at
                            ) ORDER BY dpq.queued_at
                        ) AS tasks
                    FROM dispatch_pending_queue dpq
                    LEFT JOIN remote_nodes rn ON rn.id = dpq.preferred_node_id
                    WHERE dpq.status IN ('queued', 'running')
                      AND (dpq.expires_at IS NULL OR dpq.expires_at > NOW())
                    GROUP BY rn.node_name, rn.node_id, rn.status, rn.mesh_ip, rn.gpu_available
                    ORDER BY running DESC, queued DESC
                    """
                )
                nodes_with_work = []
                for r in cur.fetchall():
                    tasks = r["tasks"] or []
                    nodes_with_work.append(
                        {
                            "node_name": r["node_name"],
                            "node_id": r["node_id"],
                            "status": r["node_status"],
                            "mesh_ip": r["mesh_ip"],
                            "gpu": bool(r["gpu_available"]),
                            "queued": r["queued"],
                            "running": r["running"],
                            "tasks": [t for t in tasks if t],
                        }
                    )

                # All online nodes (include idle ones)
                cur.execute(
                    """
                    SELECT node_id, node_name, status, mesh_ip, gpu_available,
                           current_load, last_heartbeat
                    FROM remote_nodes
                    WHERE is_active = TRUE AND status = 'online'
                      AND last_heartbeat > NOW() - INTERVAL '3 minutes'
                    ORDER BY node_name
                    """
                )
                online_nodes = [dict(r) for r in cur.fetchall()]

                # Recent dispatch log from dispatch_pending_queue (has node routing info)
                cur.execute(
                    """
                    SELECT dpq.agent_name, dpq.capability, dpq.source_product,
                           dpq.status, dpq.queued_at, dpq.completed_at,
                           COALESCE(rn.node_name, 'Hub') AS node_name
                    FROM dispatch_pending_queue dpq
                    LEFT JOIN remote_nodes rn ON rn.id = dpq.preferred_node_id
                    WHERE dpq.status IN ('done', 'completed', 'failed')
                      AND COALESCE(dpq.completed_at, dpq.queued_at) > NOW() - INTERVAL '30 minutes'
                    ORDER BY COALESCE(dpq.completed_at, dpq.queued_at) DESC
                    LIMIT 20
                    """
                )
                log = []
                for r in cur.fetchall():
                    log.append(
                        {
                            "agent": r["agent_name"],
                            "capability": r["capability"],
                            "source": r["source_product"],
                            "node": r["node_name"],
                            "success": r["status"] != "failed",
                            "duration_ms": None,
                            "ts": (
                                (r["completed_at"] or r["queued_at"]).isoformat()
                                if (r["completed_at"] or r["queued_at"])
                                else None
                            ),
                        }
                    )

            return jsonify(
                success=True,
                nodes_with_work=nodes_with_work,
                online_nodes=[
                    {
                        "node_id": n["node_id"],
                        "node_name": n["node_name"],
                        "status": n["status"],
                        "mesh_ip": str(n["mesh_ip"] or ""),
                        "gpu": bool(n["gpu_available"]),
                        "load": n["current_load"] or 0,
                        "last_heartbeat": n["last_heartbeat"].isoformat() if n["last_heartbeat"] else None,
                    }
                    for n in online_nodes
                ],
                dispatch_log=log,
            )
        except Exception as exc:
            logger.error("api_fleet_cluster_activity: %s", exc)
            return jsonify(success=False, error=str(exc)[:200]), 500
