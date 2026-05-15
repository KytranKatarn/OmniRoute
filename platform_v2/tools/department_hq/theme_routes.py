"""DHQ S.I.G.N.A.L. — Content Theme management API routes."""

import logging

from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_theme_routes(bp, admin_required):
    """Register content theme management routes on the DHQ blueprint."""
    if getattr(bp, "_theme_routes_registered", False):
        return
    bp._theme_routes_registered = True

    @bp.route("/api/signal/themes")
    @admin_required
    def api_signal_themes():
        from tools.media_studio.services.theme_service import get_all_themes

        account = request.args.get("account") or None
        return jsonify({"themes": get_all_themes(active_only=False, account=account)})

    @bp.route("/api/signal/themes/<int:theme_id>/scenes")
    @admin_required
    def api_signal_theme_scenes(theme_id):
        from tools.media_studio.services.theme_service import (
            get_scenes_for_theme,
            get_theme,
        )

        theme = get_theme(theme_id)
        if not theme:
            return jsonify({"error": "not found"}), 404
        return jsonify({"theme": theme, "scenes": get_scenes_for_theme(theme_id)})

    @bp.route("/api/signal/themes/<int:theme_id>", methods=["PATCH"])
    @admin_required
    def api_signal_update_theme(theme_id):
        from tools.media_studio.services.theme_service import update_theme

        data = request.get_json() or {}
        updated = update_theme(theme_id, **data)
        if not updated:
            return jsonify({"error": "not found or no valid fields"}), 400
        return jsonify(updated)

    @bp.route("/api/signal/themes/<int:theme_id>/scenes", methods=["POST"])
    @admin_required
    def api_signal_add_scene(theme_id):
        from tools.media_studio.services.theme_service import upsert_scene

        data = request.get_json() or {}
        scene = upsert_scene(theme_id, scene_id=None, **data)
        return jsonify(scene), 201

    @bp.route("/api/signal/themes/<int:theme_id>/scenes/<int:scene_id>", methods=["PATCH"])
    @admin_required
    def api_signal_update_scene(theme_id, scene_id):
        from tools.media_studio.services.theme_service import upsert_scene

        data = request.get_json() or {}
        scene = upsert_scene(theme_id, scene_id=scene_id, **data)
        return jsonify(scene)

    # ── Calendar ──────────────────────────────────────────────────

    @bp.route("/api/signal/calendar")
    @admin_required
    def api_signal_calendar():
        from tools.media_studio.services.calendar_service import get_week_calendar

        return jsonify({"days": get_week_calendar()})

    @bp.route("/api/signal/calendar/slots")
    @admin_required
    def api_signal_calendar_slots():
        from tools.media_studio.services.calendar_service import get_calendar_slots

        return jsonify({"slots": get_calendar_slots()})

    @bp.route("/api/signal/calendar/slots", methods=["POST"])
    @admin_required
    def api_signal_upsert_slot():
        from tools.media_studio.services.calendar_service import upsert_calendar_slot

        data = request.get_json() or {}
        day = data.pop("day_of_week", 0)
        order = data.pop("slot_order", 0)
        slot = upsert_calendar_slot(day_of_week=day, slot_order=order, **data)
        return jsonify(slot), 201

    @bp.route("/api/signal/calendar/slots/<int:slot_id>", methods=["DELETE"])
    @admin_required
    def api_signal_delete_slot(slot_id):
        from tools.media_studio.services.calendar_service import delete_calendar_slot

        ok = delete_calendar_slot(slot_id)
        return jsonify({"deleted": ok})

    @bp.route("/api/signal/calendar/generate-caption", methods=["POST"])
    @admin_required
    def api_signal_generate_caption():
        from tools.media_studio.services.calendar_service import generate_themed_caption

        data = request.get_json() or {}
        agent_id = data.get("agent_id")
        theme_id = data.get("theme_id")
        if not agent_id or not theme_id:
            return jsonify({"error": "agent_id and theme_id required"}), 400
        caption = generate_themed_caption(agent_id, theme_id, data.get("scene_description", ""))
        return jsonify({"caption": caption})

    # ── Agent Voice ────────────────────────────────────────────────

    @bp.route("/api/signal/agent/<int:agent_id>/voice")
    @admin_required
    def api_signal_agent_voice(agent_id):
        from tools.media_studio.services.calendar_service import get_agent_voice

        return jsonify(get_agent_voice(agent_id))

    @bp.route("/api/signal/agent/<int:agent_id>/voice", methods=["PATCH"])
    @admin_required
    def api_signal_update_agent_voice(agent_id):
        from tools.media_studio.services.calendar_service import upsert_agent_voice

        data = request.get_json() or {}
        return jsonify(upsert_agent_voice(agent_id, **data))
