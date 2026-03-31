"""
Traffic Monitoring API Routes
==============================
Network traffic bandwidth, hosts, flows, and protocol analysis endpoints.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_traffic_routes(bp, admin_required_decorator):
    """Register all traffic monitoring endpoints on the security_network blueprint."""

    @bp.route("/api/traffic/bandwidth")
    @login_required
    @admin_required_decorator
    def traffic_bandwidth():
        """Get interface bandwidth statistics from Ntopng."""
        ifid = request.args.get("ifid", type=int)
        try:
            from .ntopng_service import NtopngService

            stats = NtopngService().get_interface_stats(ifid)
            return jsonify({"success": True, "bandwidth": stats})
        except Exception as exc:
            logger.error("traffic_bandwidth error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/traffic/hosts")
    @login_required
    @admin_required_decorator
    def traffic_hosts():
        """Get active hosts from Ntopng."""
        ifid = request.args.get("ifid", type=int)
        try:
            from .ntopng_service import NtopngService

            hosts = NtopngService().get_hosts(ifid)
            return jsonify({"success": True, "hosts": hosts})
        except Exception as exc:
            logger.error("traffic_hosts error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/traffic/flows")
    @login_required
    @admin_required_decorator
    def traffic_flows():
        """Get active network flows from Ntopng."""
        ifid = request.args.get("ifid", type=int)
        try:
            from .ntopng_service import NtopngService

            flows = NtopngService().get_flows(ifid)
            return jsonify({"success": True, "flows": flows})
        except Exception as exc:
            logger.error("traffic_flows error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/traffic/protocols")
    @login_required
    @admin_required_decorator
    def traffic_protocols():
        """Get Layer 7 protocol breakdown from Ntopng."""
        ifid = request.args.get("ifid", type=int)
        try:
            from .ntopng_service import NtopngService

            protocols = NtopngService().get_l7_stats(ifid)
            return jsonify({"success": True, "protocols": protocols})
        except Exception as exc:
            logger.error("traffic_protocols error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/traffic/history")
    @login_required
    @admin_required_decorator
    def traffic_history():
        """Get historical traffic stats grouped by device and hour."""
        hours = request.args.get("hours", 24, type=int)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        device_mac,
                        device_ip,
                        DATE_TRUNC('hour', recorded_at) AS hour,
                        SUM(bytes_sent) AS bytes_sent,
                        SUM(bytes_recv) AS bytes_recv,
                        SUM(bytes_sent + bytes_recv) AS bytes_total
                    FROM network_traffic_stats
                    WHERE recorded_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY device_mac, device_ip, DATE_TRUNC('hour', recorded_at)
                    ORDER BY hour DESC, bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()
                history = [
                    {
                        "device_mac": row[0],
                        "device_ip": row[1],
                        "hour": row[2].isoformat() if row[2] else None,
                        "bytes_sent": row[3],
                        "bytes_recv": row[4],
                        "bytes_total": row[5],
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "history": history, "hours": hours})
        except Exception as exc:
            logger.error("traffic_history error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
