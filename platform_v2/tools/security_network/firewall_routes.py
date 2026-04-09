"""
Firewall & Connections Routes
==============================
REST endpoints for UFW firewall management (status, rules, enable/disable,
allow/deny/delete) and active network connections.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

# Import security service (firewall + connections)
try:
    from .security_service import (
        get_firewall_status,
        get_active_connections,
    )

    SECURITY_SERVICE_AVAILABLE = True
except ImportError:
    SECURITY_SERVICE_AVAILABLE = False


def register_firewall_routes(bp, admin_required_decorator):
    """Register all firewall and connection endpoints."""

    @bp.route("/api/firewall/status")
    @login_required
    @admin_required_decorator
    def api_firewall_status():
        """Get firewall status"""
        if not SECURITY_SERVICE_AVAILABLE:
            return (
                jsonify({"success": False, "error": "Security service not available"}),
                503,
            )

        try:
            status = get_firewall_status()
            return jsonify({"success": True, "firewall": status})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/firewall/rules")
    @login_required
    @admin_required_decorator
    def api_firewall_rules():
        """Get firewall rules via host_command_client."""
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return jsonify({"success": True, "rules": [], "note": "Host command queue not available"})
            result_data = submit_and_wait("firewall_rules", {}, timeout=60, submitted_by="security_network")
            cmd_result = result_data.get("result", {})
            if cmd_result.get("success"):
                return jsonify({"success": True, "rules": cmd_result.get("rules", [])})
            return jsonify({"success": True, "rules": [], "note": cmd_result.get("error", "No rules returned")})
        except Exception as e:
            logger.warning("firewall rules: %s", e)
            return jsonify(
                {"success": True, "rules": [], "note": "Host agent busy — rules will appear shortly after daemon syncs"}
            )

    @bp.route("/api/firewall/enable", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_firewall_enable():
        """Enable firewall via host_command_client."""
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return (
                    jsonify({"success": False, "error": "Host command queue not available"}),
                    503,
                )
            result_data = submit_and_wait("firewall_enable", {}, timeout=60, submitted_by="security_network")
            return jsonify(result_data.get("result", {"success": False}))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/firewall/disable", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_firewall_disable():
        """Disable firewall via host_command_client."""
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return (
                    jsonify({"success": False, "error": "Host command queue not available"}),
                    503,
                )
            result_data = submit_and_wait("firewall_disable", {}, timeout=60, submitted_by="security_network")
            return jsonify(result_data.get("result", {"success": False}))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/firewall/allow", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_firewall_allow():
        """Add firewall allow rule via host_command_client."""
        data = request.get_json(silent=True) or {}
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return (
                    jsonify({"success": False, "error": "Host command queue not available"}),
                    503,
                )
            result_data = submit_and_wait("firewall_allow", data, timeout=60, submitted_by="security_network")
            return jsonify(result_data.get("result", {"success": False}))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/firewall/deny", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_firewall_deny():
        """Add firewall deny rule via host_command_client."""
        data = request.get_json(silent=True) or {}
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return (
                    jsonify({"success": False, "error": "Host command queue not available"}),
                    503,
                )
            result_data = submit_and_wait("firewall_deny", data, timeout=60, submitted_by="security_network")
            return jsonify(result_data.get("result", {"success": False}))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/firewall/delete", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_firewall_delete():
        """Delete firewall rule via host_command_client."""
        data = request.get_json(silent=True) or {}
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return (
                    jsonify({"success": False, "error": "Host command queue not available"}),
                    503,
                )
            result_data = submit_and_wait("firewall_delete", data, timeout=60, submitted_by="security_network")
            return jsonify(result_data.get("result", {"success": False}))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/connections/active")
    @login_required
    @admin_required_decorator
    def api_active_connections():
        """Get active network connections"""
        if not SECURITY_SERVICE_AVAILABLE:
            return (
                jsonify({"success": False, "error": "Security service not available"}),
                503,
            )

        try:
            connections = get_active_connections()
            return jsonify({"success": True, "connections": connections})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
