"""
NOC Overview API Routes
=======================
Network Operations Center aggregation endpoints.
"""

import logging
import concurrent.futures

from flask import jsonify
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)


def _check_adguard():
    try:
        from tools.security_network.adguard_service import AdGuardService

        ag = AdGuardService()
        ag_status = ag.get_status()
        stats = ag.get_stats() or {}
        return {
            "service": {"status": "online" if ag_status else "offline"},
            "dns_queries_24h": stats.get("num_dns_queries", 0),
            "threats_blocked_24h": stats.get("num_blocked_filtering", 0),
        }
    except Exception as exc:
        logger.warning("noc adguard: %s", exc)
        return {"service": {"status": "error"}}


def _check_ntopng():
    try:
        from tools.security_network.ntopng_service import NtopngService

        nt = NtopngService()
        healthy = nt.is_healthy()
        result = {"service": {"status": "online" if healthy else "offline"}}
        if healthy:
            iface_stats = nt.get_interface_stats(0) or {}
            result["traffic_bytes"] = iface_stats.get("bytes", 0)
        return result
    except Exception as exc:
        logger.warning("noc ntopng: %s", exc)
        return {"service": {"status": "error"}}


def _check_nagios():
    try:
        from tools.security_network.nagios_service import NagiosService

        nag = NagiosService()
        healthy = nag.is_healthy()
        result = {"service": {"status": "online" if healthy else "offline"}}
        if healthy:
            counts = nag.get_host_count()
            result["nagios_hosts_up"] = counts.get("data", {}).get("count", {}).get("up", 0)
        return result
    except Exception as exc:
        logger.warning("noc nagios: %s", exc)
        return {"service": {"status": "error"}}


def _check_fail2ban():
    try:
        from tools.security_network.fail2ban_service import Fail2banService

        fb = Fail2banService()
        fb_status = fb.get_status()
        running = fb_status.get("running", False)
        result = {"service": {"status": "online" if running else "offline"}}
        if running:
            jails = fb_status.get("jails", [])
            result["jail_count"] = len(jails)
        return result
    except Exception as exc:
        logger.warning("noc fail2ban: %s", exc)
        return {"service": {"status": "error"}}


def _check_ddns():
    try:
        from tools.security_network.ddns_service import DdnsService

        ddns = DdnsService()
        status = ddns.get_status()
        return {"service": {"status": "online" if status.get("stored_ip") else "offline"}}
    except Exception as exc:
        logger.warning("noc ddns: %s", exc)
        return {"service": {"status": "error"}}


def _check_ufw():
    try:
        from tools.security_network.security_service import get_firewall_status

        fw = get_firewall_status()
        active = fw.get("enabled") or fw.get("status") == "active"
        return {"service": {"status": "online" if active else "offline"}}
    except Exception as exc:
        logger.warning("noc ufw: %s", exc)
        return {"service": {"status": "error"}}


def register_noc_routes(bp, admin_required_decorator):
    """Register all NOC overview endpoints on the security_network blueprint."""

    @bp.route("/api/noc/overview")
    @login_required
    @admin_required_decorator
    def noc_overview():
        """Aggregate status from all security services — runs checks in parallel."""
        services = {}
        hero_stats = {
            "dns_queries_24h": 0,
            "threats_blocked_24h": 0,
            "traffic_bytes": 0,
            "currently_banned": 0,
            "network_status": "unknown",
        }

        # Run all service checks in parallel (max 5s timeout)
        checks = {
            "adguard": _check_adguard,
            "ntopng": _check_ntopng,
            "nagios": _check_nagios,
            "fail2ban": _check_fail2ban,
            "ddns": _check_ddns,
            "ufw": _check_ufw,
        }

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {name: pool.submit(fn) for name, fn in checks.items()}
            for name, future in futures.items():
                try:
                    result = future.result(timeout=8)
                    services[name] = result.get("service", {"status": "error"})
                    # Merge hero stats from results
                    for key in (
                        "dns_queries_24h",
                        "threats_blocked_24h",
                        "traffic_bytes",
                        "currently_banned",
                        "nagios_hosts_up",
                        "jail_count",
                    ):
                        if key in result:
                            hero_stats[key] = result[key]
                except concurrent.futures.TimeoutError:
                    logger.warning("noc %s timed out", name)
                    services[name] = {"status": "timeout"}
                except Exception as exc:
                    logger.warning("noc %s error: %s", name, exc)
                    services[name] = {"status": "error"}

        # Derive overall network status
        online_count = sum(1 for s in services.values() if s.get("status") == "online")
        total_count = len(services)
        if total_count > 0:
            ratio = online_count / total_count
            hero_stats["network_status"] = "healthy" if ratio >= 0.8 else ("degraded" if ratio >= 0.5 else "critical")

        # Recent alerts from DB
        recent_alerts = []
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, alert_type, severity, title, source, created_at
                       FROM network_alerts
                       ORDER BY created_at DESC LIMIT 10"""
                )
                cols = [d[0] for d in cur.description]
                recent_alerts = [dict(zip(cols, row)) for row in cur.fetchall()]
                for a in recent_alerts:
                    if a.get("created_at"):
                        a["created_at"] = a["created_at"].isoformat()
        except Exception as exc:
            logger.warning("noc alerts query: %s", exc)

        return jsonify(
            {
                "success": True,
                "services": services,
                "hero_stats": hero_stats,
                "recent_alerts": recent_alerts,
            }
        )

    @bp.route("/api/noc/top-consumers")
    @login_required
    @admin_required_decorator
    def noc_top_consumers():
        """Get top bandwidth consumers from Ntopng."""
        try:
            from .ntopng_service import NtopngService

            talkers = NtopngService().get_top_talkers()
            return jsonify({"success": True, "top_consumers": talkers})
        except Exception as exc:
            logger.error("noc_top_consumers error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
