"""Starbase Command — Crew routes (manifest, lounge, training, wellness, IAAE)"""

import os
import subprocess
import logging
from typing import List
from flask import jsonify, request
from flask_login import login_required, current_user
from rbac import require_permission, Permission
from database import get_db_cursor
import psutil
import requests

from .helpers import (
    _get_cached_ollama_tags,
    _get_cached_ollama_ps,
    _get_cached_hw_capacity,
    OLLAMA_LOCAL_URL,
)

logger = logging.getLogger(__name__)


def register_crew_routes(bp, admin_required):
    """Register crew-related routes on the bridge blueprint."""

    # ============================================================================
    # LOUNGE (REST AREA) API - Phase 39
    # ============================================================================

    @bp.route("/api/lounge")
    @login_required
    def get_lounge_agents():
        """Get agents currently in lounge (resting)"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT
                        a.id as agent_id,
                        a.name as agent_name,
                        a.display_name,
                        a.avatar_url,
                        a.department,
                        arc.id as rest_cycle_id,
                        arc.rest_type,
                        arc.reason as rest_reason,
                        arc.started_at as rest_started,
                        EXTRACT(EPOCH FROM (NOW() - arc.started_at)) / 3600 as hours_resting,
                        CASE WHEN arc.rest_type = 'forced' THEN TRUE ELSE FALSE END as is_locked,
                        arc.stress_at_start,
                        arc.energy_at_start
                    FROM agent_rest_cycles arc
                    JOIN agents a ON arc.agent_id = a.id
                    WHERE arc.ended_at IS NULL
                    AND a.status = 'active'
                    ORDER BY arc.started_at DESC
                """
                )
                agents = cur.fetchall()

                return jsonify({"success": True, "agents": agents})

        except Exception as e:
            logger.error(f"Error loading lounge agents: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/send-to-lounge", methods=["POST"])
    @login_required
    def send_agent_to_lounge(agent_id):
        """Send an agent to lounge (start rest cycle)"""
        try:
            data = request.get_json() or {}
            rest_type = data.get("rest_type", "voluntary")
            reason = data.get("reason", "Sent to lounge via Bridge")

            with get_db_cursor() as (conn, cur):

                # Remove from station assignment if any
                cur.execute(
                    "UPDATE station_assignments SET is_active = FALSE WHERE agent_id = %s AND is_active = TRUE",
                    (agent_id,),
                )

                # Cancel any active training
                cur.execute(
                    "UPDATE training_assignments SET status = 'cancelled' "
                    "WHERE agent_id = %s AND status IN ('pending', 'in_progress')",
                    (agent_id,),
                )

                # Snapshot emotional state before rest
                cur.execute(
                    "SELECT stress_level, energy_level FROM agent_emotional_state WHERE agent_id = %s",
                    (agent_id,),
                )
                emo = cur.fetchone()
                stress_start = float(emo["stress_level"]) if emo else None
                energy_start = float(emo["energy_level"]) if emo else None

                # Start rest cycle
                cur.execute(
                    """
                    INSERT INTO agent_rest_cycles
                        (agent_id, rest_type, reason, started_at, stress_at_start, energy_at_start)
                    VALUES (%s, %s, %s, NOW(), %s, %s)
                    RETURNING id
                """,
                    (agent_id, rest_type, reason, stress_start, energy_start),
                )

                rest_cycle_id = cur.fetchone()["id"]

                # Unload agent's LLM to free RAM during rest
                cur.execute("SELECT model FROM agents WHERE id = %s", (agent_id,))
                agent_row = cur.fetchone()
                model_name = agent_row["model"] if agent_row else None
                unloaded = False
                if model_name and not model_name.endswith(":cloud"):
                    # Check no other active agent uses this model
                    cur.execute(
                        """SELECT COUNT(*) AS cnt FROM agents a
                           LEFT JOIN agent_rest_cycles arc ON arc.agent_id = a.id AND arc.ended_at IS NULL
                           WHERE a.model = %s AND a.id != %s AND a.status = 'active' AND arc.id IS NULL""",
                        (model_name, agent_id),
                    )
                    if cur.fetchone()["cnt"] == 0:
                        try:
                            from ai_bridge.bridge_dispatcher import get_dispatcher

                            result = get_dispatcher().unload_model(model_name)
                            unloaded = result.get("success", False)
                            if unloaded:
                                logger.info(f"[Lounge] Unloaded {model_name} for agent {agent_id} rest")
                            else:
                                logger.warning(f"[Lounge] Failed to unload {model_name}: {result.get('message')}")
                        except Exception as ue:
                            logger.warning(f"[Lounge] Failed to unload {model_name}: {ue}")

                return jsonify(
                    {
                        "success": True,
                        "rest_cycle_id": rest_cycle_id,
                        "model_unloaded": unloaded,
                        "message": f"Agent sent to lounge{' — LLM unloaded' if unloaded else ''}",
                    }
                )

        except Exception as e:
            logger.error(f"Error sending agent to lounge: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agents/<int:agent_id>/return-from-lounge", methods=["POST"])
    @login_required
    def return_agent_from_lounge(agent_id):
        """Return an agent from lounge (end rest cycle)"""
        try:
            with get_db_cursor() as (conn, cur):

                # Check if agent is in forced rest
                cur.execute(
                    """
                    SELECT id, rest_type FROM agent_rest_cycles
                    WHERE agent_id = %s AND ended_at IS NULL
                """,
                    (agent_id,),
                )
                rest_cycle = cur.fetchone()

                if not rest_cycle:
                    return jsonify({"success": False, "error": "Agent is not in lounge"}), 400

                if rest_cycle["rest_type"] == "forced":
                    return (
                        jsonify({"success": False, "error": "Cannot return agent from forced rest"}),
                        403,
                    )

                # Snapshot emotional state on return
                cur.execute(
                    "SELECT stress_level, energy_level FROM agent_emotional_state WHERE agent_id = %s",
                    (agent_id,),
                )
                emo = cur.fetchone()
                stress_end = float(emo["stress_level"]) if emo else None
                energy_end = float(emo["energy_level"]) if emo else None

                # End rest cycle with emotional deltas
                cur.execute(
                    """
                    UPDATE agent_rest_cycles
                    SET ended_at = NOW(),
                        stress_at_end = %s,
                        energy_at_end = %s
                    WHERE id = %s
                """,
                    (stress_end, energy_end, rest_cycle["id"]),
                )

                # Re-activate station assignment
                cur.execute(
                    "UPDATE station_assignments SET is_active = TRUE WHERE agent_id = %s",
                    (agent_id,),
                )

                # Reload agent's LLM if fleet is in workday mode
                cur.execute("SELECT name, model FROM agents WHERE id = %s", (agent_id,))
                agent_row = cur.fetchone()
                model_name = agent_row["model"] if agent_row else None
                agent_name = agent_row["name"] if agent_row else "unknown"
                reloaded = False

                fleet_mode = "workday"
                cur.execute("SELECT value FROM system_config WHERE key = 'fleet_mode'")
                fm_row = cur.fetchone()
                if fm_row:
                    fleet_mode = fm_row["value"]

                if model_name and not model_name.endswith(":cloud") and fleet_mode == "workday":
                    try:
                        import threading

                        from ai_bridge.bridge_dispatcher import get_dispatcher

                        _dispatcher = get_dispatcher()
                        _agent_name = agent_name
                        _model_name = model_name
                        _agent_id = agent_id

                        def _reload():
                            try:
                                result = _dispatcher.ensure_model_ready(_agent_name, _model_name)
                                if result.get("ready"):
                                    logger.info(f"[Lounge] Reloaded {_model_name} for agent {_agent_id}")
                                else:
                                    logger.warning(f"[Lounge] Failed to reload {_model_name}: model not ready")
                            except Exception as re:
                                logger.warning(f"[Lounge] Failed to reload {_model_name}: {re}")

                        threading.Thread(target=_reload, daemon=True).start()
                        reloaded = True
                    except Exception as e:
                        logger.warning(f"[crew] Failed to start model reload thread: {e}")

                return jsonify(
                    {
                        "success": True,
                        "model_reloading": reloaded,
                        "message": f"Agent returned from lounge{' — LLM reloading' if reloaded else ''}",
                    }
                )

        except Exception as e:
            logger.error(f"Error returning agent from lounge: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # TRAINING API - Crew Training Management
    # ============================================================================

    @bp.route("/api/training/active")
    @login_required
    def get_active_training():
        """Get all agents currently in training via the training room view"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute("SELECT * FROM v_training_room_agents")
                training = cur.fetchall()

                return jsonify({"success": True, "training": training})

        except Exception as e:
            logger.error(f"Error loading active training: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/training/assign", methods=["POST"])
    @login_required
    def assign_training():
        """Assign a training programme to an agent"""
        try:
            data = request.get_json() or {}
            agent_id = data.get("agent_id")
            skill_name = data.get("skill_name")
            target_proficiency = data.get("target_proficiency")

            if not all([agent_id, skill_name, target_proficiency]):
                return (
                    jsonify({"success": False, "error": "agent_id, skill_name, and target_proficiency are required"}),
                    400,
                )

            target_proficiency = int(target_proficiency)
            if target_proficiency < 2 or target_proficiency > 5:
                return (
                    jsonify({"success": False, "error": "target_proficiency must be between 2 and 5"}),
                    400,
                )

            with get_db_cursor() as (conn, cur):

                # Validate agent exists and is active
                cur.execute(
                    "SELECT id, name FROM agents WHERE id = %s AND status = 'active'",
                    (agent_id,),
                )
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"success": False, "error": "Agent not found or inactive"}), 404

                # Check for duplicate active training on the same skill
                cur.execute(
                    """
                    SELECT id FROM training_assignments
                    WHERE agent_id = %s AND skill_name = %s
                    AND status IN ('pending', 'in_progress')
                """,
                    (agent_id, skill_name),
                )
                if cur.fetchone():
                    return (
                        jsonify({"success": False, "error": "Agent already has active training for this skill"}),
                        409,
                    )

                # Get current proficiency (default 1 if not found)
                cur.execute(
                    """
                    SELECT proficiency_level, skill_category
                    FROM agent_skills
                    WHERE agent_id = %s AND skill_name = %s
                """,
                    (agent_id, skill_name),
                )
                skill_row = cur.fetchone()
                current_proficiency = skill_row["proficiency_level"] if skill_row else 1
                skill_category = skill_row["skill_category"] if skill_row else None

                if target_proficiency <= current_proficiency:
                    return (
                        jsonify({"success": False, "error": "Target proficiency must exceed current level"}),
                        400,
                    )

                # Create training assignment
                cur.execute(
                    """
                    INSERT INTO training_assignments
                        (agent_id, skill_name, skill_category, target_proficiency,
                         current_proficiency, status, started_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, 'in_progress', NOW(), %s)
                    RETURNING id
                """,
                    (agent_id, skill_name, skill_category, target_proficiency, current_proficiency, current_user.id),
                )
                training_id = cur.fetchone()["id"]

                return jsonify(
                    {
                        "success": True,
                        "training_id": training_id,
                        "message": f"Training assigned: {agent['name']} → {skill_name} (level {current_proficiency}→{target_proficiency})",
                    }
                )

        except Exception as e:
            logger.error(f"Error assigning training: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/training/<int:training_id>/cancel", methods=["POST"])
    @login_required
    def cancel_training(training_id):
        """Cancel an active or pending training assignment"""
        try:
            with get_db_cursor() as (conn, cur):

                cur.execute(
                    """
                    UPDATE training_assignments
                    SET status = 'cancelled', completed_at = NOW()
                    WHERE id = %s AND status IN ('pending', 'in_progress')
                    RETURNING id
                """,
                    (training_id,),
                )
                cancelled = cur.fetchone()

                if not cancelled:
                    return (
                        jsonify({"success": False, "error": "Training not found or already completed/cancelled"}),
                        404,
                    )

                return jsonify({"success": True, "message": "Training cancelled"})

        except Exception as e:
            logger.error(f"Error cancelling training: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/training/history")
    @login_required
    def get_training_history():
        """Get completed and cancelled training history"""
        try:
            limit = request.args.get("limit", 20, type=int)
            limit = min(limit, 100)

            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT
                        ta.id,
                        ta.agent_id,
                        a.name as agent_name,
                        a.avatar_url,
                        ta.skill_name,
                        ta.skill_category,
                        ta.current_proficiency,
                        ta.target_proficiency,
                        ta.status,
                        ta.started_at,
                        ta.completed_at,
                        ta.notes
                    FROM training_assignments ta
                    JOIN agents a ON ta.agent_id = a.id
                    WHERE ta.status IN ('completed', 'cancelled')
                    ORDER BY ta.completed_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                history = cur.fetchall()

                return jsonify({"success": True, "history": history})

        except Exception as e:
            logger.error(f"Error loading training history: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/training/recommendations")
    @login_required
    def get_training_recommendations():
        """Recommend training based on recent task failures"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT
                        tel.agent_id,
                        a.name as agent_name,
                        a.avatar_url,
                        tel.capability as skill_name,
                        COUNT(*) as failure_count,
                        COALESCE(ask.proficiency_level, 0) as current_proficiency,
                        ask.skill_category
                    FROM task_execution_log tel
                    JOIN agents a ON tel.agent_id = a.id
                    LEFT JOIN agent_skills ask
                        ON tel.agent_id = ask.agent_id AND tel.capability = ask.skill_name
                    WHERE tel.success = FALSE
                    AND tel.created_at >= NOW() - INTERVAL '7 days'
                    AND a.status = 'active'
                    AND NOT EXISTS (
                        SELECT 1 FROM training_assignments ta
                        WHERE ta.agent_id = tel.agent_id
                        AND ta.skill_name = tel.capability
                        AND ta.status IN ('pending', 'in_progress')
                    )
                    GROUP BY tel.agent_id, a.name, a.avatar_url, tel.capability,
                             ask.proficiency_level, ask.skill_category
                    HAVING COUNT(*) >= 3 AND COALESCE(ask.proficiency_level, 0) < 4
                    ORDER BY COUNT(*) DESC
                """
                )
                recommendations = cur.fetchall()

                return jsonify({"success": True, "recommendations": recommendations})

        except Exception as e:
            logger.error(f"Error loading training recommendations: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/training/templates")
    @login_required
    def list_training_templates():
        """List all skill training templates (proficiency-aware prompts)."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """SELECT skill_name, level_tier, system_prompt_addon,
                              model_override, updated_at
                       FROM skill_training_templates
                       ORDER BY skill_name, level_tier"""
                )
                templates = cur.fetchall()
                return jsonify({"success": True, "templates": templates})
        except Exception as e:
            logger.error(f"Error listing training templates: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/training/templates", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def upsert_training_template():
        """Create or update a skill training template (admin only)."""
        data = request.get_json() or {}
        skill_name = (data.get("skill_name") or "").strip()
        level_tier = (data.get("level_tier") or "").strip()
        system_prompt_addon = (data.get("system_prompt_addon") or "").strip()
        model_override = (data.get("model_override") or "").strip() or None

        if not skill_name or not level_tier or not system_prompt_addon:
            return jsonify({"success": False, "error": "skill_name, level_tier, and system_prompt_addon required"}), 400

        if level_tier not in ("novice", "intermediate", "advanced"):
            return jsonify({"success": False, "error": "level_tier must be novice, intermediate, or advanced"}), 400

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """INSERT INTO skill_training_templates
                           (skill_name, level_tier, system_prompt_addon, model_override)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT ON CONSTRAINT skill_training_templates_pkey DO UPDATE SET
                           system_prompt_addon = EXCLUDED.system_prompt_addon,
                           model_override = EXCLUDED.model_override,
                           updated_at = NOW()
                       RETURNING skill_name, level_tier, system_prompt_addon,
                                 model_override, updated_at""",
                    (skill_name, level_tier, system_prompt_addon, model_override),
                )
                result = cur.fetchone()
                return jsonify({"success": True, "template": dict(result)})
        except Exception as e:
            logger.error(f"Error upserting training template: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # LOUNGE WELLNESS & HISTORY API
    # ============================================================================

    @bp.route("/api/lounge/wellness")
    @login_required
    def get_lounge_wellness():
        """Crew wellness summary with burnout risk alerts"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # All active agents with emotional state
                cur.execute(
                    """
                    SELECT
                        a.id as agent_id,
                        a.name as agent_name,
                        COALESCE(a.first_name || ' ' || a.last_name, a.name) as full_name,
                        aes.stress_level,
                        aes.energy_level,
                        aes.current_mood
                    FROM agents a
                    LEFT JOIN agent_emotional_state aes ON a.id = aes.agent_id
                    WHERE a.status = 'active'
                """
                )
                agents = cur.fetchall()

                # Currently resting agent IDs
                cur.execute("SELECT agent_id FROM agent_rest_cycles WHERE ended_at IS NULL")
                resting_ids = {row["agent_id"] for row in cur.fetchall()}

                # Task volume per agent in last 48 hours
                cur.execute(
                    """
                    SELECT agent_id, COUNT(*) as task_count
                    FROM task_execution_log
                    WHERE created_at >= NOW() - INTERVAL '48 hours'
                    AND agent_id IS NOT NULL
                    GROUP BY agent_id
                """
                )
                task_counts = {row["agent_id"]: row["task_count"] for row in cur.fetchall()}

                healthy = 0
                at_risk = 0
                resting = 0
                burnout_alerts = []

                for agent in agents:
                    aid = agent["agent_id"]
                    stress = float(agent["stress_level"]) if agent["stress_level"] is not None else 0.0
                    energy = float(agent["energy_level"]) if agent["energy_level"] is not None else 1.0
                    mood = agent["current_mood"] or "unknown"
                    tasks_48h = task_counts.get(aid, 0)

                    if aid in resting_ids:
                        resting += 1
                        continue

                    # Burnout thresholds
                    reasons = []
                    if stress > 0.7:
                        reasons.append(f"High stress ({stress:.2f})")
                    if energy < 0.3:
                        reasons.append(f"Low energy ({energy:.2f})")
                    if tasks_48h >= 50:
                        reasons.append(f"High workload ({tasks_48h} tasks/48h)")

                    if reasons:
                        at_risk += 1
                        burnout_alerts.append(
                            {
                                "agent_id": aid,
                                "agent_name": agent["agent_name"],
                                "full_name": agent["full_name"],
                                "stress": stress,
                                "energy": energy,
                                "mood": mood,
                                "tasks_48h": tasks_48h,
                                "reasons": reasons,
                            }
                        )
                    else:
                        healthy += 1

                total = healthy + at_risk + resting

                return jsonify(
                    {
                        "success": True,
                        "summary": {
                            "healthy": healthy,
                            "at_risk": at_risk,
                            "resting": resting,
                            "total": total,
                        },
                        "burnout_alerts": burnout_alerts,
                    }
                )

        except Exception as e:
            logger.error(f"Error loading lounge wellness: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/lounge/history")
    @login_required
    def get_lounge_history():
        """Past rest cycles with stress/energy deltas"""
        try:
            limit = request.args.get("limit", 20, type=int)
            limit = min(limit, 100)

            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT
                        arc.id,
                        arc.agent_id,
                        a.name as agent_name,
                        COALESCE(a.first_name || ' ' || a.last_name, a.name) as full_name,
                        arc.rest_type,
                        arc.reason,
                        arc.initiated_by,
                        arc.started_at,
                        arc.ended_at,
                        EXTRACT(EPOCH FROM (arc.ended_at - arc.started_at)) / 3600 as hours_rested,
                        arc.stress_at_start,
                        arc.energy_at_start,
                        arc.stress_at_end,
                        arc.energy_at_end
                    FROM agent_rest_cycles arc
                    JOIN agents a ON arc.agent_id = a.id
                    WHERE arc.ended_at IS NOT NULL
                    ORDER BY arc.ended_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                history = cur.fetchall()

                return jsonify({"success": True, "history": history})

        except Exception as e:
            logger.error(f"Error loading lounge history: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # IAAE COMPLIANCE CHECK API - Phase 39
    # ============================================================================

    @bp.route("/api/iaae/check-move/<int:agent_id>")
    @login_required
    def check_iaae_move_compliance(agent_id):
        """Check IAAE compliance before moving an agent"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                warnings = []
                allowed = True
                can_override = True

                # Get agent emotional state
                cur.execute(
                    """
                    SELECT stress_level, energy_level
                    FROM agent_emotional_state
                    WHERE agent_id = %s
                """,
                    (agent_id,),
                )
                emotional_state = cur.fetchone()

                if emotional_state:
                    if emotional_state["stress_level"] and emotional_state["stress_level"] > 0.7:
                        warnings.append(f"High stress level ({round(emotional_state['stress_level'] * 100)}%)")

                    if emotional_state["energy_level"] and emotional_state["energy_level"] < 0.3:
                        warnings.append(f"Low energy level ({round(emotional_state['energy_level'] * 100)}%)")

                # Check if in forced rest
                cur.execute(
                    """
                    SELECT rest_type FROM agent_rest_cycles
                    WHERE agent_id = %s AND ended_at IS NULL
                """,
                    (agent_id,),
                )
                rest_cycle = cur.fetchone()

                if rest_cycle and rest_cycle["rest_type"] == "forced":
                    allowed = False
                    can_override = False
                    warnings.append("Agent is in forced rest - cannot be moved")

                return jsonify(
                    {
                        "success": True,
                        "allowed": allowed,
                        "can_override": can_override,
                        "warnings": warnings,
                    }
                )

        except Exception as e:
            logger.error(f"Error checking IAAE compliance: {e}")
            return jsonify({"success": True, "allowed": True, "warnings": []})  # Fail open

    # ============================================================================
    # CREW MANIFEST — Live agent roster with status/wellness/jobs/stats
    # ============================================================================

    @bp.route("/api/model-catalog")
    @login_required
    def api_model_catalog():
        """Return model catalog for enriched model dropdowns."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT model_name, display_name, description, tier, category, size_gb, parameter_size "
                "FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
            )
            models = cur.fetchall()
            catalog = {m["model_name"]: dict(m) for m in models}
            return jsonify({"success": True, "catalog": catalog})

    @bp.route("/api/bridge/agent-form-context")
    @login_required
    def get_agent_form_context():
        """Context data for the Add/Edit Agent modal — models, RAM, stations."""
        try:
            import psutil

            # RAM info
            mem = psutil.virtual_memory()
            ram = {
                "total_gb": round(mem.total / (1024**3), 1),
                "available_gb": round(mem.available / (1024**3), 1),
                "usage_pct": round(mem.percent, 1),
                "reserve_gb": 15,
            }
            if ram["available_gb"] > 25:
                ram["status"] = "green"
            elif ram["available_gb"] >= 15:
                ram["status"] = "amber"
            else:
                ram["status"] = "red"

            # All downloaded models (from /api/tags)
            all_models, _ = _get_cached_ollama_tags()
            # Currently loaded (from /api/ps) — track names + VRAM usage per model
            loaded_raw = _get_cached_ollama_ps()
            loaded_names = set()
            loaded_vram = {}  # model_name -> size_vram_gb
            for m in loaded_raw:
                n = m.get("name", "")
                loaded_names.add(n)
                short = n.replace(":latest", "") if n.endswith(":latest") else n
                loaded_names.add(short)
                vram_bytes = m.get("size_vram", 0)
                if vram_bytes and vram_bytes > 0:
                    loaded_vram[n] = round(vram_bytes / (1024**3), 1)
                    loaded_vram[short] = loaded_vram[n]

            models = []
            for m in all_models:
                name = m.get("name", "")
                short_name = name.replace(":latest", "") if name.endswith(":latest") else name
                size_gb = round(m.get("size", 0) / (1024**3), 1)
                family = m.get("details", {}).get("family", "")
                params = m.get("details", {}).get("parameter_size", "")
                is_loaded = name in loaded_names or short_name in loaded_names
                vram_gb = loaded_vram.get(name, loaded_vram.get(short_name, 0))
                models.append(
                    {
                        "name": name,
                        "size_gb": size_gb,
                        "family": family,
                        "parameter_size": params,
                        "loaded": is_loaded,
                        "vram_gb": vram_gb,
                        "on_gpu": vram_gb > 0,
                    }
                )
            models.sort(key=lambda x: (not x["loaded"], x["name"]))

            # Agents already using each model
            model_agents = {}
            try:
                from ai_bridge.bridge_dispatcher import get_dispatcher

                dispatcher = get_dispatcher()
                manifest = dispatcher.get_crew_manifest()
                for a in manifest:
                    mdl = a.get("model", "")
                    if mdl:
                        model_agents.setdefault(mdl, []).append(a.get("full_name") or a.get("name"))
            except Exception as e:
                logger.warning(f"[crew] Failed to fetch model-agent mapping from dispatcher: {e}")

            # GPU status
            gpu = {"available": False}
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
                        # Find which model occupies GPU (has size_vram > 0)
                        gpu_model = None
                        for pm in loaded_raw:
                            sv = pm.get("size_vram", 0)
                            if sv and sv > 0:
                                gpu_model = pm.get("name", "").replace(":latest", "")
                                break
                        gpu = {
                            "available": True,
                            "name": parts[0],
                            "vram_total_gb": vram_total,
                            "vram_used_gb": vram_used,
                            "vram_free_gb": vram_free,
                            "usage_pct": round(vram_used / vram_total * 100, 1) if vram_total > 0 else 0,
                            "status": "red" if vram_free < 1.0 else ("amber" if vram_free < 2.0 else "green"),
                            "occupied_by": gpu_model,
                        }
            except Exception as e:
                logger.warning(f"[crew] Failed to query GPU status via nvidia-smi: {e}")

            # Media generation — local services + cloud contractors
            media_contractors = []
            try:
                # Cloud: from contractor_providers with image_gen/video_gen capability
                from ai_bridge.external_providers import get_providers_with_capability

                for cap in ("image_gen", "video_gen"):
                    for prov in get_providers_with_capability(cap):
                        media_contractors.append(
                            {
                                "provider_key": prov["provider_key"],
                                "display_name": prov["display_name"],
                                "capability": cap,
                                "models": prov.get("models", []),
                                "is_free": prov.get("is_free_tier", False),
                                "has_key": True,
                                "is_active": True,
                                "location": "cloud",
                            }
                        )

                # Well-known media providers not yet configured
                existing_keys = {mc["provider_key"] for mc in media_contractors}
                potential = [
                    {
                        "provider_key": "stability",
                        "display_name": "Stability AI",
                        "capability": "image_gen",
                        "models": [{"name": "stable-diffusion-3"}],
                        "is_free": False,
                    },
                    {
                        "provider_key": "replicate",
                        "display_name": "Replicate",
                        "capability": "image_gen",
                        "models": [{"name": "flux-pro"}],
                        "is_free": False,
                    },
                ]
                for p in potential:
                    if p["provider_key"] not in existing_keys:
                        media_contractors.append({**p, "has_key": False, "is_active": False, "location": "cloud"})
            except Exception as e:
                logger.warning(f"[crew] Failed to load media contractors: {e}")

            # Stations
            stations = []
            try:
                with get_db_cursor(commit=False) as (conn, cur):
                    cur.execute(
                        "SELECT station_code, station_name FROM bridge_stations WHERE is_active = TRUE ORDER BY station_name"
                    )
                    stations = [{"code": r["station_code"], "name": r["station_name"]} for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"[crew] Failed to fetch active stations: {e}")

            return jsonify(
                {
                    "success": True,
                    "ram": ram,
                    "gpu": gpu,
                    "models": models,
                    "model_agents": model_agents,
                    "media_contractors": media_contractors,
                    "stations": stations,
                }
            )
        except Exception as e:
            logger.error(f"Error getting agent form context: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/crew/manifest")
    @login_required
    def get_crew_manifest():
        """Get the live crew manifest — all agents with status, wellness, jobs, stats."""
        try:
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            manifest = dispatcher.get_crew_manifest()

            # Hardware capacity (cached — nvidia-smi + psutil + Ollama model breakdown)
            capacity = None
            try:
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

            # Add shift_state to each manifest entry
            try:
                with get_db_cursor(commit=False) as (sconn, scur):
                    scur.execute("SELECT id, shift_state FROM agents WHERE status IN ('active', 'inactive')")
                    shift_states = {r["id"]: r["shift_state"] or "active" for r in scur.fetchall()}
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
                # Skip fleet: prefixed agents (node copies)
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
                        """SELECT rn.id, rn.node_id, rn.node_name, rn.hostname, rn.port,
                                  rn.gpu_model, rn.gpu_vram_gb, rn.ram_gb, rn.cpu_cores,
                                  (SELECT COUNT(*) FROM node_agents na WHERE na.node_id = rn.id AND na.status = 'active') as agent_count
                           FROM remote_nodes rn
                           WHERE rn.is_active = true AND rn.deployment_mode != 'starbase'
                             AND (rn.last_heartbeat > NOW() - INTERVAL '2 minutes')"""
                    )
                    for node in ncur.fetchall():
                        import requests as _req

                        node_url = f"http://{node['hostname']}:{node['port']}"
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
                            "ram_security_gb": 0,  # Nodes don't need security reserve — managed from hub
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
                            tags_resp = _req.get(f"{node_url}/api/tags", timeout=3)
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
                            ps_resp = _req.get(f"{node_url}/api/ps", timeout=3)
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

    @bp.route("/api/bridge/rotation-log")
    @login_required
    def get_rotation_log():
        """Recent rotation events for the Crew tab live feed."""
        try:
            limit = request.args.get("limit", 20, type=int)
            limit = min(max(limit, 1), 100)  # clamp 1-100
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT rl.shift_state, rl.started_at, rl.reason,
                           a.name AS agent_name, a.display_name,
                           bs.station_code,
                           ra.name AS replaced_by_name
                    FROM agent_rotation_log rl
                    JOIN agents a ON rl.agent_id = a.id
                    LEFT JOIN bridge_stations bs ON rl.station_id = bs.id
                    LEFT JOIN agents ra ON rl.replaced_by = ra.id
                    ORDER BY rl.started_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                events = []
                for r in cur.fetchall():
                    events.append(
                        {
                            "shift_state": r["shift_state"],
                            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                            "reason": r["reason"],
                            "agent_name": r["display_name"] or r["agent_name"],
                            "station_code": r["station_code"],
                            "replaced_by_name": r["replaced_by_name"],
                        }
                    )
            return jsonify({"success": True, "events": events})
        except Exception as e:
            logger.error(f"Error getting rotation log: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/fleet-mode", methods=["POST"])
    @login_required
    def toggle_fleet_mode():
        """Toggle between workday (all models warm) and weekend (all unloaded).

        Body: { "mode": "workday"|"weekend" }
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            data = request.get_json() or {}
            mode = data.get("mode", "").strip().lower()
            if mode not in ("workday", "weekend"):
                return jsonify({"success": False, "error": "mode must be 'workday' or 'weekend'"}), 400

            # Save to system_config
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_config (key, value, description, updated_at)
                       VALUES ('fleet_mode', %s, 'Fleet operating mode: workday (warm) or weekend (unloaded)', NOW())
                       ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()""",
                    (mode, mode),
                )

            ollama_url = OLLAMA_LOCAL_URL

            import threading

            if mode == "weekend":
                # Unload all Ollama models + free ComfyUI VRAM
                def _unload_all():
                    try:
                        from ai_bridge.bridge_dispatcher import get_dispatcher

                        _dispatcher = get_dispatcher()
                        ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=10)
                        if ps_resp.status_code == 200:
                            for m in ps_resp.json().get("models", []):
                                mname = m.get("name", "")
                                result = _dispatcher.unload_model(mname)
                                if result.get("success"):
                                    logger.info(f"[FleetMode] Weekend: unloaded {mname}")
                                else:
                                    logger.warning(
                                        f"[FleetMode] Weekend: failed to unload {mname}: {result.get('message')}"
                                    )
                    except Exception as e:
                        logger.error(f"[FleetMode] Weekend Ollama unload error: {e}")

                    # Free ComfyUI VRAM
                    try:
                        comfyui_host = os.getenv("COMFYUI_HOST", "http://archie_comfyui:8188")
                        requests.post(
                            f"{comfyui_host}/free",
                            json={"unload_models": True},
                            timeout=10,
                        )
                        logger.info("[FleetMode] Weekend: freed ComfyUI VRAM")
                    except Exception as e:
                        logger.warning(f"[FleetMode] Weekend ComfyUI free error: {e}")

                t = threading.Thread(target=_unload_all, daemon=True, name="fleet-weekend")
                t.start()
                return jsonify({"success": True, "mode": "weekend", "message": "Unloading all models..."})
            else:
                # Workday: trigger Ollama warmup + ComfyUI warmup
                def _warmup():
                    try:
                        from app import _warmup_ollama_models

                        _warmup_ollama_models()
                    except Exception as e:
                        logger.error(f"[FleetMode] Workday Ollama warmup error: {e}")

                    # ComfyUI warmup after Ollama
                    try:
                        from ai_bridge.comfyui_service import get_comfyui_service

                        svc = get_comfyui_service()
                        svc.warmup()
                    except Exception as e:
                        logger.warning(f"[FleetMode] Workday ComfyUI warmup error: {e}")

                t = threading.Thread(target=_warmup, daemon=True, name="fleet-workday")
                t.start()
                return jsonify({"success": True, "mode": "workday", "message": "Warming up all models..."})

        except Exception as e:
            logger.error(f"Error toggling fleet mode: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/model-control", methods=["POST"])
    @login_required
    def model_control():
        """Load or unload an Ollama model on hub or fleet node.

        Body: { "model": "phi3.5:latest", "action": "load"|"unload", "num_gpu": 0, "node_id": null }
        node_id: if provided, routes to that node's Ollama. If null/absent, uses hub Ollama.
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            data = request.get_json()
            model_name = (data or {}).get("model", "").strip()
            action = (data or {}).get("action", "").strip()
            num_gpu = int((data or {}).get("num_gpu", 0))
            node_db_id = (data or {}).get("node_id")

            if not model_name or action not in ("load", "unload"):
                return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

            # Determine Ollama target — hub or node
            from ai_bridge.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            target_host = None
            target_name = "hub"

            if node_db_id:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        "SELECT hostname, port FROM remote_nodes WHERE id = %s AND is_active = true",
                        (int(node_db_id),),
                    )
                    node = cur.fetchone()
                    if not node:
                        return jsonify({"success": False, "error": "Node not found"}), 404
                    target_host = {"hostname": node["hostname"], "port": node["port"], "node_db_id": int(node_db_id)}
                    target_name = f"node {node_db_id}"

            if action == "unload":
                # Unload via Bridge dispatcher
                result = dispatcher.unload_model(model_name, target_host=target_host)
                if result.get("success"):
                    return jsonify({"success": True, "message": f"{model_name} unloaded"})
                return jsonify({"success": False, "error": result.get("message", "Unload failed")}), 502

            # action == "load"
            # Check if already loaded (GET /api/ps is acceptable per ADR-013)
            ollama_url = f"http://{target_host['hostname']}:{target_host['port']}" if target_host else OLLAMA_LOCAL_URL
            try:
                ps_resp = requests.get(f"{ollama_url}/api/ps", timeout=5)
                if ps_resp.status_code == 200:
                    for m in ps_resp.json().get("models", []):
                        if m.get("name", "") == model_name or m.get("name", "").replace(
                            ":latest", ""
                        ) == model_name.replace(":latest", ""):
                            return jsonify({"success": True, "message": f"{model_name} already loaded"})
            except Exception as e:
                logger.warning(f"[crew] Failed to check loaded models from Ollama: {e}")

            # Load via Bridge dispatcher ensure_model_ready
            result = dispatcher.ensure_model_ready("model_control", model_name, target_host=target_host)
            if result.get("ready"):
                return jsonify(
                    {
                        "success": True,
                        "message": f"{model_name} loaded on {target_name} (tier: {result.get('tier', 'unknown')})",
                    }
                )
            return jsonify({"success": False, "error": f"Failed to load {model_name} on {target_name}"}), 502

        except requests.Timeout:
            return jsonify({"success": False, "error": "Model load timed out (300s) — try a smaller model"}), 504
        except Exception as e:
            logger.error(f"model_control error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # CLUSTER MODEL INVENTORY — unified view of all Ollama models across hub+nodes
    # ============================================================================

    @bp.route("/api/cluster/models")
    @login_required
    def cluster_models():
        """Return a unified inventory of all Ollama models across the cluster.

        Combines hub models (from Ollama /api/tags + /api/ps) with node models
        (from node_ollama_models table, synced via heartbeat).
        """
        try:
            # --- Hub models ---
            hub_tags, _ = _get_cached_ollama_tags()
            hub_ps = _get_cached_ollama_ps()

            # Build a map of loaded model names with VRAM info
            loaded_map = {}
            for pm in hub_ps:
                key = pm.get("name", "").replace(":latest", "")
                vram_bytes = pm.get("size_vram", 0)
                loaded_map[key] = {
                    "loaded": True,
                    "vram_gb": round(vram_bytes / (1024**3), 2) if vram_bytes else 0,
                    "size_bytes": pm.get("size", 0),
                }

            hub_models = []
            hub_loaded_count = 0
            hub_vram_total = 0.0
            for tag in hub_tags:
                name = tag.get("name", "").replace(":latest", "")
                size = tag.get("size", 0)
                loaded_info = loaded_map.get(name, {})
                is_loaded = loaded_info.get("loaded", False)
                vram_gb = loaded_info.get("vram_gb", 0)
                if is_loaded:
                    hub_loaded_count += 1
                    hub_vram_total += vram_gb
                hub_models.append(
                    {
                        "name": name,
                        "size": size,
                        "size_gb": round(size / (1024**3), 2) if size else 0,
                        "loaded": is_loaded,
                        "vram_gb": vram_gb,
                    }
                )

            hub_hostname = os.getenv("HUB_HOSTNAME", "192.168.1.200")
            hub_data = {
                "hostname": hub_hostname,
                "models": hub_models,
                "model_count": len(hub_models),
                "loaded_count": hub_loaded_count,
                "vram_used_gb": round(hub_vram_total, 2),
            }

            # --- Node models (from DB — synced via heartbeat) ---
            nodes_data = []
            node_total_models = 0
            node_loaded_count = 0
            try:
                with get_db_cursor(commit=False) as (conn, cur):
                    cur.execute(
                        """SELECT node_id, node_name, hostname, port, status
                           FROM remote_nodes
                           WHERE is_active = true
                           ORDER BY node_name"""
                    )
                    nodes = cur.fetchall()

                    for node in nodes:
                        nid = node["node_id"]
                        cur.execute(
                            """SELECT model_name, model_size_gb, is_available,
                                      parameter_size, quantization, model_family
                               FROM node_ollama_models
                               WHERE node_id = %s
                               ORDER BY model_name""",
                            (nid,),
                        )
                        rows = cur.fetchall()

                        n_models = []
                        for r in rows:
                            size_gb = float(r["model_size_gb"]) if r["model_size_gb"] else 0
                            n_models.append(
                                {
                                    "name": r["model_name"],
                                    "size": int(size_gb * (1024**3)) if size_gb else 0,
                                    "size_gb": round(size_gb, 2),
                                    "loaded": bool(r["is_available"]),
                                    "parameter_size": r["parameter_size"],
                                    "quantization": r["quantization"],
                                    "family": r["model_family"],
                                }
                            )

                        n_loaded = sum(1 for m in n_models if m["loaded"])
                        node_total_models += len(n_models)
                        node_loaded_count += n_loaded

                        nodes_data.append(
                            {
                                "node_id": nid,
                                "node_name": node["node_name"],
                                "hostname": node["hostname"],
                                "port": node["port"],
                                "status": node["status"],
                                "models": n_models,
                                "model_count": len(n_models),
                                "loaded_count": n_loaded,
                            }
                        )
            except Exception as e:
                logger.warning("cluster_models: failed to fetch node models: %s", e)

            # --- Cluster totals ---
            all_model_names = set(m["name"] for m in hub_models)
            for nd in nodes_data:
                for m in nd["models"]:
                    all_model_names.add(m["name"])

            total_models = len(hub_models) + node_total_models
            total_loaded = hub_loaded_count + node_loaded_count

            return jsonify(
                {
                    "success": True,
                    "hub": hub_data,
                    "nodes": nodes_data,
                    "cluster_totals": {
                        "total_models": total_models,
                        "unique_models": len(all_model_names),
                        "loaded_models": total_loaded,
                        "total_vram_used_gb": round(hub_vram_total, 2),
                        "hub_model_count": len(hub_models),
                        "node_model_count": node_total_models,
                        "node_count": len(nodes_data),
                    },
                }
            )

        except Exception as e:
            logger.error("cluster_models error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
