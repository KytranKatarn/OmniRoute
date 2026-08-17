"""
Device Management API Routes
=============================
Network device user mappings and per-device bandwidth consumption endpoints.
"""

import logging
import re

from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

MAC_PATTERN = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$")


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
                users = []
                for row in rows:
                    r = dict(row)
                    users.append(
                        {
                            "id": r.get("id"),
                            "mac_address": r.get("mac_address"),
                            "user_name": r.get("user_name"),
                            "device_label": r.get("device_label"),
                            "device_type": r.get("device_type"),
                            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                            "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
                            "ip_address": r.get("ip_address"),
                            "hostname": r.get("hostname"),
                            "vendor": r.get("manufacturer"),
                        }
                    )
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
        # Accept both the backend keys and the keys the UI form actually sends
        # (mac / username / device_name) — the mismatch 400'd every submit.
        mac_address = (data.get("mac_address") or data.get("mac") or "").strip().upper()
        user_name = (data.get("user_name") or data.get("username") or "").strip()
        device_label = (data.get("device_label") or data.get("device_name") or "").strip()
        device_type = data.get("device_type", "").strip()

        if not mac_address or not user_name:
            return jsonify({"success": False, "error": "mac_address and user_name are required"}), 400

        if not MAC_PATTERN.match(mac_address):
            return jsonify({"success": False, "error": "Invalid MAC address format"}), 400

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
                record_id = row["id"] if row else None
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
                        nts.device_ip,
                        nts.device_mac,
                        COALESCE(nd.owner, nd.friendly_name, nd.hostname) AS user_name,
                        nd.friendly_name AS device_label,
                        nd.device_type,
                        MAX(nts.bytes_out) AS bytes_sent,
                        MAX(nts.bytes_in) AS bytes_recv,
                        MAX(nts.bytes_in + nts.bytes_out) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_devices nd ON nd.ip_address = nts.device_ip::inet
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                    GROUP BY nts.device_ip, nts.device_mac, nd.owner, nd.friendly_name, nd.hostname, nd.device_type
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()
                consumption = [
                    {
                        "device_ip": row["device_ip"],
                        "device_mac": row["device_mac"],
                        "user_name": row["user_name"],
                        "device_label": row["device_label"],
                        "device_type": row["device_type"],
                        "bytes_sent": row["bytes_sent"],
                        "bytes_recv": row["bytes_recv"],
                        "bytes_total": row["bytes_total"],
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
                        COALESCE(nd.owner, nd.friendly_name, nd.hostname, 'Unknown') AS user_name,
                        COUNT(DISTINCT nts.device_ip) AS device_count,
                        SUM(nts.bytes_out) AS bytes_sent,
                        SUM(nts.bytes_in) AS bytes_recv,
                        SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_devices nd ON nd.ip_address = nts.device_ip::inet
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                    GROUP BY COALESCE(nd.owner, nd.friendly_name, nd.hostname, 'Unknown')
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()
                by_user = [
                    {
                        "user_name": row["user_name"],
                        "device_count": row["device_count"],
                        "bytes_sent": row["bytes_sent"],
                        "bytes_recv": row["bytes_recv"],
                        "bytes_total": row["bytes_total"],
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "by_user": by_user, "hours": hours})
        except Exception as exc:
            logger.error("devices_consumption_by_user error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ---------------------------------------------------------------------------
    # Device list with bandwidth (for Devices tab table)
    # ---------------------------------------------------------------------------

    @bp.route("/api/devices/list")
    @login_required
    @admin_required_decorator
    def devices_list_with_bandwidth():
        """Return all local devices with recent bandwidth and unique domain counts."""
        hours = request.args.get("hours", 24, type=int)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        nts.device_ip,
                        nts.device_mac,
                        COALESCE(nd.owner, nd.friendly_name, nd.hostname) AS user_name,
                        nd.friendly_name AS device_label,
                        nd.device_type,
                        SUM(nts.bytes_in)  AS total_in,
                        SUM(nts.bytes_out) AS total_out,
                        COUNT(DISTINCT ddh.domain) AS unique_domains
                    FROM network_traffic_stats nts
                    LEFT JOIN network_devices nd
                        ON nd.ip_address = nts.device_ip::inet
                    LEFT JOIN device_dns_history ddh
                        ON ddh.device_ip = nts.device_ip
                        AND ddh.hour_bucket >= NOW() - INTERVAL '1 hour' * %s
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '1 hour' * %s
                    GROUP BY
                        nts.device_ip, nts.device_mac,
                        nd.owner, nd.friendly_name, nd.hostname, nd.device_type
                    ORDER BY (SUM(nts.bytes_in) + SUM(nts.bytes_out)) DESC
                    """,
                    (hours, hours),
                )
                rows = cur.fetchall()
                devices = [
                    {
                        "device_ip": row["device_ip"],
                        "device_mac": row["device_mac"],
                        "user_name": row["user_name"],
                        "device_label": row["device_label"],
                        "device_type": row["device_type"],
                        "total_in": row["total_in"] or 0,
                        "total_out": row["total_out"] or 0,
                        "total": (row["total_in"] or 0) + (row["total_out"] or 0),
                        "unique_domains": row["unique_domains"] or 0,
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "devices": devices, "hours": hours})
        except Exception as exc:
            logger.error("devices_list_with_bandwidth error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ---------------------------------------------------------------------------
    # Per-device detail endpoint
    # ---------------------------------------------------------------------------

    IP_PATTERN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

    @bp.route("/api/devices/presence/<device_ip>")
    @login_required
    @admin_required_decorator
    def device_presence_timeline(device_ip):
        """Get online/offline timeline for a device."""
        if not IP_PATTERN.match(device_ip):
            return jsonify({"success": False, "error": "Invalid IP address"}), 400

        days = request.args.get("days", 7, type=int)
        days = max(1, min(days, 90))  # clamp to 1-90

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT event_type, detected_at
                    FROM device_presence_log
                    WHERE device_ip = %s AND detected_at >= NOW() - INTERVAL '1 day' * %s
                    ORDER BY detected_at DESC
                    LIMIT 100
                    """,
                    (device_ip, days),
                )
                rows = cur.fetchall()
                events = [
                    {
                        "type": row["event_type"],
                        "time": row["detected_at"].isoformat(),
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "events": events, "device_ip": device_ip, "days": days})
        except Exception as exc:
            logger.error("device_presence_timeline error for %s: %s", device_ip, exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/devices/detail/<device_ip>")
    @login_required
    @admin_required_decorator
    def device_detail(device_ip):
        """Get comprehensive detail for a single device: info, bandwidth, top domains, timeline."""
        if not IP_PATTERN.match(device_ip):
            return jsonify({"success": False, "error": "Invalid IP address"}), 400

        try:
            with get_db_cursor() as (conn, cur):
                # --- Device info ---
                cur.execute(
                    """
                    SELECT
                        nd.mac_address,
                        COALESCE(nd.owner, nd.friendly_name, nd.hostname) AS user_name,
                        nd.friendly_name AS device_label,
                        nd.device_type
                    FROM network_devices nd
                    WHERE nd.ip_address = %s::inet
                    LIMIT 1
                    """,
                    (device_ip,),
                )
                info_row = cur.fetchone()
                device_info = {
                    "ip": device_ip,
                    "mac": info_row["mac_address"] if info_row else None,
                    "user_name": info_row["user_name"] if info_row else None,
                    "device_label": info_row["device_label"] if info_row else None,
                    "device_type": info_row["device_type"] if info_row else None,
                }

                # --- Bandwidth summary (last 24 h) ---
                cur.execute(
                    """
                    SELECT SUM(bytes_in) AS total_in, SUM(bytes_out) AS total_out
                    FROM network_traffic_stats
                    WHERE device_ip = %s
                      AND hour_bucket >= NOW() - INTERVAL '24 hours'
                    """,
                    (device_ip,),
                )
                bw_row = cur.fetchone()
                total_in = int(bw_row["total_in"] or 0) if bw_row else 0
                total_out = int(bw_row["total_out"] or 0) if bw_row else 0
                bandwidth = {
                    "total_in": total_in,
                    "total_out": total_out,
                    "total": total_in + total_out,
                    "hours": 24,
                }

                # --- Top domains (last 24 h) ---
                cur.execute(
                    """
                    SELECT domain, SUM(query_count) AS queries, bool_or(blocked) AS blocked
                    FROM device_dns_history
                    WHERE device_ip = %s
                      AND hour_bucket >= NOW() - INTERVAL '24 hours'
                    GROUP BY domain
                    ORDER BY queries DESC
                    LIMIT 20
                    """,
                    (device_ip,),
                )
                domain_rows = cur.fetchall()
                top_domains = [
                    {
                        "domain": r["domain"],
                        "queries": int(r["queries"] or 0),
                        "blocked": bool(r["blocked"]),
                    }
                    for r in domain_rows
                ]

                # --- Hourly bandwidth timeline (last 24 h) ---
                cur.execute(
                    """
                    SELECT hour_bucket, bytes_in, bytes_out
                    FROM network_traffic_stats
                    WHERE device_ip = %s
                      AND hour_bucket >= NOW() - INTERVAL '24 hours'
                    ORDER BY hour_bucket
                    """,
                    (device_ip,),
                )
                timeline_rows = cur.fetchall()
                timeline = [
                    {
                        "hour": r["hour_bucket"].isoformat() if r["hour_bucket"] else None,
                        "bytes_in": int(r["bytes_in"] or 0),
                        "bytes_out": int(r["bytes_out"] or 0),
                    }
                    for r in timeline_rows
                ]

            return jsonify(
                {
                    "success": True,
                    "device": device_info,
                    "bandwidth": bandwidth,
                    "top_domains": top_domains,
                    "timeline": timeline,
                }
            )
        except Exception as exc:
            logger.error("device_detail error for %s: %s", device_ip, exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ---------------------------------------------------------------------------
    # Bandwidth history (for Chart.js graphs)
    # ---------------------------------------------------------------------------

    @bp.route("/api/devices/bandwidth-history/<device_ip>")
    @login_required
    @admin_required_decorator
    def device_bandwidth_history(device_ip):
        """Get hourly bandwidth history for a device over a configurable period."""
        if not IP_PATTERN.match(device_ip):
            return jsonify({"success": False, "error": "Invalid IP address"}), 400

        period = request.args.get("period", "24h")
        interval_map = {"24h": "24 hours", "7d": "7 days", "30d": "30 days"}
        interval = interval_map.get(period, "24 hours")

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT hour_bucket, bytes_in, bytes_out "
                    "FROM network_traffic_stats "
                    "WHERE device_ip = %s "
                    "AND hour_bucket >= NOW() - %s::interval "
                    "ORDER BY hour_bucket",
                    (device_ip, interval),
                )
                rows = cur.fetchall()
                history = [
                    {
                        "hour": row["hour_bucket"].isoformat(),
                        "bytes_in": int(row["bytes_in"] or 0),
                        "bytes_out": int(row["bytes_out"] or 0),
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "history": history, "period": period, "device_ip": device_ip})
        except Exception as exc:
            logger.error("device_bandwidth_history error for %s: %s", device_ip, exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/devices/bandwidth-history/by-user")
    @login_required
    @admin_required_decorator
    def bandwidth_history_by_user():
        """Get bandwidth history grouped by user for Chart.js graphs."""
        period = request.args.get("period", "24h")
        interval_map = {"24h": "24 hours", "7d": "7 days", "30d": "30 days"}
        interval = interval_map.get(period, "24 hours")

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT date_trunc('hour', nts.hour_bucket) AS hour, "
                    "COALESCE(nd.owner, nd.friendly_name, nd.hostname, 'Unknown') AS user_name, "
                    "SUM(nts.bytes_in) AS bytes_in, SUM(nts.bytes_out) AS bytes_out "
                    "FROM network_traffic_stats nts "
                    "LEFT JOIN network_devices nd ON nd.ip_address = nts.device_ip::inet "
                    "WHERE nts.hour_bucket >= NOW() - %s::interval "
                    "GROUP BY hour, user_name ORDER BY hour",
                    (interval,),
                )
                rows = cur.fetchall()
                history = [
                    {
                        "hour": row["hour"].isoformat(),
                        "user": row["user_name"],
                        "bytes_in": int(row["bytes_in"] or 0),
                        "bytes_out": int(row["bytes_out"] or 0),
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "history": history, "period": period})
        except Exception as exc:
            logger.error("bandwidth_history_by_user error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    # ---------------------------------------------------------------------------
    # Traffic classification per device
    # ---------------------------------------------------------------------------

    @bp.route("/api/devices/traffic-breakdown/<device_ip>")
    @login_required
    @admin_required_decorator
    def device_traffic_breakdown(device_ip):
        """Get traffic breakdown by category for a device."""
        if not IP_PATTERN.match(device_ip):
            return jsonify({"success": False, "error": "Invalid IP address"}), 400

        hours = request.args.get("hours", 24, type=int)
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        COALESCE(tc.category, 'other') AS category,
                        SUM(ddh.query_count) AS queries
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    WHERE ddh.device_ip = %s
                      AND ddh.hour_bucket >= NOW() - INTERVAL '1 hour' * %s
                    GROUP BY COALESCE(tc.category, 'other')
                    ORDER BY queries DESC
                    """,
                    (device_ip, hours),
                )
                breakdown = [{"category": row["category"], "queries": int(row["queries"])} for row in cur.fetchall()]
            return jsonify({"success": True, "breakdown": breakdown, "device_ip": device_ip})
        except Exception as exc:
            logger.error("device_traffic_breakdown error for %s: %s", device_ip, exc)
            return jsonify({"success": False, "error": str(exc)}), 500
