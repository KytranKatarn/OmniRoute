"""DHQ S.I.G.N.A.L. — Content Theme management API routes."""

import logging

from flask import jsonify, request

logger = logging.getLogger(__name__)


def register_theme_routes(bp, admin_required):
    """Register content theme management routes on the DHQ blueprint."""

    @bp.route("/api/signal/themes")
    @admin_required
    def api_signal_themes():
        from platform_v2.tools.media_studio.services.theme_service import get_all_themes

        return jsonify({"themes": get_all_themes(active_only=False)})

    @bp.route("/api/signal/themes/<int:theme_id>/scenes")
    @admin_required
    def api_signal_theme_scenes(theme_id):
        from platform_v2.tools.media_studio.services.theme_service import (
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
        from platform_v2.tools.media_studio.services.theme_service import update_theme

        data = request.get_json() or {}
        updated = update_theme(theme_id, **data)
        if not updated:
            return jsonify({"error": "not found or no valid fields"}), 400
        return jsonify(updated)

    @bp.route("/api/signal/themes/<int:theme_id>/scenes", methods=["POST"])
    @admin_required
    def api_signal_add_scene(theme_id):
        from platform_v2.tools.media_studio.services.theme_service import upsert_scene

        data = request.get_json() or {}
        scene = upsert_scene(theme_id, scene_id=None, **data)
        return jsonify(scene), 201

    @bp.route("/api/signal/themes/<int:theme_id>/scenes/<int:scene_id>", methods=["PATCH"])
    @admin_required
    def api_signal_update_scene(theme_id, scene_id):
        from platform_v2.tools.media_studio.services.theme_service import upsert_scene

        data = request.get_json() or {}
        scene = upsert_scene(theme_id, scene_id=scene_id, **data)
        return jsonify(scene)
