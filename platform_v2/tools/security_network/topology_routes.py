"""
Network Topology Map API
=========================
D3.js-compatible graph endpoints for network topology visualization.
Returns nodes (devices) and links (traffic flows) for the last 24 hours.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

GATEWAY_IP = "192.168.1.254"
HUB_IP = "192.168.1.200"
WIFI_AP_IP = "192.168.1.251"
# Devices wired directly to router — everything else goes through WiFi AP
WIRED_IPS = {GATEWAY_IP, HUB_IP, WIFI_AP_IP}


def register_topology_routes(bp, admin_required_decorator):
    """Register network topology graph endpoints on the security_network blueprint."""

    @bp.route("/api/topology/graph")
    @login_required
    @admin_required_decorator
    def topology_graph():
        """Return a D3.js-compatible graph of network devices and traffic links.

        Query params:
            hours (int): Lookback window in hours (default 24, max 168).

        Each node represents a device seen in network_traffic_stats, enriched
        with labels from network_device_users and OS info from device_fingerprints.
        Links connect every device to the gateway (192.168.1.1) weighted by
        total bytes transferred.
        """
        hours = min(request.args.get("hours", 24, type=int), 168)

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        nts.device_ip,
                        nts.device_mac,
                        ndu.device_label,
                        ndu.user_name,
                        ndu.device_type,
                        df.os_name,
                        df.os_version,
                        SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu
                        ON ndu.mac_address = nts.device_mac
                    LEFT JOIN device_fingerprints df
                        ON df.device_ip = nts.device_ip
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                      AND nts.device_ip LIKE '192.168.1.%%'
                      AND nts.device_ip NOT IN ('192.168.1.255')
                      AND nts.device_ip NOT LIKE '224.%%'
                      AND nts.device_ip NOT LIKE '239.%%'
                      AND nts.device_ip NOT LIKE '255.%%'
                      AND nts.device_ip NOT LIKE 'fe80:%%'
                    GROUP BY
                        nts.device_ip,
                        nts.device_mac,
                        ndu.device_label,
                        ndu.user_name,
                        ndu.device_type,
                        df.os_name,
                        df.os_version
                    ORDER BY bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()

            # -- Build node list ------------------------------------------------
            nodes = []
            seen_ips = set()

            for row in rows:
                ip = row["device_ip"]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)

                os_display = None
                if row["os_name"]:
                    os_display = row["os_name"]
                    if row["os_version"]:
                        os_display = f"{row['os_name']} {row['os_version']}"

                nodes.append(
                    {
                        "id": ip,
                        "mac": row["device_mac"],
                        "label": row["device_label"] or ip,
                        "user": row["user_name"],
                        "type": row["device_type"],
                        "os": os_display,
                        "bytes_total": int(row["bytes_total"] or 0),
                        "is_gateway": ip == GATEWAY_IP,
                        "is_hub": ip == HUB_IP,
                    }
                )

            # Ensure the gateway node exists even if it has no traffic rows
            if GATEWAY_IP not in seen_ips:
                nodes.append(
                    {
                        "id": GATEWAY_IP,
                        "mac": None,
                        "label": "Gateway",
                        "user": None,
                        "type": "router",
                        "os": None,
                        "bytes_total": 0,
                        "is_gateway": True,
                        "is_hub": False,
                    }
                )

            # -- Build link list (physical topology) ---------------------------
            # Wired devices (.200 hub, .251 wifi AP) connect to gateway (.254)
            # All other devices connect through WiFi AP (.251)
            links = []
            seen_ips = {n["id"] for n in nodes}

            # Ensure WiFi AP node exists
            if WIFI_AP_IP not in seen_ips:
                nodes.append(
                    {
                        "id": WIFI_AP_IP,
                        "mac": None,
                        "label": "WiFi AP",
                        "user": None,
                        "type": "access_point",
                        "os": None,
                        "bytes_total": 0,
                        "is_gateway": False,
                        "is_hub": False,
                    }
                )

            for node in nodes:
                ip = node["id"]
                if ip == GATEWAY_IP:
                    continue
                if node["bytes_total"] <= 0 and ip not in WIRED_IPS:
                    continue
                if ip in WIRED_IPS:
                    # Hub and WiFi AP connect directly to router
                    links.append({"source": ip, "target": GATEWAY_IP, "bytes": node["bytes_total"]})
                else:
                    # Everything else connects through WiFi AP
                    links.append({"source": ip, "target": WIFI_AP_IP, "bytes": node["bytes_total"]})

            # -- WAN layer: remote nodes + Internet cloud --------------------
            internet_id = "INTERNET"
            nodes.append(
                {
                    "id": internet_id,
                    "mac": None,
                    "label": "Internet",
                    "user": None,
                    "type": "cloud",
                    "os": None,
                    "bytes_total": 0,
                    "is_gateway": False,
                    "is_hub": False,
                }
            )
            # Gateway connects to Internet
            links.append({"source": GATEWAY_IP, "target": internet_id, "bytes": 0})

            # Add remote/fleet nodes from DB
            with get_db_cursor() as (conn2, cur2):
                cur2.execute(
                    """
                    SELECT node_name, public_ip, hostname, status,
                           node_type, location_label
                    FROM remote_nodes
                    WHERE hostname NOT LIKE '172.%%'
                    ORDER BY node_name
                    """
                )
                remote_rows = cur2.fetchall()

            node_ids_added = {n["id"] for n in nodes}
            for rn in remote_rows:
                node_ip = rn["public_ip"] or rn["hostname"] or ""
                if not node_ip or node_ip in node_ids_added:
                    continue
                node_ids_added.add(node_ip)
                is_lan = node_ip.startswith("192.168.1.")

                nodes.append(
                    {
                        "id": node_ip,
                        "mac": None,
                        "label": rn["node_name"],
                        "user": rn["location_label"],
                        "type": rn["node_type"] or "server",
                        "os": None,
                        "bytes_total": 0,
                        "is_gateway": False,
                        "is_hub": False,
                        "status": rn["status"],
                    }
                )
                if is_lan:
                    # LAN fleet nodes connect through WiFi or wired
                    links.append({"source": node_ip, "target": GATEWAY_IP, "bytes": 0})
                else:
                    # WAN nodes connect through Internet
                    links.append({"source": node_ip, "target": internet_id, "bytes": 0})

            return jsonify(
                {
                    "success": True,
                    "graph": {"nodes": nodes, "links": links},
                    "hours": hours,
                }
            )

        except Exception as exc:
            logger.error("topology_graph error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/topology/stats")
    @login_required
    @admin_required_decorator
    def topology_stats():
        """Return summary statistics for the network topology.

        Query params:
            hours (int): Lookback window in hours (default 24, max 168).

        Returns total device count, total bandwidth, and the top-talker device.
        """
        hours = min(request.args.get("hours", 24, type=int), 168)

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT nts.device_ip) AS device_count,
                        COALESCE(SUM(nts.bytes_in + nts.bytes_out), 0) AS total_bytes
                    FROM network_traffic_stats nts
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                      AND nts.device_ip LIKE '192.168.1.%%'
                      AND nts.device_ip NOT IN ('192.168.1.255')
                    """,
                    (hours,),
                )
                summary = cur.fetchone()

                # Top talker
                cur.execute(
                    """
                    SELECT
                        nts.device_ip,
                        ndu.device_label,
                        ndu.user_name,
                        SUM(nts.bytes_in + nts.bytes_out) AS bytes_total
                    FROM network_traffic_stats nts
                    LEFT JOIN network_device_users ndu
                        ON ndu.mac_address = nts.device_mac
                    WHERE nts.hour_bucket >= NOW() - INTERVAL '%s hours'
                      AND nts.device_ip LIKE '192.168.1.%%'
                      AND nts.device_ip NOT IN ('192.168.1.255')
                    GROUP BY nts.device_ip, ndu.device_label, ndu.user_name
                    ORDER BY bytes_total DESC
                    LIMIT 1
                    """,
                    (hours,),
                )
                top = cur.fetchone()

            top_talker = None
            if top:
                top_talker = {
                    "ip": top["device_ip"],
                    "label": top["device_label"] or top["device_ip"],
                    "user": top["user_name"],
                    "bytes_total": int(top["bytes_total"] or 0),
                }

            return jsonify(
                {
                    "success": True,
                    "stats": {
                        "device_count": int(summary["device_count"]),
                        "total_bytes": int(summary["total_bytes"]),
                        "top_talker": top_talker,
                    },
                    "hours": hours,
                }
            )

        except Exception as exc:
            logger.error("topology_stats error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
