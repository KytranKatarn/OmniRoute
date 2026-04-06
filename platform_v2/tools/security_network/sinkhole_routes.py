"""
Sinkhole & Traffic Classification Routes — DNS sinkhole analytics,
VPN leak detection, and traffic categorization.
ADR-045 pattern: register_sinkhole_routes(bp, admin_required_decorator)
"""

import logging
from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)


def register_sinkhole_routes(bp, admin_required_decorator):
    """Register DNS sinkhole and traffic classification endpoints."""

    @bp.route("/api/dns/sinkhole-stats", methods=["GET"])
    @login_required
    @admin_required_decorator
    def dns_sinkhole_stats():
        """Top blocked domains from device_dns_history with category breakdown."""
        try:
            hours = min(int(request.args.get("hours", 24)), 168)  # max 7 days

            with get_db_cursor() as (conn, cur):
                # Top 50 blocked domains by count
                cur.execute(
                    """
                    SELECT domain, COUNT(*) as block_count,
                           COUNT(DISTINCT device_ip) as unique_devices
                    FROM device_dns_history
                    WHERE blocked = true
                      AND queried_at > NOW() - INTERVAL '%s hours'
                    GROUP BY domain
                    ORDER BY block_count DESC
                    LIMIT 50
                    """,
                    (hours,),
                )
                top_blocked = [dict(row) for row in cur.fetchall()]

                # Category breakdown: join blocked domains against traffic_categories
                cur.execute(
                    """
                    SELECT COALESCE(tc.category, 'uncategorized') AS category,
                           COUNT(*) AS block_count
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    WHERE ddh.blocked = true
                      AND ddh.queried_at > NOW() - INTERVAL '%s hours'
                    GROUP BY tc.category
                    ORDER BY block_count DESC
                    """,
                    (hours,),
                )
                categories = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "status": "ok",
                    "hours": hours,
                    "top_blocked": top_blocked,
                    "categories": categories,
                    "total_blocked": sum(d["block_count"] for d in top_blocked),
                }
            )
        except Exception as e:
            logger.error("[Sinkhole] Stats failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/dns/vpn-leak-check", methods=["GET"])
    @login_required
    @admin_required_decorator
    def dns_vpn_leak_check():
        """Detect VPN split-tunnel DNS leaks.

        Logic:
        1. Find devices querying VPN-related domains (cae.com, cae.ca).
        2. Check if those same devices also query public DNS or non-VPN domains
           during work hours (weekdays 9-17).
        3. Return potential leak devices with evidence.
        """
        try:
            hours = min(int(request.args.get("hours", 48)), 168)

            with get_db_cursor() as (conn, cur):
                # Step 1: Devices that query VPN-related domains
                cur.execute(
                    """
                    SELECT DISTINCT device_ip
                    FROM device_dns_history
                    WHERE (domain LIKE '%%cae.com' OR domain LIKE '%%cae.ca')
                      AND queried_at > NOW() - INTERVAL '%s hours'
                    """,
                    (hours,),
                )
                vpn_devices = [row["device_ip"] for row in cur.fetchall()]

                if not vpn_devices:
                    return jsonify(
                        {
                            "status": "ok",
                            "leak_devices": [],
                            "message": "No VPN devices detected in timeframe",
                        }
                    )

                # Step 2: Check for non-VPN queries during work hours from those devices
                cur.execute(
                    """
                    SELECT ddh.device_ip,
                           COUNT(*) AS non_vpn_queries,
                           ARRAY_AGG(DISTINCT ddh.domain ORDER BY ddh.domain) AS sample_domains
                    FROM device_dns_history ddh
                    WHERE ddh.device_ip = ANY(%s)
                      AND ddh.domain NOT LIKE '%%cae.com'
                      AND ddh.domain NOT LIKE '%%cae.ca'
                      AND ddh.domain NOT LIKE '%%internal%%'
                      AND ddh.queried_at > NOW() - INTERVAL '%s hours'
                      AND EXTRACT(DOW FROM ddh.queried_at) BETWEEN 1 AND 5
                      AND EXTRACT(HOUR FROM ddh.queried_at) BETWEEN 9 AND 16
                    GROUP BY ddh.device_ip
                    HAVING COUNT(*) > 5
                    ORDER BY non_vpn_queries DESC
                    """,
                    (vpn_devices, hours),
                )
                leak_candidates = []
                for row in cur.fetchall():
                    domains = row["sample_domains"] or []
                    leak_candidates.append(
                        {
                            "device_ip": row["device_ip"],
                            "non_vpn_queries": row["non_vpn_queries"],
                            "sample_domains": domains[:20],  # cap sample size
                        }
                    )

            return jsonify(
                {
                    "status": "ok",
                    "vpn_devices_checked": len(vpn_devices),
                    "leak_devices": leak_candidates,
                    "hours": hours,
                }
            )
        except Exception as e:
            logger.error("[VPN Leak Check] Failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/traffic/classification", methods=["GET"])
    @login_required
    @admin_required_decorator
    def traffic_classification():
        """Classify DNS traffic by category using traffic_categories table.

        Joins device_dns_history (last 24h) against traffic_categories
        on base domain extraction.
        """
        try:
            hours = min(int(request.args.get("hours", 24)), 168)

            with get_db_cursor() as (conn, cur):
                # Per-device category breakdown
                cur.execute(
                    """
                    SELECT ddh.device_ip,
                           COALESCE(tc.category, 'uncategorized') AS category,
                           COUNT(*) AS query_count
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    WHERE ddh.queried_at > NOW() - INTERVAL '%s hours'
                    GROUP BY ddh.device_ip, tc.category
                    ORDER BY query_count DESC
                    """,
                    (hours,),
                )
                per_device = [dict(row) for row in cur.fetchall()]

                # Aggregate category totals
                cur.execute(
                    """
                    SELECT COALESCE(tc.category, 'uncategorized') AS category,
                           COUNT(*) AS query_count,
                           COUNT(DISTINCT ddh.device_ip) AS unique_devices
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    WHERE ddh.queried_at > NOW() - INTERVAL '%s hours'
                    GROUP BY tc.category
                    ORDER BY query_count DESC
                    """,
                    (hours,),
                )
                aggregate = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "status": "ok",
                    "hours": hours,
                    "per_device": per_device,
                    "aggregate": aggregate,
                }
            )
        except Exception as e:
            logger.error("[Traffic Classification] Failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/traffic/classification/by-user", methods=["GET"])
    @login_required
    @admin_required_decorator
    def traffic_classification_by_user():
        """Traffic classification grouped by user from network_device_users."""
        try:
            hours = min(int(request.args.get("hours", 24)), 168)

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT COALESCE(ndu.user_name, 'unknown') AS user_name,
                           COALESCE(tc.category, 'uncategorized') AS category,
                           COUNT(*) AS query_count,
                           COUNT(DISTINCT ddh.device_ip) AS unique_devices
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    LEFT JOIN network_device_users ndu
                        ON ndu.device_ip = ddh.device_ip
                    WHERE ddh.queried_at > NOW() - INTERVAL '%s hours'
                    GROUP BY ndu.user_name, tc.category
                    ORDER BY query_count DESC
                    """,
                    (hours,),
                )
                by_user = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "status": "ok",
                    "hours": hours,
                    "by_user": by_user,
                }
            )
        except Exception as e:
            logger.error("[Traffic Classification by User] Failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500
