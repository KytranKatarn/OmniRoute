"""
Device Registry Routes
=======================
REST endpoints for network device management — listing, registration,
filtering, sync with AdGuard, and per-device DNS activity reports.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

# Import Device Registry service
try:
    from tools.security_network.device_registry_service import DeviceRegistryService

    device_registry = DeviceRegistryService()
    DEVICE_REGISTRY_AVAILABLE = True
except Exception as e:
    logger.debug("Device registry service unavailable: %s", e)
    device_registry = None
    DEVICE_REGISTRY_AVAILABLE = False

# Import AdGuard service (needed for per-device DNS reports)
try:
    from .adguard_service import AdGuardService

    _adguard_service = AdGuardService()
    _ADGUARD_AVAILABLE = True
except ImportError:
    _adguard_service = None
    _ADGUARD_AVAILABLE = False


def register_device_registry_routes(bp, admin_required_decorator):
    """Register all device registry endpoints."""

    @bp.route("/api/devices")
    @login_required
    @admin_required_decorator
    def api_devices_list():
        """List all devices with optional filters"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            zone = request.args.get("zone")
            # UI sends ?type=; accept it alongside the canonical ?device_type=.
            device_type = request.args.get("device_type") or request.args.get("type")
            owner = request.args.get("owner")
            online = request.args.get("online")
            if online is not None:
                online = online.lower() == "true"
            status = request.args.get("status")
            devices = device_registry.get_devices(
                zone=zone,
                device_type=device_type,
                owner=owner,
                online=online,
                status=status,
            )
            return jsonify({"success": True, "devices": devices})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/stats")
    @login_required
    @admin_required_decorator
    def api_devices_stats():
        """Get device registry statistics"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            stats = device_registry.get_stats()
            return jsonify({"success": True, "stats": stats})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/unregistered")
    @login_required
    @admin_required_decorator
    def api_devices_unregistered():
        """Get unregistered devices from AdGuard"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            unregistered = device_registry.get_unregistered()
            return jsonify({"success": True, "devices": unregistered})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/<int:device_id>")
    @login_required
    @admin_required_decorator
    def api_devices_get(device_id):
        """Get a single device by ID"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            device = device_registry.get_device(device_id)
            if not device:
                return jsonify({"success": False, "error": "Device not found"}), 404
            return jsonify({"success": True, "device": device})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/register", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_devices_register():
        """Register or update a device"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            data = request.get_json() or {}
            result = device_registry.register_device(
                device_id=data.get("id"),
                friendly_name=data.get("friendly_name"),
                device_type=data.get("device_type"),
                owner=data.get("owner"),
                security_zone=data.get("security_zone"),
                notes=data.get("notes"),
            )
            return jsonify({"success": True, "device": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/<int:device_id>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def api_devices_update(device_id):
        """Update device fields"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            data = request.get_json() or {}
            # update_device(self, device_id, **kwargs) — pass the fields as kwargs,
            # not the dict positionally (which raised TypeError -> 500 every edit).
            result = device_registry.update_device(device_id, **data)
            if not result:
                return jsonify({"success": False, "error": "Device not found"}), 404
            return jsonify({"success": True, "device": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/<int:device_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def api_devices_delete(device_id):
        """Delete a device from the registry"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            result = device_registry.delete_device(device_id)
            if not result:
                return jsonify({"success": False, "error": "Device not found"}), 404
            return jsonify({"success": True, "message": f"Device {device_id} deleted"})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/sync", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_devices_sync():
        """Force full AdGuard sync"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        try:
            result = device_registry.sync()
            return jsonify({"success": True, "sync": result})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/devices/<int:device_id>/dns-report")
    @login_required
    @admin_required_decorator
    def api_device_dns_report(device_id):
        """Per-device DNS activity report"""
        if not DEVICE_REGISTRY_AVAILABLE or not device_registry:
            return jsonify({"success": False, "error": "Device registry not available"}), 503
        if not _ADGUARD_AVAILABLE or not _adguard_service:
            return jsonify({"success": False, "error": "AdGuard service not available"}), 503
        try:
            device = device_registry.get_device(device_id)
            if not device:
                return jsonify({"success": False, "error": "Device not found"}), 404
            ip_address = device.get("ip_address", "")
            if not ip_address:
                return jsonify({"success": False, "error": "Device has no IP address"}), 400
            report = _adguard_service.get_client_report(ip_address)
            return jsonify(
                {
                    "success": True,
                    "device_name": device.get("friendly_name") or device.get("hostname", "Unknown"),
                    "ip_address": ip_address,
                    "report": report,
                }
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
