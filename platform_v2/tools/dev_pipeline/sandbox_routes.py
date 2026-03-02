"""Dev Pipeline — Sandbox tab routes.

Proxies to Sandbox Manager's existing route functions, re-mounted under
the dev_pipeline blueprint at /api/sandbox/*.
"""

import logging

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_sandbox_routes(bp, admin_required):
    """Register sandbox-related routes on the dev_pipeline blueprint."""

    def _sbx():
        from tools.sandbox_manager import routes as sbx

        return sbx

    # ---- Sandbox CRUD ----

    @bp.route("/api/sandbox/list")
    @login_required
    @admin_required
    def sandbox_list():
        return _sbx().get_sandboxes()

    @bp.route("/api/sandbox/<module_id>")
    @login_required
    @admin_required
    def sandbox_get(module_id):
        return _sbx().get_sandbox(module_id)

    @bp.route("/api/sandbox/<module_id>/create", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_create(module_id):
        return _sbx().create_sandbox(module_id)

    @bp.route("/api/sandbox/<module_id>/destroy", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_destroy(module_id):
        return _sbx().destroy_sandbox(module_id)

    @bp.route("/api/sandbox/<module_id>/status")
    @login_required
    @admin_required
    def sandbox_status(module_id):
        return _sbx().get_sandbox_status(module_id)

    @bp.route("/api/sandbox/<module_id>/test", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_run_test(module_id):
        return _sbx().run_sandbox_tests(module_id)

    @bp.route("/api/sandbox/<module_id>/reset", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_reset(module_id):
        return _sbx().reset_sandbox(module_id)

    # ---- Config ----

    @bp.route("/api/sandbox/config")
    @login_required
    @admin_required
    def sandbox_config_get():
        return _sbx().get_config()

    @bp.route("/api/sandbox/config", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_config_update():
        return _sbx().update_config()

    # ---- Integration ----

    @bp.route("/api/sandbox/apply-from-sentinel", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_apply_sentinel():
        return _sbx().apply_from_code_sentinel()

    @bp.route("/api/sandbox/apply-from-proposals", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_apply_proposals():
        return _sbx().apply_from_improvements()

    # ---- Test Suites ----

    @bp.route("/api/sandbox/suites")
    @login_required
    @admin_required
    def sandbox_suites_list():
        return _sbx().get_test_suites()

    @bp.route("/api/sandbox/suites", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_suites_create():
        return _sbx().create_test_suite()

    @bp.route("/api/sandbox/suites/<int:suite_id>", methods=["PUT"])
    @login_required
    @admin_required
    def sandbox_suites_update(suite_id):
        return _sbx().update_test_suite(suite_id)

    @bp.route("/api/sandbox/suites/<int:suite_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def sandbox_suites_delete(suite_id):
        return _sbx().delete_test_suite(suite_id)

    # ---- Test Runs ----

    @bp.route("/api/sandbox/run", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_run():
        return _sbx().run_tests()

    @bp.route("/api/sandbox/run/<run_id>")
    @login_required
    @admin_required
    def sandbox_run_status(run_id):
        return _sbx().get_run_status(run_id)

    @bp.route("/api/sandbox/run/<run_id>/cancel", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_run_cancel(run_id):
        return _sbx().cancel_run(run_id)

    # ---- Results & History ----

    @bp.route("/api/sandbox/test-results")
    @login_required
    @admin_required
    def sandbox_test_results():
        return _sbx().get_test_results()

    @bp.route("/api/sandbox/history")
    @login_required
    @admin_required
    def sandbox_history():
        return _sbx().get_test_history()

    @bp.route("/api/sandbox/history/<run_id>")
    @login_required
    @admin_required
    def sandbox_history_detail(run_id):
        return _sbx().get_run_details(run_id)

    @bp.route("/api/sandbox/trends")
    @login_required
    @admin_required
    def sandbox_trends():
        return _sbx().get_test_trends()

    # ---- Deployments & Benchmarks ----

    @bp.route("/api/sandbox/deployments")
    @login_required
    @admin_required
    def sandbox_deployments():
        return _sbx().get_deployments()

    @bp.route("/api/sandbox/deploy", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_deploy():
        return _sbx().deploy_to_production()

    @bp.route("/api/sandbox/benchmark", methods=["POST"])
    @login_required
    @admin_required
    def sandbox_benchmark():
        return _sbx().run_benchmark()

    @bp.route("/api/sandbox/discover")
    @login_required
    @admin_required
    def sandbox_discover():
        return _sbx().discover_tests()

    @bp.route("/api/sandbox/module-status")
    @login_required
    @admin_required
    def sandbox_module_status():
        return _sbx().get_status()
