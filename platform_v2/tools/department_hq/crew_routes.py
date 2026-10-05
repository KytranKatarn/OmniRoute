"""Department HQ — Crew manifest & agent personality routes.

Migrated from Starbase Command crew_routes.py (2026-04-08).
Provides hub-level crew roster with workload, wellness, shift states,
and agent personality data for CLI identity building.

ENDPOINTS:
  /api/crew/manifest              — full crew manifest with capacity + workload
  /api/crew/agent-personality/<id> — personality, mood, relationship data
"""

import logging
from flask import jsonify
from flask_login import login_required
from database import get_db_cursor
import requests

from services.agent_service import list_agents

logger = logging.getLogger(__name__)


def register_crew_routes(bp, admin_required):
    """Register crew manifest routes on the department_hq blueprint."""

    @bp.route("/api/crew/manifest")
    @login_required
    def get_crew_manifest():
        """Get the live crew manifest — all agents with status, wellness, jobs, stats."""
        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            manifest = dispatcher.get_crew_manifest()

            # Hardware capacity (cached — nvidia-smi + psutil + Ollama model breakdown)
            capacity = None
            try:
                from .fleet_helpers import _get_cached_hw_capacity

                capacity = _get_cached_hw_capacity()
            except Exception as cap_err:
                logger.debug(f"Could not get capacity info: {cap_err}")

            # Merge workload data (daily caps, token usage, risk levels)
            workload_map = {}
            try:
                with get_db_cursor(commit=False) as (wconn, wcur):
                    wcur.execute(
                        """
                        SELECT a.id,
                            COALESCE(ab.task_queue_limit, 50) as daily_cap,
                            COALESCE(ab.token_limit_per_day, 500000) as token_cap,
                            COUNT(tel.id) as tasks_24h,
                            COALESCE(SUM(tel.tokens_used), 0) as tokens_used_24h
                        FROM agents a
                        LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
                        LEFT JOIN task_execution_log tel ON tel.agent_id = a.id
                            AND tel.created_at >= NOW() - INTERVAL '24 hours'
                        WHERE a.status = 'active'
                        GROUP BY a.id, ab.task_queue_limit, ab.token_limit_per_day
                    """
                    )
                    for r in wcur.fetchall():
                        daily_cap = int(r["daily_cap"]) or 50
                        token_cap = int(r["token_cap"]) or 500000
                        tasks = int(r["tasks_24h"])
                        tokens = int(r["tokens_used_24h"])
                        wl_pct = min(round(tasks / daily_cap * 100, 1), 100) if daily_cap > 0 else 0
                        tk_pct = min(round(tokens / token_cap * 100, 1), 100) if token_cap > 0 else 0
                        risk = (
                            "overloaded"
                            if wl_pct >= 100
                            else "critical" if wl_pct >= 80 else "elevated" if wl_pct >= 60 else "healthy"
                        )
                        workload_map[r["id"]] = {
                            "daily_cap": daily_cap,
                            "token_cap": token_cap,
                            "tasks_24h": tasks,
                            "tokens_used_24h": tokens,
                            "workload_pct": wl_pct,
                            "token_usage_pct": tk_pct,
                            "risk_level": risk,
                        }
            except Exception as e:
                logger.warning(f"[crew] Failed to compute agent workload metrics: {e}")

            # Attach workload to each crew member
            for member in manifest:
                wl = workload_map.get(member.get("agent_id") or member.get("id"), {})
                member["workload"] = wl

            # Add shift_state to each manifest entry (from agent_service)
            try:
                all_agents = list_agents(limit=500)
                shift_states = {a["id"]: a.get("shift_state") or "active" for a in all_agents}
                for entry in manifest:
                    entry["shift_state"] = shift_states.get(entry.get("agent_id") or entry.get("id"), "active")
            except Exception as e:
                logger.warning(f"[crew] Failed to fetch agent shift states: {e}")

            # Fleet overview counts
            shift_counts = {
                "active": 0,
                "deployed": 0,
                "barracked": 0,
                "winding_down": 0,
                "cooldown": 0,
                "off_duty": 0,
                "reserves": 0,
            }
            for entry in manifest:
                if entry.get("name", "").startswith("fleet:"):
                    continue
                state = entry.get("shift_state", "active")
                if state in shift_counts:
                    shift_counts[state] += 1
            shift_counts["reserves"] = shift_counts["barracked"]

            # Get fleet mode (workday/weekend)
            fleet_mode = "workday"
            try:
                with get_db_cursor(commit=False) as (_fconn, _fcur):
                    _fcur.execute("SELECT value FROM system_config WHERE key = 'fleet_mode'")
                    _frow = _fcur.fetchone()
                    if _frow:
                        fleet_mode = _frow["value"]
            except Exception as e:
                logger.warning(f"[crew] Failed to read fleet mode from system_config: {e}")

            # Node fleet capacity (GPU/RAM for each online node)
            node_capacities = []
            try:
                with get_db_cursor(commit=False) as (nconn, ncur):
                    ncur.execute(
                        """SELECT rn.id, rn.node_id, rn.node_name, rn.hostname, rn.mesh_ip, rn.vpn_ip, rn.port,
                                  rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb, rn.cpu_cores,
                                  (SELECT COUNT(*) FROM node_agents na WHERE na.node_id = rn.id AND na.status = 'active') as agent_count
                           FROM remote_nodes rn
                           WHERE rn.is_active = true AND rn.deployment_mode != 'starbase'
                             AND (rn.last_heartbeat > NOW() - INTERVAL '2 minutes')"""
                    )
                    from tools.department_hq.fleet_helpers import node_inter_cluster_host

                    for node in ncur.fetchall():
                        node_url = f"http://{node_inter_cluster_host(node)}:{node['port']}"
                        vram_total = float(node["gpu_vram_gb"]) if node["gpu_vram_gb"] else 0
                        ram_total = float(node["ram_gb"]) if node["ram_gb"] else 0

                        node_cap = {
                            "node_id": node["node_id"],
                            "node_name": node["node_name"],
                            "gpu_model": node["gpu_model"],
                            "gpu_vram_gb": vram_total,
                            "gpu_vram_used_gb": 0,
                            "gpu_vram_free_gb": vram_total,
                            "ram_gb": ram_total,
                            "ram_used_gb": 0,
                            "ram_free_gb": ram_total,
                            "ram_agent_budget_gb": round(ram_total * 0.80, 1),
                            "ram_swap_buffer_gb": round(ram_total * 0.05, 1),
                            "ram_reserve_gb": round(ram_total * 0.15, 1),
                            "ram_security_gb": 0,
                            "models_ram_gb": 0,
                            "cpu_cores": node["cpu_cores"] or 0,
                            "agent_count": node["agent_count"],
                            "models_installed": [],
                            "models_loaded": [],
                            "models_loaded_count": 0,
                            "models_installed_count": 0,
                        }

                        # Fetch installed models (/api/tags)
                        try:
                            tags_resp = requests.get(f"{node_url}/api/tags", timeout=3)
                            if tags_resp.status_code == 200:
                                for m in tags_resp.json().get("models", []):
                                    node_cap["models_installed"].append(
                                        {
                                            "name": m["name"],
                                            "size_gb": round(m.get("size", 0) / 1e9, 1),
                                        }
                                    )
                                node_cap["models_installed_count"] = len(node_cap["models_installed"])
                        except Exception as e:
                            logger.warning("Failed to fetch node installed models: %s", e)

                        # Fetch loaded models (/api/ps) — live VRAM/RAM usage
                        try:
                            ps_resp = requests.get(f"{node_url}/api/ps", timeout=3)
                            if ps_resp.status_code == 200:
                                vram_used = 0
                                ram_used = 0
                                for m in ps_resp.json().get("models", []):
                                    size_vram = m.get("size_vram", 0)
                                    size_total = m.get("size", 0)
                                    size_ram = size_total - size_vram
                                    vram_used += size_vram
                                    ram_used += size_ram
                                    node_cap["models_loaded"].append(
                                        {
                                            "name": m["name"],
                                            "size_gb": round(size_total / 1e9, 1),
                                            "vram_gb": round(size_vram / 1e9, 1),
                                            "ram_gb": round(size_ram / 1e9, 1),
                                        }
                                    )
                                node_cap["gpu_vram_used_gb"] = round(vram_used / 1e9, 1)
                                node_cap["gpu_vram_free_gb"] = round(max(0, vram_total - vram_used / 1e9), 1)
                                node_cap["ram_used_gb"] = round(ram_used / 1e9, 1)
                                node_cap["ram_free_gb"] = round(max(0, ram_total - ram_used / 1e9), 1)
                                node_cap["models_ram_gb"] = round((vram_used + ram_used) / 1e9, 1)
                                node_cap["models_loaded_count"] = len(node_cap["models_loaded"])
                        except Exception as e:
                            logger.warning("Failed to fetch node loaded models: %s", e)

                        node_capacities.append(node_cap)
            except Exception as nc_err:
                logger.debug(f"Node capacity fetch failed: {nc_err}")

            resp = {
                "success": True,
                "crew": manifest,
                "total": len(manifest),
                "fleet_mode": fleet_mode,
                "fleet_overview": shift_counts,
                "node_capacities": node_capacities,
            }
            if capacity:
                resp["capacity"] = capacity
            return jsonify(resp)
        except Exception as e:
            logger.error(f"Error getting crew manifest: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/crew/agent-personality/<int:agent_id>")
    @login_required
    def get_agent_personality(agent_id):
        """Return personality, mood, and relationship data for an agent.
        Used by ARCHIE Code CLI to build dynamic system prompts."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Core agent info
                cur.execute(
                    """SELECT id, name, display_name, title, department, bio,
                              pronouns, communication_style, personality_prompt
                       FROM agents WHERE id = %s""",
                    (agent_id,),
                )
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"error": "Agent not found"}), 404

                # Latest emotional state
                cur.execute(
                    """SELECT current_mood, mood_intensity, stress_level, energy_level
                       FROM agent_emotional_state
                       WHERE agent_id = %s
                       ORDER BY timestamp DESC LIMIT 1""",
                    (agent_id,),
                )
                emotional = cur.fetchone()

                # Personality traits (archie_personality key-value pairs)
                personality_traits = {}
                cur.execute("SELECT trait_name, trait_value FROM archie_personality")
                for row in cur.fetchall():
                    personality_traits[row["trait_name"]] = row["trait_value"]

                # Build response matching CLI PersonalityBuilder expected shape
                mood_data = {
                    "current": "neutral",
                    "intensity": 0.5,
                }
                if emotional:
                    mood_data["current"] = emotional["current_mood"] or "neutral"
                    mood_data["intensity"] = float(emotional["mood_intensity"] or 0.5)

                # No relationship_strength table — derive from stress_level
                relationship_data = {
                    "strength": 0.99,
                    "user_stress": float(emotional["stress_level"] or 0.0) if emotional else 0.0,
                }

                return jsonify(
                    {
                        "agent_id": agent["id"],
                        "name": agent["name"],
                        "display_name": agent["display_name"],
                        "pronouns": agent["pronouns"],
                        "title": agent["title"],
                        "department": agent["department"],
                        "communication_style": agent["communication_style"],
                        "personality_traits": personality_traits,
                        "mood": mood_data,
                        "relationship": relationship_data,
                    }
                )

        except Exception as e:
            logger.error("Error fetching agent personality: %s", e)
            return jsonify({"error": str(e)}), 500
