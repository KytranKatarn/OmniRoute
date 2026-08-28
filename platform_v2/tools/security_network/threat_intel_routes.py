"""
Threat Intelligence Routes
==========================
API endpoints for IOC feed sync, hit detection, and threat browsing.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_threat_intel_routes(bp, admin_required_decorator):
    """Register all threat-intel endpoints on the security_network blueprint."""

    @bp.route("/api/threat-intel/status")
    @login_required
    @admin_required_decorator
    def threat_intel_status():
        """Feed sync status and IOC counts."""
        try:
            from .threat_intel_service import ThreatIntelService

            svc = ThreatIntelService()
            status = svc.get_feed_status()
            return jsonify({"success": True, "feeds": status})
        except Exception as exc:
            logger.error("threat_intel_status error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/hits")
    @login_required
    @admin_required_decorator
    def threat_intel_hits():
        """Recent threat hits with optional filters."""
        try:
            from .threat_intel_service import ThreatIntelService

            limit = request.args.get("limit", 50, type=int)
            limit = min(max(limit, 1), 500)

            svc = ThreatIntelService()
            hits = svc.get_recent_hits(limit=limit)

            # Optional device_ip filter
            device_ip = request.args.get("device_ip")
            if device_ip:
                hits = [h for h in hits if h["device_ip"] == device_ip]

            return jsonify({"success": True, "hits": hits, "count": len(hits)})
        except Exception as exc:
            logger.error("threat_intel_hits error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/sync", methods=["POST"])
    @login_required
    @admin_required_decorator
    def threat_intel_sync():
        """Trigger manual feed sync and hit check."""
        try:
            from .threat_intel_service import ThreatIntelService

            svc = ThreatIntelService()
            sync_result = svc.sync_feeds()
            new_hits = svc.check_hits()

            return jsonify(
                {
                    "success": True,
                    "sync": sync_result,
                    "new_hits": len(new_hits),
                    "hits": new_hits,
                }
            )
        except Exception as exc:
            logger.error("threat_intel_sync error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/iocs")
    @login_required
    @admin_required_decorator
    def threat_intel_iocs():
        """List IOCs with optional filters."""
        try:
            from database import get_db_cursor

            feed = request.args.get("feed")
            ioc_type = request.args.get("type")
            severity = request.args.get("severity")
            limit = request.args.get("limit", 100, type=int)
            limit = min(max(limit, 1), 1000)

            conditions = []
            params = []

            if feed:
                conditions.append("feed_name = %s")
                params.append(feed)
            if ioc_type:
                conditions.append("ioc_type = %s")
                params.append(ioc_type)
            if severity:
                conditions.append("severity = %s")
                params.append(severity)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            params.append(limit)

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT id, ioc_type, ioc_value, severity, feed_name, "
                    "description, first_seen, last_updated "
                    "FROM threat_intel_iocs " + where + " ORDER BY last_updated DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()

            iocs = [
                {
                    "id": r["id"],
                    "ioc_type": r["ioc_type"],
                    "ioc_value": r["ioc_value"],
                    "severity": r["severity"],
                    "feed_source": r["feed_name"],
                    "description": r["description"],
                    "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                    "last_updated": r["last_updated"].isoformat() if r["last_updated"] else None,
                }
                for r in rows
            ]

            return jsonify({"success": True, "iocs": iocs, "count": len(iocs)})
        except Exception as exc:
            logger.error("threat_intel_iocs error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/dns-crossref")
    @login_required
    @admin_required_decorator
    def threat_intel_dns_crossref():
        """Cross-reference AdGuard blocked domains against IOC feeds."""
        try:
            from .adguard_service import AdGuardService
            from database import get_db_cursor

            adguard = AdGuardService()
            stats = adguard.get_stats() or {}

            # Get blocked domains from AdGuard
            blocked_domains = []
            for item in stats.get("top_blocked_domains") or []:
                for domain, count in item.items():
                    blocked_domains.append({"domain": domain, "count": count})

            # Cross-reference with IOC database
            matches = []
            if blocked_domains:
                with get_db_cursor() as (conn, cur):
                    for bd in blocked_domains[:50]:
                        cur.execute(
                            """SELECT ioc_value, severity, feed_name, description
                               FROM threat_intel_iocs
                               WHERE ioc_type = 'domain'
                                 AND (ioc_value = %s OR %s LIKE '%%.' || ioc_value)
                               LIMIT 1""",
                            (bd["domain"], bd["domain"]),
                        )
                        row = cur.fetchone()
                        if row:
                            matches.append(
                                {
                                    "domain": bd["domain"],
                                    "blocked_count": bd["count"],
                                    "ioc_match": row["ioc_value"],
                                    "severity": row["severity"],
                                    "feed": row["feed_name"],
                                    "threat_type": row["description"],
                                }
                            )

            dns_blocked = stats.get("num_blocked_filtering", 0)

            return jsonify(
                {
                    "success": True,
                    "dns_blocked_24h": dns_blocked,
                    "total_blocked_domains": len(blocked_domains),
                    "ioc_matches": matches,
                    "match_count": len(matches),
                }
            )
        except Exception as exc:
            logger.error("dns-crossref error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/search")
    @login_required
    @admin_required_decorator
    def threat_intel_search():
        """Search IOC database for a specific domain or IP."""
        try:
            from database import get_db_cursor

            query = request.args.get("q", "").strip()
            if not query or len(query) < 3:
                return jsonify({"success": False, "error": "Query must be at least 3 characters"})

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, ioc_type, ioc_value, severity, feed_name,
                              description, first_seen, last_updated
                       FROM threat_intel_iocs
                       WHERE ioc_value LIKE %s
                       ORDER BY last_updated DESC LIMIT 20""",
                    (f"%{query}%",),
                )
                rows = cur.fetchall()

            results = [
                {
                    "ioc_value": r["ioc_value"],
                    "ioc_type": r["ioc_type"],
                    "severity": r["severity"],
                    "feed": r["feed_name"],
                    "description": r["description"],
                }
                for r in rows
            ]
            return jsonify({"success": True, "results": results, "count": len(results)})
        except Exception as exc:
            logger.error("threat-intel search error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/scan-querylog", methods=["POST"])
    @login_required
    @admin_required_decorator
    def threat_intel_scan_querylog():
        """Scan AdGuard query log against IOC database — finds threats AdGuard didn't block."""
        try:
            from .adguard_service import AdGuardService
            from database import get_db_cursor

            adguard = AdGuardService()
            query_log = adguard.get_query_log(limit=500) or {}
            entries = query_log.get("data") or []

            # Extract unique domains from query log
            queried_domains = set()
            for entry in entries:
                domain = entry.get("question", {}).get("name", "")
                if domain:
                    queried_domains.add(domain)

            # Check against IOC database
            threats_found = []
            if queried_domains:
                with get_db_cursor() as (conn, cur):
                    for domain in queried_domains:
                        cur.execute(
                            """SELECT ioc_value, severity, feed_name, description
                               FROM threat_intel_iocs
                               WHERE ioc_type = 'domain'
                                 AND (ioc_value = %s OR %s LIKE '%%.' || ioc_value)
                               LIMIT 1""",
                            (domain, domain),
                        )
                        row = cur.fetchone()
                        if row:
                            threats_found.append(
                                {
                                    "domain": domain,
                                    "ioc_match": row["ioc_value"],
                                    "severity": row["severity"],
                                    "feed": row["feed_name"],
                                    "threat_type": row["description"],
                                }
                            )

            return jsonify(
                {
                    "success": True,
                    "domains_scanned": len(queried_domains),
                    "threats_found": threats_found,
                    "threat_count": len(threats_found),
                }
            )
        except Exception as exc:
            logger.error("scan-querylog error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/auto-block", methods=["POST"])
    @login_required
    @admin_required_decorator
    def threat_intel_auto_block():
        """Auto-block IOC domains via AdGuard user rules."""
        try:
            from .adguard_service import AdGuardService
            from database import get_db_cursor

            adguard = AdGuardService()
            severity_filter = request.get_json(silent=True) or {}
            min_severity = severity_filter.get("min_severity", "high")

            sev_levels = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            min_level = sev_levels.get(min_severity, 3)

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT DISTINCT ioc_value FROM threat_intel_iocs
                       WHERE ioc_type = 'domain'"""
                )
                cur.fetchall()

            # Filter by severity and get current rules
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT ioc_value, severity FROM threat_intel_iocs
                       WHERE ioc_type = 'domain'"""
                )
                domain_iocs = [r for r in cur.fetchall() if sev_levels.get(r["severity"], 0) >= min_level]

            blocked = 0
            for ioc in domain_iocs[:100]:
                result = adguard.block_domain(ioc["ioc_value"])
                if result:
                    blocked += 1

            return jsonify(
                {
                    "success": True,
                    "blocked": blocked,
                    "total_eligible": len(domain_iocs),
                    "min_severity": min_severity,
                }
            )
        except Exception as exc:
            logger.error("auto-block error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/threat-intel/severity-stats")
    @login_required
    @admin_required_decorator
    def threat_intel_severity_stats():
        """IOC count breakdown by severity for chart rendering."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT severity, COUNT(*) AS cnt
                       FROM threat_intel_iocs
                       GROUP BY severity ORDER BY cnt DESC"""
                )
                rows = cur.fetchall()

                cur.execute("SELECT COUNT(*) AS total FROM threat_intel_iocs")
                total = cur.fetchone()["total"]

            breakdown = [{"severity": r["severity"], "count": r["cnt"]} for r in rows]
            return jsonify({"success": True, "total": total, "breakdown": breakdown})
        except Exception as exc:
            logger.error("severity-stats error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
