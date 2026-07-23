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

    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _SCREENSHOT_ALLOWED_DIRS = [
        os.path.realpath("/tmp/qa_screenshots"),
        os.path.realpath(os.path.join(_APP_ROOT, "static", "qa_screenshots")),
    ]
    _SCREENSHOT_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

    @bp.route("/api/qa/screenshot")
    @login_required
    @admin_required
    def qa_screenshot_serve():
        """Serve a QA screenshot — allowlist-only, no path traversal.

        Only bare filenames are accepted from the client.  The server
        searches each allowed screenshot directory and rejects anything
        that resolves outside those directories.
        """
        import mimetypes

        raw_path = request.args.get("path", "").strip()
        if not raw_path:
            return jsonify({"error": "path is required"}), 400

        # Strip any directory component the client provides — use basename only.
        filename = os.path.basename(raw_path)
        if not filename or filename.startswith("."):
            return jsonify({"error": "invalid filename"}), 400

        # Enforce image extension allowlist.
        _, ext = os.path.splitext(filename)
        if ext.lower() not in _SCREENSHOT_ALLOWED_EXTS:
            return jsonify({"error": "file type not allowed"}), 400

        # Search allowlisted directories only.
        for allowed_dir in _SCREENSHOT_ALLOWED_DIRS:
            candidate = os.path.realpath(os.path.join(allowed_dir, filename))
            # Verify the resolved path stays within the allowed directory.
            if candidate.startswith(allowed_dir + os.sep) and os.path.isfile(candidate):
                mime, _ = mimetypes.guess_type(candidate)
                return send_file(candidate, mimetype=mime or "image/png")

        return jsonify({"error": "screenshot not found"}), 404

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
            # ADDITIVE counts. `runs` is capped by `limit` (default 20), so len(runs) is a
            # PAGE SIZE, not a total — the Repair Bay "Test Runs" tile counted a list like
            # this and could never report more than its cap. Anything displaying a total
            # must read these, never len(runs). (#5138)
            counts = {}
            try:
                from database import get_db_cursor

                with get_db_cursor() as (_conn, cur):
                    cur.execute(
                        """SELECT COUNT(*) AS total,
                                  COUNT(*) FILTER (
                                      WHERE started_at > NOW() - INTERVAL '24 hours'
                                  ) AS last_24h
                           FROM qa_test_runs"""
                    )
                    row = cur.fetchone() or {}
                    counts = {
                        "total_runs": row["total"] or 0,
                        "runs_24h": row["last_24h"] or 0,
                    }
            except Exception:  # noqa: BLE001 — counts are a bonus, never break the list
                logger.exception("qa_runs_list: count query failed")

            return jsonify({"success": True, "runs": runs, **counts})
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

    # -----------------------------------------------------------------------
    # P.R.O.B.E. perf baselines + regressions (Task 11 of perf-baselines plan)
    # -----------------------------------------------------------------------

    @bp.route("/api/qa/baselines", methods=["GET"])
    @login_required
    @admin_required
    def api_qa_baselines():
        """List all qa_perf_baselines (one row per suite/test pair with ≥10 samples)."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT b.id, b.suite_id, s.name AS suite_name, b.test_name,
                           b.baseline_p95_ms, b.sample_count, b.last_updated_at
                      FROM qa_perf_baselines b
                      LEFT JOIN qa_test_suites s ON s.id = b.suite_id
                     ORDER BY s.name, b.test_name
                    """
                )
                rows = [dict(r) for r in cur.fetchall()]
            return jsonify({"baselines": rows})
        except Exception as e:
            logger.exception("Failed to list qa baselines")
            return jsonify({"baselines": [], "error": str(e)}), 500

    @bp.route("/api/qa/regressions", methods=["GET"])
    @login_required
    @admin_required
    def api_qa_regressions():
        """List qa_perf_regressions, filterable by ?status=pending|cleared|accepted."""
        from database import get_db_cursor

        status = (request.args.get("status") or "").strip()
        try:
            sql = """
                SELECT r.id, r.run_id, r.suite_id, s.name AS suite_name, r.test_name,
                       r.baseline_ms, r.observed_ms, r.pct_over, r.is_critical,
                       r.action_taken, r.proposal_id, r.status,
                       r.created_at, r.cleared_at, r.cleared_by
                  FROM qa_perf_regressions r
                  LEFT JOIN qa_test_suites s ON s.id = r.suite_id
            """
            params = ()
            if status:
                sql += " WHERE r.status = %s"
                params = (status,)
            sql += " ORDER BY r.created_at DESC LIMIT 200"

            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
            return jsonify({"regressions": rows})
        except Exception as e:
            logger.exception("Failed to list qa regressions")
            return jsonify({"regressions": [], "error": str(e)}), 500

    @bp.route("/api/qa/regressions/<int:regression_id>/clear", methods=["POST"])
    @login_required
    @admin_required
    def api_qa_regression_clear(regression_id: int):
        """Mark regression cleared. If no other pending rows remain, lift the
        deploy_paused_perf flag so the sandbox queue resumes claims."""
        from flask_login import current_user
        from database import get_db_cursor

        try:
            cleared_by = getattr(current_user, "username", None) or "system"
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE qa_perf_regressions
                          SET status = 'cleared',
                              cleared_at = NOW(),
                              cleared_by = %s
                        WHERE id = %s
                        RETURNING id""",
                    (cleared_by, regression_id),
                )
                if cur.fetchone() is None:
                    return jsonify({"success": False, "error": "regression not found"}), 404

                # If no more pending regressions, lift the global pause flag
                cur.execute("SELECT COUNT(*) AS n FROM qa_perf_regressions WHERE status = 'pending'")
                pending = cur.fetchone()["n"]
                if pending == 0:
                    cur.execute(
                        """INSERT INTO system_config (key, value, updated_at)
                           VALUES ('deploy_paused_perf', 'false', NOW())
                           ON CONFLICT (key) DO UPDATE
                               SET value = 'false', updated_at = NOW()"""
                    )

            return jsonify({"success": True, "regression_id": regression_id, "pending_remaining": pending})
        except Exception as e:
            logger.exception("Failed to clear regression #%s", regression_id)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/qa/regressions/<int:regression_id>/accept", methods=["POST"])
    @login_required
    @admin_required
    def api_qa_regression_accept(regression_id: int):
        """Mark regression accepted as new normal. Records qa_perf_acceptances
        and immediately recomputes the baseline so subsequent runs gauge against
        the post-accept window."""
        from flask_login import current_user
        from database import get_db_cursor
        from services import qa_baseline_service

        try:
            accepted_by = getattr(current_user, "username", None) or "system"
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE qa_perf_regressions
                          SET status = 'accepted'
                        WHERE id = %s
                        RETURNING suite_id, test_name""",
                    (regression_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return jsonify({"success": False, "error": "regression not found"}), 404

                suite_id = row["suite_id"]
                test_name = row["test_name"]
                cur.execute(
                    """INSERT INTO qa_perf_acceptances
                           (suite_id, test_name, accepted_at, accepted_by)
                       VALUES (%s, %s, NOW(), %s)
                       ON CONFLICT (suite_id, test_name) DO UPDATE
                           SET accepted_at = NOW(),
                               accepted_by = EXCLUDED.accepted_by""",
                    (suite_id, test_name, accepted_by),
                )

            # Recompute baseline immediately so the new normal lands ASAP
            try:
                p95, count = qa_baseline_service.compute_baseline(suite_id, test_name)
                if p95 is not None:
                    qa_baseline_service._upsert_baseline(suite_id, test_name, p95, count)
            except Exception as _rc_exc:  # noqa: BLE001 — non-blocking
                logger.warning("post-accept recompute failed for suite=%s test=%s: %s", suite_id, test_name, _rc_exc)

            return jsonify({"success": True, "regression_id": regression_id})
        except Exception as e:
            logger.exception("Failed to accept regression #%s", regression_id)
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------
    # Module Health overview — latest run per suite (P.R.O.B.E. dashboard)
    # ------------------------------------------------------------------

    @bp.route("/api/qa/suite-health")
    @login_required
    @admin_required
    def qa_suite_health():
        """Return the latest run summary per active suite.

        Response:
            [{suite_id, suite_name, suite_type, last_run_status,
              last_pass_rate, last_run_at, total_runs}]

        ``last_run_status`` is one of: 'completed', 'failed', 'running', or None
        when the suite has never been run.
        ``last_pass_rate`` is a float 0–100 rounded to 1 dp, or None.
        """
        from database import get_db_cursor

        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """
                    SELECT
                        s.id          AS suite_id,
                        s.name        AS suite_name,
                        s.suite_type,
                        r.status      AS last_run_status,
                        CASE
                            WHEN r.total_tests > 0
                            THEN ROUND(r.passed::numeric / r.total_tests * 100, 1)
                            ELSE NULL
                        END           AS last_pass_rate,
                        r.started_at  AS last_run_at,
                        COALESCE(cnt.total_runs, 0) AS total_runs
                    FROM qa_test_suites s
                    LEFT JOIN LATERAL (
                        SELECT status, total_tests, passed, started_at
                        FROM qa_test_runs
                        WHERE suite_id = s.id
                        ORDER BY started_at DESC
                        LIMIT 1
                    ) r ON true
                    LEFT JOIN (
                        SELECT suite_id, COUNT(*) AS total_runs
                        FROM qa_test_runs
                        GROUP BY suite_id
                    ) cnt ON cnt.suite_id = s.id
                    WHERE s.is_active = true
                    ORDER BY s.name
                    """
                )
                rows = [dict(row) for row in cur.fetchall()]
            return jsonify({"success": True, "suites": rows})
        except Exception as e:
            logger.exception("Failed to load suite health")
            return jsonify({"success": False, "error": str(e)}), 500
