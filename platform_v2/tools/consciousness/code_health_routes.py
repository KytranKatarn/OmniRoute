"""
Code Health Routes — Consciousness Module
==========================================
API endpoints for codebase metrics, audit progress, and snapshots.
"""

from flask import jsonify


def register_code_health_routes(bp, admin_required):
    @bp.route("/api/code-health/scan", methods=["POST"])
    @admin_required
    def code_health_scan():
        from services.code_metrics_service import scan_codebase, save_snapshot

        metrics = scan_codebase()
        snapshot_id = save_snapshot(metrics)
        return jsonify({"success": True, "snapshot_id": snapshot_id, "metrics": metrics})

    @bp.route("/api/code-health/current")
    @admin_required
    def code_health_current():
        from services.code_metrics_service import scan_codebase

        metrics = scan_codebase()
        return jsonify(metrics)

    @bp.route("/api/code-health/snapshots")
    @admin_required
    def code_health_snapshots():
        from services.code_metrics_service import get_snapshots

        snapshots = get_snapshots(limit=365)
        return jsonify({"snapshots": snapshots})

    @bp.route("/api/code-health/audit-log")
    @admin_required
    def code_health_audit_log():
        from services.code_metrics_service import get_audit_log

        entries = get_audit_log()
        return jsonify({"entries": entries})

    @bp.route("/api/code-health/backfill-git", methods=["POST"])
    @admin_required
    def code_health_backfill_git():
        from services.code_metrics_service import backfill_git_history

        result = backfill_git_history()
        return jsonify(result)
