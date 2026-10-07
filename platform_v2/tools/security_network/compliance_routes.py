"""
Compliance API Routes
=====================
REST endpoints for compliance scanning, results, and remediation.
"""

import logging
import os

from flask import jsonify, request, Response
from flask_login import login_required, current_user

from . import compliance_service

logger = logging.getLogger(__name__)

def _session_is_admin() -> bool:
    """True when the request carries an authenticated admin session."""
    try:
        u = current_user
        if not getattr(u, "is_authenticated", False):
            return False
        adm = getattr(u, "is_admin", False)
        return bool(adm() if callable(adm) else adm)
    except Exception:
        return False


def _internal_key_ok() -> bool:
    """True when the request carries an internal key that holds the ``compliance`` scope.

    Accepts either ``X-Internal-Key: <key>`` or ``Authorization: Bearer <key>`` —
    the ONE implementation lives in ``services.internal_auth`` (#6657); KSO's own key
    is the only one granted ``compliance`` (the legacy flat key still passes during
    the migration window).
    """
    from services.internal_auth import caller_has_scope

    return caller_has_scope("compliance")


def register_compliance_routes(bp, admin_required_decorator):
    """Register all compliance endpoints on the security_network blueprint."""

    @bp.route("/api/compliance/rule-packs", methods=["GET"])
    def compliance_rule_packs():
        """Serve rule packs to KSO (internal key) or an admin session.

        Was fully public. The payload includes host remediation *fix command*
        strings, so anonymous access leaked exactly what the root-exec path runs
        (Full Security Review Tier-0). KSO's ``sync_rule_packs_from_hub`` sends
        ``X-Internal-Key``; interactive admins are also allowed.
        """
        if not (_internal_key_ok() or _session_is_admin()):
            return jsonify({"success": False, "error": "unauthorized"}), 401
        try:
            packs = compliance_service.get_all_rule_packs()
            return jsonify({"success": True, "packs": packs})
        except Exception as exc:
            logger.error("Failed to get rule packs: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/scan", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_run_scan():
        """Trigger a compliance scan."""
        data = request.get_json(silent=True) or {}
        pack_ids = data.get("pack_ids")
        try:
            result = compliance_service.run_scan(pack_ids=pack_ids, triggered_by="manual")
            return jsonify(result)
        except Exception as exc:
            logger.error("Compliance scan failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/scans", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_scan_history():
        """Get scan history."""
        limit = request.args.get("limit", 20, type=int)
        try:
            scans = compliance_service.get_scan_history(limit=limit)
            return jsonify({"scans": scans})
        except Exception as exc:
            logger.error("Failed to get scan history: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/scans/<scan_id>", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_scan_results(scan_id):
        """Get results for a specific scan."""
        status = request.args.get("status")
        severity = request.args.get("severity")
        pack_id = request.args.get("pack_id")
        try:
            results = compliance_service.get_scan_results(scan_id, status=status, severity=severity, pack_id=pack_id)
            return jsonify({"scan_id": scan_id, "results": results, "count": len(results)})
        except Exception as exc:
            logger.error("Failed to get scan results: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/scans/<scan_id>/findings/<rule_id>/action-info", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_finding_action_info(scan_id, rule_id):
        """Return finding details + linked proposal_id + auto-approval state.

        Powers the Repair Bay approval card buttons (Apply Once / Apply + Always
        Allow / Dismiss) in the security_network compliance tab. The frontend
        needs the proposal_id to POST to /api/proposals/<id>/compliance-action.
        """
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """SELECT rule_id, severity, status, details, actual_value,
                              expected_value, pack_id
                       FROM compliance_scan_results
                       WHERE scan_id = %s AND rule_id = %s
                       LIMIT 1""",
                    (scan_id, rule_id),
                )
                finding = cur.fetchone()
                if not finding:
                    return jsonify({"success": False, "error": "finding not found"}), 404

                cur.execute(
                    """SELECT id, status, metadata, proposed_at
                       FROM improvement_proposals
                       WHERE category = 'compliance_fix'
                         AND status IN ('proposed', 'pending', 'pending_approval')
                         AND metadata->>'rule_id' = %s
                       ORDER BY proposed_at DESC
                       LIMIT 1""",
                    (rule_id,),
                )
                proposal = cur.fetchone()

            approval = compliance_service.get_rule_auto_approval(rule_id)

            finding_dict = dict(finding)
            blocklist_reason = None
            if proposal and proposal.get("metadata"):
                meta = proposal["metadata"]
                fix_def = meta.get("fix_def") or {}
                finding_dict["fix_type"] = fix_def.get("type")
                # Build a human-readable fix summary from whichever fields apply
                if fix_def.get("type") == "sysctl":
                    finding_dict["fix_summary"] = f"sysctl {fix_def.get('parameter')} = {fix_def.get('value')}"
                elif fix_def.get("type") == "file_line":
                    finding_dict["fix_summary"] = f"{fix_def.get('path')} → {fix_def.get('line')}"
                elif fix_def.get("type") == "service":
                    finding_dict["fix_summary"] = f"{fix_def.get('action', 'enable')} {fix_def.get('name')}"
                elif fix_def.get("type") == "command":
                    cmd = fix_def.get("command", "")
                    finding_dict["fix_summary"] = (cmd[:160] + "…") if len(cmd) > 160 else cmd
                blocklist_reason = meta.get("blocklist_reason")

            return jsonify(
                {
                    "success": True,
                    "finding": finding_dict,
                    "proposal_id": proposal["id"] if proposal else None,
                    "proposal_status": proposal["status"] if proposal else None,
                    "auto_approval_status": approval["status"] if approval else None,
                    "blocklist_reason": blocklist_reason,
                }
            )
        except Exception as exc:
            logger.error("action-info lookup failed for %s/%s: %s", scan_id, rule_id, exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/scores", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_latest_scores():
        """Get latest compliance scores."""
        try:
            scores = compliance_service.get_latest_scores()
            if scores is None:
                return jsonify({"success": False, "message": "No completed scans yet"}), 404
            scores["success"] = True
            return jsonify(scores)
        except Exception as exc:
            logger.error("Failed to get scores: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/soc2", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_soc2_scores():
        """Get SOC 2 Trust Service Criteria scores and evidence freshness."""
        scan_id = request.args.get("scan_id")
        try:
            result = compliance_service.get_soc2_scores(scan_id=scan_id)
            if result is None:
                return jsonify({"success": False, "message": "No scans yet"}), 404
            result["success"] = True
            return jsonify(result)
        except Exception as exc:
            logger.error("SOC 2 scores failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/packs", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_list_packs():
        """List loaded rule packs."""
        try:
            packs = compliance_service.get_loaded_packs()
            return jsonify({"packs": packs})
        except Exception as exc:
            logger.error("Failed to list packs: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/fix", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_apply_fix():
        """Apply a remediation fix."""
        data = request.get_json(silent=True) or {}
        scan_id = data.get("scan_id")
        rule_id = data.get("rule_id")
        if not scan_id or not rule_id:
            return jsonify({"error": "scan_id and rule_id are required"}), 400
        try:
            result = compliance_service.apply_fix(scan_id, rule_id, user_id=current_user.id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as exc:
            logger.error("Fix failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/file-history", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_file_history():
        """Get change history for a config file (git-style log)."""
        file_path = request.args.get("path", "").strip()
        if not file_path:
            return jsonify({"error": "path is required"}), 400
        try:
            history = compliance_service.get_file_history(file_path, limit=50)
            return jsonify({"success": True, "history": history, "path": file_path})
        except Exception as exc:
            logger.error("File history failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/blocklist", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_blocklist_list():
        """List all rules in the compliance blocklist."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, rule_id, pack_id, reason, risk_level,
                              manual_steps, manually_applied_at,
                              manually_applied_by, manually_applied_note,
                              created_at
                       FROM compliance_rule_blocklist
                       ORDER BY pack_id, rule_id"""
                )
                rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                for k in ["manually_applied_at", "created_at"]:
                    if r.get(k):
                        r[k] = r[k].isoformat()
            return jsonify({"success": True, "blocklist": rows, "count": len(rows)})
        except Exception as exc:
            logger.error("blocklist_list error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/blocklist/<rule_id>/mark-manual", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_blocklist_mark_manual(rule_id):
        """Mark a blocklisted rule as manually applied by the admin."""
        try:
            from database import get_db_cursor

            data = request.get_json(silent=True) or {}
            note = data.get("note", "")

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE compliance_rule_blocklist
                       SET manually_applied_at = NOW(),
                           manually_applied_by = %s,
                           manually_applied_note = %s,
                           updated_at = NOW()
                       WHERE rule_id = %s
                       RETURNING id""",
                    (current_user.id, note, rule_id),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Rule not in blocklist"}), 404
            return jsonify({"success": True, "rule_id": rule_id})
        except Exception as exc:
            logger.error("mark_manual error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/pending-fixes", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_pending_fixes():
        """List rules with pending Telegram approvals so the UI can show state."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT action_type, action_data->>'rule_id' AS rule_id,
                              action_data->>'scan_id' AS scan_id,
                              id AS approval_id, created_at
                       FROM autonomy_approval_queue
                       WHERE action_type LIKE 'compliance_fix_%%'
                         AND status = 'pending'
                       ORDER BY created_at DESC"""
                )
                rows = [dict(r) for r in cur.fetchall()]
            return jsonify(
                {
                    "success": True,
                    "pending": [
                        {
                            "rule_id": r["rule_id"],
                            "scan_id": r["scan_id"],
                            "approval_id": r["approval_id"],
                        }
                        for r in rows
                    ],
                }
            )
        except Exception as exc:
            logger.error("pending-fixes error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/rollback", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_rollback():
        """Rollback a file to a previous snapshot."""
        data = request.get_json(silent=True) or {}
        snapshot_id = data.get("snapshot_id")
        if not snapshot_id:
            return jsonify({"error": "snapshot_id is required"}), 400
        try:
            result = compliance_service.rollback_file_snapshot(snapshot_id, user_id=current_user.id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as exc:
            logger.error("Rollback failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/export/ckl", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_export_ckl():
        """Export scan results as STIG Viewer .ckl XML file."""
        scan_id = request.args.get("scan_id")
        if not scan_id:
            return jsonify({"error": "scan_id parameter required"}), 400
        try:
            xml_str = compliance_service.generate_ckl(scan_id)
            if xml_str is None:
                return jsonify({"error": "Scan not found"}), 404
            return Response(
                xml_str,
                mimetype="application/xml",
                headers={"Content-Disposition": f'attachment; filename="compliance-scan-{scan_id}.ckl"'},
            )
        except Exception as exc:
            logger.error("CKL export failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/export/evidence", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_export_evidence():
        """Export scan evidence as ZIP file (summary JSON + CSV + CKL)."""
        scan_id = request.args.get("scan_id")
        if not scan_id:
            return jsonify({"error": "scan_id parameter required"}), 400
        try:
            zip_bytes = compliance_service.generate_evidence_zip(scan_id)
            if zip_bytes is None:
                return jsonify({"error": "Scan not found"}), 404
            return Response(
                zip_bytes,
                mimetype="application/zip",
                headers={"Content-Disposition": f'attachment; filename="compliance-evidence-{scan_id}.zip"'},
            )
        except Exception as exc:
            logger.error("Evidence export failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/evidence/collect", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_collect_evidence():
        """Trigger evidence collection for SOC 2."""
        scan_id = request.json.get("scan_id") if request.is_json else None
        try:
            result = compliance_service.collect_evidence(scan_id=scan_id)
            return jsonify({"success": True, **result})
        except Exception as exc:
            logger.error("Evidence collection failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/evidence", methods=["GET"])
    @login_required
    @admin_required_decorator
    def api_list_evidence():
        """List collected evidence artifacts."""
        from database import get_db_cursor

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, control_id, artifact_type, artifact_name, collected_at
                    FROM compliance_evidence
                    ORDER BY collected_at DESC LIMIT 50
                """
                )
                evidence = [dict(r) for r in cur.fetchall()]
                for e in evidence:
                    if e.get("collected_at"):
                        e["collected_at"] = e["collected_at"].isoformat()
            return jsonify({"success": True, "evidence": evidence})
        except Exception as exc:
            logger.error("Evidence list failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/report/<scan_id>")
    @login_required
    @admin_required_decorator
    def compliance_pdf_report(scan_id):
        """Generate and serve a branded compliance report (print-to-PDF)."""
        client_name = request.args.get("client", "System Assessment")
        try:
            html = compliance_service.generate_report_html(scan_id, client_name=client_name)
            if html is None:
                return jsonify({"error": "Scan not found"}), 404
            return Response(html, mimetype="text/html")
        except Exception as exc:
            logger.error("Report generation failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/packs/reload", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_reload_packs():
        """Reload rule packs from disk."""
        try:
            results = compliance_service.load_all_packs()
            return jsonify({"loaded": results})
        except Exception as exc:
            logger.error("Pack reload failed: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @bp.route("/api/compliance/plan/<rule_id>", methods=["POST"])
    @login_required
    @admin_required_decorator
    def compliance_generate_plan(rule_id):
        """Ask F.O.R.G.E. to generate a customized remediation plan for a rule."""
        data = request.get_json(silent=True) or {}
        scan_id = data.get("scan_id")
        if not scan_id:
            return jsonify({"success": False, "error": "scan_id is required"}), 400
        try:
            result = compliance_service.generate_remediation_plan(scan_id, rule_id, user_id=current_user.id)
            status_code = 200 if result.get("success") else 400
            return jsonify(result), status_code
        except Exception as exc:
            logger.error("Plan generation failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/plan/<int:plan_id>", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_get_plan(plan_id):
        """Fetch a stored remediation plan."""
        try:
            plan = compliance_service.get_remediation_plan(plan_id)
            if plan is None:
                return jsonify({"success": False, "error": "Plan not found"}), 404
            return jsonify({"success": True, "plan": plan})
        except Exception as exc:
            logger.error("Get plan failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/compliance/plans", methods=["GET"])
    @login_required
    @admin_required_decorator
    def compliance_list_plans():
        """List remediation plans, optionally filtered by rule_id or status."""
        rule_id = request.args.get("rule_id")
        status = request.args.get("status")
        try:
            plans = compliance_service.list_remediation_plans(rule_id=rule_id, status=status)
            return jsonify({"success": True, "plans": plans, "count": len(plans)})
        except Exception as exc:
            logger.error("List plans failed: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500
