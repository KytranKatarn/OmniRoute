"""
Starship Command — Crew routes.

Real crew data via Bridge dispatcher enrichment.
Replaces fake wellness/stats generation with live dispatcher manifest data.
"""

import json as json
import logging

from flask import jsonify
from flask import request as request
from flask_login import current_user as current_user

from database import get_db_cursor
from database import check_fleet_model_unique as check_fleet_model_unique
from .fleet_helpers import _get_node_for_user_by_int_id as _get_node_for_user_by_int_id

# Legacy station colors for backward-compatible rendering (bridge_stations deprecated)
_LEGACY_STATION_COLORS = {
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

logger = logging.getLogger(__name__)


def register_crew_routes(bp, auth_decorator):
    """Register crew-related routes on the starship blueprint."""

    @bp.route("/api/nodes/<int:node_id>/crew-manifest")
    @auth_decorator
    def fleet_api_node_crew_manifest(node_id):
        """Return node agents in Bridge manifest-compatible format for rich card rendering."""
        # Try to get real dispatcher manifest for enrichment
        manifest_lookup = {}
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            hub_manifest = dispatcher.get_crew_manifest()
            manifest_lookup = {m["name"]: m for m in hub_manifest}
        except Exception:
            logger.debug("Could not fetch dispatcher manifest for crew enrichment")

        with get_db_cursor() as (conn, cur):
            # Get all node agents
            cur.execute(
                """
                SELECT na.id as agent_id, na.name,
                       COALESCE(a.display_name, na.display_name) as full_name,
                       COALESCE(na.title, a.title) as title,
                       COALESCE(na.model, a.model) as model,
                       COALESCE(na.status, a.status) as status,
                       na.station_codes, na.is_allowed as allowed,
                       a.shift_state
                FROM node_agents na
                LEFT JOIN agents a ON a.id = na.hub_agent_id
                WHERE na.node_id = %s
                ORDER BY na.name
                """,
                (node_id,),
            )
            agents = cur.fetchall()

            # Get node's Ollama models for LLM readiness check
            cur.execute(
                "SELECT node_id FROM remote_nodes WHERE id = %s",
                (node_id,),
            )
            node_row = cur.fetchone()
            if not node_row:
                return jsonify({"success": False, "error": "Node not found"}), 404

            # Get available models on this node
            cur.execute(
                """
                SELECT model_name, is_available
                FROM node_ollama_models
                WHERE node_id = %s
                """,
                (node_row["node_id"],),
            )
            models = cur.fetchall()
            available_models = {m["model_name"].split(":")[0].lower() for m in models if m["is_available"]}
            available_exact = {m["model_name"] for m in models if m["is_available"]}

            # Station colors — from Python map (bridge_stations deprecated)
            station_colors = _LEGACY_STATION_COLORS

            manifest = []
            for a in agents:
                agent_model = a["model"] or ""
                agent_base = agent_model.split(":")[0].lower()

                # Determine LLM readiness from node models
                if agent_model in available_exact or agent_base in available_models:
                    local_llm_status = "loaded"
                else:
                    local_llm_status = "barracked"

                codes = a["station_codes"] or []
                colors = [station_colors.get(c, "#00e5ff") for c in codes]

                # Enrich with real dispatcher data when available
                hub_data = manifest_lookup.get(a["name"], {})
                wellness = hub_data.get("wellness", {"stress": 0, "energy": 1.0, "mood": "ready"})
                stats_24h = hub_data.get("stats_24h", {"dispatches": 0, "success_rate": 0})
                current_job = hub_data.get("current_job")
                llm_status = hub_data.get("llm_status", local_llm_status)

                manifest.append(
                    {
                        "agent_id": a["agent_id"],
                        "hub_agent_id": hub_data.get("id") or hub_data.get("agent_id"),
                        "name": a["name"],
                        "display_name": a["full_name"] or a["name"],
                        "full_name": a["full_name"] or a["name"],
                        "title": a["title"] or "",
                        "model": agent_model,
                        "status": "active" if a["status"] == "active" else "idle",
                        "shift_state": a.get("shift_state") or hub_data.get("shift_state", "active"),
                        "llm_status": llm_status,
                        "llm_size_gb": hub_data.get("llm_size_gb", 0),
                        "hardware": hub_data.get("hardware", "CPU"),
                        "station": codes[0] if codes else "UNASSIGNED",
                        "station_codes": codes,
                        "station_colors": colors,
                        "allowed": bool(a["allowed"]) if a["allowed"] is not None else True,
                        "wellness": wellness,
                        "stats_24h": stats_24h,
                        "current_job": current_job,
                    }
                )

            return jsonify({"success": True, "crew": manifest})

    @bp.route("/api/nodes/<int:node_id>/agents/<int:agent_id>/profile")
    @auth_decorator
    def fleet_api_node_agent_profile(node_id, agent_id):
        """Get full agent profile — proxies to hub agent via hub_agent_id."""
        try:
            with get_db_cursor() as (conn, cur):
                # Get hub_agent_id from node_agents
                cur.execute(
                    "SELECT hub_agent_id FROM node_agents WHERE id = %s AND node_id = %s",
                    (agent_id, node_id),
                )
                na = cur.fetchone()
                if not na or not na["hub_agent_id"]:
                    return (
                        jsonify({"success": False, "error": "Agent not linked to hub"}),
                        404,
                    )
                hub_id = na["hub_agent_id"]

                # Agent details (same query pattern as Bridge)
                cur.execute(
                    """
                    SELECT a.id, a.name, a.first_name, a.last_name, a.title,
                           a.department, a.bio, a.model, a.status, a.avatar_url,
                           a.pronouns, a.worker_type, a.cost_tier, a.capabilities,
                           a.created_at, a.last_used,
                           a.department as station_code,
                           a.department as station_name,
                           NULL as station_color
                    FROM agents a
                    WHERE a.id = %s
                    """,
                    (hub_id,),
                )
                agent = cur.fetchone()
                if not agent:
                    return (
                        jsonify({"success": False, "error": "Hub agent not found"}),
                        404,
                    )
                for k in ["created_at", "last_used"]:
                    if agent.get(k):
                        agent[k] = agent[k].isoformat()

                # Skills
                cur.execute(
                    """
                    SELECT skill_name, skill_category, proficiency_level, notes
                    FROM agent_skills WHERE agent_id = %s
                    ORDER BY proficiency_level DESC, skill_name
                    """,
                    (hub_id,),
                )
                skills = cur.fetchall()

                # Emotional state (latest)
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, stress_level, energy_level,
                           trigger_event, timestamp
                    FROM agent_emotional_state WHERE agent_id = %s
                    ORDER BY timestamp DESC LIMIT 1
                    """,
                    (hub_id,),
                )
                emotional = cur.fetchone()
                if emotional and emotional.get("timestamp"):
                    emotional["timestamp"] = emotional["timestamp"].isoformat()

                # Performance (24h)
                cur.execute(
                    """
                    SELECT COUNT(*) as tasks_24h,
                           COUNT(*) FILTER (WHERE success = TRUE) as completed,
                           COUNT(*) FILTER (WHERE success = FALSE) as failed,
                           COALESCE(AVG(duration_ms), 0) as avg_duration_ms
                    FROM task_execution_log
                    WHERE agent_id = %s AND created_at >= NOW() - INTERVAL '24 hours'
                    """,
                    (hub_id,),
                )
                perf = cur.fetchone()

                # Identity traits
                cur.execute(
                    """
                    SELECT identity_key, identity_value, confidence
                    FROM agent_identity WHERE agent_id = %s ORDER BY identity_key
                    """,
                    (hub_id,),
                )
                identity = cur.fetchall()

                # Voice profile
                cur.execute(
                    """
                    SELECT profile_name, engine, language, speaker
                    FROM agent_voice_profiles
                    WHERE agent_id = %s AND is_active = true LIMIT 1
                    """,
                    (hub_id,),
                )
                voice = cur.fetchone()

                # Emotional history (last 10)
                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, energy_level, stress_level,
                           trigger_event, timestamp
                    FROM agent_emotional_state
                    WHERE agent_id = %s ORDER BY timestamp DESC LIMIT 10
                    """,
                    (hub_id,),
                )
                emotional_history = cur.fetchall()
                for eh in emotional_history:
                    if eh.get("timestamp"):
                        eh["timestamp"] = eh["timestamp"].isoformat()

                # Rest cycles (last 5)
                cur.execute(
                    """
                    SELECT rest_type, started_at, ended_at, reason,
                           stress_at_start, energy_at_start
                    FROM agent_rest_cycles WHERE agent_id = %s
                    ORDER BY started_at DESC LIMIT 5
                    """,
                    (hub_id,),
                )
                rest_cycles = cur.fetchall()
                for rc in rest_cycles:
                    for k in ["started_at", "ended_at"]:
                        if rc.get(k):
                            rc[k] = rc[k].isoformat()

                # Memory highlights (top 5)
                cur.execute(
                    """
                    SELECT memory_type, content, importance_score, source_module, created_at
                    FROM agent_memory
                    WHERE agent_id = %s AND is_deleted = FALSE
                    ORDER BY importance_score DESC NULLS LAST LIMIT 5
                    """,
                    (hub_id,),
                )
                memories = cur.fetchall()
                for m in memories:
                    if m.get("created_at"):
                        m["created_at"] = m["created_at"].isoformat()

                return jsonify(
                    {
                        "success": True,
                        "agent": dict(agent),
                        "skills": [dict(s) for s in skills],
                        "emotional_state": dict(emotional) if emotional else None,
                        "emotional_history": [dict(eh) for eh in emotional_history],
                        "identity": [dict(i) for i in identity],
                        "voice": dict(voice) if voice else None,
                        "rest_cycles": [dict(rc) for rc in rest_cycles],
                        "performance_24h": {
                            "tasks": perf["tasks_24h"],
                            "completed": perf["completed"],
                            "failed": perf["failed"],
                            "avg_duration_ms": round(float(perf["avg_duration_ms"]), 1),
                        },
                        "memories": [dict(m) for m in memories],
                    }
                )
        except Exception:
            logger.exception("Failed to get agent profile")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<int:node_id>/agent-form-context")
    @auth_decorator
    def api_node_agent_form_context(node_id):
        """Return models + catalog for agent edit form."""
        try:
            with get_db_cursor() as (conn, cur):
                # Models installed on this node
                cur.execute(
                    "SELECT model_name FROM node_ollama_models WHERE node_id = %s",
                    (node_id,),
                )
                installed = [r["model_name"] for r in cur.fetchall()]

                # Full catalog
                cur.execute(
                    "SELECT model_name, display_name, description, tier, category, size_gb, parameter_size "
                    "FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
                )
                catalog = [dict(r) for r in cur.fetchall()]

                return jsonify(
                    {
                        "success": True,
                        "installed_models": installed,
                        "catalog": catalog,
                    }
                )
        except Exception:
            logger.exception("Failed to get agent form context for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    from .fleet_crew_action_routes import register_crew_action_routes

    register_crew_action_routes(bp, auth_decorator)

    @bp.route("/api/nodes/<int:node_id>/stations")
    @auth_decorator
    def api_node_stations(node_id):
        """Return node stations formatted for StationOps — uses node_agents, NOT hub assignments."""
        try:
            with get_db_cursor() as (conn, cur):
                # Get node agents grouped by station
                cur.execute(
                    """SELECT na.name, na.display_name, na.model, na.status,
                              na.station_codes, na.first_name, na.last_name,
                              a.shift_state, a.title
                       FROM node_agents na
                       LEFT JOIN agents a ON a.id = na.hub_agent_id
                       WHERE na.node_id = %s AND na.status = 'active'
                       ORDER BY na.name""",
                    (node_id,),
                )
                agents = cur.fetchall()

                # Station metadata — from Python map (bridge_stations deprecated)
                all_stations = {
                    code: {"code": code, "name": code.title(), "color": color, "max_primary": 10, "max_auxiliary": 5}
                    for code, color in _LEGACY_STATION_COLORS.items()
                }

                # Build station list with only this node's stations
                station_map = {}
                for ag in agents:
                    codes = ag["station_codes"] or []
                    for code in codes:
                        if code not in station_map:
                            st = all_stations.get(
                                code,
                                {"code": code, "name": code, "color": "#00e5ff", "max_primary": 2, "max_auxiliary": 1},
                            )
                            station_map[code] = {
                                "id": st.get("id", 0),
                                "code": code,
                                "name": st.get("name", code),
                                "color": st.get("color", "#00e5ff"),
                                "max_primary": st.get("max_primary", 2),
                                "max_auxiliary": st.get("max_auxiliary", 1),
                                "assigned_agents": [],
                            }
                        station_map[code]["assigned_agents"].append(
                            {
                                "name": ag["name"],
                                "first_name": (
                                    ag.get("first_name") or (ag["display_name"] or "").split()[0]
                                    if ag.get("display_name")
                                    else ag["name"]
                                ),
                                "last_name": ag.get("last_name") or "",
                                "title": ag.get("title") or "",
                                "status": ag["status"],
                                "shift_state": "active",  # Node agents are always active ON the node
                                "assignment_type": "primary",
                                "model": ag["model"],
                            }
                        )

                stations = sorted(station_map.values(), key=lambda s: s["code"])
                return jsonify({"success": True, "stations": stations})
        except Exception:
            logger.exception("Failed to get node stations for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500
