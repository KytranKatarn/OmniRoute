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
            hours = int(request.args.get("hours", 24))
            # 0 = all time, otherwise cap at 8760 (1 year)
            if hours > 0:
                hours = min(hours, 8760)
            time_filter = "AND hour_bucket > NOW() - INTERVAL '%s hours'" % hours if hours > 0 else ""

            with get_db_cursor() as (conn, cur):
                # Top 50 blocked domains by count
                cur.execute(
                    "SELECT domain, SUM(query_count) as block_count, COUNT(DISTINCT device_ip) as unique_devices "
                    "FROM device_dns_history WHERE blocked = true " + time_filter + " AND domain LIKE '%%.%%' "
                    "GROUP BY domain ORDER BY block_count DESC LIMIT 50"
                )
                top_blocked = [dict(row) for row in cur.fetchall()]

                # Category breakdown: join blocked domains against traffic_categories
                cur.execute(
                    "SELECT COALESCE(tc.category, 'uncategorized') AS category, SUM(ddh.query_count) AS block_count "
                    "FROM device_dns_history ddh "
                    "LEFT JOIN traffic_categories tc ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$') "
                    "WHERE ddh.blocked = true "
                    + time_filter.replace("hour_bucket", "ddh.hour_bucket")
                    + " AND ddh.domain LIKE '%%.%%' GROUP BY tc.category ORDER BY block_count DESC"
                )
                categories = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
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

    @bp.route("/api/dns/sinkhole-stats/category", methods=["GET"])
    @login_required
    @admin_required_decorator
    def dns_sinkhole_category_domains():
        """Return blocked domains for a specific category."""
        category = request.args.get("category", "").strip()
        if not category:
            return jsonify({"success": False, "error": "category required"}), 400

        hours = int(request.args.get("hours", 24))
        if hours > 0:
            hours = min(hours, 8760)
        time_filter = "AND ddh.hour_bucket > NOW() - INTERVAL '%s hours'" % hours if hours > 0 else ""

        try:
            with get_db_cursor() as (conn, cur):
                if category == "uncategorized":
                    cur.execute(
                        "SELECT ddh.domain, SUM(ddh.query_count) AS block_count, COUNT(DISTINCT ddh.device_ip) AS unique_devices "
                        "FROM device_dns_history ddh "
                        "LEFT JOIN traffic_categories tc ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$') "
                        "WHERE ddh.blocked = true AND tc.category IS NULL "
                        + time_filter
                        + " AND ddh.domain LIKE '%%.%%' GROUP BY ddh.domain ORDER BY block_count DESC LIMIT 30"
                    )
                else:
                    cur.execute(
                        "SELECT ddh.domain, SUM(ddh.query_count) AS block_count, COUNT(DISTINCT ddh.device_ip) AS unique_devices "
                        "FROM device_dns_history ddh "
                        "JOIN traffic_categories tc ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$') "
                        "WHERE ddh.blocked = true AND tc.category = %s "
                        + time_filter
                        + " AND ddh.domain LIKE '%%.%%' GROUP BY ddh.domain ORDER BY block_count DESC LIMIT 30",
                        (category,),
                    )
                domains = [dict(row) for row in cur.fetchall()]

            return jsonify({"success": True, "category": category, "domains": domains})
        except Exception as e:
            logger.error("[Sinkhole] Category domains failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dns/domain-intel", methods=["GET"])
    @login_required
    @admin_required_decorator
    def dns_domain_intel():
        """Instant intelligence for a domain — history, devices, category, status."""
        domain = request.args.get("domain", "").strip().lower()
        if not domain:
            return jsonify({"success": False, "error": "domain required"}), 400

        result = {
            "domain": domain,
            "total_queries": 0,
            "blocked_queries": 0,
            "first_seen": None,
            "last_seen": None,
            "devices": [],
            "category": "uncategorized",
            "adguard_status": None,
            "hourly": [],
            "last_report": None,
            "report_age": None,
        }

        try:
            with get_db_cursor() as (conn, cur):
                # Aggregate stats
                cur.execute(
                    """SELECT SUM(query_count) as total,
                              SUM(CASE WHEN blocked THEN query_count ELSE 0 END) as blocked,
                              MIN(hour_bucket) as first_seen,
                              MAX(hour_bucket) as last_seen
                       FROM device_dns_history WHERE domain = %s""",
                    (domain,),
                )
                row = cur.fetchone()
                if row:
                    r = dict(row)
                    result["total_queries"] = int(r.get("total") or 0)
                    result["blocked_queries"] = int(r.get("blocked") or 0)
                    result["first_seen"] = r["first_seen"].isoformat() if r.get("first_seen") else None
                    result["last_seen"] = r["last_seen"].isoformat() if r.get("last_seen") else None

                # Per-device breakdown
                cur.execute(
                    """SELECT ddh.device_ip,
                              COALESCE(ndu.user_name, ndu.device_label, ddh.device_ip) as label,
                              SUM(ddh.query_count) as queries,
                              MAX(ddh.hour_bucket) as last_seen
                       FROM device_dns_history ddh
                       LEFT JOIN network_device_users ndu
                           ON ndu.mac_address = (
                               SELECT device_mac FROM network_traffic_stats
                               WHERE device_ip = ddh.device_ip LIMIT 1
                           )
                       WHERE ddh.domain = %s
                       GROUP BY ddh.device_ip, label
                       ORDER BY queries DESC LIMIT 10""",
                    (domain,),
                )
                for row in cur.fetchall():
                    r = dict(row)
                    result["devices"].append(
                        {
                            "ip": r.get("device_ip", ""),
                            "label": r.get("label", r.get("device_ip", "")),
                            "queries": int(r.get("queries") or 0),
                            "last_seen": (r["last_seen"].isoformat() if r.get("last_seen") else None),
                        }
                    )

                # Category from traffic_categories
                base_domain = ".".join(domain.rsplit(".", 2)[-2:])
                cur.execute(
                    "SELECT category FROM traffic_categories WHERE domain_pattern = %s",
                    (base_domain,),
                )
                cat_row = cur.fetchone()
                if cat_row:
                    result["category"] = cat_row["category"]

                # Recent hourly trend for this domain
                cur.execute(
                    """SELECT hour_bucket, query_count, blocked
                       FROM device_dns_history
                       WHERE domain = %s AND hour_bucket >= NOW() - INTERVAL '48 hours'
                       ORDER BY hour_bucket DESC LIMIT 48""",
                    (domain,),
                )
                for row in cur.fetchall():
                    r = dict(row)
                    result["hourly"].append(
                        {
                            "hour": r["hour_bucket"].isoformat() if r.get("hour_bucket") else "",
                            "count": int(r.get("query_count") or 0),
                            "blocked": bool(r.get("blocked")),
                        }
                    )

            # Check AdGuard status
            try:
                import os

                import requests as _req

                ag_host = os.getenv("ADGUARD_HOST", "host.docker.internal")
                ag_port = os.getenv("ADGUARD_PORT", "5354")
                ag_user = os.getenv("ADGUARD_USER", "kytran")
                ag_pass = os.getenv("ADGUARD_PASS", "")
                r = _req.get(
                    f"http://{ag_host}:{ag_port}/control/filtering/check_host",
                    params={"name": domain},
                    auth=(ag_user, ag_pass),
                    timeout=3,
                )
                if r.status_code == 200:
                    result["adguard_status"] = r.json()
            except Exception:
                pass

            # Check for cached AI report in database
            try:
                with get_db_cursor() as (conn2, cur2):
                    cur2.execute(
                        """SELECT report, risk_level, investigated_by,
                                  created_at, updated_at
                           FROM domain_intel_reports WHERE domain = %s""",
                        (domain,),
                    )
                    rpt = cur2.fetchone()
                    if rpt:
                        rpt = dict(rpt)
                        result["last_report"] = rpt.get("report")
                        result["report_risk"] = rpt.get("risk_level", "unknown")
                        result["report_by"] = rpt.get("investigated_by", "AI Bridge")
                        result["report_age"] = rpt["updated_at"].isoformat() if rpt.get("updated_at") else None
            except Exception:
                pass

        except Exception as e:
            logger.error("[Domain Intel] Failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

        return jsonify({"success": True, **result})

    @bp.route("/api/dns/domain-investigate", methods=["POST"])
    @login_required
    @admin_required_decorator
    def dns_domain_investigate():
        """Use AI Bridge to investigate a domain — returns analysis report."""
        data = request.get_json() or {}
        domain = data.get("domain", "").strip().lower()
        if not domain:
            return jsonify({"success": False, "error": "domain required"}), 400

        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError

            from tools.department_hq.services.department_dispatcher import dispatch

            prompt = (
                f"Investigate the domain '{domain}'. Provide a brief security analysis:\n"
                f"1. What is this domain? (company, service, or threat)\n"
                f"2. Is it safe, suspicious, or malicious?\n"
                f"3. What category? (ads/tracking, social, streaming, work, malware, etc.)\n"
                f"4. Should it be blocked or allowed on a home network?\n"
                f"Keep the response under 150 words, be direct."
            )

            # Dispatch through Department HQ — let it assign the right agent
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    dispatch,
                    capability="classify",
                    prompt=prompt,
                    module_id="security_network",
                )
                try:
                    result = future.result(timeout=120)
                except TimeoutError:
                    logger.warning("[Domain Investigate] Dispatch timed out after 120s")
                    return jsonify(
                        {
                            "success": False,
                            "error": "Investigation timed out — AI agents are busy. Try again shortly.",
                            "domain": domain,
                        }
                    )

            if result and result.success:
                # Persist report to database
                try:
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """INSERT INTO domain_intel_reports (domain, report, investigated_by, updated_at)
                               VALUES (%s, %s, %s, NOW())
                               ON CONFLICT (domain) DO UPDATE
                               SET report = EXCLUDED.report,
                                   investigated_by = EXCLUDED.investigated_by,
                                   updated_at = NOW()""",
                            (
                                domain,
                                result.response,
                                getattr(result, "agent_name", "AI Bridge"),
                            ),
                        )
                except Exception as db_err:
                    logger.warning("[Domain Investigate] DB save failed: %s", db_err)

                return jsonify({"success": True, "domain": domain, "report": result.response})
            return jsonify(
                {
                    "success": False,
                    "error": "AI analysis unavailable",
                    "domain": domain,
                }
            )

        except Exception as e:
            logger.error("[Domain Investigate] Failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/dns/query-trend", methods=["GET"])
    @login_required
    @admin_required_decorator
    def dns_query_trend():
        """Hourly/daily DNS query counts for trend chart."""
        try:
            hours = int(request.args.get("hours", 24))
            if hours > 0:
                hours = min(hours, 8760)

            # Use day buckets for >48h, hour for shorter
            bucket = "day" if hours > 48 or hours == 0 else "hour"
            fmt = "%b %d" if bucket == "day" else "%H:%M"

            time_filter = f"WHERE hour_bucket > NOW() - INTERVAL '{hours} hours'" if hours > 0 else "WHERE 1=1"

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT date_trunc('" + bucket + "', hour_bucket) as bucket, "
                    "SUM(query_count) as total, SUM(CASE WHEN blocked THEN query_count ELSE 0 END) as blocked "
                    "FROM device_dns_history " + time_filter + " GROUP BY 1 ORDER BY 1"
                )
                points = []
                for row in cur.fetchall():
                    r = dict(row)
                    points.append(
                        {
                            "label": r["bucket"].strftime(fmt) if r.get("bucket") else "",
                            "total": int(r.get("total") or 0),
                            "blocked": int(r.get("blocked") or 0),
                        }
                    )

            return jsonify({"success": True, "points": points, "bucket": bucket})
        except Exception as e:
            logger.error("[DNS Trend] Failed: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

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
                      AND hour_bucket > NOW() - INTERVAL '%s hours'
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
                      AND ddh.hour_bucket > NOW() - INTERVAL '%s hours'
                      AND EXTRACT(DOW FROM ddh.hour_bucket) BETWEEN 1 AND 5
                      AND EXTRACT(HOUR FROM ddh.hour_bucket) BETWEEN 9 AND 16
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
                           SUM(ddh.query_count) AS query_count
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    WHERE ddh.hour_bucket > NOW() - INTERVAL '%s hours'
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
                           SUM(ddh.query_count) AS query_count,
                           COUNT(DISTINCT ddh.device_ip) AS unique_devices
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    WHERE ddh.hour_bucket > NOW() - INTERVAL '%s hours'
                    GROUP BY tc.category
                    ORDER BY query_count DESC
                    """,
                    (hours,),
                )
                aggregate = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
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
        """Traffic classification grouped by user/device owner."""
        try:
            hours = min(int(request.args.get("hours", 24)), 168)

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT COALESCE(nd.owner, nd.friendly_name, nd.hostname,
                                    ddh.device_ip::text, 'unknown') AS user_name,
                           COALESCE(tc.category, 'uncategorized') AS category,
                           SUM(ddh.query_count) AS queries,
                           COUNT(DISTINCT ddh.device_ip) AS unique_devices
                    FROM device_dns_history ddh
                    LEFT JOIN traffic_categories tc
                        ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                    LEFT JOIN network_devices nd
                        ON nd.ip_address = ddh.device_ip::inet
                    WHERE ddh.hour_bucket > NOW() - INTERVAL '%s hours'
                    GROUP BY user_name, tc.category
                    ORDER BY queries DESC
                    """,
                    (hours,),
                )
                data = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
                    "status": "ok",
                    "hours": hours,
                    "data": data,
                }
            )
        except Exception as e:
            logger.error("[Traffic Classification by User] Failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/traffic/classification/domains", methods=["GET"])
    @login_required
    @admin_required_decorator
    def traffic_classification_domains():
        """Top domains for a specific user + category combination."""
        try:
            hours = min(int(request.args.get("hours", 24)), 168)
            user_filter = request.args.get("user", "")
            category = request.args.get("category", "")

            with get_db_cursor() as (conn, cur):
                if category and category != "uncategorized":
                    cur.execute(
                        """
                        SELECT ddh.domain,
                               SUM(ddh.query_count) AS queries,
                               bool_or(ddh.blocked) AS ever_blocked
                        FROM device_dns_history ddh
                        JOIN traffic_categories tc
                            ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                        LEFT JOIN network_devices nd
                            ON nd.ip_address = ddh.device_ip::inet
                        WHERE ddh.hour_bucket > NOW() - INTERVAL '%s hours'
                          AND tc.category = %s
                          AND COALESCE(nd.owner, nd.friendly_name, nd.hostname,
                                       ddh.device_ip::text, 'unknown') = %s
                        GROUP BY ddh.domain
                        ORDER BY queries DESC
                        LIMIT 50
                        """,
                        (hours, category, user_filter),
                    )
                else:
                    # Uncategorized = domains NOT in traffic_categories
                    cur.execute(
                        """
                        SELECT ddh.domain,
                               SUM(ddh.query_count) AS queries,
                               bool_or(ddh.blocked) AS ever_blocked
                        FROM device_dns_history ddh
                        LEFT JOIN traffic_categories tc
                            ON tc.domain_pattern = SUBSTRING(ddh.domain FROM '([^.]+\\.[^.]+)$')
                        LEFT JOIN network_devices nd
                            ON nd.ip_address = ddh.device_ip::inet
                        WHERE ddh.hour_bucket > NOW() - INTERVAL '%s hours'
                          AND tc.category IS NULL
                          AND COALESCE(nd.owner, nd.friendly_name, nd.hostname,
                                       ddh.device_ip::text, 'unknown') = %s
                        GROUP BY ddh.domain
                        ORDER BY queries DESC
                        LIMIT 50
                        """,
                        (hours, user_filter),
                    )
                domains = [dict(row) for row in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
                    "user": user_filter,
                    "category": category or "uncategorized",
                    "hours": hours,
                    "domains": domains,
                }
            )
        except Exception as e:
            logger.error("[Traffic Classification Domains] Failed: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/traffic/classification/reclassify", methods=["POST"])
    @login_required
    @admin_required_decorator
    def traffic_reclassify_domain():
        """Add or update a domain's category in traffic_categories."""
        data = request.get_json(silent=True) or {}
        domain_pattern = data.get("domain_pattern", "").strip().lower()
        category = data.get("category", "").strip().lower()

        if not domain_pattern or not category:
            return jsonify({"success": False, "message": "domain_pattern and category required"}), 400

        valid_cats = [
            "work",
            "social",
            "streaming",
            "gaming",
            "shopping",
            "ads",
            "adult",
            "infrastructure",
        ]
        if category not in valid_cats:
            return jsonify({"success": False, "message": f"Invalid category. Use: {', '.join(valid_cats)}"}), 400

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO traffic_categories (domain_pattern, category, source)
                    VALUES (%s, %s, 'manual')
                    ON CONFLICT (domain_pattern)
                    DO UPDATE SET category = EXCLUDED.category, source = 'manual'
                    """,
                    (domain_pattern, category),
                )
            logger.info("Reclassified %s -> %s", domain_pattern, category)
            return jsonify({"success": True, "domain_pattern": domain_pattern, "category": category})
        except Exception as e:
            logger.error("[Reclassify Domain] Failed: %s", e)
            return jsonify({"success": False, "message": str(e)}), 500
