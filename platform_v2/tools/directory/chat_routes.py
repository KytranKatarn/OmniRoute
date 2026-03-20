"""Directory chat routes — auth-required endpoints for status and messaging."""

from flask import jsonify, request, session
from functools import wraps


def login_required_api(f):
    """API auth decorator — returns 401 JSON instead of redirect."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated


def register_chat_routes(bp, admin_required):
    """Register auth-gated directory routes."""

    @bp.route("/api/directory/status")
    @login_required_api
    def get_agent_status():
        """Get live roster status for all agents."""
        try:
            from ai_bridge.bridge_dispatcher import get_crew_manifest

            manifest = get_crew_manifest()
        except Exception:
            manifest = []

        status_map = {}
        for member in manifest:
            agent_id = member.get("agent_id") or member.get("id")
            if agent_id:
                model_loaded = member.get("model_loaded", False)
                shift_state = member.get("shift_state", "off_duty")
                is_online = shift_state == "active" and model_loaded
                status_map[str(agent_id)] = {
                    "is_online": is_online,
                    "status": "Online" if is_online else "Off Duty",
                    "chat_available": is_online,
                    "shift_state": shift_state,
                }

        return jsonify({"status": status_map})
