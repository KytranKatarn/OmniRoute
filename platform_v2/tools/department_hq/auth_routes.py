"""Device authentication routes — registration, approval, revocation."""

import logging
from flask import jsonify, request
from flask_login import current_user

logger = logging.getLogger(__name__)


def register_auth_routes(bp, admin_required):

    @bp.route("/api/auth/register", methods=["POST"])
    def register_device_route():
        """Public endpoint — any device can register (gets pending status)."""
        data = request.get_json(silent=True) or {}
        device_name = data.get("device_name", "").strip()
        device_type = data.get("device_type", "cli")
        hostname = data.get("hostname", "")
        hardware_info = data.get("hardware_info", {})
        purpose = data.get("purpose", "")

        if not device_name:
            return jsonify({"error": "device_name is required"}), 400
        if device_type not in ("cli", "node", "kso", "kbs", "standalone"):
            return jsonify({"error": f"Invalid device_type: {device_type}"}), 400

        from services.auth_service import register_device

        device_id = register_device(device_name, device_type, hostname, hardware_info, purpose)

        return (
            jsonify(
                {
                    "device_id": device_id,
                    "status": "pending",
                    "message": "Registration received. Awaiting admin approval in Department HQ.",
                }
            ),
            201,
        )

    # NOTE: GET /api/auth/devices (device list) was removed 2026-08-17 (#5706) —
    # zero runtime callers repo-wide (the DHQ Devices tab it served is gone).
    # The register/approve/deny/revoke/validate device API-key flow below stays:
    # /api/auth/register is actively called by archie_engine/hub_skills.py.

    @bp.route("/api/auth/approve/<int:device_id>", methods=["POST"])
    @admin_required
    def approve_device_route(device_id):
        """Approve a pending device — returns API key (one-time)."""
        from services.auth_service import approve_device

        approved_by = current_user.id if hasattr(current_user, "id") else None
        api_key = approve_device(device_id, approved_by=approved_by)
        if not api_key:
            return jsonify({"error": "Device not found or already processed"}), 404
        return jsonify(
            {
                "device_id": device_id,
                "api_key": api_key,
                "message": "Device approved. Store this API key securely — it won't be shown again.",
            }
        )

    @bp.route("/api/auth/deny/<int:device_id>", methods=["POST"])
    @admin_required
    def deny_device_route(device_id):
        """Deny a pending device registration."""
        from services.auth_service import deny_device

        deny_device(device_id)
        return jsonify({"device_id": device_id, "status": "denied"})

    @bp.route("/api/auth/revoke/<int:device_id>", methods=["POST"])
    @admin_required
    def revoke_device_route(device_id):
        """Revoke an approved device's access."""
        from services.auth_service import revoke_device

        revoke_device(device_id)
        return jsonify({"device_id": device_id, "status": "revoked"})

    @bp.route("/api/auth/validate", methods=["POST"])
    def validate_key():
        """Validate an API key — for standalone products to verify access."""
        data = request.get_json(silent=True) or {}
        api_key = data.get("api_key", "")
        if not api_key:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                api_key = auth_header[7:]

        if not api_key:
            return jsonify({"valid": False, "error": "No API key provided"}), 401

        from services.auth_service import validate_api_key

        device = validate_api_key(api_key)
        if device:
            return jsonify({"valid": True, "device": device})
        return jsonify({"valid": False, "error": "Invalid or revoked API key"}), 401
