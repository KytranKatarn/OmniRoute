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
                conditions.append("feed_source = %s")
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
                    f"""
                    SELECT id, ioc_type, ioc_value, severity, feed_source,
                           threat_type, first_seen, last_updated
                    FROM threat_intel_iocs
                    {where}
                    ORDER BY last_updated DESC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()

            iocs = [
                {
                    "id": r["id"],
                    "ioc_type": r["ioc_type"],
                    "ioc_value": r["ioc_value"],
                    "severity": r["severity"],
                    "feed_source": r["feed_source"],
                    "threat_type": r["threat_type"],
                    "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                    "last_updated": r["last_updated"].isoformat() if r["last_updated"] else None,
                }
                for r in rows
            ]

            return jsonify({"success": True, "iocs": iocs, "count": len(iocs)})
        except Exception as exc:
            logger.error("threat_intel_iocs error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
