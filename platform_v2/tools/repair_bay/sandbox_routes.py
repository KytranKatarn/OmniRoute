"""Repair Bay — Sandbox tab routes.

Thin HTTP layer calling services.sandbox_service for all business logic.
Migrated from proxy pattern in Project #103, Phase 3.
"""

import logging

from flask import jsonify, request
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def register_sandbox_routes(bp, admin_required):
    """Register sandbox-related routes on the repair_bay blueprint."""

    from services import sandbox_service

    # ---- Sandbox CRUD ----

    @bp.route("/api/sandbox/list")
    @login_required
    @admin_required
    def sandbox_list():
        return jsonify(sandbox_service.list_sandboxes())

    @bp.route("/api/sandbox/gate-runs")
    @login_required
    @admin_required
    def sandbox_gate_runs():
        """Recent proposal rehearsals: sandbox-gate + post-deploy QA runs.

        Spec 2026-08-26 §6.6 (Test Bay): the gate always ran invisibly — 399
        P.R.O.B.E. suite-79 rehearsals had no UI surface. Static rule, so the
        /api/sandbox/<module_id> converter below cannot swallow it.
        """
        from database import get_db_cursor

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, suite_id, status, triggered_by, total_tests, passed, failed, started_at
                       FROM qa_test_runs
                       WHERE triggered_by LIKE 'tiered_approval_gate_proposal_%%'
                          OR triggered_by LIKE 'repair_bay_deploy:%%'
                          OR triggered_by = 'staging_test_bay'
                       ORDER BY id DESC LIMIT 20"""
                )
                runs = []
                for r in cur.fetchall():
                    d = dict(r)
                    if d.get("started_at") is not None and hasattr(d["started_at"], "isoformat"):
                        d["started_at"] = d["started_at"].isoformat()
                    runs.append(d)
            return jsonify({"success": True, "runs": runs})
        except Exception as e:
            logger.error("sandbox_gate_runs: %s", e)
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/sandbox/<module_id>")
    @login_required
    @admin_required
    def sandbox_get(module_id):
        return jsonify(sandbox_service.get_sandbox(module_id))

    @bp.route("/api/sandbox/<module_id>/create", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_create(module_id):
        data = request.get_json() or {}
        return jsonify(sandbox_service.create_sandbox(module_id, proposal_id=data.get("proposal_id")))

    @bp.route("/api/sandbox/<module_id>/destroy", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_destroy(module_id):
        return jsonify(sandbox_service.destroy_sandbox(module_id))

    @bp.route("/api/sandbox/<module_id>/status")
    @login_required
    @admin_required
    def sandbox_status(module_id):
        return jsonify(sandbox_service.get_sandbox_status(module_id))

    @bp.route("/api/sandbox/<module_id>/test", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_run_test(module_id):
        data = request.get_json() or {}
        return jsonify(sandbox_service.run_sandbox_tests(module_id, test_suite=data.get("test_suite", "default")))

    @bp.route("/api/sandbox/<module_id>/reset", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_reset(module_id):
        return jsonify(sandbox_service.reset_sandbox(module_id))

    # ---- Config ----

    @bp.route("/api/sandbox/config")
    @login_required
    @admin_required
    def sandbox_config_get():
        result = sandbox_service.get_config()
        try:
            from tools.repair_bay.services.sandbox_manager import DOCKER_AVAILABLE

            result["docker_available"] = DOCKER_AVAILABLE
        except Exception:
            result["docker_available"] = False
        return jsonify(result)

    @bp.route("/api/sandbox/config", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_config_update():
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400
        config_key = data.get("config_key")
        if not config_key:
            return jsonify({"success": False, "error": "config_key is required"}), 400
        result = sandbox_service.update_config(
            config_key=config_key,
            config_value=data.get("config_value"),
            module_id=data.get("module_id"),
            user_id=current_user.id if hasattr(current_user, "id") else None,
        )
        return jsonify(result)

    # ---- Integration ----

    @bp.route("/api/sandbox/apply-from-sentinel", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_apply_sentinel():
        data = request.get_json()
        if not data or not data.get("issue_id"):
            return jsonify({"success": False, "error": "issue_id is required"}), 400
        result = sandbox_service.apply_from_scan(data["issue_id"])
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/sandbox/apply-from-proposals", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_apply_proposals():
        data = request.get_json()
        if not data or not data.get("proposal_id"):
            return jsonify({"success": False, "error": "proposal_id is required"}), 400
        result = sandbox_service.apply_from_proposal(data["proposal_id"])
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    # ---- Test Suites ----

    @bp.route("/api/sandbox/suites")
    @login_required
    @admin_required
    def sandbox_suites_list():
        return jsonify(sandbox_service.get_test_suites())

    @bp.route("/api/sandbox/suites", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_suites_create():
        data = request.get_json() or {}
        name = data.get("name")
        test_command = data.get("test_command")
        if not name or not test_command:
            return jsonify({"success": False, "error": "name and test_command are required"}), 400
        result = sandbox_service.create_test_suite(
            name=name,
            test_command=test_command,
            description=data.get("description", ""),
            test_type=data.get("test_type", "custom"),
            timeout=data.get("timeout_seconds", 300),
            required=data.get("required", False),
        )
        return jsonify(result)

    @bp.route("/api/sandbox/suites/<int:suite_id>", methods=["PUT"])
    @login_required
    @admin_required
    def sandbox_suites_update(suite_id):
        data = request.get_json() or {}
        if not data:
            return jsonify({"success": False, "error": "No fields to update"}), 400
        result = sandbox_service.update_test_suite(suite_id, data)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/sandbox/suites/<int:suite_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def sandbox_suites_delete(suite_id):
        result = sandbox_service.delete_test_suite(suite_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)

    # ---- Test Runs ----

    @bp.route("/api/sandbox/run", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_run():
        data = request.get_json() or {}
        result = sandbox_service.run_tests(
            run_type=data.get("type", "all"),
            suite_id=data.get("suite_id"),
            file_path=data.get("file_path"),
            timeout=data.get("timeout", 300),
        )
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result)

    @bp.route("/api/sandbox/run/<run_id>")
    @login_required
    @admin_required
    def sandbox_run_status(run_id):
        result = sandbox_service.get_run_status(run_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/api/sandbox/run/<run_id>/stream")
    @login_required
    @admin_required
    def sandbox_run_stream(run_id):
        """SSE endpoint — polls run status/results and streams changes to the browser."""
        import json
        import time

        from flask import Response, stream_with_context

        def generate():
            last_result_count = 0
            last_status = None
            terminal = {"completed", "failed", "cancelled", "error"}
            for _ in range(120):  # max 60 seconds
                try:
                    data = sandbox_service.get_run_status(run_id)
                    if not data.get("success"):
                        yield f"data: {json.dumps({'type': 'error', 'message': data.get('error', 'Run not found')})}\n\n"
                        return
                    # get_run_status returns {"success": True, "run": run_dict}
                    run_data = data["run"]
                    status = run_data.get("status", "unknown")
                    # in-memory run dict uses "tests" not "results"
                    results = run_data.get("tests", [])

                    if status != last_status:
                        yield f"data: {json.dumps({'type': 'status', 'status': status})}\n\n"
                        last_status = status

                    for r in results[last_result_count:]:
                        yield f"data: {json.dumps({'type': 'result', 'result': r})}\n\n"
                    last_result_count = len(results)

                    if status in terminal:
                        yield f"data: {json.dumps({'type': 'done', 'status': status, 'summary': run_data.get('summary', {})})}\n\n"
                        return

                    time.sleep(0.5)
                except Exception as exc:
                    yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                    return

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @bp.route("/api/sandbox/run/<run_id>/cancel", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_run_cancel(run_id):
        result = sandbox_service.cancel_run(run_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)

    # ---- Results & History ----

    @bp.route("/api/sandbox/test-results")
    @login_required
    @admin_required
    def sandbox_test_results():
        limit = request.args.get("limit", 50, type=int)
        return jsonify(sandbox_service.get_test_results(limit=limit))

    @bp.route("/api/sandbox/history")
    @login_required
    @admin_required
    def sandbox_history():
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)
        return jsonify(sandbox_service.get_test_history(limit=limit, offset=offset))

    @bp.route("/api/sandbox/history/<run_id>")
    @login_required
    @admin_required
    def sandbox_history_detail(run_id):
        result = sandbox_service.get_run_details(run_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/api/sandbox/trends")
    @login_required
    @admin_required
    def sandbox_trends():
        days = request.args.get("days", 30, type=int)
        return jsonify(sandbox_service.get_test_trends(days=days))

    # ---- Deployments & Benchmarks ----

    @bp.route("/api/sandbox/deployments")
    @login_required
    @admin_required
    def sandbox_deployments():
        limit = request.args.get("limit", 50, type=int)
        return jsonify(sandbox_service.get_deployments(limit=limit))

    @bp.route("/api/sandbox/deploy", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_deploy():
        data = request.get_json()
        if not data or not data.get("module_id"):
            return jsonify({"success": False, "error": "module_id is required"}), 400
        result = sandbox_service.deploy_to_production(
            module_id=data["module_id"],
            proposal_id=data.get("proposal_id"),
            skip_backup=data.get("skip_backup", False),
            user_id=current_user.id if hasattr(current_user, "id") else None,
        )
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/sandbox/benchmark", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_benchmark():
        data = request.get_json() or {}
        result = sandbox_service.run_benchmark(
            bench_type=data.get("type", "api"),
            target=data.get("target", "/"),
            iterations=min(data.get("iterations", 10), 100),
        )
        return jsonify(result)

    @bp.route("/api/sandbox/discover")
    @login_required
    @admin_required
    def sandbox_discover():
        return jsonify(sandbox_service.discover_tests())

    @bp.route("/api/sandbox/module-status")
    @login_required
    @admin_required
    def sandbox_module_status():
        return jsonify(sandbox_service.get_module_status())

    # ---- Persistent Staging Environment (sandbox.kytranempowerment.com) ----

    @bp.route("/api/sandbox/staging-status")
    @login_required
    @admin_required
    def sandbox_staging_status():
        import subprocess
        from database import get_db_cursor

        STAGING_CONTAINER = "archie_staging"
        STAGING_URL = "https://sandbox.kytranempowerment.com"
        STAGING_PORT = 3003
        PROBE_SUITE_ID = 79

        # Container health
        try:
            out = (
                subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.Status}}|{{.State.Health.Status}}|{{.State.StartedAt}}",
                        STAGING_CONTAINER,
                    ],
                    timeout=5,
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
            )
            parts = out.split("|")
            container_status = parts[0] if len(parts) > 0 else "unknown"
            health_status = parts[1] if len(parts) > 1 else "unknown"
            started_at = parts[2][:19].replace("T", " ") if len(parts) > 2 else ""
        except Exception:
            container_status = "not_found"
            health_status = "unknown"
            started_at = ""

        healthy = container_status == "running" and health_status in ("healthy", "")

        # Last QA run for suite #79
        last_run = None
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, passed, failed, total_tests AS total,
                           status, started_at, completed_at
                    FROM qa_test_runs
                    WHERE suite_id = %s
                    ORDER BY started_at DESC LIMIT 1
                """,
                    (PROBE_SUITE_ID,),
                )
                row = cur.fetchone()
                if row:
                    last_run = dict(row)
        except Exception:
            pass

        return jsonify(
            {
                "url": STAGING_URL,
                "port": STAGING_PORT,
                "container": STAGING_CONTAINER,
                "container_status": container_status,
                "health_status": health_status,
                "healthy": healthy,
                "started_at": started_at,
                "probe_suite_id": PROBE_SUITE_ID,
                "last_qa_run": last_run,
            }
        )

    @bp.route("/api/sandbox/staging-run-qa", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_staging_run_qa():
        from services.qa_service import run_suite

        PROBE_SUITE_ID = 79
        try:
            result = run_suite(PROBE_SUITE_ID, triggered_by="staging_test_bay")
            return jsonify({"success": True, "run_id": result.get("run_id"), "result": result})
        except Exception as e:
            logger.exception("staging QA run failed")
            return jsonify({"success": False, "error": str(e)}), 500
