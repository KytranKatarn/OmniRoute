"""
Surveillance Routes
====================
REST endpoints for Home Assistant camera surveillance — camera listing,
snapshots, MJPEG streams, alarm arm/disarm, and event history.
"""

import logging

from flask import jsonify, request, Response
from flask_login import login_required

logger = logging.getLogger(__name__)

# Import Home Assistant Surveillance service
try:
    from .ha_surveillance_service import HASurveillanceService

    surveillance_service = HASurveillanceService()
    SURVEILLANCE_SERVICE_AVAILABLE = surveillance_service.available
except ImportError:
    surveillance_service = None
    SURVEILLANCE_SERVICE_AVAILABLE = False


def register_surveillance_routes(bp, admin_required_decorator):
    """Register all surveillance endpoints on the security_network blueprint."""

    @bp.route("/api/surveillance/cameras")
    @login_required
    @admin_required_decorator
    def api_surveillance_cameras():
        """Get all camera states via auto-discovery"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return (
                jsonify({"success": False, "error": "Surveillance service not configured"}),
                503,
            )

        try:
            cameras = surveillance_service.get_cameras()
            alarm_state = surveillance_service.get_alarm_state()
            return jsonify(
                {
                    "success": True,
                    "cameras": cameras,
                    "alarm": alarm_state,
                }
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/surveillance/camera/<path:entity_id>/snapshot")
    @login_required
    @admin_required_decorator
    def api_surveillance_snapshot(entity_id):
        """Proxy camera snapshot image from HA"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return (
                jsonify({"success": False, "error": "Surveillance service not configured"}),
                503,
            )

        try:
            image_bytes = surveillance_service.get_camera_snapshot(entity_id)
            if image_bytes is None:
                return (
                    jsonify({"success": False, "error": "Could not fetch snapshot"}),
                    404,
                )
            return Response(
                image_bytes,
                mimetype="image/jpeg",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/surveillance/camera/<path:entity_id>/stream")
    @login_required
    @admin_required_decorator
    def api_surveillance_stream(entity_id):
        """Get camera MJPEG stream URL"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return (
                jsonify({"success": False, "error": "Surveillance service not configured"}),
                503,
            )

        try:
            stream_url = surveillance_service.get_camera_stream_url(entity_id)
            if stream_url is None:
                return (
                    jsonify({"success": False, "error": "Invalid camera entity"}),
                    404,
                )
            return jsonify({"success": True, "stream_url": stream_url})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/surveillance/camera/<path:entity_id>/stream-proxy")
    @login_required
    @admin_required_decorator
    def api_surveillance_stream_proxy(entity_id):
        """Proxy MJPEG stream from HA through ARCHIE (avoids exposing HA token to browser)"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return jsonify({"success": False, "error": "Surveillance not configured"}), 503

        if not entity_id.startswith("camera."):
            return jsonify({"success": False, "error": "Invalid entity"}), 400

        import requests as req

        ha_url = surveillance_service.base_url
        token = surveillance_service.token

        def generate():
            try:
                r = req.get(
                    f"{ha_url}/api/camera_proxy_stream/{entity_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    stream=True,
                    timeout=30,
                )
                for chunk in r.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except Exception as e:
                logger.debug("Camera stream interrupted for %s: %s", entity_id, e)

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @bp.route("/api/surveillance/status")
    @login_required
    @admin_required_decorator
    def api_surveillance_status():
        """HA connection status + camera count"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return jsonify(
                {
                    "success": True,
                    "status": {
                        "connected": False,
                        "error": "HA_API_TOKEN not configured",
                        "camera_count": 0,
                    },
                }
            )

        try:
            health = surveillance_service.check_health()
            return jsonify({"success": True, "status": health})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/surveillance/system/arm", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_surveillance_arm():
        """Arm the surveillance system"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return (
                jsonify({"success": False, "error": "Surveillance service not configured"}),
                503,
            )

        try:
            success = surveillance_service.arm_system()
            if success:
                return jsonify({"success": True, "message": "System armed"})
            return (
                jsonify({"success": False, "error": "Failed to arm system"}),
                500,
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/surveillance/system/disarm", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_surveillance_disarm():
        """Disarm the surveillance system"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return (
                jsonify({"success": False, "error": "Surveillance service not configured"}),
                503,
            )

        try:
            success = surveillance_service.disarm_system()
            if success:
                return jsonify({"success": True, "message": "System disarmed"})
            return (
                jsonify({"success": False, "error": "Failed to disarm system"}),
                500,
            )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/surveillance/events")
    @login_required
    @admin_required_decorator
    def api_surveillance_events():
        """Get recent surveillance events"""
        if not SURVEILLANCE_SERVICE_AVAILABLE or not surveillance_service:
            return (
                jsonify({"success": False, "error": "Surveillance service not configured"}),
                503,
            )

        hours = request.args.get("hours", 24, type=int)

        try:
            events = surveillance_service.get_recent_events(hours)
            return jsonify({"success": True, "events": events})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500
