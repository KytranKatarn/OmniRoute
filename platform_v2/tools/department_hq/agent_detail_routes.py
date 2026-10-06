"""
Department HQ — Agent Detail routes

Endpoints:
  GET   /api/agent/<id>/profile              — Full agent profile (agent + skills + welfare + performance)
  PATCH /api/agent/<id>                      — Partial update (single-source editor for profile modal, #1916)
  GET   /api/agent/<id>/skills               — Agent skills list
  POST  /api/agent/<id>/skills               — Add/update a skill {skill_name, level, category}
  GET   /api/agent/<id>/facts                — List agent's curated facts
  POST  /api/agent/<id>/facts                — Add a curated fact {fact_text, category?, importance?}
  POST  /api/agent/facts/<fact_id>/toggle    — Activate/deactivate a fact {is_active: bool}
  POST  /api/agent/facts/<fact_id>/delete    — Delete a fact
  GET   /api/agent/<id>/welfare              — Agent welfare metrics
  POST  /api/agent/<id>/shift                — Change shift state {shift_state}
  POST  /api/agent/<id>/department           — Reassign department {department}

Uses the centralized agent_service for all operations.
"""

import json as _json
import logging

from flask import jsonify, request
from flask_login import current_user

from services.agent_service import (
    get_agent,
    get_skills,
    get_welfare,
    get_performance,
    update_agent,
    add_skill,
    DEPARTMENT_FLOOR_MAP,
    VALID_SHIFT_STATES,
)
from services.ollama_availability import is_model_available
from .services import agent_profile_helpers as _profile_helpers

logger = logging.getLogger(__name__)

# Fields the PATCH endpoint will accept. Anything else → 400 unknown_field.
EDITABLE_FIELDS = {
    # Identity
    "display_name",
    "title",
    "bio",
    "acronym",
    "acronym_expansion",
    "pronouns",
    "current_grade",
    # Classification
    "department",
    "floor",
    "writing_tone",
    "is_department_ai",
    "reports_to_agent_id",
    # Dispatch (sensitive)
    "model",
    "temperature",
    "max_tokens",
    "system_prompt",
    # Appearance/narrative
    "communication_style",
    "appearance_notes",
    "age_range",
    "gender",
    "ethnicity",
    # Portrait (lives in agent_portraits, delegated to portrait_service)
    "identity_prompt",
    # Voice & social
    "social_topics",
    "auto_approve_threshold",
}

# Fields that trigger the confirm-on-dirty client overlay.
SENSITIVE_FIELDS = {
    "model",
    "temperature",
    "max_tokens",
    "system_prompt",
    "is_department_ai",
    "reports_to_agent_id",
}


def _get_identity_prompt(agent_id: int):
    return _profile_helpers.get_identity_prompt(agent_id, logger=logger)


def _get_voice_profile(agent_id: int):
    return _profile_helpers.get_voice_profile(agent_id, logger=logger)


