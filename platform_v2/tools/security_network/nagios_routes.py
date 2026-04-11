"""
Nagios Monitoring Routes
========================
REST endpoints for Nagios host/service status, problems, and health.
"""

import logging

from flask import jsonify
from flask_login import login_required

logger = logging.getLogger(__name__)

try:
    from .nagios_service import NagiosService

    nagios = NagiosService()
    NAGIOS_AVAILABLE = True
except ImportError:
    nagios = None
    NAGIOS_AVAILABLE = False


def register_nagios_routes(bp, admin_required_decorator):
    """Register all Nagios monitoring endpoints."""

    @bp.route("/api/nagios/status")
    @login_required
    @admin_required_decorator
    def nagios_status():
        """Get full Nagios dashboard: host/service counts + problems"""
        if not NAGIOS_AVAILABLE or not nagios:
            return jsonify({"success": False, "error": "Nagios not available"}), 503

        try:
            healthy = nagios.is_healthy()
            host_count = nagios.get_host_count()
            service_count = nagios.get_service_count()
            problems = nagios.get_problems()

            # Count problems
            problem_hosts = len(problems.get("hosts", {}))
            problem_services = sum(len(svcs) for svcs in problems.get("services", {}).values())

            return jsonify(
                {
                    "success": True,
                    "healthy": healthy,
                    "hosts": host_count,
                    "services": service_count,
                    "problem_count": problem_hosts + problem_services,
                    "problem_hosts": problem_hosts,
                    "problem_services": problem_services,
                }
            )
        except Exception as e:
            logger.exception("Nagios status error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nagios/hosts")
    @login_required
    @admin_required_decorator
    def nagios_hosts():
        """Get detailed host status"""
        if not NAGIOS_AVAILABLE or not nagios:
            return jsonify({"success": False, "error": "Nagios not available"}), 503

        try:
            hosts = nagios.get_host_status()
            host_list = []
            for name, info in hosts.items():
                host_list.append(
                    {
                        "name": name,
                        "status": nagios._status_text(info.get("status", 0), is_host=True),
                        "status_code": info.get("status", 0),
                        "plugin_output": info.get("plugin_output", ""),
                        "last_check": info.get("last_check", 0),
                        "last_state_change": info.get("last_state_change", 0),
                        "current_attempt": info.get("current_attempt", 0),
                        "max_attempts": info.get("max_attempts", 0),
                        "performance_data": info.get("performance_data", ""),
                    }
                )
            return jsonify({"success": True, "hosts": host_list})
        except Exception as e:
            logger.exception("Nagios hosts error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nagios/services")
    @login_required
    @admin_required_decorator
    def nagios_services():
        """Get detailed service status across all hosts"""
        if not NAGIOS_AVAILABLE or not nagios:
            return jsonify({"success": False, "error": "Nagios not available"}), 503

        try:
            services = nagios.get_service_status()
            service_list = []
            for host, svcs in services.items():
                for svc_name, svc_info in svcs.items():
                    service_list.append(
                        {
                            "host": host,
                            "service": svc_name,
                            "status": nagios._status_text(svc_info.get("status", 0), is_host=False),
                            "status_code": svc_info.get("status", 0),
                            "plugin_output": svc_info.get("plugin_output", ""),
                            "last_check": svc_info.get("last_check", 0),
                            "last_state_change": svc_info.get("last_state_change", 0),
                            "current_attempt": svc_info.get("current_attempt", 0),
                            "max_attempts": svc_info.get("max_attempts", 0),
                            "performance_data": svc_info.get("performance_data", ""),
                        }
                    )
            return jsonify({"success": True, "services": service_list})
        except Exception as e:
            logger.exception("Nagios services error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nagios/problems")
    @login_required
    @admin_required_decorator
    def nagios_problems():
        """Get current problems (non-OK hosts and services)"""
        if not NAGIOS_AVAILABLE or not nagios:
            return jsonify({"success": False, "error": "Nagios not available"}), 503

        try:
            problems = nagios.get_problems()
            result = {"hosts": [], "services": []}

            for name, info in problems.get("hosts", {}).items():
                result["hosts"].append(
                    {
                        "name": name,
                        "status": nagios._status_text(info.get("status", 0), is_host=True),
                        "plugin_output": info.get("plugin_output", ""),
                        "last_check": info.get("last_check", 0),
                    }
                )

            for host, svcs in problems.get("services", {}).items():
                for svc_name, svc_info in svcs.items():
                    result["services"].append(
                        {
                            "host": host,
                            "service": svc_name,
                            "status": nagios._status_text(svc_info.get("status", 0), is_host=False),
                            "plugin_output": svc_info.get("plugin_output", ""),
                            "last_check": svc_info.get("last_check", 0),
                        }
                    )

            return jsonify({"success": True, "problems": result})
        except Exception as e:
            logger.exception("Nagios problems error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
