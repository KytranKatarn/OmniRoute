"""Repair Bay — P.R.O.B.E. QA tab routes.

Thin HTTP layer calling services.qa_service and services.qa_report_service
for all business logic. Follows ADR-045 register_*_routes pattern.
"""

import logging
import os

from flask import jsonify, request, send_file
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_qa_routes(bp, admin_required):
    """Register QA-related routes on the repair_bay blueprint."""

    from services import qa_service, qa_report_service

    @bp.route("/api/qa/suites")
    @login_required
    @admin_required
    def qa_suites_list():
        """List all active test suites."""
        try:
            suites = qa_service.get_suites()
            return jsonify({"success": True, "suites": suites})
        except Exception as e:
            logger.exception("Failed to list QA suites")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/suites", methods=["POST"])
    @login_required
    @admin_required
    def qa_suites_create():
        """Create a new test suite from JSON body."""
        from database import get_db_cursor

        data = request.get_json(silent=True) or {}
        name = data.get("name")
        if not name:
            return jsonify({"success": False, "error": "name is required"}), 400

        description = data.get("description", "")
        target_url = data.get("target_url", "")
        spec = data.get("spec", {})
        suite_type = data.get("suite_type", "functional")

        try:
            from psycopg2.extras import Json

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO qa_test_suites (name, description, target_url, spec, suite_type)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id""",
                    (name, description, target_url, Json(spec), suite_type),
                )
                suite_id = cur.fetchone()["id"]
            return jsonify({"success": True, "suite_id": suite_id}), 201
        except Exception as e:
            logger.exception("Failed to create QA suite")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/run/<int:suite_id>", methods=["POST"])
    @login_required
    @admin_required
    def qa_run_suite(suite_id):
        """Trigger a test run for a given suite."""
        data = request.get_json(silent=True) or {}
        triggered_by = data.get("triggered_by", "manual")

        try:
            result = qa_service.run_suite(suite_id, triggered_by)
            return jsonify(result)
        except Exception as e:
            logger.exception("Failed to run QA suite %d", suite_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/runs")
    @login_required
    @admin_required
    def qa_runs_list():
        """List recent test runs."""
        limit = request.args.get("limit", 20, type=int)
        try:
            runs = qa_service.get_recent_runs(limit)
            return jsonify({"success": True, "runs": runs})
        except Exception as e:
            logger.exception("Failed to list QA runs")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/runs/<int:run_id>")
    @login_required
    @admin_required
    def qa_run_detail(run_id):
        """Get run detail with results."""
        try:
            result = qa_service.get_run_results(run_id)
            if result is None:
                return jsonify({"success": False, "error": "Run not found"}), 404
            return jsonify({"success": True, **result})
        except Exception as e:
            logger.exception("Failed to get QA run %d", run_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/runs/<int:run_id>/report", methods=["POST"])
    @login_required
    @admin_required
    def qa_run_generate_report(run_id):
        """Generate a PDF report for a test run."""
        try:
            branded = request.args.get("branded", "false").lower() == "true"
            filepath = qa_report_service.generate_report(run_id, branded=branded)
            if not filepath:
                return (
                    jsonify({"success": False, "error": "Report generation failed"}),
                    500,
                )
            return jsonify({"success": True, "report_path": filepath})
        except Exception as e:
            logger.exception("Failed to generate report for run %d", run_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/runs/<int:run_id>/report/download")
    @login_required
    @admin_required
    def qa_run_download_report(run_id):
        """Download the PDF report for a test run."""
        try:
            result = qa_service.get_run_results(run_id)
            if result is None:
                return jsonify({"success": False, "error": "Run not found"}), 404

            report_path = result.get("report_path")
            if not report_path or not os.path.isfile(report_path):
                return (
                    jsonify({"success": False, "error": "Report not available"}),
                    404,
                )

            return send_file(
                report_path,
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"qa-report-{run_id}.pdf",
            )
        except Exception as e:
            logger.exception("Failed to download report for run %d", run_id)
            return jsonify({"success": False, "error": str(e)}), 500
