"""
Starship Command — Health monitoring routes.

Unified health status from Nagios + ARCHIE heartbeats.
"""

import logging

from flask import jsonify

logger = logging.getLogger(__name__)


def register_health_routes(bp, auth_decorator):
    """Register health monitoring routes on the starship blueprint."""

    @bp.route("/api/health-status")
    @auth_decorator
    def api_health_status():
        """Unified health status for all monitored hosts."""
        try:
            from services.monitoring_service import get_unified_health

            health = get_unified_health()

            ok_count = 0
            warn_count = 0
            crit_count = 0

            hosts = []
            for node_id, data in health.items():
                if data["summary"] == "ok":
                    ok_count += 1
                elif data["summary"] == "warning":
                    warn_count += 1
                elif data["summary"] == "critical":
                    crit_count += 1

                hosts.append(
                    {
                        "node_id": node_id,
                        "summary": data["summary"],
                        "host_status": (data["host"]["status"] if data["host"] else "unknown"),
                        "services": [
                            {
                                "name": s["check_name"],
                                "status": s["status"],
                                "output": s["output"],
                                "last_check": s["last_check"],
                            }
                            for s in data["services"]
                        ],
                    }
                )

            return jsonify(
                {
                    "success": True,
                    "summary": {
                        "total": len(hosts),
                        "ok": ok_count,
                        "warning": warn_count,
                        "critical": crit_count,
                    },
                    "hosts": hosts,
                }
            )
        except Exception as e:
            logger.error("Health status error: %s", e)
            return (
                jsonify({"success": False, "error": "Internal server error"}),
                500,
            )

    @bp.route("/api/health-status/<node_id>")
    @auth_decorator
    def api_host_health(node_id):
        """Health checks for a specific host."""
        try:
            from services.monitoring_service import get_host_checks

            data = get_host_checks(node_id)
            return jsonify(
                {
                    "success": True,
                    "node_id": node_id,
                    "summary": data["summary"],
                    "host": data["host"],
                    "services": data["services"],
                }
            )
        except Exception as e:
            logger.error("Host health error: %s", e)
            return (
                jsonify({"success": False, "error": "Internal server error"}),
                500,
            )
