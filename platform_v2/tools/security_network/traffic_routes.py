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

    # ── Streaming / service detection categories ──
    SERVICE_PATTERNS = {
        "Netflix": ["netflix", "nflx"],
        "YouTube": ["youtube", "googlevideo", "ytimg", "youtu.be"],
        "Disney+": ["disney", "bamgrid", "dssott"],
        "Amazon Video": ["primevideo", "amazonvideo", "aiv-cdn"],
        "Twitch": ["twitch", "jtvnw"],
        "Spotify": ["spotify", "scdn"],
        "TikTok": ["tiktok", "tiktokcdn", "musical.ly"],
        "Instagram": ["instagram", "cdninstagram"],
        "Facebook": ["facebook", "fbcdn"],
        "Gaming": ["epicgames", "steampowered", "playstation", "xbox.com", "riotgames", "valve"],
        "Apple": ["apple.com", "icloud", "mzstatic"],
        "Microsoft": ["microsoft", "windows.com", "office", "live.com", "bing.com"],
        "Google": ["google.com", "googleapis", "gstatic"],
        "Snapchat": ["snapchat", "snap-storage"],
        "Porn": ["pornhub", "xvideos", "xhamster", "xnxx", "redtube", "youporn", "brazzers", "onlyfans"],
    }

    def _classify_domain(domain):
        """Classify a domain into a service category."""
        dl = domain.lower()
        for service, patterns in SERVICE_PATTERNS.items():
            if any(p in dl for p in patterns):
                return service
        return None

    @bp.route("/api/traffic/activity")
    @login_required
    @admin_required_decorator
    def traffic_activity():
        """Per-client DNS activity with streaming/service detection from AdGuard."""
        limit = request.args.get("limit", 5000, type=int)
        client_ip = request.args.get("client")
        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()

            # Get query log via AdGuardService
            ql = (
                ag.get_query_log(
                    limit=min(limit, 5000),
                    search=client_ip,
                )
                or {}
            )
            entries = ql.get("data", [])

            # Aggregate per client
            clients = {}
            for entry in entries:
                ip = entry.get("client", "")
                domain = entry.get("question", {}).get("name", "").lower().rstrip(".")
                blocked = entry.get("reason", "") != ""

                if ip not in clients:
                    clients[ip] = {
                        "ip": ip,
                        "total_queries": 0,
                        "blocked": 0,
                        "services": {},
                        "top_domains": {},
                    }
                c = clients[ip]
                c["total_queries"] += 1
                if blocked:
                    c["blocked"] += 1

                # Classify
                service = _classify_domain(domain)
                if service:
                    c["services"][service] = c["services"].get(service, 0) + 1

                # Track top domains
                c["top_domains"][domain] = c["top_domains"].get(domain, 0) + 1

            # Build response with top 10 domains per client
            result = []
            for ip, c in sorted(clients.items(), key=lambda x: -x[1]["total_queries"]):
                top = sorted(c["top_domains"].items(), key=lambda x: -x[1])[:10]
                result.append(
                    {
                        "ip": c["ip"],
                        "total_queries": c["total_queries"],
                        "blocked": c["blocked"],
                        "services": c["services"],
                        "top_domains": [{"domain": d, "count": n} for d, n in top],
                    }
                )

            return jsonify({"success": True, "clients": result, "query_count": len(entries)})
        except Exception as exc:
            logger.error("traffic_activity error: %s", exc)
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
