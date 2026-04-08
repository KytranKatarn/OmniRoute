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
        }
        recent_alerts = []

        try:
            with get_db_cursor() as (conn, cur):
                # AdGuard — check via direct lightweight HTTP (fast, no host command)
                try:
                    import requests

                    import os

                    ag_host = os.getenv("ADGUARD_HOST", "network_adguard")
                    ag_port = os.getenv("ADGUARD_PORT", "80")
                    ag_user = os.getenv("ADGUARD_USER", "archie_admin")
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
                    else:
                        services["ntopng"] = {"status": "offline"}
                except Exception as nt_exc:
                    logger.debug("ntopng live fetch failed: %s", nt_exc)
                    services["ntopng"] = {"status": "error"}

                # Traffic from cached DB — override live ntopng if we have recent rows
                try:
                    cur.execute(
                        "SELECT COALESCE(SUM(bytes_in + bytes_out), 0) "
                        "FROM network_traffic_stats "
                        "WHERE hour_bucket >= NOW() - INTERVAL '24 hours'"
                    )
                    row = cur.fetchone()
                    cached_bytes = int(row[0]) if row and row[0] else 0
                    if cached_bytes:
                        hero_stats["traffic_bytes"] = cached_bytes
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
