"""
NOC Overview API Routes
=======================
Network Operations Center aggregation endpoints.
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
        """Aggregate status from all security services for the NOC dashboard."""
        services = {}
        hero_stats = {
            "dns_queries_24h": 0,
            "threats_blocked_24h": 0,
            "traffic_bytes": 0,
            "currently_banned": 0,
            "network_status": "unknown",
        }
        recent_alerts = []

        # AdGuard
        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()
            ag_status = ag.get_status()
            services["adguard"] = {"status": "online" if ag_status else "offline"}
            stats = ag.get_stats() or {}
            hero_stats["dns_queries_24h"] = stats.get("num_dns_queries", 0)
            hero_stats["threats_blocked_24h"] = stats.get("num_blocked_filtering", 0)
        except Exception as exc:
            logger.warning("noc_overview adguard error: %s", exc)
            services["adguard"] = {"status": "error"}

        # Ntopng
        try:
            from .ntopng_service import NtopngService

            nt = NtopngService()
            nt_healthy = nt.is_healthy()
            services["ntopng"] = {"status": "online" if nt_healthy else "offline"}
            if nt_healthy:
                iface_stats = nt.get_interface_stats(0) or {}
                hero_stats["traffic_bytes"] = iface_stats.get("bytes", 0)
        except Exception as exc:
            logger.warning("noc_overview ntopng error: %s", exc)
            services["ntopng"] = {"status": "error"}

        # Nagios
        try:
            from .nagios_service import NagiosService

            nag = NagiosService()
            nag_healthy = nag.is_healthy()
            services["nagios"] = {"status": "online" if nag_healthy else "offline"}
            if nag_healthy:
                counts = nag.get_host_count()
                hero_stats["nagios_hosts_up"] = counts.get("data", {}).get("count", {}).get("up", 0)
        except Exception as exc:
            logger.warning("noc_overview nagios error: %s", exc)
            services["nagios"] = {"status": "error"}

        # Fail2ban
        try:
            from .fail2ban_service import Fail2banService

            fb = Fail2banService()
            fb_status = fb.get_status()
            services["fail2ban"] = {"status": "online" if fb_status else "offline"}
            all_jails = fb.get_all_jail_statuses() or []
            total_banned = sum(j.get("currently_banned", 0) for j in all_jails if isinstance(j, dict))
            hero_stats["currently_banned"] = total_banned
        except Exception as exc:
            logger.warning("noc_overview fail2ban error: %s", exc)
            services["fail2ban"] = {"status": "error"}

        # DDNS
        try:
            from .ddns_service import DdnsService

            ddns = DdnsService()
            ddns_status = ddns.get_status()
            services["ddns"] = {"status": "online" if ddns_status else "offline"}
        except Exception as exc:
            logger.warning("noc_overview ddns error: %s", exc)
            services["ddns"] = {"status": "error"}

        # UFW (via host command client)
        try:
            from .security_service import get_firewall_status

            fw = get_firewall_status()
            services["ufw"] = {"status": "online" if fw.get("enabled") or fw.get("status") == "active" else "offline"}
        except Exception as exc:
            logger.warning("noc_overview ufw error: %s", exc)
            services["ufw"] = {"status": "error"}

        # Derive overall network status
        online_count = sum(1 for s in services.values() if s.get("status") == "online")
        total_count = len(services)
        if total_count > 0:
            ratio = online_count / total_count
            hero_stats["network_status"] = "healthy" if ratio >= 0.8 else ("degraded" if ratio >= 0.5 else "critical")

        # Recent alerts from DB
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, alert_type, severity, message, created_at
                    FROM network_alerts
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                )
                rows = cur.fetchall()
                for row in rows:
                    recent_alerts.append(
                        {
                            "id": row[0],
                            "alert_type": row[1],
                            "severity": row[2],
                            "message": row[3],
                            "created_at": row[4].isoformat() if row[4] else None,
                        }
                    )
        except Exception as exc:
            logger.warning("noc_overview alerts query error: %s", exc)

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
