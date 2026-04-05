"""
Defense API Routes
==================
Fail2ban intrusion prevention and DDNS management endpoints.
"""

import logging
import re

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

JAIL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def register_defense_routes(bp, admin_required_decorator):
    """Register all defense (fail2ban + DDNS) endpoints on the security_network blueprint."""

    @bp.route("/api/fail2ban/status")
    @login_required
    @admin_required_decorator
    def fail2ban_status():
        """Get overall Fail2ban service status."""
        try:
            from .fail2ban_service import Fail2banService

            status = Fail2banService().get_status()
            return jsonify({"success": True, "status": status})
        except Exception as exc:
            logger.error("fail2ban_status error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fail2ban/jails")
    @login_required
    @admin_required_decorator
    def fail2ban_jails():
        """Get status of all Fail2ban jails."""
        try:
            from .fail2ban_service import Fail2banService

            jails = Fail2banService().get_all_jail_statuses()
            return jsonify({"success": True, "jails": jails})
        except Exception as exc:
            logger.error("fail2ban_jails error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fail2ban/jail/<jail_name>")
    @login_required
    @admin_required_decorator
    def fail2ban_jail_detail(jail_name):
        """Get status of a specific Fail2ban jail."""
        if not JAIL_NAME_PATTERN.match(jail_name):
            return jsonify({"success": False, "error": "Invalid jail name"}), 400
        try:
            from .fail2ban_service import Fail2banService

            jail = Fail2banService().get_jail_status(jail_name)
            return jsonify({"success": True, "jail": jail})
        except Exception as exc:
            logger.error("fail2ban_jail_detail error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fail2ban/ban", methods=["POST"])
    @login_required
    @admin_required_decorator
    def fail2ban_ban():
        """Manually ban an IP in a Fail2ban jail."""
        data = request.get_json(silent=True) or {}
        jail = data.get("jail")
        ip = data.get("ip")
        if not jail or not ip:
            return jsonify({"success": False, "error": "jail and ip are required"}), 400
        if not JAIL_NAME_PATTERN.match(jail):
            return jsonify({"success": False, "error": "Invalid jail name"}), 400
        try:
            from .fail2ban_service import Fail2banService

            result = Fail2banService().ban_ip(jail, ip)
            return jsonify({"success": True, "result": result})
        except Exception as exc:
            logger.error("fail2ban_ban error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/fail2ban/unban", methods=["POST"])
    @login_required
    @admin_required_decorator
    def fail2ban_unban():
        """Manually unban an IP from a Fail2ban jail."""
        data = request.get_json(silent=True) or {}
        jail = data.get("jail")
        ip = data.get("ip")
        if not jail or not ip:
            return jsonify({"success": False, "error": "jail and ip are required"}), 400
        if not JAIL_NAME_PATTERN.match(jail):
            return jsonify({"success": False, "error": "Invalid jail name"}), 400
        try:
            from .fail2ban_service import Fail2banService

            result = Fail2banService().unban_ip(jail, ip)
            return jsonify({"success": True, "result": result})
        except Exception as exc:
            logger.error("fail2ban_unban error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/ddns/status")
    @login_required
    @admin_required_decorator
    def ddns_status():
        """Get DDNS service status and current public IP."""
        try:
            from .ddns_service import DdnsService

            svc = DdnsService()
            status = svc.get_status()
            live_ip = svc.get_live_public_ip()
            return jsonify({"success": True, "status": status, "live_ip": live_ip})
        except Exception as exc:
            logger.error("ddns_status error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/ddns/history")
    @login_required
    @admin_required_decorator
    def ddns_history():
        """Get DDNS IP change history."""
        limit = request.args.get("limit", 50, type=int)
        try:
            from .ddns_service import DdnsService

            history = DdnsService().get_ip_history(limit)
            return jsonify({"success": True, "history": history})
        except Exception as exc:
            logger.error("ddns_history error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/ddns/update", methods=["POST"])
    @login_required
    @admin_required_decorator
    def ddns_trigger_update():
        """Trigger a manual DDNS update."""
        try:
            from .ddns_service import DdnsService

            result = DdnsService().trigger_update()
            return jsonify({"success": True, "result": result})
        except Exception as exc:
            logger.error("ddns_trigger_update error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
