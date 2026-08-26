"""Repair Bay — Scan tab routes.

Thin HTTP layer calling services.scan_service for all business logic.
Migrated from proxy pattern in Project #103, Phase 1.
"""

import logging

from flask import jsonify, request, session
from flask_login import login_required

logger = logging.getLogger(__name__)


def _has_open_proposal(file_path: str, category: str) -> bool:
    """Return True if a pending/open proposal already exists for this file+category.
    Used to prevent duplicate proposals on repeated scans.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            # #6045: there is no file_path COLUMN — it lives in metadata jsonb. The
            # old column query raised, hit the bare except, and FAILED OPEN, so this
            # dedup never deduped anything.
            cur.execute(
                """SELECT 1 FROM improvement_proposals
                   WHERE metadata->>'file_path' = %s
                     AND category = %s
                     AND status IN ('proposed', 'pending', 'in_review', 'approved',
                                    'ready_for_review', 'fix_requested', 'pr_open')
                   LIMIT 1""",
                (file_path, category),
            )
            return cur.fetchone() is not None
    except Exception:
        return False  # fail open — let proposal through if DB unavailable


def register_scan_routes(bp, admin_required):
    """Register scan-related routes on the repair_bay blueprint."""

    from services import scan_service

    @bp.route("/api/scan/status")
    @login_required
    @admin_required
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

    @bp.route("/api/scan/issues-to-proposals", methods=["POST"])
    @login_required
    @admin_required
    def scan_issues_to_proposals():
        """Convert scan issues into grouped improvement proposals.

        Groups issues by file_path + category, creates one proposal per group.
        Optional JSON body: scan_id (int), min_severity (str, default 'medium').
        """
        import json
        import os
        from database import _get_db_password

        import psycopg2
        from psycopg2.extras import RealDictCursor

        data = request.get_json(force=True, silent=True) or {}
        scan_id = data.get("scan_id")
        min_severity = data.get("min_severity", "medium")

        severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
        min_rank = severity_rank.get(min_severity, 2)

        # Map severity to proposal priority (integer)
        severity_to_priority = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

        try:
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "archie_database"),
                port=os.getenv("DB_PORT", "5432"),
                database=os.getenv("DB_NAME", "archie"),
                user=os.getenv("DB_USER", "archie"),
                password=_get_db_password(),
            )
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Fetch open issues, optionally filtered by scan_id
            sql = """SELECT id, file_path, category, severity, message, line_number, suggestion
                     FROM code_issues
                     WHERE status = 'open' AND proposal_id IS NULL"""
            params = []
            if scan_id:
                sql += " AND scan_id = %s"
                params.append(scan_id)
            sql += " ORDER BY file_path, category, severity DESC"
            cur.execute(sql, params)
            issues = cur.fetchall()

            # Filter by min severity
            filtered = [i for i in issues if severity_rank.get(i.get("severity", "info"), 0) >= min_rank]

            # Group by (file_path, category)
            groups = {}
            for issue in filtered:
                key = (issue["file_path"] or "unknown", issue.get("category") or "general")
                if key not in groups:
                    groups[key] = []
                groups[key].append(issue)

            created = 0
            for (file_path, category), group_issues in groups.items():
                count = len(group_issues)
                max_sev = max(group_issues, key=lambda i: severity_rank.get(i.get("severity", "info"), 0))
                priority = severity_to_priority.get(max_sev.get("severity", "medium"), 3)

                title = f"{count} {category} issue{'s' if count != 1 else ''} in {file_path}"
                description_parts = []
                for i in group_issues:
                    line_info = f" (line {i['line_number']})" if i.get("line_number") else ""
                    msg = i.get("message", "No description")
                    sug = i.get("suggestion", "")
                    part = f"- [{i.get('severity', 'medium').upper()}]{line_info} {msg}"
                    if sug:
                        part += f"\n  Suggestion: {sug}"
                    description_parts.append(part)
                description = "\n".join(description_parts)

                metadata = json.dumps(
                    {
                        "file_path": file_path,
                        "issue_count": count,
                        "issue_ids": [i["id"] for i in group_issues],
                        "max_severity": max_sev.get("severity", "medium"),
                        "source": "scan_issues_to_proposals",
                    }
                )

                # Skip if a proposal for this file+category is already open (dedup guard)
                if _has_open_proposal(file_path, category):
                    logger.debug("Skipping duplicate proposal for %s / %s", file_path, category)
                    continue

                # #6045: file_path lives in the metadata JSON built above (no such
                # column); proposed_by is a nullable INTEGER, so the old scan_bridge
                # string writer could never insert; priority is varchar.
                cur.execute(
                    """INSERT INTO improvement_proposals
                       (title, description, category, priority, status, proposed_at, metadata)
                       VALUES (%s, %s, %s, %s, 'proposed', NOW(), %s::jsonb)
                       RETURNING id""",
                    (title, description, category, str(priority), metadata),
                )
                proposal_id = cur.fetchone()["id"]

                # Auto-create a Code session for this proposal
                try:
                    from tools.archie_chat.code_service import create_session_from_proposal as _create_code_session

                    _severity = max_sev.get("severity", "medium")
                    _title = "Fix: {} — {}".format(
                        category,
                        (file_path or "")[:60],
                    )
                    _create_code_session(
                        proposal_id=proposal_id,
                        title=_title,
                        severity=_severity,
                    )
                except Exception as _e:
                    logger.warning("Code session auto-create failed: %s", _e)

                # Link issues back to the proposal
                issue_ids = [i["id"] for i in group_issues]
                cur.execute(
                    "UPDATE code_issues SET proposal_id = %s WHERE id = ANY(%s)",
                    (proposal_id, issue_ids),
                )

                # F.O.R.G.E.: Auto-create GitHub issue for critical/high severity
                max_severity = max_sev.get("severity", "medium")
                if max_severity in ("critical", "high"):
                    try:
                        from .services.github_service import (
                            create_issue as gh_create_issue,
                            find_existing_issue,
                        )

                        existing = find_existing_issue(file_path, category)
                        if not existing:
                            gh_body = (
                                f"## F.O.R.G.E. Scan Finding\n\n"
                                f"**File**: `{file_path}`\n"
                                f"**Category**: {category}\n"
                                f"**Severity**: {max_severity}\n"
                                f"**Issues Found**: {count}\n"
                                f"**Proposal**: #{proposal_id}\n\n"
                                f"### Details\n{description[:2000]}\n\n"
                                f"---\n"
                                f"*Auto-created by F.O.R.G.E. scan pipeline*\n"
                                f"*Platform: http://192.168.1.200:3000/tools/repair-bay*"
                            )
                            gh_create_issue(
                                title=f"[SCAN] {title}",
                                body=gh_body,
                                severity=max_severity,
                            )
                            logger.info(f"[FORGE] GitHub issue created for %s (%s)", file_path, max_severity)
                    except Exception as gh_err:
                        logger.warning(f"[FORGE] GitHub issue creation failed: %s", gh_err)

                created += 1

            conn.commit()
            cur.close()
            conn.close()

            return jsonify(
                {
                    "success": True,
                    "proposals_created": created,
                    "issues_processed": len(filtered),
                    "issues_skipped": len(issues) - len(filtered),
                }
            )
        except Exception as e:
            logger.error(f"issues_to_proposals: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

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
