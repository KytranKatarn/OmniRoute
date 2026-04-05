"""
Agent Automation Routes
========================
REST endpoints for security agent automation — configuration, suggestion
management (approve/dismiss), action history, and pause/resume controls.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

# Import Agent Automation service
try:
    from .agent_automation import AgentAutomationService

    agent_automation_service = AgentAutomationService()
    AGENT_AUTOMATION_AVAILABLE = True
except ImportError:
    agent_automation_service = None
    AGENT_AUTOMATION_AVAILABLE = False


def register_agent_automation_routes(bp, admin_required_decorator):
    """Register all agent automation endpoints."""

    @bp.route("/api/agent/config")
    @login_required
    @admin_required_decorator
    def api_agent_config_get():
        """Get agent automation configuration"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        try:
            config = agent_automation_service.get_config()
            return jsonify({"success": True, "config": config})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/config", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def api_agent_config_update():
        """Update agent automation configuration"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        data = request.get_json() or {}

        try:
            config = agent_automation_service.get_config()

            # Update mode if provided
            if "mode" in data:
                config["mode"] = data["mode"]

            # Update categories if provided
            if "categories" in data:
                for cat_name, cat_data in data["categories"].items():
                    if cat_name in config.get("categories", {}):
                        if "auto_enabled" in cat_data:
                            config["categories"][cat_name]["auto_enabled"] = cat_data["auto_enabled"]

            success = agent_automation_service.save_config(config)
            if success:
                return jsonify({"success": True, "config": config})
            return jsonify({"success": False, "error": "Failed to save configuration"}), 500
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/suggestions")
    @login_required
    @admin_required_decorator
    def api_agent_suggestions():
        """Get pending agent suggestions"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        limit = request.args.get("limit", 50, type=int)
        category = request.args.get("category")

        try:
            suggestions = agent_automation_service.get_pending_suggestions(category, limit)
            return jsonify({"success": True, "suggestions": suggestions})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/suggestions/<int:suggestion_id>/approve", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_agent_approve_suggestion(suggestion_id):
        """Approve an agent suggestion"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        try:
            success = agent_automation_service.approve_suggestion(suggestion_id)
            if success:
                return jsonify({"success": True, "message": f"Suggestion {suggestion_id} approved"})
            return (
                jsonify({"success": False, "error": "Suggestion not found or already processed"}),
                404,
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/suggestions/<int:suggestion_id>/dismiss", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_agent_dismiss_suggestion(suggestion_id):
        """Dismiss an agent suggestion"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        data = request.get_json() or {}
        reason = data.get("reason", "Dismissed by admin")  # noqa: F841

        try:
            success = agent_automation_service.dismiss_suggestion(suggestion_id)
            if success:
                return jsonify({"success": True, "message": f"Suggestion {suggestion_id} dismissed"})
            return (
                jsonify({"success": False, "error": "Suggestion not found or already processed"}),
                404,
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/actions")
    @login_required
    @admin_required_decorator
    def api_agent_action_history():
        """Get agent action history"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        limit = request.args.get("limit", 100, type=int)

        try:
            actions = agent_automation_service.get_action_history(limit)
            return jsonify({"success": True, "actions": actions})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/pause", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_agent_pause():
        """Pause agent automation"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        try:
            success = agent_automation_service.set_paused(True)
            if success:
                return jsonify({"success": True, "message": "Agent automation paused"})
            return jsonify({"success": False, "error": "Failed to pause automation"}), 500
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/agent/resume", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_agent_resume():
        """Resume agent automation"""
        if not AGENT_AUTOMATION_AVAILABLE or not agent_automation_service:
            return (
                jsonify({"success": False, "error": "Agent automation service not available"}),
                503,
            )

        try:
            success = agent_automation_service.set_paused(False)
            if success:
                return jsonify({"success": True, "message": "Agent automation resumed"})
            return jsonify({"success": False, "error": "Failed to resume automation"}), 500
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
