"""
Compliance API Routes
=====================
REST endpoints for compliance scanning, results, and remediation.
"""

import logging

from flask import jsonify, request
from flask_login import login_required, current_user

from . import compliance_service

logger = logging.getLogger(__name__)


def register_compliance_routes(bp, admin_required_decorator):
    """Register all compliance endpoints on the security_network blueprint."""

    @bp.route("/api/compliance/scan", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_run_scan():
        """Trigger a compliance scan."""
        data = request.get_json(silent=True) or {}
        pack_ids = data.get("pack_ids")
        try:
            result = compliance_service.run_scan(pack_ids=pack_ids, triggered_by="manual")
            return jsonify(result)
        except Exception as exc:
            logger.error("Compliance scan failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/scans", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_scan_history():
        """Get scan history."""
        limit = request.args.get("limit", 20, type=int)
        try:
            scans = compliance_service.get_scan_history(limit=limit)
            return jsonify({"scans": scans})
        except Exception as exc:
            logger.error("Failed to get scan history: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/scans/<scan_id>", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_scan_results(scan_id):
        """Get results for a specific scan."""
        status = request.args.get("status")
        severity = request.args.get("severity")
        pack_id = request.args.get("pack_id")
        try:
            results = compliance_service.get_scan_results(scan_id, status=status, severity=severity, pack_id=pack_id)
            return jsonify({"scan_id": scan_id, "results": results, "count": len(results)})
        except Exception as exc:
            logger.error("Failed to get scan results: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/scores", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_latest_scores():
        """Get latest compliance scores."""
        try:
            scores = compliance_service.get_latest_scores()
            if scores is None:
                return jsonify({"message": "No completed scans yet"}), 404
            return jsonify(scores)
        except Exception as exc:
            logger.error("Failed to get scores: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/packs", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_list_packs():
        """List loaded rule packs."""
        try:
            packs = compliance_service.get_loaded_packs()
            return jsonify({"packs": packs})
        except Exception as exc:
            logger.error("Failed to list packs: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/fix", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_apply_fix():
        """Apply a remediation fix."""
        data = request.get_json(silent=True) or {}
        scan_id = data.get("scan_id")
        rule_id = data.get("rule_id")
        if not scan_id or not rule_id:
            return jsonify({"error": "scan_id and rule_id are required"}), 400
        try:
            result = compliance_service.apply_fix(scan_id, rule_id, user_id=current_user.id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as exc:
            logger.error("Fix failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/packs/reload", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_reload_packs():
        """Reload rule packs from disk."""
        try:
            results = compliance_service.load_all_packs()
            return jsonify({"loaded": results})
        except Exception as exc:
            logger.error("Pack reload failed: %s", exc)
            return jsonify({"error": str(exc)}), 500
