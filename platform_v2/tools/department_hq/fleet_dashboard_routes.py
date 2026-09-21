"""
A.R.C.H.I.E. FLEET COMMAND Routes
===================================
Central command center for all AI/LLM operations + fleet node management.
Merged from starbase/routes.py and starship/routes.py during Fleet migration.

Author: A.R.C.H.I.E. Platform
Date: 2026-04-08
"""

import os
import time
import logging
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from database import get_db_cursor
from services.fleet_resource_router import is_stale, utilization_pct

from .fleet_helpers import (
    OLLAMA_LOCAL_HOST,
    OLLAMA_DEFAULT_PORT,
    _get_cached_ollama_tags,
    _get_cached_ollama_ps,
    check_ollama_status,
    get_ollama_models,
    _get_user_nodes,
    _compute_node_health,
    _compute_node_status,
    normalize_node_label,
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

                # Get active agents count — use shift_state (canonical live state),
                # not the legacy `status` column which over-counts (75 vs 56).
                cur.execute(
                    """
                    SELECT COUNT(*) as active_agents
                    FROM agents
                    WHERE shift_state = 'active'
                """
                )
                agent_stats = cur.fetchone()

                # Recent token usage (last 24h) — was reading the DEAD token_usage_log
                # table (frozen 2026-05-13, always ~0). task_execution_log is the live
                # per-dispatch ledger with real Ollama eval counts (prompt+completion).
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(tokens_used), 0) as total_tokens,
                        COUNT(*) as total_requests
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """
                )
                token_stats = cur.fetchone()

                # In-flight work right now — for a meaningful system_load proxy.
                # (Using the 24h request count would peg load to ~100%.)
                cur.execute(
                    """
                    SELECT COUNT(*) AS inflight
                    FROM bridge_jobs
                    WHERE status NOT IN
                        ('completed','failed','error','expired','cancelled','timeout')
                """
                )
                inflight_stats = cur.fetchone()

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

                # System load from IN-FLIGHT work ratio (capped 0-100). active_requests
                # = jobs running/queued now, not the 24h total (which pegged load ~100%).
                active_requests = inflight_stats["inflight"] if inflight_stats else 0
                system_load = min(int(active_requests / max(1, active_requests + 10) * 100), 100)

                return jsonify(
                    {
                        "success": True,
                        "stats": {
                            "llm_status": {"online": llm_online, "total": llm_total},
                            "active_requests": active_requests,
                            "system_load": system_load,
                            "active_agents": (agent_stats["active_agents"] if agent_stats else 0),
                            "tokens_24h": (token_stats["total_tokens"] if token_stats else 0),
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
                        "captain": {
                            "name": "Kytran",
                            "role": "Admin",
                            "status": "On Duty",
                        },
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
                            "fail_rate": (round(100 * failed / total, 2) if total else 0.0),
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
        """Models active across hub + fleet nodes.

        Hub: live from cached Ollama tags (existing behaviour).
        Fleet nodes: recent models from task_execution_log (last 2h) per node —
        no direct Ollama calls needed, uses existing logged data.
        """
        # Hub models — existing cached path
        hub_models, hub_count = _get_cached_ollama_tags()
        hub_detail = [{"name": m["name"], "node": "Hub", "loaded": True} for m in hub_models]
        all_models = list(hub_detail)
        by_node: dict = {"Hub": hub_detail}

        # Fleet nodes — recent model usage from task_execution_log
        try:
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute(
                    """
                    SELECT rn.node_name,
                           tel.model_used,
                           MAX(tel.created_at) AS last_used
                    FROM task_execution_log tel
                    JOIN remote_nodes rn ON rn.id = tel.node_used_id
                    WHERE tel.created_at > NOW() - INTERVAL '2 hours'
                      AND tel.model_used IS NOT NULL
                      AND tel.node_used_id IS NOT NULL
                    GROUP BY rn.node_name, tel.model_used
                    ORDER BY rn.node_name, last_used DESC
                    """
                )
                for r in cur.fetchall() or []:
                    node = normalize_node_label(r["node_name"])
                    entry = {
                        "name": r["model_used"],
                        "node": node,
                        "loaded": True,
                        "last_used": (r["last_used"].isoformat() if r["last_used"] else None),
                    }
                    all_models.append(entry)
                    by_node.setdefault(node, []).append(entry)
        except Exception:
            pass  # Fallback gracefully to hub-only

        return jsonify(
            {
                "success": True,
                "count": len(all_models),
                "models": [m["name"] for m in all_models],  # backward compat flat list
                "models_detail": all_models,  # node-attributed list
                "by_node": by_node,  # grouped by node
            }
        )

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
                # Cast Decimal→float so jsonify can serialize psycopg2 numeric values
                stress_vals = [float(r["stress_level"]) for r in welfare_rows if r["stress_level"] is not None]
                energy_vals = [float(r["energy_level"]) for r in welfare_rows if r["energy_level"] is not None]
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
                            "timestamp": (r["timestamp"].isoformat() if r["timestamp"] else None),
                            "event_category": r["event_category"] or "governance",
                            "label": label,
                            "agent_name": r["agent_first_name"] or r["agent_name"],
                            "severity": ("warning" if r["event_category"] == "autonomy" else "info"),
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
                            "timestamp": (r["created_at"].isoformat() if r["created_at"] else None),
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
                            "timestamp": (r["created_at"].isoformat() if r["created_at"] else None),
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
                                "timestamp": (r["timestamp"].isoformat() if r["timestamp"] else None),
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
                                "timestamp": (r["created_at"].isoformat() if r["created_at"] else None),
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
                                "timestamp": (r["created_at"].isoformat() if r["created_at"] else None),
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
                        # #5218 — status alone conflates two different questions.
                        # 'health' distinguishes a node that heartbeats over the LAN
                        # but is unreachable on the MESH (dispatch cannot land) from a
                        # genuinely healthy one, and reports ingress nodes by
                        # reachability instead of a heartbeat they never send.
                        "health": _compute_node_health(n),
                        "node_role": n.get("node_role") or "agent",
                        "mesh_status": n.get("mesh_status"),
                        "mesh_latency_ms": n.get("mesh_latency_ms"),
                        "reachable_port": n.get("reachable_port"),
                        "is_active": n["is_active"],
                        "bridge_enabled": n["bridge_enabled"],
                        "bridge_priority": n["bridge_priority"],
                        "approval_status": n["approval_status"],
                        "gpu_model": n["gpu_model"],
                        "gpu_vram_gb": (float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else None),
                        "cpu_model": n["cpu_model"],
                        "cpu_cores": n["cpu_cores"],
                        "ram_gb": float(n["ram_gb"]) if n["ram_gb"] else None,
                        "disk_gb": float(n["disk_gb"]) if n["disk_gb"] else None,
                        "last_heartbeat": (n["last_heartbeat"].isoformat() if n["last_heartbeat"] else None),
                        "privacy_settings": n["privacy_settings"],
                    }
                )
            return jsonify({"success": True, "nodes": result})
        except Exception:
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
        except Exception:
            logger.exception("Failed to get fleet agents")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/starbase-stats")
    @auth_decorator
    def api_starbase_stats():
        """Hero Starbase stats -- real data from dispatcher + DB."""
        try:
            from tools.department_hq.services.department_dispatcher import (
                get_dispatcher,
            )

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

                # Read the STATUS COLUMN — do not re-derive liveness here (#5218).
                #
                # This used to count a node online only if last_heartbeat was within
                # 30 SECONDS. Nodes beat every ~45-60s, so at any given sample most of
                # them fell outside the window and the figure oscillated (measured live:
                # 4 -> 6 -> 4 -> 6 of 9). It also disagreed with the platform's own
                # staleness rule, which is 2 MINUTES (services/fleet_jobs.py).
                #
                # Worse, it judged EVERY node by heartbeat. An ingress node (Beacon) runs
                # no node agent by design, so it can never send one and was permanently
                # uncounted — the exact category error #5218 fixed. That fix landed in
                # remote_nodes.status; this endpoint bypassed it by rolling its own signal.
                #
                # check_fleet_health() owns status for agent nodes (heartbeat) and
                # check_mesh_health() owns it for ingress nodes (TCP reachability), so
                # the column already encodes the right signal PER ROLE. Five other call
                # sites in this package read status='online' — this is now the sixth.
                cur.execute(
                    """SELECT COUNT(*) as cnt FROM remote_nodes
                       WHERE is_active = true AND status = 'online'"""
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
                    SELECT a.department,
                           COUNT(*) as agent_count,
                           COUNT(*) FILTER (WHERE a.shift_state = 'active') as active_count,
                           COALESCE(AVG(es.stress_level), 0) as avg_stress,
                           COALESCE(AVG(es.energy_level), 0.5) as avg_energy,
                           COALESCE(SUM(a.total_tokens_used), 0) as total_tokens,
                           COALESCE(AVG(a.total_tokens_used), 0) as avg_tokens_per_agent
                    FROM agents a
                    LEFT JOIN LATERAL (
                        SELECT stress_level, energy_level
                        FROM agent_emotional_state
                        WHERE agent_id = a.id
                        ORDER BY timestamp DESC
                        LIMIT 1
                    ) es ON true
                    GROUP BY a.department
                    ORDER BY SUM(a.total_tokens_used) DESC NULLS LAST
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
                    SELECT a.id, a.name, a.display_name, a.department,
                           a.total_tokens_used,
                           COALESCE(es.stress_level, 0) as stress_level,
                           COALESCE(es.energy_level, 0.5) as energy_level
                    FROM agents a
                    LEFT JOIN LATERAL (
                        SELECT stress_level, energy_level
                        FROM agent_emotional_state
                        WHERE agent_id = a.id
                        ORDER BY timestamp DESC
                        LIMIT 1
                    ) es ON true
                    WHERE a.shift_state = 'active'
                    ORDER BY COALESCE(es.stress_level, 0) DESC,
                             COALESCE(es.energy_level, 0.5) ASC
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

    def _loadability_findings():
        """#6688 — nodes that can no longer LOAD a model, for the Cluster panel.

        Imported lazily and wrapped: this is a WARNING surface, and a warning
        that can 500 the panel it warns on is worse than no warning. Any failure
        degrades to [] and the panel renders exactly as it did before.
        """
        try:
            from services.model_loadability_monitor import findings_for_display

            return findings_for_display()
        except Exception as exc:  # noqa: BLE001
            logger.debug("queue-status: loadability unavailable: %s", exc)
            return []

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
                           MIN(queued_at) AS oldest,
                           MODE() WITHIN GROUP (ORDER BY module_id) AS top_module
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
                        "module": r["top_module"] or "",
                    }
                    for r in cur.fetchall()
                ]
                # #5699 item 3: split warmup (kin_warmth infrastructure pings) out of
                # the headline totals so real stuck work stays visible. `totals` keeps
                # its historical meaning (everything); `totals_real` excludes warmup.
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS cnt,
                           COUNT(*) FILTER (WHERE capability = 'warmup') AS warmup_cnt
                    FROM dispatch_pending_queue
                    WHERE status IN ('queued', 'running')
                    GROUP BY status
                    """
                )
                _total_rows = cur.fetchall()
                totals = {r["status"]: r["cnt"] for r in _total_rows}
                totals_real = {r["status"]: r["cnt"] - r["warmup_cnt"] for r in _total_rows}

                # Unified platform queue — aggregates all module queues into one feed
                platform_queues = [
                    {
                        "source": "Dispatch",
                        "source_key": "dispatch",
                        "capability": it["capability"],
                        "status": it["status"],
                        "count": it["count"],
                        "oldest": it["oldest"],
                        "model": it.get("model"),
                        "module": it.get("module"),
                    }
                    for it in items
                ]
                for _src, _key, _sql in [
                    (
                        "Media Studio",
                        "media",
                        """SELECT COALESCE(params->>'media_type','image') AS cap,
                                  status, COUNT(*) AS cnt, MIN(queued_at) AS oldest
                           FROM media_generation_queue
                           WHERE status IN ('pending','dispatched','generating')
                           GROUP BY 1, 2 ORDER BY cnt DESC""",
                    ),
                    (
                        "Bridge",
                        "bridge",
                        """SELECT COALESCE(action_type,'workflow') AS cap,
                                  status, COUNT(*) AS cnt, MIN(created_at) AS oldest
                           FROM bridge_jobs WHERE status = 'running'
                           GROUP BY 1, 2 ORDER BY cnt DESC LIMIT 10""",
                    ),
                    (
                        "F.O.R.G.E.",
                        "forge",
                        """SELECT 'code_review' AS cap, review_status AS status,
                                  COUNT(*) AS cnt, MIN(created_at) AS oldest
                           FROM pr_reviews
                           WHERE review_status IN ('pending','in_progress')
                           GROUP BY 2""",
                    ),
                ]:
                    try:
                        cur.execute(_sql)
                        for r in cur.fetchall() or []:
                            platform_queues.append(
                                {
                                    "source": _src,
                                    "source_key": _key,
                                    "capability": r["cap"],
                                    "status": r["status"],
                                    "count": int(r["cnt"]),
                                    "oldest": (r["oldest"].isoformat() if r.get("oldest") else None),
                                }
                            )
                    except Exception:
                        pass

            # --- fleet node model state from DB (job #46 saves every 5m) ---
            fleet_loaded = []
            remote_rows = []
            try:
                with get_db_cursor(commit=False) as (_, cur2):
                    cur2.execute(
                        """
                        -- LOADED MODELS asserts CURRENT state, so it must be
                        -- constrained on both liveness and freshness.
                        --
                        -- Measured 2026-09-11: this panel was rendering
                        -- model_load_state rows for Outpost-Singapore, -Lithuania
                        -- and -UK, all saved 2026-08-29 — the day those VPSs were
                        -- RETIRED and cancelled. Thirteen-day-old rows from machines
                        -- that no longer exist, shown as currently-loaded models.
                        -- "14 loaded" was really 11. NODE HEALTH, on the same page,
                        -- filters correctly and showed 5 — the table was never the
                        -- problem, each panel deciding for itself was.
                        --
                        -- Both clauses earn their place: status catches a retired
                        -- node, and saved_at catches a LIVE node whose state saver
                        -- (job #46, every 5m) has stopped — which status alone
                        -- would render as fresh forever.
                        SELECT mls.model_name, mls.size_gb, mls.tier, rn.node_name,
                               rn.gpu_available, rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb
                        FROM model_load_state mls
                        JOIN remote_nodes rn ON rn.id = mls.node_db_id
                        WHERE mls.host_type = 'node'
                          AND rn.status = 'online'
                          AND mls.saved_at > NOW() - INTERVAL '30 minutes'
                        ORDER BY rn.node_name, mls.model_name
                        """
                    )
                    for row in cur2.fetchall():
                        n = row["node_name"] or ""
                        short = normalize_node_label(n).replace("Starship-", ".").strip() or n
                        # `model_load_state.tier` IS the GPU/CPU answer, and always
                        # was: _save_model_state (department_dispatcher ~L11657) reads
                        # `size_vram` off /api/ps and stores 'gpu' or 'cpu' in it on
                        # every job-#46 cycle. The column is NOT NULL.
                        #
                        # This panel simply never SELECTed it, so it showed a GB figure
                        # and let the reader infer residency -- which rendered every
                        # remote model as GPU-resident, including on Citadel and
                        # Outpost-US, which have no GPU at all. An earlier fix in this
                        # same session reported "unknown" instead, on the false premise
                        # that the table could not answer. It could; nobody asked it.
                        #
                        # `tier` is a SIDE, not a split: it says gpu-or-cpu, not what
                        # fraction of layers were offloaded. So gpu_pct stays None for
                        # remote rows -- the hub rows, which read /api/ps directly, are
                        # the only ones that can honestly report a percentage.
                        _tier = (row["tier"] or "").strip().lower()
                        # Keep the raw row for the per-node view built below. The
                        # flat `loaded` list stays byte-identical in shape for any
                        # existing consumer; `nodes` is purely additive.
                        remote_rows.append(
                            {
                                "node": n,
                                "label": short,
                                "name": row["model_name"],
                                "gb": float(row["size_gb"] or 0),
                                "tier": _tier,
                                "gpu_available": bool(row["gpu_available"]),
                                "gpu_model": row["gpu_model"],
                                "gpu_vram_gb": (float(row["gpu_vram_gb"]) if row["gpu_vram_gb"] else None),
                                "ram_gb": float(row["ram_gb"]) if row["ram_gb"] else None,
                            }
                        )
                        if _tier in ("gpu", "cpu"):
                            _proc = _tier
                        else:
                            # Unexpected value -- do not invent one (ADR-017).
                            _proc = "cpu" if not row["gpu_available"] else "unknown"
                        fleet_loaded.append(
                            {
                                "name": row["model_name"],
                                "size_gb": float(row["size_gb"] or 0),
                                "vram_gb": None,
                                "processor": _proc,
                                "gpu_pct": None,
                                "node": short,
                            }
                        )
            except Exception:
                pass

            loaded = []
            hub_raw = []
            try:
                resp = _ureq.urlopen("http://192.168.1.200:11434/api/ps", timeout=3)
                for m in _json.loads(resp.read()).get("models", []):
                    _tot = m.get("size", 0) or 0
                    _vr = m.get("size_vram", 0) or 0
                    # Bytes, not rounded GB: the card attribution below matches a
                    # model against a process's VRAM allocation, and rounding to
                    # 0.1GB throws away the precision that makes two similarly
                    # sized models distinguishable at all.
                    hub_raw.append({"name": m["name"], "size": _tot, "size_vram": _vr})
                    # Same arithmetic `ollama ps` uses for its PROCESSOR column.
                    if _vr <= 0:
                        _proc, _pct = "cpu", 0
                    elif _vr >= _tot:
                        _proc, _pct = "gpu", 100
                    else:
                        _proc, _pct = "split", int(round(_vr / _tot * 100)) if _tot else 0
                    loaded.append(
                        {
                            "name": m["name"],
                            "size_gb": round(_tot / 1e9, 1),
                            "vram_gb": round(_vr / 1e9, 1),
                            "processor": _proc,
                            "gpu_pct": _pct,
                            "node": "Hub",
                        }
                    )
            except Exception:
                pass

            loaded.extend(fleet_loaded)

            # Per-GPU capacity for the utilisation bar. _get_hw_capacity is
            # TTL-cached, so this is cheap, and it now enumerates EVERY card
            # (it previously read only GPU 0 -- see fleet_helpers).
            gpu_hw = None
            try:
                from .fleet_helpers import _get_cached_hw_capacity

                gpu_hw = (_get_cached_hw_capacity() or {}).get("gpu")
            except Exception as _ge:
                logger.debug("queue-status: gpu capacity unavailable: %s", _ge)

            # UNITS: everything in this view is BINARY GB (GiB). nvidia-smi
            # reports MiB and /proc/meminfo KiB, so cards and RAM were already
            # binary, while Ollama's byte figures were being divided by 1e9 --
            # decimal. That made a model look BIGGER than its card's own usage
            # (observed: Quadro "6.7 GB used" carrying a model labelled 7.2 GB,
            # both describing the same 6852 MiB). One unit, or the arithmetic on
            # screen does not add up.
            # ---- PER-NODE VIEW -------------------------------------------------
            # Additive. `loaded` above keeps its exact shape for existing readers;
            # this groups the same facts by node, then by CARD within a node, so
            # "which card is carrying which model" and "how much RAM is actually
            # committed" are answerable without arithmetic in the reader's head.
            #
            # Two different CONFIDENCE levels are reported and must never be
            # rendered identically:
            #   measured  -- nvidia-smi on this host: real used VRAM per card, and
            #                model->card attribution where it is provably unique.
            #   declared  -- a remote node publishes capacity only (gpu_vram_gb,
            #                ram_gb) via heartbeat, so per-card USE is the resident
            #                models' FOOTPRINT, not an observation.
            nodes = []
            try:
                from .services.gpu_residency import (
                    attribute,
                    attribute_named,
                    gpu_process_snapshot,
                    pid_name_map,
                )

                # --- hub ---
                hub_cards = []
                gpus = (gpu_hw or {}).get("gpus") or []
                # PREFER the host exporter: it reads /proc and Ollama's manifests,
                # so it NAMES each process exactly instead of inferring from VRAM
                # sizes (which cannot separate two 7Bs reporting identical
                # size_vram). Byte-matching stays as the fallback for a host with
                # no exporter, and `gpu_attribution` reports which one answered so
                # a silent downgrade is visible rather than invisible.
                # LIVE numbers, exporter-supplied NAMES. nvidia-smi is read now
                # (so every byte figure is current); the exporter contributes only
                # pid -> model, which the container cannot compute at all because
                # it has its own PID namespace.
                #
                # An earlier attempt took the CARD figures from the exporter too,
                # for "one consistent snapshot". That was wrong: its 60s cron
                # meant a 46s-old snapshot reported both cards EMPTY while
                # nvidia-smi showed 4906 MiB live, because models cycle on
                # KEEP_ALIVE expiry. A pid, by contrast, is a stable identity for
                # the life of its process -- a 60s-old NAME for a still-running
                # pid is correct, and an exited pid is simply absent from the live
                # list. So names may age; numbers may not.
                _live_procs = gpu_process_snapshot()
                _names = None
                try:
                    from services.model_service import read_gpu_state

                    _names = pid_name_map(read_gpu_state())
                except Exception as _ae:
                    logger.debug("queue-status: exporter name map unavailable: %s", _ae)
                attribution = attribute_named(_live_procs, _names, hub_raw)
                if attribution is None:
                    attribution = attribute(hub_raw, _live_procs)

                claimed = set()
                for g in gpus:
                    mine = attribution["by_uuid"].get(g.get("uuid")) or []
                    for mm in mine:
                        claimed.add(mm["name"])
                    anon = attribution.get("anon_by_uuid", {}).get(g.get("uuid")) or []
                    hub_cards.append(
                        {
                            "index": g.get("index"),
                            "name": g.get("name"),
                            "vram_total_gb": g.get("vram_total_gb"),
                            "vram_used_gb": g.get("vram_used_gb"),
                            "usage_pct": g.get("usage_pct"),
                            "measured": True,
                            "models": [{"name": mm["name"], "gb": round(mm["bytes"] / 1024**3, 1)} for mm in mine],
                            # Measured bytes whose MODEL could not be named. A card
                            # carrying one of these is emphatically not idle, and
                            # saying so is the difference between "unknown which"
                            # and the false "nothing here".
                            # `candidates` is populated where the exporter
                            # narrowed a SHARED weights blob to a few tags but
                            # not one: "one of these two" beats both a blank and
                            # a coin-flip pick.
                            "unnamed": [
                                {
                                    "gb": round(a["bytes"] / 1024**3, 1),
                                    "candidates": list(a.get("candidates") or []),
                                }
                                for a in anon
                            ],
                        }
                    )
                hub_gpu_unplaced = [
                    {"name": m["name"], "gb": round(m["size_vram"] / 1024**3, 1)}
                    for m in hub_raw
                    if (m["size_vram"] or 0) > 0 and m["name"] not in claimed
                ]
                hub_cpu = [
                    {
                        "name": m["name"],
                        # The CPU-resident PORTION, not the whole model: a split
                        # model holds only its un-offloaded remainder in RAM.
                        "gb": round(max(m["size"] - m["size_vram"], 0) / 1024**3, 1),
                    }
                    for m in hub_raw
                    if (m["size"] - m["size_vram"]) > 0
                ]
                ram_total = ram_used = None
                try:
                    _mi = {}
                    with open("/proc/meminfo", "r") as fh:
                        for _ln in fh:
                            _k, _v = _ln.split(":", 1)
                            _mi[_k] = int(_v.split()[0])
                    # The container's /proc/meminfo is the HOST's (verified on the
                    # hub: 131825476 kB == 125.7 GiB), so this is real system RAM,
                    # not a cgroup figure.
                    ram_total = round(_mi["MemTotal"] / 1048576, 1)
                    ram_used = round((_mi["MemTotal"] - _mi["MemAvailable"]) / 1048576, 1)
                except Exception:
                    pass
                nodes.append(
                    {
                        "key": "Hub",
                        "label": "Starbase - A.R.C.H.I.E.",
                        "is_hub": True,
                        "cards": hub_cards,
                        "gpu_unplaced": hub_gpu_unplaced,
                        # 'exact'       — named from Ollama's own manifests via the
                        #                 host exporter; no inference involved.
                        # 'inferred'    — byte-matched, refusing where ambiguous.
                        # 'unavailable' — nvidia-smi said nothing.
                        # Reported so a downgrade to guessing is VISIBLE.
                        "gpu_attribution": (
                            "exact"
                            if attribution.get("source") == "exporter"
                            else "inferred" if attribution["available"] else "unavailable"
                        ),
                        # Age of the snapshot the exact figures came from. The
                        # exporter runs on a 60s cron, so a reader must be able to
                        # tell "2s ago" from "4 minutes ago" rather than assume
                        # live. None on the inferred path, which IS live.
                        # How many live GPU processes carry an exact name. The
                        # figures are always live; only the NAME lookup can lag,
                        # and this says how much of the picture it covered.
                        "gpu_named_procs": sum(len(v) for v in attribution["by_uuid"].values()),
                        "cpu_models": hub_cpu,
                        "ram_total_gb": ram_total,
                        "ram_used_gb": ram_used,
                        "ram_models_gb": round(sum(c["gb"] for c in hub_cpu), 1),
                        "ram_measured": ram_used is not None,
                    }
                )

                # --- fleet nodes ---
                seen = []
                for r in remote_rows:
                    if r["node"] not in seen:
                        seen.append(r["node"])
                for nm in seen:
                    rows = [r for r in remote_rows if r["node"] == nm]
                    first = rows[0]
                    gpu_models = [{"name": r["name"], "gb": r["gb"]} for r in rows if r["tier"] == "gpu"]
                    cpu_models = [{"name": r["name"], "gb": r["gb"]} for r in rows if r["tier"] != "gpu"]
                    cards = []
                    if first["gpu_available"] and first["gpu_vram_gb"]:
                        footprint = round(sum(m["gb"] for m in gpu_models), 1)
                        total = first["gpu_vram_gb"]
                        # A footprint LARGER than the card is not a 112%-full card;
                        # it means the model did not fully fit and Ollama offloaded
                        # part of it to CPU. Measured live on USS-245: mistral:7b
                        # (4.5 GB) against a 4 GB RTX 3050 rendered "4.5 / 4 GB",
                        # which is nonsense on its face. `tier` says gpu-or-cpu, not
                        # what FRACTION was offloaded, so the honest ceiling is the
                        # card itself, with the overflow reported separately.
                        overflow = round(max(footprint - total, 0), 1) if total else 0
                        used = min(footprint, total) if total else footprint
                        cards.append(
                            {
                                "index": 0,
                                "name": first["gpu_model"] or "GPU",
                                "vram_total_gb": total,
                                "vram_used_gb": used,
                                "footprint_gb": footprint,
                                "overflow_gb": overflow,
                                "usage_pct": (round(used / total * 100, 1) if total else 0),
                                # Footprint, not an observation -- and a single-GPU
                                # node needs no matcher: there is only one card a
                                # GPU-resident model can be on.
                                "measured": False,
                                "models": gpu_models,
                                # A remote node publishes no per-process data, so
                                # there is nothing unnamed to report -- the key is
                                # present so the renderer needs no special case.
                                "unnamed": [],
                            }
                        )
                    nodes.append(
                        {
                            "key": nm,
                            "label": first["label"],
                            "is_hub": False,
                            "cards": cards,
                            # With one card, nothing is ever unplaced; if a node
                            # somehow reports GPU models with no card, they surface
                            # here rather than vanishing.
                            "gpu_unplaced": [] if cards else gpu_models,
                            "gpu_attribution": "declared" if cards else "none",
                            "cpu_models": cpu_models,
                            "ram_total_gb": first["ram_gb"],
                            "ram_used_gb": None,
                            "ram_models_gb": round(sum(m["gb"] for m in cpu_models), 1),
                            "ram_measured": False,
                        }
                    )
            except Exception as _ne:
                logger.debug("queue-status: per-node view unavailable: %s", _ne)
                nodes = []

            # #5321: hardware-rest schedule visibility on the cluster view —
            # advisory strip data; a snapshot error must never break the panel.
            rest = None
            try:
                from .fleet_helpers import rest_status_snapshot

                rest = rest_status_snapshot()
            except Exception:
                pass

            return jsonify(
                success=True,
                queued=totals.get("queued", 0),
                running=totals.get("running", 0),
                # Warmup-excluded counts (#5699 item 3) — real work only, so warmup
                # noise cannot mask a genuinely stuck queue. Additive; the legacy
                # `queued`/`running` keys keep their all-rows meaning.
                queued_real=totals_real.get("queued", 0),
                running_real=totals_real.get("running", 0),
                items=items,
                loaded=loaded,
                gpu_hw=gpu_hw,
                nodes=nodes,
                # #6688 — the counterweight to `loaded`.
                #
                # On 2026-09-11 this panel showed 4 healthy resident models on the
                # hub for two days while NOTHING new could load — Repair Bay's
                # code-gen sat at 0 successes and every view here read green,
                # because "what is loaded" and "what can load" are different
                # questions and only the first was ever asked.
                #
                # Display-only accessor: never alerts (a page refresh must not
                # send Telegram) and is TTL-cached, so polling costs nothing.
                # Fail-safe [] — a panel must never break on its own warning.
                loadability=_loadability_findings(),
                platform_queues=platform_queues,
                rest=rest,
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

    @bp.route("/api/fleet/dispatch-mode", methods=["GET", "POST"])
    @auth_decorator
    def api_fleet_dispatch_mode():
        """Get or set fleet dispatch profile (auto / news / platform).

        #6080 AUX POWER: under 'platform', an optional ``focus`` (a module
        family from fleet_dispatch_profile.MODULE_FAMILIES) promotes that
        family's queued work to the front of every drain claim pool. The focus
        lives in its OWN system_config key (fleet_dispatch_focus) so the trio
        contract of fleet_dispatch_mode — which the dispatcher's node-ordering
        block reads raw — is untouched. Selecting a non-platform mode clears
        the focus so a stale boost cannot survive a mode change invisibly.
        """
        VALID_MODES = ("auto", "news", "platform")
        from services.fleet_dispatch_profile import MODULE_FAMILIES

        def _set_config(key, value):
            with get_db_cursor(commit=True) as (_, cur):
                cur.execute(
                    """INSERT INTO system_config (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE
                         SET value=EXCLUDED.value, updated_at=NOW()""",
                    (key, value),
                )

        def _get_config(key, default=""):
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute("SELECT value FROM system_config WHERE key=%s", (key,))
                row = cur.fetchone()
                return (row["value"] if row else default).lower()

        try:
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                mode = str(data.get("mode", "auto")).lower()
                if mode not in VALID_MODES:
                    return (
                        jsonify({"success": False, "error": f"Invalid mode '{mode}'"}),
                        400,
                    )
                focus = str(data.get("focus", "") or "").lower()
                if focus and focus not in MODULE_FAMILIES:
                    return (
                        jsonify({"success": False, "error": f"Invalid focus '{focus}'"}),
                        400,
                    )
                if mode != "platform":
                    focus = ""  # focus is a PLATFORM sub-selector only
                _set_config("fleet_dispatch_mode", mode)
                _set_config("fleet_dispatch_focus", focus)
                return jsonify(
                    {
                        "success": True,
                        "mode": mode,
                        "focus": focus,
                        "available_focus": sorted(MODULE_FAMILIES.keys()),
                    }
                )
            else:
                mode = _get_config("fleet_dispatch_mode", "auto")
                focus = _get_config("fleet_dispatch_focus", "")
                if focus not in MODULE_FAMILIES:
                    focus = ""
                return jsonify(
                    {
                        "success": True,
                        "mode": mode,
                        "focus": focus if mode == "platform" else "",
                        "available_focus": sorted(MODULE_FAMILIES.keys()),
                    }
                )
        except Exception as exc:
            logger.error("api_fleet_dispatch_mode: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fleet/rest-mode", methods=["GET", "POST"])
    @auth_decorator
    def api_fleet_rest_mode():
        """Get or set fleet hardware rest schedule (suppresses starship dispatch 8PM–6AM)."""
        from .fleet_helpers import (
            get_fleet_rest_config,
            set_fleet_rest_config,
            is_fleet_rest_active,
            is_starships_undocked,
            force_undock_until,
            rest_status_snapshot,
        )

        try:
            if request.method == "GET":
                cfg = get_fleet_rest_config()
                _force_until = force_undock_until()
                return jsonify(
                    success=True,
                    enabled=cfg.get("enabled", False),
                    start_hour=cfg.get("start_hour", 20),
                    end_hour=cfg.get("end_hour", 6),
                    active_now=is_fleet_rest_active(),
                    # #5332: the COMBINED truth every gate consults (schedule OR force)
                    undocked=is_starships_undocked(),
                    force_undock_until=_force_until.isoformat() if _force_until else None,
                    # #5321c: the real window, so no UI ever hardcodes '8PM–6AM' again
                    rest_window=f"{int(cfg.get('start_hour', 20)):02d}:00–{int(cfg.get('end_hour', 6)):02d}:00 ET",
                    # #5816: the A.R.M.A.D.A. Cluster panel needs in_window /
                    # now_et / next_transition too. Serve the SAME snapshot the
                    # FLEET DOCK strip uses rather than letting a second surface
                    # recompute the window — that divergence is exactly what
                    # #5321 was filed for.
                    status=rest_status_snapshot(cfg=cfg),
                )
            data = request.get_json(silent=True) or {}
            enabled = bool(data.get("enabled", False))
            start_hour = int(data.get("start_hour", 20))
            end_hour = int(data.get("end_hour", 6))
            set_fleet_rest_config(enabled=enabled, start_hour=start_hour, end_hour=end_hour)
            return jsonify(
                success=True,
                enabled=enabled,
                active_now=is_fleet_rest_active(),
                undocked=is_starships_undocked(),
                rest_window=f"{start_hour:02d}:00–{end_hour:02d}:00 ET",
                # Re-READ from system_config rather than echoing the request
                # body: the caller must be able to tell a persisted change from
                # an accepted-but-lost one (ADR-014 — gate on the artifact).
                status=rest_status_snapshot(),
            )
        except Exception as exc:
            logger.error("api_fleet_rest_mode: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fleet/force-undock", methods=["POST"])
    @auth_decorator
    def api_fleet_force_undock():
        """#5332: manually detach the Starships NOW (or redock early).

        Body {"action": "undock"} arms a force-undock that AUTO-EXPIRES at the
        next rest-window end boundary (<24h) — a manual force can never
        permanently strand a ship. {"action": "clear"} redocks early. Every
        gate (dispatch pins, ComfyUI, keep-warms, model-control, queued-pin
        claims) reads the combined is_starships_undocked() predicate.
        """
        from .fleet_helpers import set_force_undock, clear_force_undock, force_undock_until, is_starships_undocked

        try:
            action = (request.get_json(silent=True) or {}).get("action", "undock")
            if action == "clear":
                clear_force_undock()
            elif action == "undock":
                set_force_undock()
            else:
                return jsonify({"success": False, "error": "action must be 'undock' or 'clear'"}), 400
            _until = force_undock_until()
            return jsonify(
                success=True,
                action=action,
                undocked=is_starships_undocked(),
                force_undock_until=_until.isoformat() if _until else None,
            )
        except Exception as exc:
            logger.error("api_fleet_force_undock: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fleet/cluster-activity")
    @auth_decorator
    def api_fleet_cluster_activity():
        """Live cluster activity — tasks per node + recent dispatch log.

        Cached ~8s (the CLUSTER subtab polls every 10s) so the heavy per-node
        aggregations run at most once per window instead of on every poll —
        keeps the render snappy and cuts DB load ~10x. Per-worker in-process
        cache; staleness is bounded by the TTL and acceptable for live activity.
        """

        # TTL slightly above the 10s client poll so overlapping requests (multi-tab,
        # multiple viewers, a manual refresh landing on a busy worker) reuse the result.
        # Single-viewer speed comes mainly from the bounded queries below, not this cache.
        _TTL_S = 15.0
        _cache = api_fleet_cluster_activity.__dict__.setdefault("_cache", {"ts": 0.0, "payload": None})
        if _cache["payload"] is not None and (time.monotonic() - _cache["ts"]) < _TTL_S:
            return jsonify(_cache["payload"])
        try:
            with get_db_cursor(commit=False) as (_, cur):
                # Resolve the hub (starbase) node ID so we can merge null-routed tasks
                cur.execute(
                    "SELECT id, node_id, node_name FROM remote_nodes " "WHERE deployment_mode = 'starbase' LIMIT 1"
                )
                hub_row = cur.fetchone()
                hub_db_id = hub_row["id"] if hub_row else None
                hub_node_id = hub_row["node_id"] if hub_row else "hub"
                hub_node_name = hub_row["node_name"] if hub_row else "Hub"

                # Queue backlog per node (CPU pre-queue — separate from warm-path dispatch)
                # NULL preferred_node_id = unrouted tasks, attributed to the hub node
                cur.execute(
                    """
                    SELECT
                        COALESCE(rn.node_name, %s)  AS node_name,
                        COALESCE(rn.node_id, %s)    AS node_id,
                        COUNT(*) FILTER (WHERE dpq.status = 'queued')  AS backlog,
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
                    GROUP BY rn.node_name, rn.node_id
                    ORDER BY running DESC, backlog DESC
                    """,
                    (hub_node_name, hub_node_id),
                )
                backlog_by_node = {}
                for r in cur.fetchall():
                    backlog_by_node[r["node_id"]] = {
                        "backlog": r["backlog"],
                        "running": r["running"],
                        "tasks": [t for t in (r["tasks"] or []) if t],
                    }

                # Real-time dispatch counts from task_execution_log (5-min window)
                # Resolves fleet-agent-{id} names so node cards show agent names.
                cur.execute(
                    """
                    SELECT
                        COALESCE(rn.node_id, %s)    AS node_id,
                        COUNT(*) FILTER (WHERE tel.created_at > NOW() - INTERVAL '60 seconds')  AS active_60s,
                        COUNT(*) AS dispatches_5m,
                        SUM(CASE WHEN tel.success THEN 1 ELSE 0 END)::float
                            / NULLIF(COUNT(*), 0) AS success_rate,
                        STRING_AGG(DISTINCT COALESCE(a.name, tel.agent_name), ', ') FILTER (
                            WHERE tel.created_at > NOW() - INTERVAL '60 seconds'
                        ) AS active_agents
                    FROM task_execution_log tel
                    LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                    LEFT JOIN agents a ON (
                        tel.agent_name ~ '^fleet-agent-[0-9]+$'
                        AND a.id::text = substring(tel.agent_name FROM 13)
                    )
                    WHERE tel.created_at > NOW() - INTERVAL '5 minutes'
                    GROUP BY 1
                    """,
                    (hub_node_id,),
                )
                activity_by_node = {}
                for r in cur.fetchall():
                    activity_by_node[r["node_id"]] = {
                        "active_60s": int(r["active_60s"] or 0),
                        "dispatches_5m": int(r["dispatches_5m"] or 0),
                        "success_rate": round(float(r["success_rate"] or 0), 3),
                        "active_agents": r["active_agents"] or "",
                    }

                # All online nodes with hardware info + roster agents
                cur.execute(
                    """
                    SELECT rn.id, rn.node_id, rn.node_name, rn.status, rn.mesh_ip,
                           rn.gpu_available, rn.current_load, rn.last_heartbeat,
                           rn.cpu_model, rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb,
                           rn.deployment_mode,
                           json_agg(
                               json_build_object(
                                   'name', a.name, 'display_name', a.display_name,
                                   'shift_state', a.shift_state, 'department', a.department
                               )
                           ) FILTER (WHERE a.id IS NOT NULL) AS roster_agents
                    FROM remote_nodes rn
                    LEFT JOIN node_agents na ON na.node_id = rn.id
                        AND na.status = 'active'
                    LEFT JOIN agents a ON a.id = na.hub_agent_id
                        AND a.worker_type = 'ai' AND a.shift_state != 'decommissioned'
                    WHERE rn.status = 'online'
                      AND (rn.last_heartbeat > NOW() - INTERVAL '3 minutes' OR rn.last_heartbeat IS NULL)
                    GROUP BY rn.id, rn.node_id, rn.node_name, rn.status, rn.mesh_ip,
                             rn.gpu_available, rn.current_load, rn.last_heartbeat,
                             rn.cpu_model, rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb,
                             rn.deployment_mode
                    ORDER BY rn.node_name
                    """
                )
                online_nodes = [dict(r) for r in cur.fetchall()]

                # Recent dispatch log — shows diverse agents, not just WTF.
                # Caps each unique agent at 3 entries so high-volume agents (V.E.R.I.F.Y.,
                # L.O.C.A.L.) don't crowd out platform agents (F.O.R.G.E., S.H.I.E.L.D.).
                # Extends window to 2h so infrequent platform agents are visible.
                cur.execute(
                    """
                    SELECT agent_name, capability, module_source, success, duration_ms, created_at, node_name
                    FROM (
                        SELECT
                            COALESCE(a.name, tel.agent_name) AS agent_name,
                            tel.capability, tel.module_source,
                            tel.success, tel.duration_ms, tel.created_at,
                            COALESCE(rn.node_name, %s) AS node_name,
                            ROW_NUMBER() OVER (
                                PARTITION BY COALESCE(a.name, tel.agent_name)
                                ORDER BY tel.created_at DESC
                            ) AS rn
                        FROM task_execution_log tel
                        LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                        LEFT JOIN agents a ON (
                            tel.agent_name ~ '^fleet-agent-[0-9]+$'
                            AND a.id::text = substring(tel.agent_name FROM 13)
                        )
                        WHERE tel.created_at > NOW() - INTERVAL '2 hours'
                    ) ranked
                    WHERE rn <= 3
                    ORDER BY created_at DESC
                    LIMIT 30
                    """,
                    (hub_node_name,),
                )
                log = []
                for r in cur.fetchall():
                    log.append(
                        {
                            "agent": r["agent_name"],
                            "capability": r["capability"],
                            "source": r["module_source"],
                            "node": r["node_name"],
                            "success": bool(r["success"]),
                            "duration_ms": r["duration_ms"],
                            "ts": (r["created_at"].isoformat() if r["created_at"] else None),
                        }
                    )

                # Cloud dispatch approvals — include pending + executed so they're
                # visible in the dispatch log, not just on Telegram
                cur.execute(
                    """
                    SELECT
                        action_data->>'original_agent'   AS agent_name,
                        action_data->>'capability'       AS capability,
                        action_data->>'escalated_model'  AS model,
                        action_data->>'module_id'        AS module_id,
                        status, reason, created_at
                    FROM autonomy_approval_queue
                    WHERE action_type = 'cloud_throughput_escalation'
                      AND created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 20
                    """
                )
                cloud_log = []
                for r in cur.fetchall():
                    cloud_log.append(
                        {
                            "agent": r["agent_name"] or "?",
                            "capability": r["capability"] or "?",
                            "model": r["model"] or "cloud",
                            "source": r["module_id"] or "cloud_approval",
                            "status": r["status"],
                            "reason": (r["reason"] or "")[:120],
                            "ts": (r["created_at"].isoformat() if r["created_at"] else None),
                        }
                    )

                # Last fleet dispatch per node from bridge_jobs metadata
                cur.execute(
                    """
                    SELECT DISTINCT ON ((metadata->>'node_name'))
                        metadata->>'node_name' AS node_name,
                        agent_name,
                        job_type AS capability,
                        completed_at,
                        created_at
                    FROM bridge_jobs
                    WHERE status IN ('completed', 'failed')
                      AND created_at > NOW() - INTERVAL '24 hours'
                      AND metadata ? 'node_name'
                      AND metadata->>'node_name' != ''
                    ORDER BY (metadata->>'node_name'), completed_at DESC NULLS LAST
                    """
                )
                last_run_by_node = {}
                for r in cur.fetchall():
                    node_name = r["node_name"]
                    ts = r["completed_at"] or r["created_at"]
                    last_run_by_node[node_name] = {
                        "agent": r["agent_name"],
                        "capability": r["capability"],
                        "ts": ts.isoformat() if ts else None,
                    }

                # Per-node throughput from task_execution_log.node_used_id
                # (column shipped in PR #802; rows attributed to fleet warm-path routing)
                cur.execute(
                    """
                    SELECT
                        CASE WHEN rn.node_id IS NULL OR rn.node_id = 'archie-starbase'
                             THEN 'Starbase - A.R.C.H.I.E.' ELSE rn.node_name END AS node_name,
                        COUNT(*) AS rows_5m,
                        COUNT(*) FILTER (WHERE tel.created_at > NOW() - INTERVAL '60 seconds') AS rows_60s,
                        SUM(CASE WHEN tel.success THEN 1 ELSE 0 END)::float
                            / NULLIF(COUNT(*), 0) AS success_rate
                    FROM task_execution_log tel
                    LEFT JOIN remote_nodes rn ON rn.id = tel.node_used_id
                    WHERE tel.created_at > NOW() - INTERVAL '5 minutes'
                    GROUP BY 1
                    """
                )
                throughput_by_node = {}
                total_rows_5m = 0
                total_rows_60s = 0
                for r in cur.fetchall():
                    rows_5m = int(r["rows_5m"] or 0)
                    rows_60s = int(r["rows_60s"] or 0)
                    total_rows_5m += rows_5m
                    total_rows_60s += rows_60s
                    throughput_by_node[r["node_name"]] = {
                        "rows_5m": rows_5m,
                        "rows_60s": rows_60s,
                        "rate_per_min": round(rows_5m / 5.0, 2),
                        "success_rate": round(float(r["success_rate"] or 0.0), 3),
                    }

                throughput_total = {
                    "rows_5m": total_rows_5m,
                    "rows_60s": total_rows_60s,
                    "rate_per_min": round(total_rows_5m / 5.0, 2),
                    "rate_per_sec": round(total_rows_5m / 300.0, 3),
                }

            # Build unified node list: merge backlog + activity + roster
            nodes_out = []
            for n in online_nodes:
                nid = n["node_id"]
                bl = backlog_by_node.get(nid, {"backlog": 0, "running": 0, "tasks": []})
                act = activity_by_node.get(
                    nid,
                    {
                        "active_60s": 0,
                        "dispatches_5m": 0,
                        "success_rate": 0,
                        "active_agents": "",
                    },
                )
                nodes_out.append(
                    {
                        "node_id": nid,
                        "node_name": n["node_name"],
                        "status": n["status"],
                        "mesh_ip": str(n["mesh_ip"] or ""),
                        "gpu": bool(n["gpu_available"]),
                        "has_cpu": True,  # all nodes can run CPU inference
                        "load": n["current_load"] or 0,
                        "last_heartbeat": (n["last_heartbeat"].isoformat() if n["last_heartbeat"] else None),
                        "cpu_model": n["cpu_model"] or "",
                        "gpu_model": n["gpu_model"] or "",
                        "gpu_vram_gb": (float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else 0),
                        "ram_gb": float(n["ram_gb"]) if n["ram_gb"] else 0,
                        "deployment_mode": n["deployment_mode"] or "",
                        # Queue backlog (CPU pre-queue — may accumulate if drain worker is behind)
                        "backlog": bl["backlog"],
                        "running": bl["running"],
                        "tasks": bl["tasks"],
                        # Real-time dispatch activity (task_execution_log — authoritative)
                        "active_60s": act["active_60s"],
                        "dispatches_5m": act["dispatches_5m"],
                        "success_rate": act["success_rate"],
                        "active_agents": act["active_agents"],
                        # Roster agents assigned to this node
                        "roster_agents": n["roster_agents"] or [],
                    }
                )

            from .fleet_helpers import get_fleet_rest_config, is_fleet_rest_active

            rest_cfg = get_fleet_rest_config()
            payload = dict(
                success=True,
                nodes_with_work=nodes_out,  # kept for JS compat
                online_nodes=nodes_out,
                hub_node_id=hub_node_id,
                dispatch_log=log,
                cloud_approvals=cloud_log,
                last_run_by_node=last_run_by_node,
                throughput_by_node=throughput_by_node,
                throughput_total=throughput_total,
                rest_enabled=rest_cfg.get("enabled", False),
                rest_active=is_fleet_rest_active(),
                rest_window=f"{int(rest_cfg.get('start_hour', 20)):02d}:00–{int(rest_cfg.get('end_hour', 6)):02d}:00 ET",
            )
            _cache["payload"] = payload
            _cache["ts"] = time.monotonic()
            return jsonify(payload)
        except Exception as exc:
            logger.error("api_fleet_cluster_activity: %s", exc)
            return jsonify(success=False, error=str(exc)[:200]), 500

    @bp.route("/api/fleet/wtf-status")
    @auth_decorator
    def api_fleet_wtf_status():
        """WTF pipeline agent status — live dispatch stats per News & Media agent.

        Returns per-agent call counts, avg response time, last seen, and node.
        Also returns backlog_pct from wtf.articles ai_analyzed coverage.
        Used by Fleet tab WTF AGENT STATUS panel (Project #350).
        """
        try:
            from database import get_db_cursor
            from datetime import datetime, timezone

            now_utc = datetime.now(timezone.utc)

            with get_db_cursor() as (_, cur):
                # Per-agent dispatch stats from last 2 hours — ALL agents, all modules.
                # Expanded from WTF-only to show full fleet activity (FLEET AGENT STATUS panel).
                # CTE resolves fleet-agent-{id} fallback names via node_agents join.
                cur.execute(
                    """
                    WITH resolved AS (
                        SELECT
                            COALESCE(
                                CASE WHEN t.agent_name ~ '^fleet-agent-[0-9]+$'
                                     THEN COALESCE(na.display_name, a_na.display_name, a_na.name, 'Fleet Agent')
                                     ELSE NULL
                                END,
                                t.agent_name
                            ) AS agent_name,
                            t.duration_ms,
                            t.created_at,
                            t.node_used_id,
                            t.module_source
                        FROM task_execution_log t
                        LEFT JOIN node_agents na ON (
                            na.hub_agent_id = (CASE WHEN t.agent_name ~ '^fleet-agent-[0-9]+$'
                                                    THEN REGEXP_REPLACE(t.agent_name, '^fleet-agent-', '')::int
                                               END)
                        )
                        LEFT JOIN agents a_na ON a_na.id = na.hub_agent_id
                        WHERE t.created_at > NOW() - INTERVAL '2 hours'
                          AND t.agent_name IS NOT NULL
                          AND t.agent_name != ''
                    )
                    SELECT
                        agent_name,
                        COUNT(*) AS calls_1h,
                        ROUND(AVG(duration_ms) / 1000.0, 1) AS avg_sec,
                        MAX(created_at) AS last_seen,
                        (SELECT rn.node_name FROM remote_nodes rn
                         WHERE rn.id = mode() WITHIN GROUP (ORDER BY node_used_id)
                         LIMIT 1) AS node
                    FROM resolved
                    GROUP BY agent_name
                    ORDER BY calls_1h DESC
                    LIMIT 25
                    """
                )
                agent_rows = cur.fetchall() or []

                # WTF articles live in a separate DB on the VPS — not queryable
                # from the hub. Backlog % is shown on what-the-fact.com/activity.
                total = done = 0
                backlog_pct = None

                # Node heartbeat status — flag stale nodes
                cur.execute(
                    """
                    SELECT node_name, last_heartbeat
                    FROM remote_nodes
                    WHERE status = 'online'
                    """
                )
                node_rows = {r["node_name"]: r["last_heartbeat"] for r in (cur.fetchall() or [])}

            agents = []
            for row in agent_rows:
                last_seen = row["last_seen"]
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                ago_sec = int((now_utc - last_seen).total_seconds()) if last_seen else None
                if ago_sec is None:
                    last_seen_label = "never"
                elif ago_sec < 60:
                    last_seen_label = f"{ago_sec}s ago"
                elif ago_sec < 3600:
                    last_seen_label = f"{ago_sec // 60}min ago"
                else:
                    last_seen_label = f"{ago_sec // 3600}h ago"

                node_name = row["node"] or "hub"
                node_hb = node_rows.get(node_name)
                node_stale = False
                if node_hb:
                    if node_hb.tzinfo is None:
                        node_hb = node_hb.replace(tzinfo=timezone.utc)
                    node_stale = (now_utc - node_hb).total_seconds() > 120

                agents.append(
                    {
                        "name": row["agent_name"],
                        "calls_1h": row["calls_1h"],
                        "avg_sec": float(row["avg_sec"] or 0),
                        "last_seen": last_seen_label,
                        "node": node_name,
                        "node_stale": node_stale,
                    }
                )

            return jsonify(
                success=True,
                agents=agents,
                backlog_pct=backlog_pct,
                total_articles=total,
                analyzed_articles=done,
            )
        except Exception as exc:
            logger.error("api_fleet_wtf_status: %s", exc)
            return jsonify(success=False, error=str(exc)[:200]), 500

    @bp.route("/api/fleet/cluster-stats")
    @auth_decorator
    def api_fleet_cluster_stats():
        """Cluster tab enrichment — top capabilities, throughput sparkline, module breakdown, node health.

        Powers four new panels in the Cluster sub-tab:
        - Top capabilities bar (what the fleet is doing)
        - Throughput sparkline (dispatches/min over last 30 min)
        - Module source breakdown (which products drive load)
        - Node health table (per-node RAM/models/rate/heartbeat)
        """
        try:
            from database import get_db_cursor
            from datetime import datetime, timezone

            with get_db_cursor(commit=False) as (_, cur):

                # 1. Top capabilities — last 1h, top 10
                cur.execute(
                    """
                    SELECT capability, COUNT(*) AS cnt,
                           ROUND(AVG(duration_ms)/1000.0, 1) AS avg_sec,
                           SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*),0) AS ok_rate
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                      AND capability IS NOT NULL AND capability != ''
                    GROUP BY capability
                    ORDER BY cnt DESC
                    LIMIT 10
                """
                )
                top_capabilities = [
                    {
                        "cap": r["capability"],
                        "cnt": int(r["cnt"]),
                        "avg_sec": float(r["avg_sec"] or 0),
                        "ok_rate": round(float(r["ok_rate"] or 0), 3),
                    }
                    for r in (cur.fetchall() or [])
                ]
                total_dispatches = sum(c["cnt"] for c in top_capabilities)

                # 2. Throughput sparkline — 2-min buckets, last 30 min
                cur.execute(
                    """
                    SELECT date_trunc('minute', created_at) -
                           MOD(EXTRACT(MINUTE FROM created_at)::int, 2) * INTERVAL '1 minute' AS bucket,
                           COUNT(*) AS cnt
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '30 minutes'
                    GROUP BY bucket
                    ORDER BY bucket
                """
                )
                sparkline = [{"t": r["bucket"].isoformat(), "cnt": int(r["cnt"])} for r in (cur.fetchall() or [])]

                # 3. Module source breakdown — last 1h, top 8 sources
                cur.execute(
                    """
                    SELECT COALESCE(module_source, 'unknown') AS src,
                           COUNT(*) AS cnt
                    FROM task_execution_log
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                    GROUP BY src
                    ORDER BY cnt DESC
                    LIMIT 8
                """
                )
                modules = [{"src": r["src"], "cnt": int(r["cnt"])} for r in (cur.fetchall() or [])]
                module_total = sum(m["cnt"] for m in modules)

                # 4. Node health table — online nodes with model count + dispatch rate
                cur.execute(
                    """
                    SELECT rn.node_name, rn.gpu_available, rn.ram_gb, rn.gpu_vram_gb,
                           rn.current_load, rn.max_concurrent, rn.last_heartbeat,
                           COALESCE(
                               (SELECT COUNT(*) FROM model_load_state mls WHERE mls.node_db_id = rn.id), 0
                           ) AS models_loaded,
                           COALESCE(
                               (SELECT COUNT(*) FROM node_ollama_models nom
                                WHERE nom.node_id = rn.node_id AND nom.is_available = TRUE), 0
                           ) AS models_available,
                           COALESCE(
                               (SELECT COUNT(*) FROM task_execution_log tel
                                WHERE tel.node_used_id = rn.id
                                  AND tel.created_at > NOW() - INTERVAL '5 minutes'), 0
                           ) AS dispatches_5m
                    FROM remote_nodes rn
                    WHERE rn.status = 'online'
                    ORDER BY rn.node_name
                """
                )
                now_utc = datetime.now(timezone.utc)
                node_health = []
                for r in cur.fetchall() or []:
                    hb = r["last_heartbeat"]
                    if hb and hb.tzinfo is None:
                        hb = hb.replace(tzinfo=timezone.utc)
                    hb_age = int((now_utc - hb).total_seconds()) if hb else None
                    node_health.append(
                        {
                            "name": r["node_name"],
                            "gpu": bool(r["gpu_available"]),
                            "ram_gb": float(r["ram_gb"] or 0),
                            "vram_gb": float(r["gpu_vram_gb"] or 0),
                            "load": int(r["current_load"] or 0),
                            "max_conc": int(r["max_concurrent"] or 5),
                            "models": int(r["models_loaded"] or 0),
                            "models_available": int(r["models_available"] or 0),
                            "disp_5m": int(r["dispatches_5m"] or 0),
                            "hb_age_s": hb_age,
                            "stale": hb_age is None or hb_age > 120,
                        }
                    )

            return jsonify(
                success=True,
                top_capabilities=top_capabilities,
                total_dispatches=total_dispatches,
                sparkline=sparkline,
                modules=modules,
                module_total=module_total,
                node_health=node_health,
            )
        except Exception as exc:
            logger.error("api_fleet_cluster_stats: %s", exc)
            return jsonify(success=False, error=str(exc)[:200]), 500
