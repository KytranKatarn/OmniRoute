"""
Device Management API Routes
=============================
Network device user mappings and per-device bandwidth consumption endpoints.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_device_routes(bp, admin_required_decorator):
    """Register all device management endpoints on the security_network blueprint."""

    @bp.route("/api/devices/users")
    @login_required
    @admin_required_decorator
    def devices_users_list():
        """List all device-to-user mappings joined with network devices."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        ndu.id,
                        ndu.mac_address,
                        ndu.user_name,
                        ndu.device_label,
                        ndu.device_type,
                        ndu.created_at,
                        ndu.updated_at,
                        nd.ip_address,
                        nd.hostname,
                        nd.manufacturer
                    FROM network_device_users ndu
                    LEFT JOIN network_devices nd ON nd.mac_address = ndu.mac_address
                    ORDER BY ndu.user_name, ndu.device_label
                    """
                )
                rows = cur.fetchall()
                users = [
                    {
                        "id": row[0],
                        "mac_address": row[1],
                        "user_name": row[2],
                        "device_label": row[3],
                        "device_type": row[4],
                        "created_at": row[5].isoformat() if row[5] else None,
                        "updated_at": row[6].isoformat() if row[6] else None,
                        "ip_address": row[7],
                        "hostname": row[8],
                        "vendor": row[9],
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "users": users})
        except Exception as exc:
            logger.error("devices_users_list error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/devices/users", methods=["POST"])
    @login_required
    @admin_required_decorator
    def devices_users_upsert():
        """Create or update a device-to-user mapping."""
        data = request.get_json(silent=True) or {}
        mac_address = data.get("mac_address", "").strip().upper()
        user_name = data.get("user_name", "").strip()
        device_label = data.get("device_label", "").strip()
        device_type = data.get("device_type", "").strip()

        if not mac_address or not user_name:
            return jsonify({"success": False, "error": "mac_address and user_name are required"}), 400

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO network_device_users (mac_address, user_name, device_label, device_type, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (mac_address)
                    DO UPDATE SET
                        user_name = EXCLUDED.user_name,
                        device_label = EXCLUDED.device_label,
                        device_type = EXCLUDED.device_type,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (mac_address, user_name, device_label, device_type),
                )
                row = cur.fetchone()
                record_id = row[0] if row else None
            return jsonify({"success": True, "id": record_id})
        except Exception as exc:
            logger.error("devices_users_upsert error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/devices/users/<int:mapping_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def devices_users_delete(mapping_id):
        """Remove a device-to-user mapping."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "DELETE FROM network_device_users WHERE id = %s RETURNING id",
                    (mapping_id,),
                )
                deleted = cur.fetchone()
            if not deleted:
                return jsonify({"success": False, "error": "Mapping not found"}), 404
            return jsonify({"success": True, "deleted_id": mapping_id})
        except Exception as exc:
            logger.error("devices_users_delete error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/devices/consumption")
    @login_required
    @admin_required_decorator
    def devices_consumption():
        """Get per-device bandwidth consumption joined with user mapping."""
        hours = request.args.get("hours", 24, type=int)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        nts.device_mac,
                        nts.device_ip,
                        ndu.user_name,
                        ndu.device_label,
                        ndu.device_type,
                        SUM(nts.bytes_sent) AS bytes_sent,
                        SUM(nts.bytes_recv) AS bytes_recv,
                        SUM(nts.bytes_sent + nts.bytes_recv) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                    WHERE nts.recorded_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY nts.device_mac, nts.device_ip, ndu.user_name, ndu.device_label, ndu.device_type
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()
                consumption = [
                    {
                        "device_mac": row[0],
                        "device_ip": row[1],
                        "user_name": row[2],
                        "device_label": row[3],
                        "device_type": row[4],
                        "bytes_sent": row[5],
                        "bytes_recv": row[6],
                        "bytes_total": row[7],
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "consumption": consumption, "hours": hours})
        except Exception as exc:
            logger.error("devices_consumption error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/devices/consumption/by-user")
    @login_required
    @admin_required_decorator
    def devices_consumption_by_user():
        """Get bandwidth consumption grouped by user name."""
        hours = request.args.get("hours", 24, type=int)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        COALESCE(ndu.user_name, 'Unknown') AS user_name,
                        COUNT(DISTINCT nts.device_mac) AS device_count,
                        SUM(nts.bytes_sent) AS bytes_sent,
                        SUM(nts.bytes_recv) AS bytes_recv,
                        SUM(nts.bytes_sent + nts.bytes_recv) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = nts.device_mac
                    WHERE nts.recorded_at >= NOW() - INTERVAL '%s hours'
                    GROUP BY COALESCE(ndu.user_name, 'Unknown')
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()
                by_user = [
                    {
                        "user_name": row[0],
                        "device_count": row[1],
                        "bytes_sent": row[2],
                        "bytes_recv": row[3],
                        "bytes_total": row[4],
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "by_user": by_user, "hours": hours})
        except Exception as exc:
            logger.error("devices_consumption_by_user error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
