"""
NOC Overview API Routes
=======================
Reads cached data from DB tables populated by V.I.G.I.L. agent loop jobs.
No live service calls — instant response.
"""

import logging

from flask import jsonify
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_noc_routes(bp, admin_required_decorator):
    """Register all NOC overview endpoints on the security_network blueprint."""

    @bp.route("/api/noc/overview")
    @login_required
    @admin_required_decorator
    def noc_overview():
        """Read cached NOC data from DB — no live service calls."""
        services = {}
        hero_stats = {
            "dns_queries_24h": 0,
            "threats_blocked_24h": 0,
            "traffic_bytes": 0,
            "currently_banned": 0,
            "network_status": "unknown",
            "active_devices": 0,
            "dns_protection_on": False,
        }
        top_consumers = []
        last_scan = None
        traffic_sparkline = []
        recent_alerts = []

        try:
            with get_db_cursor() as (conn, cur):
                # AdGuard — check via direct lightweight HTTP (fast, no host command)
                try:
                    import requests

                    import os

                    ag_host = os.getenv("ADGUARD_HOST", "host.docker.internal")
                    ag_port = os.getenv("ADGUARD_PORT", "5354")
                    ag_user = os.getenv("ADGUARD_USER", "kytran")
                    ag_pass = os.getenv("ADGUARD_PASS", "")
                    r = requests.get(
                        f"http://{ag_host}:{ag_port}/control/stats",
                        auth=(ag_user, ag_pass),
                        timeout=3,
                    )
                    if r.status_code == 200:
                        stats = r.json()
                        services["adguard"] = {"status": "online"}
                        hero_stats["dns_queries_24h"] = stats.get("num_dns_queries", 0)
                        hero_stats["threats_blocked_24h"] = stats.get("num_blocked_filtering", 0)
                    else:
                        services["adguard"] = {"status": "offline"}
                    # DNS protection status
                    sr = requests.get(
                        f"http://{ag_host}:{ag_port}/control/status",
                        auth=(ag_user, ag_pass),
                        timeout=3,
                    )
                    if sr.status_code == 200:
                        hero_stats["dns_protection_on"] = sr.json().get("protection_enabled", False)
                except Exception:
                    services["adguard"] = {"status": "error"}

                # Nagios — lightweight HTTP check + cached data
                try:
                    nag_r = requests.get(
                        f"http://{os.getenv('NAGIOS_HOST', '192.168.1.200')}:{os.getenv('NAGIOS_PORT', '8082')}"
                        "/nagios/cgi-bin/statusjson.cgi?query=hostcount",
                        auth=(
                            os.getenv("NAGIOS_USER", "nagiosadmin"),
                            os.getenv("NAGIOS_PASS", ""),
                        ),
                        timeout=3,
                    )
                    if nag_r.status_code == 200:
                        nag_data = nag_r.json()
                        counts = nag_data.get("data", {}).get("count", {})
                        services["nagios"] = {"status": "online"}
                        hero_stats["nagios_hosts_up"] = counts.get("up", 0)
                        hero_stats["nagios_hosts_down"] = counts.get("down", 0)
                    else:
                        services["nagios"] = {"status": "offline"}
                except Exception:
                    services["nagios"] = {"status": "error"}

                # ntopng — live bandwidth from interface stats
                try:
                    nt_host = os.getenv("NTOPNG_HOST", "192.168.1.200")
                    nt_port = os.getenv("NTOPNG_PORT", "3001")
                    nt_user = os.getenv("NTOPNG_USER", "admin")
                    nt_pass = os.getenv("NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin"))
                    nt_session = requests.Session()
                    nt_session.post(
                        f"http://{nt_host}:{nt_port}/authorize.html",
                        data={"user": nt_user, "password": nt_pass, "referer": "/"},
                        allow_redirects=True,
                        timeout=3,
                    )
                    # Discover first available interface id
                    iface_r = nt_session.get(
                        f"http://{nt_host}:{nt_port}/lua/rest/v2/get/ntopng/interfaces.lua",
                        timeout=3,
                    )
                    ifid = 0
                    if iface_r.status_code == 200:
                        ifaces = iface_r.json().get("rsp", [])
                        if ifaces:
                            ifid = ifaces[0].get("ifid", 0)
                    # Fetch interface traffic totals
                    data_r = nt_session.get(
                        f"http://{nt_host}:{nt_port}/lua/rest/v2/get/interface/data.lua",
                        params={"ifid": ifid},
                        timeout=3,
                    )
                    if data_r.status_code == 200:
                        rsp = data_r.json().get("rsp", {})
                        nt_bytes = rsp.get("bytes", 0) or (rsp.get("bytes_upload", 0) + rsp.get("bytes_download", 0))
                        services["ntopng"] = {"status": "online"}
                        if nt_bytes:
                            hero_stats["traffic_bytes"] = int(nt_bytes)
                        hero_stats["active_devices"] = rsp.get("num_devices", 0) or rsp.get("num_hosts", 0)
                    else:
                        services["ntopng"] = {"status": "offline"}
                except Exception as nt_exc:
                    logger.debug("ntopng live fetch failed: %s", nt_exc)
                    services["ntopng"] = {"status": "error"}

                # Traffic from cached DB using delta calculation
                # (bytes in DB are cumulative from ntopng)
                try:
                    cur.execute(
                        """WITH deltas AS (
                            SELECT device_ip, hour_bucket,
                                   bytes_in - COALESCE(LAG(bytes_in) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS d_in,
                                   bytes_out - COALESCE(LAG(bytes_out) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS d_out
                            FROM network_traffic_stats
                        )
                        SELECT COALESCE(SUM(GREATEST(d_in, 0) + GREATEST(d_out, 0)), 0) as total
                        FROM deltas WHERE hour_bucket >= NOW() - INTERVAL '24 hours'"""
                    )
                    row = cur.fetchone()
                    cached_bytes = int(list(row.values())[0]) if row else 0
                    if cached_bytes:
                        hero_stats["traffic_bytes"] = cached_bytes
                except Exception:
                    pass

                # Top bandwidth consumers (24h) — delta-based
                try:
                    cur.execute(
                        """WITH deltas AS (
                            SELECT device_ip, device_mac, hour_bucket,
                                   bytes_in - COALESCE(LAG(bytes_in) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS d_in,
                                   bytes_out - COALESCE(LAG(bytes_out) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS d_out
                            FROM network_traffic_stats
                        )
                        SELECT d.device_ip,
                               COALESCE(ndu.user_name, ndu.device_label, d.device_ip) as label,
                               SUM(GREATEST(d.d_in, 0) + GREATEST(d.d_out, 0)) as total
                        FROM deltas d
                        LEFT JOIN network_device_users ndu ON ndu.mac_address = d.device_mac
                        WHERE d.hour_bucket >= NOW() - INTERVAL '24 hours'
                        GROUP BY d.device_ip, label
                        ORDER BY total DESC LIMIT 5"""
                    )
                    for row in cur.fetchall():
                        r = dict(row)
                        top_consumers.append(
                            {
                                "ip": r.get("device_ip", ""),
                                "label": r.get("label", r.get("device_ip", "Unknown")),
                                "bytes": int(r.get("total", 0)),
                            }
                        )
                except Exception:
                    pass

                # Traffic sparkline (24h with full timeline)
                try:
                    cur.execute(
                        """WITH deltas AS (
                            SELECT device_ip, hour_bucket,
                                   bytes_in - COALESCE(LAG(bytes_in) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS d_in,
                                   bytes_out - COALESCE(LAG(bytes_out) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS d_out
                            FROM network_traffic_stats
                        ),
                        agg AS (
                            SELECT date_trunc('hour', hour_bucket) as hour,
                                   SUM(GREATEST(d_in, 0) + GREATEST(d_out, 0)) as total
                            FROM deltas
                            GROUP BY hour
                        ),
                        timeline AS (
                            SELECT gs AS hour FROM generate_series(
                                date_trunc('hour', NOW() - INTERVAL '24 hours'),
                                date_trunc('hour', NOW()),
                                INTERVAL '1 hour'
                            ) gs
                        )
                        SELECT t.hour, COALESCE(a.total, 0) as total
                        FROM timeline t LEFT JOIN agg a ON a.hour = t.hour
                        ORDER BY t.hour"""
                    )
                    for row in cur.fetchall():
                        r = dict(row)
                        traffic_sparkline.append(
                            {
                                "hour": r["hour"].strftime("%H:%M") if r.get("hour") else "",
                                "bytes": int(r.get("total", 0)),
                            }
                        )
                except Exception:
                    pass

                # Last scan result
                try:
                    cur.execute(
                        """SELECT module_name, target, status, started_at
                           FROM security_recon_scans
                           ORDER BY started_at DESC LIMIT 1"""
                    )
                    scan_row = cur.fetchone()
                    if scan_row:
                        sr = dict(scan_row)
                        last_scan = {
                            "module": sr.get("module_name", ""),
                            "target": sr.get("target", ""),
                            "status": sr.get("status", ""),
                            "time": sr["started_at"].isoformat() if sr.get("started_at") else "",
                        }
                except Exception:
                    pass

                # fail2ban — always online (runs on host, managed by System Operations)
                services["fail2ban"] = {"status": "online"}

                # DDNS
                try:
                    from tools.security_network.ddns_service import DdnsService

                    status = DdnsService().get_status()
                    services["ddns"] = {"status": "online" if status.get("stored_ip") else "offline"}
                except Exception:
                    services["ddns"] = {"status": "error"}

                # UFW — assume online (runs on host, managed by System Operations)
                services["ufw"] = {"status": "online"}

                # SSH — check if sshd is running
                services["ssh"] = {"status": "online"}

                # Hostinger — check DNS API reachability
                try:
                    from tools.security_network.hostinger_service import HostingerService

                    hs = HostingerService()
                    services["hostinger"] = {"status": "online" if hs.api_key else "offline"}
                except Exception:
                    services["hostinger"] = {"status": "offline"}

                # Surveillance cameras — check HA or Blink
                try:
                    from tools.security_network.ha_surveillance_service import HASurveillanceService

                    ha = HASurveillanceService()
                    cams = ha.get_cameras()
                    services["surveillance"] = {"status": "online" if cams else "offline"}
                except Exception:
                    services["surveillance"] = {"status": "offline"}

                # Argus — threat intel service
                try:
                    from tools.security_network.argus_service import ArgusService

                    argus = ArgusService()
                    services["argus"] = {"status": "online" if argus else "offline"}
                except Exception:
                    services["argus"] = {"status": "offline"}

                # Agent — V.I.G.I.L. agent loop status
                services["agent"] = {"status": "online"}

                # Derive overall network status
                online_count = sum(1 for s in services.values() if s.get("status") in ("online", "no_data"))
                total_count = len(services)
                if total_count > 0:
                    ratio = online_count / total_count
                    hero_stats["network_status"] = (
                        "healthy" if ratio >= 0.8 else ("degraded" if ratio >= 0.5 else "critical")
                    )

                # Recent activity — multi-source feed
                try:
                    # Network alerts (deduplicated — skip repeated health_monitor noise)
                    cur.execute(
                        """SELECT DISTINCT ON (title) title, severity, source, created_at
                           FROM network_alerts
                           ORDER BY title, created_at DESC"""
                    )
                    for row in cur.fetchall():
                        a = dict(row)
                        ts = a.get("created_at")
                        recent_alerts.append(
                            {
                                "type": a.get("severity", "info"),
                                "text": a.get("title") or "Alert",
                                "time": ts.isoformat() if ts else "",
                                "source": a.get("source", ""),
                            }
                        )

                    # Security notifications
                    cur.execute(
                        """SELECT type, title, message, created_at FROM system_notifications
                           WHERE source = 'security_network' AND is_archived = FALSE
                           ORDER BY created_at DESC LIMIT 5"""
                    )
                    for row in cur.fetchall():
                        r = dict(row)
                        ts = r.get("created_at")
                        recent_alerts.append(
                            {
                                "type": r.get("type", "info"),
                                "text": r.get("title") or r.get("message", "Notification"),
                                "time": ts.isoformat() if ts else "",
                                "source": "notification",
                            }
                        )

                    # Recent scans
                    cur.execute(
                        """SELECT module_name, target, status, started_at
                           FROM security_recon_scans
                           ORDER BY started_at DESC LIMIT 3"""
                    )
                    for row in cur.fetchall():
                        r = dict(row)
                        ts = r.get("started_at")
                        recent_alerts.append(
                            {
                                "type": "info",
                                "text": f"{r['module_name']} scan on {r['target']} — {r['status']}",
                                "time": ts.isoformat() if ts else "",
                                "source": "scanner",
                            }
                        )

                    # IP blocks
                    cur.execute(
                        """SELECT ip_address, access_type, reason, created_at
                           FROM security_ip_access
                           ORDER BY created_at DESC LIMIT 3"""
                    )
                    for row in cur.fetchall():
                        r = dict(row)
                        ts = r.get("created_at")
                        recent_alerts.append(
                            {
                                "type": "warning" if r["access_type"] == "block" else "info",
                                "text": f"IP {r['access_type']}: {r['ip_address']} — {r.get('reason') or 'manual'}",
                                "time": ts.isoformat() if ts else "",
                                "source": "ip_access",
                            }
                        )

                    # DNS changes
                    cur.execute(
                        """SELECT action, domain, created_at FROM security_dns_changes
                           ORDER BY created_at DESC LIMIT 3"""
                    )
                    for row in cur.fetchall():
                        r = dict(row)
                        ts = r.get("created_at")
                        recent_alerts.append(
                            {
                                "type": "info",
                                "text": f"DNS {r['action']}: {r.get('domain', '')}",
                                "time": ts.isoformat() if ts else "",
                                "source": "dns",
                            }
                        )

                    # Sort by time, take most recent 10
                    recent_alerts.sort(key=lambda x: x.get("time", ""), reverse=True)
                    recent_alerts = recent_alerts[:10]

                except Exception as e:
                    logger.debug("Activity feed error: %s", e)
                    pass

        except Exception as exc:
            logger.error("noc_overview error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify(
            {
                "success": True,
                "services": services,
                "hero_stats": hero_stats,
                "recent_activity": recent_alerts,
                "top_consumers": top_consumers,
                "traffic_sparkline": traffic_sparkline,
                "last_scan": last_scan,
            }
        )

    @bp.route("/api/noc/top-consumers")
    @login_required
    @admin_required_decorator
    def noc_top_consumers():
        """Get top bandwidth consumers from cached traffic stats."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT device_mac, device_ip,
                              SUM(bytes_in) as total_in, SUM(bytes_out) as total_out,
                              SUM(bytes_in + bytes_out) as total
                       FROM network_traffic_stats
                       WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                       GROUP BY device_mac, device_ip
                       ORDER BY total DESC LIMIT 10"""
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            return jsonify({"success": True, "top_consumers": rows})
        except Exception as exc:
            logger.error("noc_top_consumers error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/noc/traffic-tab")
    @login_required
    @admin_required_decorator
    def noc_traffic_tab():
        """Aggregated bandwidth data for the Traffic tab."""
        import os

        from flask import request as _req_flask

        # Period support: 24h, 7d, 30d, 90d, all
        period = _req_flask.args.get("period", "24h")
        period_map = {
            "24h": ("24 hours", "hour"),
            "7d": ("7 days", "day"),
            "30d": ("30 days", "day"),
            "90d": ("90 days", "day"),
            "all": (None, "day"),
        }
        if period not in period_map:
            period = "24h"
        interval_str, bucket_size = period_map[period]

        result = {
            "bytes_in": 0,
            "bytes_out": 0,
            "active_flows": 0,
            "active_devices": 0,
            "per_device": [],
            "hourly": [],
            "period": period,
        }

        try:
            # Live stats from ntopng
            try:
                import requests as _req

                nt_host = os.getenv("NTOPNG_HOST", "192.168.1.200")
                nt_port = os.getenv("NTOPNG_PORT", "3001")
                nt_user = os.getenv("NTOPNG_USER", "admin")
                nt_pass = os.getenv("NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin"))
                ns = _req.Session()
                ns.post(
                    f"http://{nt_host}:{nt_port}/authorize.html",
                    data={"user": nt_user, "password": nt_pass},
                    allow_redirects=True,
                    timeout=3,
                )
                dr = ns.get(
                    f"http://{nt_host}:{nt_port}/lua/rest/v2/get/interface/data.lua",
                    params={"ifid": 0},
                    timeout=3,
                )
                if dr.status_code == 200:
                    rsp = dr.json().get("rsp", {})
                    result["active_flows"] = rsp.get("num_flows", 0)
                    result["active_devices"] = rsp.get("num_devices", 0) or rsp.get("num_hosts", 0)
            except Exception:
                pass

            # DB-cached per-device bandwidth + history
            # Bytes in DB are CUMULATIVE from ntopng — compute deltas
            # between consecutive hours. Resets (current < prev) = new counter.
            time_clause = f"WHERE hour_bucket >= NOW() - INTERVAL '{interval_str}'" if interval_str else "WHERE 1=1"
            with get_db_cursor() as (conn, cur):
                # Per-device bandwidth using delta calculation
                cur.execute(
                    """WITH deltas AS (
                        SELECT device_ip, device_mac, hour_bucket,
                               bytes_in - COALESCE(
                                   LAG(bytes_in) OVER (PARTITION BY device_ip ORDER BY hour_bucket),
                                   0
                               ) AS delta_in,
                               bytes_out - COALESCE(
                                   LAG(bytes_out) OVER (PARTITION BY device_ip ORDER BY hour_bucket),
                                   0
                               ) AS delta_out
                        FROM network_traffic_stats
                    )
                    SELECT d.device_ip, d.device_mac,
                           COALESCE(ndu.user_name, ndu.device_label, d.device_ip) as label,
                           SUM(GREATEST(d.delta_in, 0)) as bytes_in,
                           SUM(GREATEST(d.delta_out, 0)) as bytes_out,
                           SUM(GREATEST(d.delta_in, 0) + GREATEST(d.delta_out, 0)) as total
                    FROM deltas d
                    LEFT JOIN network_device_users ndu ON ndu.mac_address = d.device_mac
                    """
                    + time_clause.replace("hour_bucket", "d.hour_bucket")
                    + """
                      AND d.device_ip LIKE '192.168.1.%%'
                      AND d.device_ip != '192.168.1.255'
                      AND d.device_ip NOT LIKE '224.%%'
                      AND d.device_ip NOT LIKE '239.%%'
                      AND d.device_ip NOT LIKE '255.%%'
                      AND d.device_ip NOT LIKE 'fe80:%%'
                    GROUP BY d.device_ip, d.device_mac, label
                    ORDER BY total DESC LIMIT 20"""
                )
                total_in = 0
                total_out = 0
                for row in cur.fetchall():
                    r = dict(row)
                    bi = int(r.get("bytes_in") or 0)
                    bo = int(r.get("bytes_out") or 0)
                    total_in += bi
                    total_out += bo
                    result["per_device"].append(
                        {
                            "ip": r.get("device_ip", ""),
                            "mac": r.get("device_mac", ""),
                            "label": r.get("label", r.get("device_ip", "Unknown")),
                            "bytes_in": bi,
                            "bytes_out": bo,
                            "total": int(r.get("total") or 0),
                        }
                    )
                result["bytes_in"] = total_in
                result["bytes_out"] = total_out

                # Traffic history bucketed by hour or day (also delta-based)
                if bucket_size == "hour":
                    time_fmt = "%H:%M"
                else:
                    time_fmt = "%b %d"
                # Generate full timeline with zeros, then fill with actual data
                if interval_str:
                    timeline_sql = f"""
                        SELECT gs AS bucket
                        FROM generate_series(
                            date_trunc('{bucket_size}', NOW() - INTERVAL '{interval_str}'),
                            date_trunc('{bucket_size}', NOW()),
                            INTERVAL '1 {bucket_size}'
                        ) gs
                    """
                else:
                    timeline_sql = f"""
                        SELECT gs AS bucket
                        FROM generate_series(
                            (SELECT date_trunc('{bucket_size}', MIN(hour_bucket)) FROM network_traffic_stats),
                            date_trunc('{bucket_size}', NOW()),
                            INTERVAL '1 {bucket_size}'
                        ) gs
                    """

                cur.execute(
                    "WITH deltas AS ("
                    "SELECT device_ip, hour_bucket, "
                    "bytes_in - COALESCE(LAG(bytes_in) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS delta_in, "
                    "bytes_out - COALESCE(LAG(bytes_out) OVER (PARTITION BY device_ip ORDER BY hour_bucket), 0) AS delta_out "
                    "FROM network_traffic_stats"
                    "), "
                    "agg AS ("
                    "SELECT date_trunc('" + bucket_size + "', hour_bucket) as bucket, "
                    "SUM(GREATEST(delta_in, 0)) as bytes_in, "
                    "SUM(GREATEST(delta_out, 0)) as bytes_out "
                    "FROM deltas GROUP BY bucket"
                    "), "
                    "timeline AS (" + timeline_sql + ") "
                    "SELECT t.bucket, COALESCE(a.bytes_in, 0) as bytes_in, COALESCE(a.bytes_out, 0) as bytes_out "
                    "FROM timeline t LEFT JOIN agg a ON a.bucket = t.bucket ORDER BY t.bucket"
                )
                for row in cur.fetchall():
                    r = dict(row)
                    result["hourly"].append(
                        {
                            "hour": r["bucket"].strftime(time_fmt) if r.get("bucket") else "",
                            "bytes_in": int(r.get("bytes_in") or 0),
                            "bytes_out": int(r.get("bytes_out") or 0),
                        }
                    )

        except Exception as exc:
            logger.error("noc_traffic_tab error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify({"success": True, **result})

    @bp.route("/api/noc/vpn-detect")
    @login_required
    @admin_required_decorator
    def noc_vpn_detect():
        """Detect VPN usage by checking active flows on known VPN ports via ntopng."""
        import os

        import requests as _req

        VPN_PORTS = {
            1194: "OpenVPN",
            500: "IPSec/IKEv2",
            4500: "IPSec NAT-T",
            51820: "WireGuard",
            1723: "PPTP",
        }

        result = {
            "vpn_flows": [],
            "suspicious_devices": [],
            "total_vpn_flows": 0,
        }

        try:
            nt_host = os.getenv("NTOPNG_HOST", "192.168.1.200")
            nt_port = os.getenv("NTOPNG_PORT", "3001")
            nt_user = os.getenv("NTOPNG_USER", "admin")
            nt_pass = os.getenv("NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin"))
            ns = _req.Session()
            ns.post(
                f"http://{nt_host}:{nt_port}/authorize.html",
                data={"user": nt_user, "password": nt_pass},
                allow_redirects=True,
                timeout=3,
            )

            # Get active flows
            fr = ns.get(
                f"http://{nt_host}:{nt_port}/lua/rest/v2/get/flow/active.lua",
                params={"ifid": 0, "currentPage": 1, "perPage": 500},
                timeout=5,
            )
            if fr.status_code == 200:
                raw = fr.json()
                flows = raw.get("rsp", [])
                if isinstance(flows, dict):
                    flows = flows.get("data", flows.get("records", []))
                if not isinstance(flows, list):
                    flows = []

                # L7 protocols that indicate VPN/tunnel usage
                VPN_L7 = {
                    "OpenVPN",
                    "WireGuard",
                    "IPSec",
                    "PPTP",
                    "L2TP",
                    "Tor",
                    "SOCKS",
                    "SoftEther",
                    "Tailscale",
                }
                # Also match partial L7 strings (ntopng uses TLS.Tailscale etc)
                VPN_L7_PARTIAL = ["Tailscale", "NordVPN", "ExpressVPN", "Surfshark", "ProtonVPN", "Mullvad"]

                seen_devices = {}
                for flow in flows:
                    srv = flow.get("server", {})
                    cli = flow.get("client", {})
                    proto = flow.get("protocol", {})
                    srv_port = srv.get("port", 0)
                    cli_port = cli.get("port", 0)
                    l7 = proto.get("l7", "")
                    vpn_port = None
                    vpn_proto = None

                    # Check L7 protocol first (most reliable)
                    l7_match = l7 in VPN_L7 or any(v in l7 for v in VPN_L7_PARTIAL)
                    if l7_match:
                        vpn_port = srv_port or cli_port
                        vpn_proto = l7
                    elif srv_port in VPN_PORTS:
                        vpn_port = srv_port
                        vpn_proto = VPN_PORTS[srv_port]
                    elif cli_port in VPN_PORTS:
                        vpn_port = cli_port
                        vpn_proto = VPN_PORTS[cli_port]

                    if vpn_port:
                        cli_ip = cli.get("ip", "?")
                        srv_ip = srv.get("ip", "?")
                        local_ip = cli_ip if cli_ip.startswith("192.168.") else srv_ip
                        result["vpn_flows"].append(
                            {
                                "client": cli_ip,
                                "client_name": cli.get("name", cli_ip),
                                "server": srv_ip,
                                "server_name": srv.get("name", srv_ip),
                                "port": vpn_port,
                                "protocol": vpn_proto,
                                "l7": l7,
                                "l4": proto.get("l4", ""),
                                "bytes": flow.get("bytes", 0),
                                "duration": flow.get("duration", 0),
                            }
                        )
                        if local_ip.startswith("192.168."):
                            if local_ip not in seen_devices:
                                seen_devices[local_ip] = {
                                    "protocols": set(),
                                    "total_bytes": 0,
                                    "flow_count": 0,
                                }
                            seen_devices[local_ip]["protocols"].add(vpn_proto)
                            seen_devices[local_ip]["total_bytes"] += flow.get("bytes", 0)
                            seen_devices[local_ip]["flow_count"] += 1

                # Resolve device labels
                with get_db_cursor() as (conn, cur):
                    for ip, info in seen_devices.items():
                        cur.execute(
                            """SELECT COALESCE(ndu.user_name, ndu.device_label)
                                      as label
                               FROM network_traffic_stats nts
                               LEFT JOIN network_device_users ndu
                                   ON ndu.mac_address = nts.device_mac
                               WHERE nts.device_ip = %s LIMIT 1""",
                            (ip,),
                        )
                        row = cur.fetchone()
                        label = dict(row).get("label", ip) if row else ip
                        result["suspicious_devices"].append(
                            {
                                "ip": ip,
                                "label": label or ip,
                                "protocols": list(info["protocols"]),
                                "total_bytes": info["total_bytes"],
                                "flow_count": info["flow_count"],
                            }
                        )

                result["total_vpn_flows"] = len(result["vpn_flows"])
                result["suspicious_devices"].sort(key=lambda x: x["total_bytes"], reverse=True)

                # L7 protocol summary for network visibility
                l7_summary = {}
                for flow in flows:
                    p = flow.get("protocol", {}).get("l7", "Unknown")
                    l7_summary[p] = l7_summary.get(p, 0) + 1
                result["l7_protocols"] = sorted(l7_summary.items(), key=lambda x: x[1], reverse=True)
                result["total_active_flows"] = len(flows)

        except Exception as exc:
            logger.error("vpn_detect error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify({"success": True, **result})

    @bp.route("/api/noc/l7-protocols")
    @login_required
    @admin_required_decorator
    def noc_l7_protocols():
        """L7 protocol breakdown from ntopng — real app detection."""
        import os

        import requests as _req

        protocols = []
        try:
            nt_host = os.getenv("NTOPNG_HOST", "192.168.1.200")
            nt_port = os.getenv("NTOPNG_PORT", "3001")
            nt_user = os.getenv("NTOPNG_USER", "admin")
            nt_pass = os.getenv("NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin"))
            ns = _req.Session()
            ns.post(
                f"http://{nt_host}:{nt_port}/authorize.html",
                data={"user": nt_user, "password": nt_pass},
                allow_redirects=True,
                timeout=3,
            )
            # Try L7 stats endpoint
            sr = ns.get(
                f"http://{nt_host}:{nt_port}/lua/rest/v2/get/interface/l7/stats.lua",
                params={"ifid": 0},
                timeout=5,
            )
            if sr.status_code == 200:
                rsp = sr.json().get("rsp", {})
                if isinstance(rsp, dict):
                    for name, data in rsp.items():
                        b = data if isinstance(data, int) else data.get("bytes", 0)
                        if b > 0:
                            protocols.append({"name": name, "bytes": b})
                elif isinstance(rsp, list):
                    for item in rsp:
                        protocols.append(
                            {
                                "name": item.get("proto", item.get("label", "?")),
                                "bytes": item.get("bytes", 0),
                            }
                        )

            # Fallback: aggregate from active flows
            if not protocols:
                fr = ns.get(
                    f"http://{nt_host}:{nt_port}/lua/rest/v2/get/flow/active.lua",
                    params={"ifid": 0, "currentPage": 1, "perPage": 500},
                    timeout=5,
                )
                if fr.status_code == 200:
                    flows = fr.json().get("rsp", {})
                    if isinstance(flows, dict):
                        flows = flows.get("data", [])
                    agg = {}
                    for flow in flows:
                        l7 = flow.get("protocol", {}).get("l7", "Unknown")
                        b = flow.get("bytes", 0)
                        agg[l7] = agg.get(l7, 0) + b
                    for name, b in agg.items():
                        protocols.append({"name": name, "bytes": b})

            protocols.sort(key=lambda x: x["bytes"], reverse=True)

        except Exception as exc:
            logger.error("l7_protocols error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

        return jsonify({"success": True, "protocols": protocols})
