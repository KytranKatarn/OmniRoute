"""
Department HQ — Agent Identity & Portrait routes

Endpoints:
  GET  /api/agent/<id>/identity                — Full identity data + portraits
  POST /api/agent/<id>/identity                — Update identity fields
  GET  /api/agent/<id>/portraits               — List portraits
  POST /api/agent/<id>/portraits/generate-prompt — Auto-generate portrait prompt
  POST /api/agent/<id>/portraits/add           — Add portrait entry (pending generation)
  POST /api/agent/<id>/portraits/<pid>/set-primary — Set primary portrait
  GET  /api/agent/<id>/gallery                 — Photo gallery
  GET  /api/identity/directors                 — All AI Directors with identity data
  GET  /api/identity/incomplete                — Agents missing identity data
"""

from flask import jsonify, request
from services.agent_service import (
    get_agent,
    get_identity,
    update_identity,
    get_portraits,
    add_portrait,
    set_primary_portrait,
    generate_portrait_prompt,
    get_photo_gallery,
    list_agents,
)


def register_identity_routes(bp, admin_required):
    """Register agent identity and portrait routes on the blueprint."""

    @bp.route("/api/agent/<int:agent_id>/identity")
    @admin_required
    def api_agent_identity(agent_id):
        """Full identity data: agent info + identity fields + portraits."""
        try:
            identity = get_identity(agent_id)
            if not identity:
                return jsonify({"error": "Agent not found"}), 404

            portraits = get_portraits(agent_id)
            gallery = get_photo_gallery(agent_id)

            return jsonify(
                {
                    "identity": {
                        "id": identity["id"],
                        "name": identity["name"],
                        "display_name": identity["display_name"],
                        "department": identity["department"],
                        "floor": identity["floor"],
                        "is_department_ai": identity.get("is_department_ai", False),
                        "bio": identity.get("bio") or "",
                        "gender": identity.get("gender") or "",
                        "ethnicity": identity.get("ethnicity") or "",
                        "age_range": identity.get("age_range") or "",
                        "appearance_notes": identity.get("appearance_notes") or "",
                        "portrait_prompt": identity.get("portrait_prompt") or "",
                        "avatar_url": identity.get("avatar_url") or "",
                    },
                    "portraits": portraits,
                    "gallery": gallery,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/identity", methods=["POST"])
    @admin_required
    def api_update_identity(agent_id):
        """Update agent identity fields."""
        data = request.get_json(silent=True) or {}

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            updated = update_identity(
                agent_id,
                bio=data.get("bio"),
                gender=data.get("gender"),
                ethnicity=data.get("ethnicity"),
                age_range=data.get("age_range"),
                appearance_notes=data.get("appearance_notes"),
                portrait_prompt=data.get("portrait_prompt"),
            )

            return jsonify({"success": True, "updated": updated})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/portraits")
    @admin_required
    def api_agent_portraits(agent_id):
        """List all portraits for an agent."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            portraits = get_portraits(agent_id)
            return jsonify({"agent_id": agent_id, "portraits": portraits})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/portraits/generate-prompt", methods=["POST"])
    @admin_required
    def api_generate_portrait_prompt(agent_id):
        """Auto-generate a portrait prompt from identity data."""
        try:
            prompt, negative = generate_portrait_prompt(agent_id)
            if not prompt:
                return jsonify({"error": "Agent not found or no identity data"}), 404

            return jsonify(
                {
                    "prompt": prompt,
                    "negative_prompt": negative,
                    "agent_id": agent_id,
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/portraits/add", methods=["POST"])
    @admin_required
    def api_add_portrait(agent_id):
        """Add a portrait entry (pending generation)."""
        data = request.get_json(silent=True) or {}
        prompt = (data.get("prompt") or "").strip()

        if not prompt:
            return jsonify({"error": "prompt is required"}), 400

        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            style = data.get("style", "professional")
            negative = data.get("negative_prompt", "")
            portrait_id = add_portrait(agent_id, prompt, style=style, negative_prompt=negative)

            return jsonify(
                {
                    "success": True,
                    "portrait_id": portrait_id,
                    "message": "Portrait queued (pending generation)",
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/portraits/<int:portrait_id>/set-primary", methods=["POST"])
    @admin_required
    def api_set_primary_portrait(agent_id, portrait_id):
        """Set a portrait as the primary."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            set_primary_portrait(agent_id, portrait_id)
            return jsonify({"success": True, "message": "Primary portrait updated"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/agent/<int:agent_id>/gallery")
    @admin_required
    def api_agent_gallery(agent_id):
        """Get agent's photo gallery."""
        try:
            agent = get_agent(agent_id)
            if not agent:
                return jsonify({"error": "Agent not found"}), 404

            gallery = get_photo_gallery(agent_id)
            return jsonify({"agent_id": agent_id, "gallery": gallery})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/identity/directors")
    @admin_required
    def api_identity_directors():
        """All AI Directors with identity data (for batch portrait generation)."""
        try:
            directors = list_agents(is_department_ai=True, limit=50)
            result = []
            for d in directors:
                identity = get_identity(d["id"])
                portraits = get_portraits(d["id"])
                result.append(
                    {
                        "id": d["id"],
                        "name": d["name"],
                        "display_name": d["display_name"],
                        "department": d["department"],
                        "floor": d["floor"],
                        "bio": (identity or {}).get("bio") or "",
                        "gender": (identity or {}).get("gender") or "",
                        "ethnicity": (identity or {}).get("ethnicity") or "",
                        "age_range": (identity or {}).get("age_range") or "",
                        "portrait_count": len(portraits),
                        "has_primary": any(p.get("is_primary") for p in portraits),
                    }
                )
            return jsonify({"directors": result})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/identity/incomplete")
    @admin_required
    def api_identity_incomplete():
        """Agents missing identity data (gender, ethnicity, or bio)."""
        try:
            agents = list_agents(limit=500)
            incomplete = []
            for a in agents:
                identity = get_identity(a["id"])
                if not identity:
                    continue
                missing = []
                if not identity.get("gender"):
                    missing.append("gender")
                if not identity.get("ethnicity"):
                    missing.append("ethnicity")
                if not identity.get("bio"):
                    missing.append("bio")
                if not identity.get("age_range"):
                    missing.append("age_range")
                if missing:
                    incomplete.append(
                        {
                            "id": a["id"],
                            "name": a["name"],
                            "display_name": a["display_name"],
                            "department": a["department"],
                            "missing": missing,
                        }
                    )
            return jsonify({"incomplete": incomplete, "total": len(incomplete)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
