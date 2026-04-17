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

    @bp.route("/api/qa/suites/generate", methods=["POST"])
    @login_required
    @admin_required
    def qa_suites_generate():
        """QA-as-a-Service: generate a suite from a URL.

        Body: ``{url, name?, max_paths?}``

        Discovers paths via sitemap.xml + home-page nav links, produces a
        page_load-heavy spec, and inserts it as a ``suite_type='customer'``
        suite. Returns the new ``suite_id`` + path list.
        """
        from flask_login import current_user

        from services.qa_auto_generator import generate_and_save

        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"success": False, "error": "url is required"}), 400

        try:
            result = generate_and_save(
                url=url,
                name=data.get("name"),
                user_id=getattr(current_user, "id", None),
                max_paths=int(data.get("max_paths") or 15),
            )
            return jsonify({"success": True, **result}), 201
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            logger.exception("Failed to auto-generate QA suite for %s", url)
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

    # ------------------------------------------------------------------
    # Visual snapshot baselines (Task #2027 — P.R.O.B.E. capability upgrade)
    # ------------------------------------------------------------------

    @bp.route("/api/qa/baselines/<int:suite_id>", methods=["GET"])
    @login_required
    @admin_required
    def qa_baselines_list(suite_id):
        """List visual_snapshot baselines for a suite."""
        from database import get_db_cursor

        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT id, snapshot_name, breakpoint, captured_at,
                              captured_from_run_id, captured_by
                       FROM qa_visual_baselines
                       WHERE suite_id = %s
                       ORDER BY snapshot_name, breakpoint""",
                    (suite_id,),
                )
                rows = [dict(r) for r in cur.fetchall() or []]
            return jsonify({"success": True, "baselines": rows})
        except Exception as e:
            logger.exception("Failed to list baselines for suite %d", suite_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/baselines/<int:suite_id>/accept", methods=["POST"])
    @login_required
    @admin_required
    def qa_baselines_accept(suite_id):
        """Promote a run's visual_snapshot results into baselines.

        Body: ``{"run_id": 123, "snapshot_names": ["foo", "bar"]}``

        ``snapshot_names`` is optional — if omitted, all visual_snapshot results
        from the run with a captured ``assertions.current`` payload are accepted.

        Accepts both ``skip`` (first-run, no baseline yet) and ``fail`` (diff
        exists — operator confirms the new state is correct).
        """
        from database import get_db_cursor
        from flask_login import current_user
        from psycopg2.extras import Json

        data = request.get_json(silent=True) or {}
        run_id = data.get("run_id")
        if not run_id:
            return jsonify({"success": False, "error": "run_id is required"}), 400
        filter_names = data.get("snapshot_names") or []

        try:
            user_id = getattr(current_user, "id", None)

            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT test_name, status, assertions
                       FROM qa_test_results
                       WHERE run_id = %s AND test_type = 'visual_snapshot'""",
                    (run_id,),
                )
                rows = cur.fetchall() or []

            accepted = []
            for row in rows:
                assertions = row.get("assertions") or {}
                snap_name = assertions.get("snapshot_name")
                breakpoint_px = assertions.get("breakpoint")
                current = assertions.get("current")
                if not (snap_name and breakpoint_px and current):
                    continue
                if filter_names and snap_name not in filter_names:
                    continue

                with get_db_cursor(commit=True) as (_c2, cur2):
                    cur2.execute(
                        """INSERT INTO qa_visual_baselines
                           (suite_id, snapshot_name, breakpoint, baseline,
                            captured_from_run_id, captured_by)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON CONFLICT (suite_id, snapshot_name, breakpoint)
                           DO UPDATE SET baseline = EXCLUDED.baseline,
                                         captured_from_run_id = EXCLUDED.captured_from_run_id,
                                         captured_by = EXCLUDED.captured_by,
                                         captured_at = NOW()
                           RETURNING id""",
                        (
                            suite_id,
                            snap_name,
                            int(breakpoint_px),
                            Json(current),
                            run_id,
                            user_id,
                        ),
                    )
                    baseline_id = cur2.fetchone()["id"]
                accepted.append(
                    {
                        "baseline_id": baseline_id,
                        "snapshot_name": snap_name,
                        "breakpoint": int(breakpoint_px),
                    }
                )

            return jsonify({"success": True, "accepted": accepted, "count": len(accepted)})
        except Exception as e:
            logger.exception("Failed to accept baselines for suite %d run %s", suite_id, run_id)
            return jsonify({"success": False, "error": str(e)}), 500
