"""
Honeypot Routes — API endpoints for managing the TCP honeypot service.
ADR-045 pattern: register_honeypot_routes(bp, admin_required_decorator)
"""

import logging
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

_honeypot = None


def _get_honeypot():
    """Lazy singleton for HoneypotService."""
    global _honeypot
    if _honeypot is None:
        from .honeypot_service import HoneypotService

        _honeypot = HoneypotService()
    return _honeypot


def register_honeypot_routes(bp, admin_required_decorator):
    """Register honeypot management endpoints on the blueprint."""

    @bp.route("/api/honeypot/events", methods=["GET"])
    @login_required
    @admin_required_decorator
    def honeypot_events():
        """List honeypot events with optional filters."""
        try:
            limit = min(int(request.args.get("limit", 100)), 500)
            source_ip = request.args.get("source_ip")
            svc = _get_honeypot()
            events = svc.get_events(limit=limit, source_ip=source_ip)
            return jsonify(
                {
                    "status": "ok",
                    "events": [dict(row) for row in events],
                    "count": len(events),
                }
            )
        except Exception as e:
            logger.error("[Honeypot] Failed to fetch events: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/honeypot/config", methods=["GET"])
    @login_required
    @admin_required_decorator
    def honeypot_config():
        """Get current honeypot configuration."""
        try:
            svc = _get_honeypot()
            return jsonify({"status": "ok", "config": svc.get_config()})
        except Exception as e:
            logger.error("[Honeypot] Failed to get config: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/honeypot/start", methods=["POST"])
    @login_required
    @admin_required_decorator
    def honeypot_start():
        """Start the honeypot service. Optional JSON body: {ports: [22, 23, ...]}."""
        try:
            svc = _get_honeypot()
            if svc._running:
                return jsonify({"status": "ok", "message": "Honeypot already running"})

            ports = None
            if request.is_json and request.json:
                ports = request.json.get("ports")
                if ports and not isinstance(ports, list):
                    return (
                        jsonify({"status": "error", "message": "ports must be a list"}),
                        400,
                    )

            svc.start(ports=ports)
            return jsonify(
                {
                    "status": "ok",
                    "message": "Honeypot started",
                    "config": svc.get_config(),
                }
            )
        except Exception as e:
            logger.error("[Honeypot] Failed to start: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500

    @bp.route("/api/honeypot/stop", methods=["POST"])
    @login_required
    @admin_required_decorator
    def honeypot_stop():
        """Stop the honeypot service."""
        try:
            svc = _get_honeypot()
            if not svc._running:
                return jsonify({"status": "ok", "message": "Honeypot not running"})

            svc.stop()
            return jsonify({"status": "ok", "message": "Honeypot stopped"})
        except Exception as e:
            logger.error("[Honeypot] Failed to stop: %s", e)
            return jsonify({"status": "error", "message": str(e)}), 500
