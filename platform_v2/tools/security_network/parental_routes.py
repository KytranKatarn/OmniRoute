"""
Parental Controls API Routes
=============================
REST endpoints for managing device-level parental schedules.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

from .parental_service import ParentalService

logger = logging.getLogger(__name__)


def register_parental_routes(bp, admin_required_decorator):
    """Register all parental-control endpoints on the security_network blueprint."""

    svc = ParentalService()

    @bp.route("/api/parental/schedules", methods=["GET"])
    @login_required
    @admin_required_decorator
    def parental_list_schedules():
        """List all parental schedules."""
        try:
            schedules = svc.get_schedules()
            return jsonify([dict(r) for r in schedules])
        except Exception as exc:
            logger.error("Failed to list parental schedules: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/parental/schedules", methods=["POST"])
    @login_required
    @admin_required_decorator
    def parental_create_schedule():
        """Create a new parental schedule."""
        data = request.get_json(silent=True) or {}
        device_mac = data.get("device_mac")
        user_name = data.get("user_name")
        schedule = data.get("schedule")
        blocked_categories = data.get("blocked_categories", [])

        if not device_mac or not schedule:
            return jsonify({"error": "device_mac and schedule are required"}), 400

        try:
            new_id = svc.create_schedule(device_mac, user_name, schedule, blocked_categories)
            return jsonify({"id": new_id, "status": "created"}), 201
        except Exception as exc:
            logger.error("Failed to create parental schedule: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/parental/schedules/<int:schedule_id>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def parental_update_schedule(schedule_id):
        """Update an existing parental schedule."""
        data = request.get_json(silent=True) or {}
        try:
            updated = svc.update_schedule(schedule_id, **data)
            if not updated:
                return jsonify({"error": "Not found or nothing to update"}), 404
            return jsonify({"status": "updated"})
        except Exception as exc:
            logger.error("Failed to update parental schedule %s: %s", schedule_id, exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/parental/schedules/<int:schedule_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def parental_delete_schedule(schedule_id):
        """Delete a parental schedule."""
        try:
            deleted = svc.delete_schedule(schedule_id)
            if not deleted:
                return jsonify({"error": "Not found"}), 404
            return jsonify({"status": "deleted"})
        except Exception as exc:
            logger.error("Failed to delete parental schedule %s: %s", schedule_id, exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/parental/enforce", methods=["POST"])
    @login_required
    @admin_required_decorator
    def parental_enforce():
        """Trigger manual enforcement of all schedules."""
        try:
            result = svc.enforce_schedules()
            return jsonify(result)
        except Exception as exc:
            logger.error("Parental enforcement failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/parental/categories", methods=["GET"])
    @login_required
    @admin_required_decorator
    def parental_categories():
        """Get available content categories and their domain patterns."""
        try:
            return jsonify(svc.get_category_domains())
        except Exception as exc:
            logger.error("Failed to get parental categories: %s", exc)
            return jsonify({"error": str(exc)}), 500
