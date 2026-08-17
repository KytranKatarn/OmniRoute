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
                reason = entry.get("reason", "")
                blocked = reason != "" and reason not in (
                    "Rewrite",
                    "NotFilteredWhiteList",
                    "NotFilteredNotFound",
                )

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

            # Pull 24h bandwidth totals from network_traffic_stats
            bandwidth_bytes_in = 0
            bandwidth_bytes_out = 0
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(bytes_in), 0) AS total_in,
                               COALESCE(SUM(bytes_out), 0) AS total_out
                        FROM network_traffic_stats
                        WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        # RealDictCursor rows are dicts; the columns are aliased so
                        # they don't collide and can be read by name (row[0] KeyError'd).
                        bandwidth_bytes_in = int(row["total_in"])
                        bandwidth_bytes_out = int(row["total_out"])
            except Exception as bw_exc:
                logger.warning("bandwidth_bytes lookup failed: %s", bw_exc)

            return jsonify(
                {
                    "success": True,
                    "clients": result,
                    "query_count": len(entries),
                    "bandwidth_bytes_in": bandwidth_bytes_in,
                    "bandwidth_bytes_out": bandwidth_bytes_out,
                }
            )
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
                # network_traffic_stats columns: device_mac, device_ip, bytes_in,
                # bytes_out, protocol, hour_bucket, created_at. The old query used
                # recorded_at/bytes_sent/bytes_recv (don't exist), an INTERVAL '%s'
                # placeholder inside a string literal (never substituted), and
                # row[0] indexing on RealDictCursor rows — every call 500'd.
                cur.execute(
                    """
                    SELECT
                        device_mac,
                        device_ip,
                        hour_bucket AS hour,
                        SUM(bytes_out) AS bytes_sent,
                        SUM(bytes_in) AS bytes_recv,
                        SUM(bytes_in + bytes_out) AS bytes_total
                    FROM network_traffic_stats
                    WHERE hour_bucket >= NOW() - make_interval(hours => %s)
                    GROUP BY device_mac, device_ip, hour_bucket
                    ORDER BY hour DESC, bytes_total DESC
                    """,
                    (hours,),
                )
                rows = cur.fetchall()
                history = [
                    {
                        "device_mac": row["device_mac"],
                        "device_ip": row["device_ip"],
                        "hour": row["hour"].isoformat() if row["hour"] else None,
                        "bytes_sent": row["bytes_sent"],
                        "bytes_recv": row["bytes_recv"],
                        "bytes_total": row["bytes_total"],
                    }
                    for row in rows
                ]
            return jsonify({"success": True, "history": history, "hours": hours})
        except Exception as exc:
            logger.error("traffic_history error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
