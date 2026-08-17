"""
Analytics Routes — Blocked domain analytics and device behavior insights.
"""

import logging
from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)

DOMAIN_CATEGORIES = {
    "social": [
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "tiktok.com",
        "snapchat.com",
        "reddit.com",
        "linkedin.com",
        "pinterest.com",
    ],
    "streaming": [
        "netflix.com",
        "youtube.com",
        "twitch.tv",
        "disney.com",
        "hulu.com",
        "spotify.com",
        "plex.tv",
        "primevideo.com",
    ],
    "gaming": [
        "epicgames.com",
        "steampowered.com",
        "roblox.com",
        "xbox.com",
        "playstation.com",
        "ea.com",
        "riot.com",
        "blizzard.com",
    ],
    "work": [
        "microsoft.com",
        "office.com",
        "teams.microsoft.com",
        "slack.com",
        "zoom.us",
        "cae.com",
        "salesforce.com",
        "atlassian.com",
    ],
    "shopping": [
        "amazon.com",
        "ebay.com",
        "shopify.com",
        "etsy.com",
        "walmart.com",
        "bestbuy.com",
    ],
    "search": [
        "google.com",
        "bing.com",
        "duckduckgo.com",
        "yahoo.com",
    ],
    "cloud": [
        "amazonaws.com",
        "azure.com",
        "cloudflare.com",
        "akamai.net",
        "digitalocean.com",
        "linode.com",
    ],
}


def _categorize_domain(domain):
    """Classify a domain into a category using substring matching."""
    domain_lower = domain.lower()
    for category, patterns in DOMAIN_CATEGORIES.items():
        for pattern in patterns:
            if pattern in domain_lower:
                return category
    return "other"


def _get_days_param():
    """Extract and validate the days query parameter (default 7, max 90)."""
    try:
        days = int(request.args.get("days", 7))
        return max(1, min(days, 90))
    except (ValueError, TypeError):
        return 7


def register_analytics_routes(bp, admin_required_decorator):
    """Register analytics endpoints on the security_network blueprint."""

    @bp.route("/api/analytics/blocked-domains")
    @login_required
    @admin_required_decorator
    def analytics_blocked_domains():
        """Top blocked domains across all devices."""
        days = _get_days_param()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT domain,
                           SUM(query_count)::int AS total_queries,
                           COUNT(DISTINCT device_ip) AS affected_devices
                    FROM device_dns_history
                    WHERE blocked = true
                      AND hour_bucket >= NOW() - INTERVAL '%s days'
                    GROUP BY domain
                    ORDER BY total_queries DESC
                    LIMIT 50
                    """,
                    (days,),
                )
                rows = cur.fetchall()
            return jsonify({"days": days, "domains": [dict(r) for r in rows]})
        except Exception as e:
            logger.exception("analytics_blocked_domains failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/analytics/noisy-devices")
    @login_required
    @admin_required_decorator
    def analytics_noisy_devices():
        """Devices with the most blocked queries (potential malware/misconfigured)."""
        days = _get_days_param()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT ddh.device_ip,
                           ndu.device_label,
                           ndu.user_name,
                           SUM(ddh.query_count)::int AS total_blocked,
                           COUNT(DISTINCT ddh.domain) AS unique_blocked_domains
                    FROM device_dns_history ddh
                    LEFT JOIN network_device_users ndu
                        ON ndu.mac_address = (
                            SELECT device_mac
                            FROM network_traffic_stats
                            WHERE device_ip = ddh.device_ip
                            LIMIT 1
                        )
                    WHERE ddh.blocked = true
                      AND ddh.hour_bucket >= NOW() - INTERVAL '%s days'
                    GROUP BY ddh.device_ip, ndu.device_label, ndu.user_name
                    ORDER BY total_blocked DESC
                    LIMIT 20
                    """,
                    (days,),
                )
                rows = cur.fetchall()
            return jsonify({"days": days, "devices": [dict(r) for r in rows]})
        except Exception as e:
            logger.exception("analytics_noisy_devices failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/analytics/device-categories")
    @login_required
    @admin_required_decorator
    def analytics_device_categories():
        """Per-device breakdown of domain categories visited."""
        days = _get_days_param()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT device_ip, domain, SUM(query_count)::int AS queries
                    FROM device_dns_history
                    WHERE hour_bucket >= NOW() - INTERVAL '%s days'
                    GROUP BY device_ip, domain
                    """,
                    (days,),
                )
                rows = cur.fetchall()

            # Build per-device category totals
            device_cats = {}
            for row in rows:
                ip = row["device_ip"]
                cat = _categorize_domain(row["domain"])
                if ip not in device_cats:
                    device_cats[ip] = {}
                device_cats[ip][cat] = device_cats[ip].get(cat, 0) + row["queries"]

            result = []
            for ip, cats in device_cats.items():
                result.append({"device_ip": ip, "categories": cats})
            result.sort(key=lambda d: sum(d["categories"].values()), reverse=True)

            return jsonify({"days": days, "devices": result[:50]})
        except Exception as e:
            logger.exception("analytics_device_categories failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/analytics/hourly-patterns")
    @login_required
    @admin_required_decorator
    def analytics_hourly_patterns():
        """Activity heatmap data - queries per device per hour of day."""
        days = _get_days_param()
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT device_ip,
                           EXTRACT(HOUR FROM hour_bucket)::int AS hour,
                           SUM(query_count)::int AS queries
                    FROM device_dns_history
                    WHERE hour_bucket >= NOW() - INTERVAL '%s days'
                    GROUP BY device_ip, EXTRACT(HOUR FROM hour_bucket)
                    ORDER BY device_ip, hour
                    """,
                    (days,),
                )
                rows = cur.fetchall()

            # Group by device
            devices = {}
            for row in rows:
                ip = row["device_ip"]
                if ip not in devices:
                    devices[ip] = [0] * 24
                devices[ip][row["hour"]] = row["queries"]

            result = [{"device_ip": ip, "hours": hours} for ip, hours in sorted(devices.items())]
            return jsonify({"days": days, "devices": result})
        except Exception as e:
            logger.exception("analytics_hourly_patterns failed")
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/analytics/threat-summary")
    @login_required
    @admin_required_decorator
    def analytics_threat_summary():
        """Overview of security-relevant findings (high unique blocked domains)."""
        days = _get_days_param()
        try:
            with get_db_cursor() as (conn, cur):
                # Devices with >10 unique blocked domains in the period
                cur.execute(
                    """
                    SELECT device_ip,
                           COUNT(DISTINCT domain) AS unique_blocked,
                           SUM(query_count)::int AS total_blocked
                    FROM device_dns_history
                    WHERE blocked = true
                      AND hour_bucket >= NOW() - INTERVAL '%s days'
                    GROUP BY device_ip
                    HAVING COUNT(DISTINCT domain) > 10
                    ORDER BY unique_blocked DESC
                    """,
                    (days,),
                )
                flagged_devices = cur.fetchall()

                # Overall totals for context
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT device_ip) AS total_devices,
                           COUNT(DISTINCT domain) AS total_blocked_domains,
                           COALESCE(SUM(query_count), 0)::int AS total_blocked_queries
                    FROM device_dns_history
                    WHERE blocked = true
                      AND hour_bucket >= NOW() - INTERVAL '%s days'
                    """,
                    (days,),
                )
                totals = dict(cur.fetchone())

            return jsonify(
                {
                    "days": days,
                    "totals": totals,
                    "flagged_devices": [dict(r) for r in flagged_devices],
                }
            )
        except Exception as e:
            logger.exception("analytics_threat_summary failed")
            return jsonify({"error": str(e)}), 500
