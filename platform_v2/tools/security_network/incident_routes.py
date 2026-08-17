"""
Incident API Routes
====================
REST endpoints for security incident management and alert correlation.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

from .incident_service import IncidentService

logger = logging.getLogger(__name__)


def register_incident_routes(bp, admin_required_decorator):
    """Register all incident endpoints on the security_network blueprint."""

    svc = IncidentService()

    @bp.route("/api/incidents", methods=["GET"])
    @login_required
    @admin_required_decorator
    def incident_list():
        """List incidents filtered by status."""
        status = request.args.get("status", "open")
        limit = request.args.get("limit", 50, type=int)
        try:
            incidents = svc.get_incidents(status=status, limit=limit)
            # The UI (loadIncidents) reads d.incidents — a bare array rendered as
            # "No open incidents" always. Return the expected object shape.
            return jsonify({"success": True, "incidents": [dict(r) for r in incidents]})
        except Exception as exc:
            logger.error("Failed to list incidents: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/incidents/<int:incident_id>", methods=["GET"])
    @login_required
    @admin_required_decorator
    def incident_detail(incident_id):
        """Get incident detail with linked alerts."""
        try:
            detail = svc.get_incident_detail(incident_id)
            if not detail:
                return jsonify({"error": "Incident not found"}), 404
            return jsonify(detail)
        except Exception as exc:
            logger.error("Failed to get incident %s: %s", incident_id, exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/incidents/<int:incident_id>/resolve", methods=["POST"])
    @login_required
    @admin_required_decorator
    def incident_resolve(incident_id):
        """Resolve an incident."""
        data = request.get_json(silent=True) or {}
        notes = data.get("notes")
        try:
            resolved = svc.resolve_incident(incident_id, notes=notes)
            if not resolved:
                return jsonify({"error": "Incident not found or already resolved"}), 404
            return jsonify({"status": "resolved"})
        except Exception as exc:
            logger.error("Failed to resolve incident %s: %s", incident_id, exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/incidents/correlate", methods=["POST"])
    @login_required
    @admin_required_decorator
    def incident_correlate():
        """Trigger manual alert correlation."""
        try:
            result = svc.correlate_alerts()
            return jsonify(result)
        except Exception as exc:
            logger.error("Alert correlation failed: %s", exc)
            return jsonify({"error": str(exc)}), 500
