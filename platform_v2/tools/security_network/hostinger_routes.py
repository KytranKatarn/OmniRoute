"""
Hostinger DNS Management Routes
================================
REST endpoints for Hostinger DNS record CRUD — list records, add, update,
delete, and domain portfolio listing.
"""

import logging

from flask import jsonify, request
from flask_login import login_required
from database import get_db_cursor
from .security_alerts import create_security_alert

logger = logging.getLogger(__name__)

# Import Hostinger DNS service
try:
    from .hostinger_service import HostingerService

    hostinger_service = HostingerService()
    HOSTINGER_SERVICE_AVAILABLE = hostinger_service.available
except ImportError:
    hostinger_service = None
    HOSTINGER_SERVICE_AVAILABLE = False


def register_hostinger_routes(bp, admin_required_decorator):
    """Register all Hostinger DNS endpoints on the security_network blueprint."""

    @bp.route("/api/dns/hostinger/records")
    @login_required
    @admin_required_decorator
    def api_dns_hostinger_records_get():
        """List Hostinger DNS records"""
        if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
            return jsonify({"success": False, "error": "Hostinger service not available"}), 503

        domain = request.args.get("domain")

        try:
            result = hostinger_service.get_dns_records(domain)
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch DNS records"}), 503
            if isinstance(result, dict) and "error" in result:
                return jsonify({"success": False, "error": result["error"]}), 500
            return jsonify({"success": True, "records": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/hostinger/records", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_hostinger_records_add():
        """Add a Hostinger DNS record"""
        if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
            return jsonify({"success": False, "error": "Hostinger service not available"}), 503

        data = request.get_json() or {}
        record_type = data.get("record_type", "")
        name = data.get("name", "")
        content = data.get("content", "")
        ttl = data.get("ttl", 3600)
        domain = data.get("domain")

        if not record_type or not name or not content:
            return jsonify({"success": False, "error": "record_type, name, and content are required"}), 400

        try:
            result = hostinger_service.add_dns_record(record_type, name, content, ttl, domain)
            if result is None:
                return jsonify({"success": False, "error": "Failed to add DNS record"}), 500
            if isinstance(result, dict) and "error" in result:
                return jsonify({"success": False, "error": result["error"]}), 500

            create_security_alert(
                "dns_change",
                f"DNS Record Added: {name}",
                f"New {record_type} record added: {name} -> {content} (TTL: {ttl})",
                priority="normal",
            )

            try:
                from psycopg2.extras import Json

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "INSERT INTO security_dns_changes (source, action, domain, details, changed_by, created_at) VALUES ('hostinger', 'add', %s, %s, 'user', NOW())",
                        (
                            domain or name,
                            Json({"record_type": record_type, "name": name, "content": content, "ttl": ttl}),
                        ),
                    )
            except Exception as e:
                logger.debug("Failed to log DNS add change: %s", e)

            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/hostinger/records/<record_id>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def api_dns_hostinger_records_update(record_id):
        """Update a Hostinger DNS record"""
        if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
            return jsonify({"success": False, "error": "Hostinger service not available"}), 503

        data = request.get_json() or {}
        domain = data.get("domain")
        record_type = data.get("record_type", "")
        name = data.get("name", "")
        content = data.get("content", "")
        ttl = data.get("ttl", 3600)

        if not record_type or not name or not content:
            return jsonify({"success": False, "error": "record_type, name, and content are required"}), 400

        try:
            records = [{"type": record_type, "name": name, "content": content, "ttl": ttl}]
            result = hostinger_service.update_dns_records_bulk(records, overwrite=False, domain=domain)
            if result is None:
                return jsonify({"success": False, "error": "Failed to update DNS record"}), 500
            if isinstance(result, dict) and "error" in result:
                return jsonify({"success": False, "error": result["error"]}), 500

            create_security_alert(
                "dns_change",
                f"DNS Record Updated: {name}",
                f"Updated {record_type} record: {name} -> {content}",
                priority="normal",
            )

            try:
                from psycopg2.extras import Json

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "INSERT INTO security_dns_changes (source, action, domain, details, changed_by, created_at) VALUES ('hostinger', 'update', %s, %s, 'user', NOW())",
                        (
                            domain or name,
                            Json(
                                {
                                    "record_id": record_id,
                                    "record_type": record_type,
                                    "name": name,
                                    "content": content,
                                    "ttl": ttl,
                                }
                            ),
                        ),
                    )
            except Exception as e:
                logger.debug("Failed to log DNS update change: %s", e)

            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/hostinger/records/<record_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_dns_hostinger_records_delete(record_id):
        """Delete a Hostinger DNS record"""
        if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
            return jsonify({"success": False, "error": "Hostinger service not available"}), 503

        data = request.get_json() or {}
        domain = data.get("domain")
        record_type = data.get("record_type")
        name = data.get("name")

        try:
            result = hostinger_service.delete_dns_records(record_type, name, domain)
            if result is None:
                return jsonify({"success": False, "error": "Failed to delete DNS record"}), 500
            if isinstance(result, dict) and "error" in result:
                return jsonify({"success": False, "error": result["error"]}), 500

            try:
                from psycopg2.extras import Json

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "INSERT INTO security_dns_changes (source, action, domain, details, changed_by, created_at) VALUES ('hostinger', 'delete', %s, %s, 'user', NOW())",
                        (
                            domain or name or "unknown",
                            Json({"record_id": record_id, "record_type": record_type, "name": name}),
                        ),
                    )
            except Exception as e:
                logger.debug("Failed to log DNS delete change: %s", e)

            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/hostinger/domains")
    @login_required
    @admin_required_decorator
    def api_dns_hostinger_domains():
        """List Hostinger domain portfolio"""
        if not HOSTINGER_SERVICE_AVAILABLE or not hostinger_service:
            return jsonify({"success": False, "error": "Hostinger service not available"}), 503

        try:
            result = hostinger_service.get_domain_list()
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch domain list"}), 503
            if isinstance(result, dict) and "error" in result:
                return jsonify({"success": False, "error": result["error"]}), 500
            return jsonify({"success": True, "domains": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
