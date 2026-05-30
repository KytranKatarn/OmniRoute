"""REST routes for the Repair Queue UI."""

import logging
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_repair_routes(bp, admin_required):
    """Register repair queue routes on the repair_bay blueprint."""

    @bp.route("/api/repair/queue")
    @login_required
    @admin_required
    def repair_queue_list():
        from tools.repair_bay.services.dependabot_service import get_repair_queue

        status = request.args.get("status")
        severity = request.args.get("severity")
        source = request.args.get("source")
        result = get_repair_queue(status=status, severity=severity, source=source)
        return jsonify(result)

    @bp.route("/api/repair/queue/<int:item_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def repair_queue_update(item_id):
        from tools.repair_bay.services.dependabot_service import update_repair_item

        data = request.get_json() or {}
        result = update_repair_item(item_id, **data)
        return jsonify(result)

    @bp.route("/api/repair/queue/<int:item_id>/triage", methods=["POST"])
    @login_required
    @admin_required
    def repair_queue_triage(item_id):
        from tools.repair_bay.services.dependabot_service import get_repair_queue
        from tools.repair_bay.services.forge_triage import triage_alert

        queue = get_repair_queue()
        item = next((i for i in queue["items"] if i["id"] == item_id), None)
        if not item:
            return jsonify({"success": False, "error": "Item not found"}), 404
        result = triage_alert(item)
        return jsonify(result)

    @bp.route("/api/repair/poll", methods=["POST"])
    @login_required
    @admin_required
    def repair_poll_now():
        from tools.repair_bay.services.dependabot_service import poll_and_ingest

        result = poll_and_ingest()
        return jsonify(result)

    @bp.route("/api/repair/manifests")
    @login_required
    @admin_required
    def repair_manifests():
        from tools.repair_bay.services.dependabot_service import discover_manifests

        manifests = discover_manifests()
        return jsonify({"success": True, "manifests": manifests, "count": len(manifests)})

    @bp.route("/api/repair/stats")
    @login_required
    @admin_required
    def repair_stats():
        from tools.repair_bay.services.dependabot_service import get_repair_queue

        all_items = get_repair_queue()
        if not all_items["success"]:
            return jsonify(all_items)
        items = all_items["items"]
        stats = {"total": len(items), "by_status": {}, "by_severity": {}, "by_source": {}}
        for item in items:
            for key in ["status", "severity", "source"]:
                bucket = f"by_{key}"
                val = item.get(key, "unknown")
                stats[bucket][val] = stats[bucket].get(val, 0) + 1
        return jsonify({"success": True, "stats": stats})