def register_agent_detail_routes(bp, admin_required):
    """Register agent detail management routes on the blueprint."""

    @bp.route("/api/agent/<int:agent_id>/profile")
    @admin_required
    def api_agent_profile(agent_id):
        """Full agent profile: agent data + skills + welfare + performance."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            skills = get_skills(agent_id)
            welfare = get_welfare(agent_id)
            perf = get_performance(agent_id)
            voice_profile = _get_voice_profile(agent_id)

            # Sanitize agent dict for JSON. Includes the full editable field
            # set used by the agent profile modal (Project #262 Task #1916).
            agent_data = {
                # Identity
                "id": agent["id"],
                "name": agent["name"],
                "display_name": agent.get("display_name"),
                "title": agent.get("title", ""),
                "bio": agent.get("bio", ""),
                "acronym": agent.get("acronym"),
                "acronym_expansion": agent.get("acronym_expansion"),
                "pronouns": agent.get("pronouns"),
                "current_grade": agent.get("current_grade"),
                # Classification
                "department": agent.get("department"),
                "floor": agent.get("floor"),
                "writing_tone": agent.get("writing_tone"),
                "is_department_ai": bool(agent.get("is_department_ai")),
                "reports_to_agent_id": agent.get("reports_to_agent_id"),
                # Dispatch (sensitive)
                "model": agent.get("model"),
                "temperature": float(agent.get("temperature") or 0.7),
                "max_tokens": agent.get("max_tokens", 2048),
                "system_prompt": agent.get("system_prompt", ""),
                # Appearance/narrative
                "communication_style": agent.get("communication_style"),
                "appearance_notes": agent.get("appearance_notes"),
                "age_range": agent.get("age_range"),
                "gender": agent.get("gender"),
                "ethnicity": agent.get("ethnicity"),
                # Voice & social
                "social_topics": agent.get("social_topics") or [],
                "auto_approve_threshold": float(agent.get("auto_approve_threshold") or 0.0),
                "voice_profile": voice_profile,
                # Portrait identity (from agent_portraits — single source of truth)
                "identity_prompt": _get_identity_prompt(agent_id),
                # Read-only
                "status": agent.get("status"),
                "shift_state": agent.get("shift_state"),
                "avatar_url": agent.get("avatar_url", ""),
                "avatar_updated_at": agent.get("updated_at").isoformat() if agent.get("updated_at") else None,
                "capabilities": agent.get("capabilities"),
                # Welfare inline (for header band / quick render)
                "stress_level": float(agent.get("stress_level") or 0),
                "energy_level": float(agent.get("energy_level") or 0.5),
                "current_mood": agent.get("current_mood", "neutral"),
                "mood_intensity": float(agent.get("mood_intensity") or 0.5),
            }

            # Welfare as separate object (may differ from agent join data)
            welfare_data = None
            if welfare:
                welfare_data = {
                    "stress_level": float(welfare.get("stress_level") or 0),
                    "energy_level": float(welfare.get("energy_level") or 0.5),
                    "current_mood": welfare.get("current_mood", "neutral"),
                    "mood_intensity": float(welfare.get("mood_intensity") or 0.5),
                }

            return jsonify(
                {
                    "agent": agent_data,
                    "skills": skills,
                    "welfare": welfare_data,
                    "performance": perf,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/skills")
    @admin_required
    def api_agent_skills(agent_id):
        """Get agent's skills."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            skills = get_skills(agent_id)
            return jsonify({"agent_id": agent_id, "skills": skills})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/skills", methods=["POST"])
    @admin_required
    def api_agent_add_skill(agent_id):
        """Add or update a skill for an agent."""
        data = request.get_json(silent=True) or {}
        skill_name = data.get("skill_name", "").strip()
        level = data.get("level", 1)
        category = data.get("category", "general")

        if not skill_name:
            return jsonify({"error": "skill_name is required"}), 400
        if not isinstance(level, int) or level < 1 or level > 5:
            return jsonify({"error": "level must be 1-5"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            add_skill(agent_id, skill_name, level=level, category=category)
            return jsonify(
                {
                    "success": True,
                    "message": f"Skill '{skill_name}' set to level {level}",
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/facts")
    @admin_required
    def api_agent_facts(agent_id):
        """List an agent's curated facts (active + inactive) for the editor."""
        from services.collaborator_facts_service import list_for_agent

        try:
            if not get_agent(agent_id):
                return jsonify({"error": "Agent not found"}), 404
            return jsonify({"agent_id": agent_id, "facts": list_for_agent(agent_id)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/facts", methods=["POST"])
    @admin_required
    def api_agent_add_fact(agent_id):
        """Add a curated fact {fact_text, category?, importance?}."""
        from services.collaborator_facts_service import add_fact

        data = request.get_json(silent=True) or {}
        fact_text = (data.get("fact_text") or "").strip()
        if not fact_text:
            return jsonify({"error": "fact_text is required"}), 400
        try:
            if not get_agent(agent_id):
                return jsonify({"error": "Agent not found"}), 404
            who = getattr(current_user, "username", None)
            importance = data.get("importance", 5)
            try:
                importance = int(importance)
            except (TypeError, ValueError):
                importance = 5
            fact = add_fact(agent_id, fact_text, category=data.get("category"), importance=importance, created_by=who)
            return jsonify({"success": True, "fact": fact})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/facts/<int:fact_id>/toggle", methods=["POST"])
    @admin_required
    def api_agent_toggle_fact(fact_id):
        """Activate/deactivate a fact {is_active: bool}."""
        from services.collaborator_facts_service import set_active

        data = request.get_json(silent=True) or {}
        try:
            fact = set_active(fact_id, bool(data.get("is_active", True)))
            if not fact:
                return jsonify({"error": "Fact not found"}), 404
            return jsonify({"success": True, "fact": fact})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/facts/<int:fact_id>/delete", methods=["POST"])
    @admin_required
    def api_agent_delete_fact(fact_id):
        """Delete a fact."""
        from services.collaborator_facts_service import delete_fact

        try:
            return jsonify({"success": delete_fact(fact_id)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/welfare")
    @admin_required
    def api_agent_welfare(agent_id):
        """Get agent's welfare metrics."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404
            welfare = get_welfare(agent_id)
            return jsonify({"agent_id": agent_id, "welfare": welfare})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/shift", methods=["POST"])
    @admin_required
    def api_agent_shift(agent_id):
        """Change agent shift state."""
        data = request.get_json(silent=True) or {}
        shift_state = data.get("shift_state")

        if not shift_state:
            return jsonify({"error": "shift_state is required"}), 400
        if shift_state not in VALID_SHIFT_STATES:
            return (
                jsonify({"error": f"Invalid shift_state: {shift_state}. Valid: {sorted(VALID_SHIFT_STATES)}"}),
                400,
            )

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            previous = agent["shift_state"]
            update_agent(agent_id, shift_state=shift_state)
            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} shift changed to {shift_state}",
                    "previous": previous,
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/department", methods=["POST"])
    @admin_required
    def api_agent_department(agent_id):
        """Reassign agent to a different department."""
        data = request.get_json(silent=True) or {}
        department = data.get("department")

        if not department:
            return jsonify({"error": "department is required"}), 400
        if department not in DEPARTMENT_FLOOR_MAP:
            return jsonify({"error": f"Invalid department: {department}"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            previous = agent["department"]
            update_agent(agent_id, department=department)
            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} moved to {department}",
                    "previous": previous,
                }
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>", methods=["PATCH"])
    @admin_required
    def api_agent_patch(agent_id):
        """Single-source profile editor write path (Project #262 Task #1916).

        Validates against EDITABLE_FIELDS allowlist, runs per-field rules,
        calls agent_service.update_agent, writes governance_audit_log.
        """
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not payload:
            return jsonify({"ok": False, "error": "empty_body"}), 400

        unknown = set(payload.keys()) - EDITABLE_FIELDS
        if unknown:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "unknown_field",
                        "fields": sorted(unknown),
                    }
                ),
                400,
            )

        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"ok": False, "error": "not_found"}), 404

        err = _validate_patch_payload(agent_id, payload)
        if err:
            return jsonify({"ok": False, **err}), 400

        before = {k: agent.get(k) for k in payload.keys()}
        # Fix before value for identity_prompt — agents table doesn't have it
        if "identity_prompt" in before:
            before["identity_prompt"] = _get_identity_prompt(agent_id)

        # identity_prompt lives in agent_portraits — delegate to portrait_service
        identity_prompt_value = payload.pop("identity_prompt", None)
        identity_prompt_in_payload = "identity_prompt" in before

        try:
            if identity_prompt_in_payload:
                from tools.media_studio.services.portrait_service import (
                    update_identity_prompt as _update_ip,
                )

                prompt_result = _update_ip(agent_id, identity_prompt_value or "")
                if prompt_result.get("error"):
                    raise RuntimeError(prompt_result["error"])
            if payload:
                update_agent(agent_id, **payload)
        except Exception as exc:
            logger.exception("agent PATCH failed for id=%s", agent_id)
            return (
                jsonify({"ok": False, "error": "update_failed", "detail": str(exc)}),
                500,
            )

        updated_fields = set(payload)
        audit_after = dict(payload)
        if identity_prompt_in_payload:
            updated_fields.add("identity_prompt")
            audit_after["identity_prompt"] = identity_prompt_value

        actor_id = getattr(current_user, "id", None)
        _audit_profile_update(
            agent_id=agent_id,
            user_id=actor_id,
            before=before,
            after=audit_after,
        )

        return (
            jsonify({"ok": True, "updated_fields": sorted(updated_fields)}),
            200,
        )

    @bp.route("/api/agents/<int:agent_id>/generate-portrait", methods=["POST"])
    @admin_required
    def api_agent_generate_portrait(agent_id):
        """Queue a portrait for explicit review in Media Studio."""
        from tools.media_studio.services.portrait_service import generate_canonical

        body = request.get_json(silent=True) or {}
        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"success": False, "error": "Agent not found"}), 404

        from database import get_db_cursor

        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT id, status
                FROM media_generation_queue
                WHERE owner_type = 'agent' AND owner_id = %s
                  AND status IN ('pending', 'dispatched')
                ORDER BY id DESC
                LIMIT 1
                """,
                (agent_id,),
            )
            existing = cur.fetchone()
        if existing:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "A portrait generation is already queued for this agent",
                        "queue_id": existing["id"],
                        "status": existing["status"],
                    }
                ),
                409,
            )

        result = generate_canonical(
            agent_id,
            prompt_override=body.get("prompt"),
            model=body.get("model"),
            model_override=body.get("model_override"),
            identity_mode=body.get("identity_mode", "auto"),
            identity_weight=body.get("identity_weight"),
        )
        if result.get("error") or not result.get("queue_id"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": result.get("error", "Portrait queue was not created"),
                    }
                ),
                500,
            )

        return (
            jsonify(
                {
                    "success": True,
                    "status": result.get("status", "pending"),
                    "message": "Portrait queued for review in Media Studio.",
                    "review_required": True,
                    "auto_approved": False,
                    "queue_id": result["queue_id"],
                    "media_id": None,
                    "active": agent.get("avatar_url"),
                    "current_avatar": agent.get("avatar_url"),
                }
            ),
            202,
        )

    @bp.route("/api/agent/<int:agent_id>/decommission-precheck")
    @admin_required
    def api_agent_decommission_precheck(agent_id):
        from services.agent_lifecycle import decommission_precheck

        try:
            out = decommission_precheck(agent_id)
            return jsonify(
                {
                    "success": True,
                    "warnings": out["warnings"],
                    "agent": {
                        "id": out["agent"]["id"],
                        "name": out["agent"].get("name"),
                        "shift_state": out["agent"].get("shift_state"),
                    },
                }
            )
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/decommission", methods=["POST"])
    @admin_required
    def api_agent_decommission(agent_id):
        from services.agent_lifecycle import decommission_agent

        data = request.get_json(silent=True) or {}
        try:
            out = decommission_agent(agent_id, acknowledge_warnings=bool(data.get("acknowledge_warnings")))
            return (jsonify(out), 200) if out["ok"] else (jsonify(out), 409)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 404
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500


def _validate_patch_payload(agent_id, payload):
    return _profile_helpers.validate_patch_payload(
        agent_id,
        payload,
        departments=DEPARTMENT_FLOOR_MAP,
        get_agent=get_agent,
        is_model_available=is_model_available,
    )


def _audit_profile_update(*, agent_id, user_id, before, after):
    return _profile_helpers.audit_profile_update(
        agent_id=agent_id,
        user_id=user_id,
        before=before,
        after=after,
        serialize=_json.dumps,
        logger=logger,
    )
