"""Family Tree — AI Record Hints routes."""

from flask import jsonify, request
from flask_login import current_user, login_required

from .services.hints_service import accept_hint, dismiss_hint, generate_hints, get_hints


def register_hints_routes(bp, admin_required):
    """Register hint endpoints on the family_tree blueprint."""

    @bp.route("/api/hints")
    @login_required
    def api_hints_list():
        """List all hints for the current user, optionally filtered by person_id."""
        person_id = request.args.get("person_id", type=int)
        hints = get_hints(current_user.id, person_id=person_id)

        # Serialize datetime for JSON
        for h in hints:
            if h.get("created_at"):
                h["created_at"] = h["created_at"].isoformat()

        return jsonify(hints)

    @bp.route("/api/hints/generate", methods=["POST"])
    @login_required
    def api_hints_generate():
        """Trigger hint generation for all persons in the user's tree."""
        stats = generate_hints(current_user.id)
        return jsonify({"ok": True, **stats})

    @bp.route("/api/hints/<int:hint_id>/accept", methods=["POST"])
    @login_required
    def api_hints_accept(hint_id):
        """Accept a hint — marks it accepted and creates a source record."""
        result = accept_hint(current_user.id, hint_id)
        if result is None:
            return jsonify({"error": "Hint not found or already processed"}), 404

        if result.get("created_at"):
            result["created_at"] = result["created_at"].isoformat()

        return jsonify({"ok": True, "hint": result})

    @bp.route("/api/hints/<int:hint_id>/dismiss", methods=["POST"])
    @login_required
    def api_hints_dismiss(hint_id):
        """Dismiss a hint so it no longer appears."""
        updated = dismiss_hint(current_user.id, hint_id)
        if not updated:
            return jsonify({"error": "Hint not found or already processed"}), 404
        return jsonify({"ok": True})
