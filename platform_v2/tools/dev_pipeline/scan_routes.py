"""Dev Pipeline — Scan tab routes.

Thin HTTP layer calling services.scan_service for all business logic.
Migrated from proxy pattern in Project #103, Phase 1.
"""

import logging

from flask import jsonify, request, session
from flask_login import login_required

logger = logging.getLogger(__name__)


def register_scan_routes(bp, admin_required):
    """Register scan-related routes on the dev_pipeline blueprint."""

    from services import scan_service

    @bp.route("/api/scan/status")
    @login_required
    def scan_status():
        """Scan module health + Bridge routing status."""
        ai = scan_service.check_ai_status()
        return jsonify(
            {
                "success": True,
                "bridge_routing": scan_service.BRIDGE_ROUTING_AVAILABLE,
                "ollama": ai,
            }
        )

    @bp.route("/api/scan/stats")
    @login_required
    @admin_required
    def scan_stats():
        """Get scan statistics."""
        result = scan_service.get_stats()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/run", methods=["POST"])
    @login_required
    @admin_required
    def scan_run():
        """Scan a single file."""
        data = request.get_json() or {}
        file_path = data.get("file_path")
        full_path = data.get("full_path")

        if not file_path and not full_path:
            return jsonify({"error": "file_path is required"}), 400

        scanned_by = session.get("username", "system")
        user_id = session.get("user_id", 4)
        if not isinstance(user_id, int):
            user_id = 4

        result = scan_service.scan_file(
            file_path=file_path,
            full_path=full_path,
            scanned_by=scanned_by,
            user_id=user_id,
        )
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/scan/batch", methods=["POST"])
    @login_required
    @admin_required
    def scan_batch():
        """Start batch scan as a tracked Bridge job (async)."""
        data = request.get_json(force=True, silent=True) or {}
        file_paths = data.get("file_paths") or data.get("files", [])

        if not file_paths:
            return jsonify({"error": "No files provided"}), 400
        if len(file_paths) > 50:
            return jsonify({"error": "Maximum 50 files per batch"}), 400

        scanned_by = session.get("username", "system")
        user_id = session.get("user_id", 4)
        if not isinstance(user_id, int):
            user_id = 4

        result = scan_service.batch_scan(
            file_paths=file_paths,
            scanned_by=scanned_by,
            user_id=user_id,
        )
        if not result.get("success"):
            code = 409 if "already running" in result.get("error", "") else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/scan/report")
    @login_required
    @admin_required
    def scan_file_report():
        """Get latest scan report for a specific file."""
        file_path = request.args.get("file")
        if not file_path:
            return jsonify({"error": "file parameter required"}), 400
        result = scan_service.get_file_report(file_path=file_path)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)

    @bp.route("/api/scan/history")
    @login_required
    @admin_required
    def scan_history():
        """Get scan history."""
        limit = request.args.get("limit", 20, type=int)
        result = scan_service.get_history(limit=limit)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/issues")
    @login_required
    @admin_required
    def scan_issues():
        """Get issues list."""
        status = request.args.get("status", "all")
        limit = request.args.get("limit", 50, type=int)
        result = scan_service.get_issues(status=status, limit=limit)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/issues/<int:issue_id>/fix", methods=["POST"])
    @login_required
    @admin_required
    def scan_fix_issue(issue_id):
        """Mark issue as fixed."""
        data = request.get_json() or {}
        fixed_by = data.get("fixed_by", session.get("username", "unknown"))
        description = data.get("description", "")
        result = scan_service.mark_fixed(
            issue_id=issue_id,
            fixed_by=fixed_by,
            description=description,
        )
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/scan/fixes")
    @login_required
    @admin_required
    def scan_fixes():
        """Get fixes list."""
        limit = request.args.get("limit", 30, type=int)
        result = scan_service.get_fixes(limit=limit)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/files")
    @login_required
    @admin_required
    def scan_files():
        """Get file health data."""
        result = scan_service.get_file_health()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/directory")
    @login_required
    @admin_required
    def scan_directory():
        """Browse directory for scanning."""
        path = request.args.get("path", "platform_v2")
        ext_str = request.args.get("ext", ".py,.js,.html")
        extensions = ext_str.split(",")
        result = scan_service.get_directory_files(path=path, extensions=extensions)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/scan/changed")
    @login_required
    @admin_required
    def scan_changed():
        """Get files modified since their last scan."""
        ext_str = request.args.get("ext", ".py,.js,.html")
        extensions = ext_str.split(",")
        result = scan_service.get_changed_files(extensions=extensions)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/modules")
    @login_required
    @admin_required
    def scan_modules():
        """List scannable modules with file counts."""
        result = scan_service.get_module_list()
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/module/<module_id>")
    @login_required
    @admin_required
    def scan_module_files(module_id):
        """Get files for a specific module."""
        ext_str = request.args.get("ext", ".py,.js,.html")
        extensions = ext_str.split(",")
        result = scan_service.get_module_files(module_id=module_id, extensions=extensions)
        if not result.get("success"):
            code = 404 if "not found" in result.get("error", "").lower() else 500
            return jsonify(result), code
        return jsonify(result)

    @bp.route("/api/scan/rescan")
    @login_required
    @admin_required
    def scan_rescan_list():
        """Get previously scanned files for rescan mode."""
        ext_str = request.args.get("ext", ".py,.js,.html")
        extensions = ext_str.split(",")
        result = scan_service.get_previously_scanned(extensions=extensions)
        if not result.get("success"):
            return jsonify(result), 500
        return jsonify(result)

    @bp.route("/api/scan/multi-agent/nodes")
    @login_required
    @admin_required
    def scan_review_nodes():
        """Get review nodes."""
        return jsonify(scan_service.get_review_nodes())

    @bp.route("/api/scan/multi-agent/agents")
    @login_required
    @admin_required
    def scan_review_agents():
        """List review agents."""
        specialty = request.args.get("specialty")
        limit = request.args.get("limit", 8, type=int)
        return jsonify(scan_service.get_review_agents(specialty=specialty, limit=limit))

    @bp.route("/api/scan/multi-agent/review", methods=["POST"])
    @login_required
    @admin_required
    def scan_start_review():
        """Start multi-agent review."""
        data = request.get_json() or {}
        code = data.get("code", "")
        file_path = data.get("file_path", "unknown")
        agents = data.get("agents")
        context = data.get("context", "")

        if not code:
            return jsonify({"success": False, "error": "No code provided"}), 400

        return jsonify(
            scan_service.start_multi_agent_review(
                code=code,
                file_path=file_path,
                agents=agents,
                context=context,
            )
        )

    @bp.route("/api/scan/multi-agent/review/<review_id>")
    @login_required
    @admin_required
    def scan_get_review(review_id):
        """Get review status."""
        result = scan_service.get_review_status(review_id)
        if not result.get("success"):
            return jsonify(result), 404
        return jsonify(result)
