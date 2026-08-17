"""
Supervision Controls API Routes
================================
REST endpoints for managing device-level supervision schedules.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

from .supervision_service import SupervisionService

logger = logging.getLogger(__name__)


def register_supervision_routes(bp, admin_required_decorator):
    """Register all supervision-control endpoints on the security_network blueprint."""

    svc = SupervisionService()

    @bp.route("/api/supervision/schedules", methods=["GET"])
    @login_required
    @admin_required_decorator
    def supervision_list_schedules():
        """List all supervision schedules."""
        try:
            schedules = svc.get_schedules()
            # The UI (loadSupervisionSchedules) reads d.success/d.schedules — a bare
            # array always renders "No supervision schedules configured".
            return jsonify({"success": True, "schedules": [dict(r) for r in schedules]})
        except Exception as exc:
            logger.error("Failed to list supervision schedules: %s", exc)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/supervision/schedules", methods=["POST"])
    @login_required
    @admin_required_decorator
    def supervision_create_schedule():
        """Create a new supervision schedule."""
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
            logger.error("Failed to create supervision schedule: %s", exc)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/supervision/schedules/<int:schedule_id>", methods=["PUT"])
    @login_required
    @admin_required_decorator
    def supervision_update_schedule(schedule_id):
        """Update an existing supervision schedule."""
        data = request.get_json(silent=True) or {}
        try:
            updated = svc.update_schedule(schedule_id, **data)
            if not updated:
                return jsonify({"error": "Not found or nothing to update"}), 404
            return jsonify({"status": "updated"})
        except Exception as exc:
            logger.error("Failed to update supervision schedule %s: %s", schedule_id, exc)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/supervision/schedules/<int:schedule_id>", methods=["DELETE"])
    @login_required
    @admin_required_decorator
    def supervision_delete_schedule(schedule_id):
        """Delete a supervision schedule."""
        try:
            deleted = svc.delete_schedule(schedule_id)
            if not deleted:
                return jsonify({"error": "Not found"}), 404
            return jsonify({"status": "deleted"})
        except Exception as exc:
            logger.error("Failed to delete supervision schedule %s: %s", schedule_id, exc)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/supervision/enforce", methods=["POST"])
    @login_required
    @admin_required_decorator
    def supervision_enforce():
        """Trigger manual enforcement of all schedules."""
        try:
            result = svc.enforce_schedules()
            return jsonify(result)
        except Exception as exc:
            logger.error("Supervision enforcement failed: %s", exc)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/supervision/known-devices", methods=["GET"])
    @login_required
    @admin_required_decorator
    def supervision_known_devices():
        """List known devices from the device registry for dropdown selection."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT ndu.mac_address, ndu.user_name, ndu.device_label,
                              ndu.device_type
                       FROM network_device_users ndu
                       WHERE ndu.device_type NOT IN ('other')
                       ORDER BY ndu.user_name, ndu.device_label"""
                )
                devices = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "devices": devices})
        except Exception as exc:
            logger.error("known-devices error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/supervision/device-activity", methods=["GET"])
    @login_required
    @admin_required_decorator
    def supervision_device_activity():
        """Get DNS activity for all supervised devices from AdGuard query log."""
        try:
            from .adguard_service import AdGuardService
            from database import get_db_cursor

            adguard = AdGuardService()
            stats = adguard.get_stats() or {}

            # Build IP → device name mapping
            ip_labels = {}
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT nd.ip_address, ndu.device_label, ndu.user_name, ndu.device_type
                       FROM network_device_users ndu
                       JOIN network_devices nd ON nd.mac_address = ndu.mac_address
                       WHERE nd.ip_address IS NOT NULL"""
                )
                for row in cur.fetchall():
                    ip_labels[row["ip_address"]] = {
                        "label": row["device_label"] or row["user_name"],
                        "user": row["user_name"],
                        "type": row["device_type"],
                    }

            # Build per-client activity from top_clients stats
            devices = []
            for item in stats.get("top_clients") or []:
                for ip, count in item.items():
                    info = ip_labels.get(ip, {})
                    devices.append(
                        {
                            "ip": ip,
                            "label": info.get("label", ip),
                            "user": info.get("user"),
                            "type": info.get("type"),
                            "total_queries": count,
                        }
                    )

            # Get top queried domains per client from query log (sample)
            query_log = adguard.get_query_log(limit=200) or {}
            client_domains = {}
            client_blocked = {}
            for entry in query_log.get("data") or []:
                client_ip = (entry.get("client") or "").split(":")[0]
                question = entry.get("question", {})
                domain = question.get("name", "")
                reason = entry.get("reason", "")
                if client_ip and domain:
                    client_domains.setdefault(client_ip, {})
                    client_domains[client_ip][domain] = client_domains[client_ip].get(domain, 0) + 1
                if "Filtered" in reason:
                    client_blocked[client_ip] = client_blocked.get(client_ip, 0) + 1

            # Enrich devices with top domains and blocked count
            for dev in devices:
                ip = dev["ip"]
                domains = client_domains.get(ip, {})
                top = sorted(domains.items(), key=lambda x: -x[1])[:5]
                dev["top_domains"] = [{"domain": d, "count": c} for d, c in top]
                dev["blocked"] = client_blocked.get(ip, 0)

            return jsonify({"success": True, "devices": devices})
        except Exception as exc:
            logger.error("device-activity error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/supervision/categories", methods=["GET"])
    @login_required
    @admin_required_decorator
    def supervision_categories():
        """Get available content categories and their domain patterns."""
        try:
            return jsonify(svc.get_category_domains())
        except Exception as exc:
            logger.error("Failed to get supervision categories: %s", exc)
            return jsonify({"error": "Internal server error"}), 500

    @bp.route("/api/supervision/available-services", methods=["GET"])
    @login_required
    @admin_required_decorator
    def supervision_available_services():
        """Get available AdGuard blocked services catalog."""
        try:
            from .adguard_service import AdGuardService

            adguard = AdGuardService()
            all_services = adguard.get_blocked_services_all() or []
            current = adguard.get_blocked_services() or []
            return jsonify(
                {
                    "success": True,
                    "available": all_services,
                    "currently_blocked": current,
                }
            )
        except Exception as exc:
            logger.error("available-services error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/supervision/blocked-services", methods=["POST"])
    @login_required
    @admin_required_decorator
    def supervision_set_blocked_services():
        """Set which services are blocked globally via AdGuard."""
        try:
            from .adguard_service import AdGuardService

            data = request.get_json(silent=True) or {}
            services = data.get("services", [])
            adguard = AdGuardService()
            adguard.set_blocked_services(services)
            return jsonify({"success": True, "blocked": services})
        except Exception as exc:
            logger.error("set-blocked-services error: %s", exc)
            return jsonify({"success": False, "error": "Internal server error"}), 500
