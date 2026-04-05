"""
AdGuard DNS Management Routes
==============================
REST endpoints for AdGuard Home DNS management — stats, query log,
filters, rewrites, clients, rules, block/unblock, and protection toggle.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

# Import AdGuard full service
try:
    from .adguard_service import AdGuardService

    adguard_service = AdGuardService()
    ADGUARD_SERVICE_AVAILABLE = True
except ImportError:
    adguard_service = None
    ADGUARD_SERVICE_AVAILABLE = False


def register_adguard_routes(bp, admin_required_decorator):
    """Register all AdGuard DNS endpoints on the security_network blueprint."""

    @bp.route("/api/dns/adguard/stats")
    @login_required
    @admin_required_decorator
    def api_dns_adguard_stats():
        """Full AdGuard statistics"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            stats = adguard_service.get_stats()
            status = adguard_service.get_status()
            if stats is None and status is None:
                return jsonify({"success": False, "error": "Could not connect to AdGuard"}), 503
            return jsonify(
                {
                    "success": True,
                    "stats": stats,
                    "status": status,
                }
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/querylog")
    @login_required
    @admin_required_decorator
    def api_dns_adguard_querylog():
        """AdGuard query log"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        search = request.args.get("search")
        response_status = request.args.get("response_status")

        try:
            result = adguard_service.get_query_log(limit, offset, search, response_status)
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch query log"}), 503
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/filters")
    @login_required
    @admin_required_decorator
    def api_dns_adguard_filters_get():
        """List AdGuard filter lists"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            result = adguard_service.get_filtering_status()
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch filters"}), 503
            return jsonify(
                {
                    "success": True,
                    "filters": result.get("filters", []),
                    "user_rules": result.get("user_rules", []),
                    "enabled": result.get("enabled", False),
                }
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/filters", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_filters_add():
        """Add an AdGuard filter list"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        name = data.get("name", "")
        url = data.get("url", "")
        enabled = data.get("enabled", True)

        if not name or not url:
            return jsonify({"success": False, "error": "Name and URL are required"}), 400

        try:
            result = adguard_service.add_filter(name, url, enabled)
            if result is None:
                return jsonify({"success": False, "error": "Failed to add filter"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/filters/<path:url>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_filters_toggle(url):
        """Toggle an AdGuard filter on/off"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        enabled = data.get("enabled", True)

        try:
            result = adguard_service.toggle_filter(url, enabled)
            if result is None:
                return jsonify({"success": False, "error": "Failed to toggle filter"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/filters/<path:url>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_filters_remove(url):
        """Remove an AdGuard filter list"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            result = adguard_service.remove_filter(url)
            if result is None:
                return jsonify({"success": False, "error": "Failed to remove filter"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/filters/refresh", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_filters_refresh():
        """Refresh all AdGuard filter lists"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            result = adguard_service.refresh_filters()
            if result is None:
                return jsonify({"success": False, "error": "Failed to refresh filters"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/rewrites")
    @login_required
    @admin_required_decorator
    def api_dns_adguard_rewrites_get():
        """List DNS rewrites"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            result = adguard_service.get_rewrites()
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch rewrites"}), 503
            return jsonify({"success": True, "rewrites": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/rewrites", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_rewrites_add():
        """Add a DNS rewrite"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        domain = data.get("domain", "")
        answer = data.get("answer", "")

        if not domain or not answer:
            return jsonify({"success": False, "error": "Domain and answer are required"}), 400

        try:
            result = adguard_service.add_rewrite(domain, answer)
            if result is None:
                return jsonify({"success": False, "error": "Failed to add rewrite"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/rewrites", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_rewrites_delete():
        """Delete a DNS rewrite"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        domain = data.get("domain", "")
        answer = data.get("answer", "")

        if not domain or not answer:
            return jsonify({"success": False, "error": "Domain and answer are required"}), 400

        try:
            result = adguard_service.delete_rewrite(domain, answer)
            if result is None:
                return jsonify({"success": False, "error": "Failed to delete rewrite"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/clients")
    @login_required
    @admin_required_decorator
    def api_dns_adguard_clients():
        """Get AdGuard client statistics"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            result = adguard_service.get_clients()
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch clients"}), 503
            return jsonify({"success": True, "clients": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/rules")
    @login_required
    @admin_required_decorator
    def api_dns_adguard_rules_get():
        """Get AdGuard user rules"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        try:
            result = adguard_service.get_user_rules()
            if result is None:
                return jsonify({"success": False, "error": "Could not fetch rules"}), 503
            # JS expects d.rules as a string (newline-separated)
            rules_list = (
                result.get("rules", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
            )
            rules_text = "\n".join(rules_list)
            return jsonify({"success": True, "rules": rules_text})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/rules", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_rules_set():
        """Set AdGuard user rules"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        rules = data.get("rules")

        if rules is None:
            return jsonify({"success": False, "error": "Rules are required"}), 400

        # Accept rules as a string (newline-separated) or list
        if isinstance(rules, str):
            rules = [r for r in rules.split("\n") if r.strip()]

        try:
            result = adguard_service.set_user_rules(rules)
            if result is None:
                return jsonify({"success": False, "error": "Failed to set rules"}), 500
            return jsonify({"success": True, "data": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/block", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_block():
        """Block a domain via AdGuard"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        domain = data.get("domain", "").strip().lower()

        if not domain:
            return jsonify({"success": False, "error": "Domain is required"}), 400

        try:
            # Check if already blocked by ANY source (user rules + all filter lists)
            check = adguard_service.check_host(domain)
            if check and check.get("reason", "").startswith("Filtered"):
                source = "a filter list"
                rule_info = check.get("rules", [])
                if rule_info:
                    fid = rule_info[0].get("filter_list_id", -1)
                    source = "user rules" if fid == 0 else f"filter list #{fid}"
                return (
                    jsonify({"success": False, "error": f"Domain {domain} is already blocked by {source}"}),
                    409,
                )

            success = adguard_service.block_domain(domain)
            if success:
                return jsonify({"success": True, "message": f"Domain {domain} blocked"})
            return jsonify({"success": False, "error": "Failed to block domain"}), 500
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/unblock", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_unblock():
        """Unblock a domain via AdGuard"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        domain = data.get("domain", "")

        if not domain:
            return jsonify({"success": False, "error": "Domain is required"}), 400

        try:
            success = adguard_service.unblock_domain(domain)
            if success:
                return jsonify({"success": True, "message": f"Domain {domain} unblocked"})
            return jsonify({"success": False, "error": "Failed to unblock domain"}), 500
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/dns/adguard/protection", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_dns_adguard_protection():
        """Toggle AdGuard protection on/off"""
        if not ADGUARD_SERVICE_AVAILABLE or not adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503

        data = request.get_json() or {}
        enabled = data.get("enabled", True)

        try:
            result = adguard_service.set_protection(enabled)
            if result is None:
                return jsonify({"success": False, "error": "Failed to toggle protection"}), 500
            return jsonify({"success": True, "protection_enabled": enabled})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
