"""
Report API Routes
=================
Daily network traffic report listing, detail, and on-demand generation endpoints.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_report_routes(bp, admin_required_decorator):
    """Register all daily report endpoints on the security_network blueprint."""

    @bp.route("/api/reports/list")
    @login_required
    @admin_required_decorator
    def reports_list():
        """List daily reports with optional type filter."""
        report_type = request.args.get("type")
        limit = request.args.get("limit", 50, type=int)
        try:
            from .report_service import ReportService

            reports = ReportService().get_reports(report_type=report_type, limit=limit)
            return jsonify({"success": True, "reports": reports})
        except Exception as exc:
            logger.error("reports_list error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/reports/<int:report_id>")
    @login_required
    @admin_required_decorator
    def report_detail(report_id):
        """Get full detail for a single report."""
        try:
            from .report_service import ReportService

            report = ReportService().get_report_detail(report_id)
            if not report:
                return jsonify({"success": False, "error": "Report not found"}), 404
            return jsonify({"success": True, "report": report})
        except Exception as exc:
            logger.error("report_detail error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/reports/generate", methods=["POST"])
    @login_required
    @admin_required_decorator
    def reports_generate():
        """On-demand report generation."""
        data = request.get_json(silent=True) or {}
        report_type = data.get("type", "daily_device")
        report_date = data.get("date")  # Optional 'YYYY-MM-DD'; defaults to today

        if report_type not in ("daily_device", "daily_user"):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "type must be 'daily_device' or 'daily_user'",
                    }
                ),
                400,
            )

        try:
            from .report_service import ReportService

            svc = ReportService()
            if report_type == "daily_device":
                result = svc.generate_daily_device_report(report_date)
            else:
                result = svc.generate_daily_user_report(report_date)

            return jsonify(result)
        except Exception as exc:
            logger.error("reports_generate error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
