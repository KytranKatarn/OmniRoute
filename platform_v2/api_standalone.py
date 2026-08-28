"""
Standalone Product API — receives compliance scan results from standalone products.

Endpoints:
  POST /api/standalone/compliance-report — store compliance scan results
  GET  /api/standalone/compliance-analysis — fetch latest S.H.I.E.L.D. AI analysis

Auth: Bearer {base64(client_id:client_secret)} validated against oauth_clients table.
"""

import base64
import logging
import threading

from flask import Blueprint, request, jsonify

from database import get_db_cursor

logger = logging.getLogger(__name__)

standalone_api_bp = Blueprint("standalone_api", __name__, url_prefix="/api/standalone")


def _authenticate_client():
    """Validate Bearer token as base64(client_id:client_secret) against oauth_clients."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Missing or invalid Authorization header"

    token = auth_header[7:]
    try:
        decoded = base64.b64decode(token).decode("utf-8")
        client_id, client_secret = decoded.split(":", 1)
    except Exception:
        return None, "Malformed Bearer token (expected base64 of client_id:client_secret)"

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, client_id FROM oauth_clients
               WHERE client_id = %s AND client_secret = %s AND is_active = true""",
            (client_id, client_secret),
        )
        client = cur.fetchone()

    if not client:
        return None, "Invalid client credentials or inactive client"

    return client, None


def _run_shield_analysis(app, scan_target, scan_data, db_scan_id):
    """Run S.H.I.E.L.D. AI compliance analysis in a background thread."""
    try:
        with app.app_context():
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            # Fetch previous scan score for trend comparison
            prev_score = None
            prev_date = None
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT score, started_at FROM compliance_scans
                           WHERE id != %s
                           ORDER BY started_at DESC LIMIT 1""",
                        (db_scan_id,),
                    )
                    prev = cur.fetchone()
                    if prev:
                        prev_score = prev["score"] if isinstance(prev, dict) else prev[0]
                        prev_date = prev["started_at"] if isinstance(prev, dict) else prev[1]
            except Exception as e:
                logger.warning("S.H.I.E.L.D.: Could not fetch previous scan: %s", e)

            # Build analysis prompt
            score = scan_data.get("score", "N/A")
            failed = scan_data.get("failed", 0)
            total = scan_data.get("total_rules", 0)
            passed = scan_data.get("passed", 0)
            pack_ids = scan_data.get("pack_ids", [])

            trend_info = ""
            if prev_score is not None:
                delta = float(score) - float(prev_score) if score != "N/A" else 0
                direction = "improved" if delta > 0 else "declined" if delta < 0 else "unchanged"
                trend_info = (
                    f"\n\nPREVIOUS SCAN:\n"
                    f"- Score: {prev_score}%\n"
                    f"- Date: {prev_date}\n"
                    f"- Delta: {delta:+.1f}% ({direction})"
                )

            failed_rules_text = ""
            failed_rules = scan_data.get("failed_rules", [])
            if failed_rules:
                lines = []
                for r in failed_rules[:30]:  # Cap at 30 to keep prompt manageable
                    rid = r.get("rule_id", "unknown")
                    sev = r.get("severity", "unknown")
                    desc = r.get("description", "")
                    lines.append(f"  - [{sev.upper()}] {rid}: {desc}")
                failed_rules_text = "\n\nFAILED RULES:\n" + "\n".join(lines)

            pack_scores_text = ""
            pack_scores = scan_data.get("pack_scores", {})
            if pack_scores:
                lines = [f"  - {k}: {v}%" for k, v in pack_scores.items()]
                pack_scores_text = "\n\nPACK SCORES:\n" + "\n".join(lines)

            prompt = (
                f"Analyze this compliance scan for '{scan_target}'.\n\n"
                f"SCAN RESULTS:\n"
                f"- Overall Score: {score}%\n"
                f"- Total Rules: {total}\n"
                f"- Passed: {passed}\n"
                f"- Failed: {failed}\n"
                f"- Packs: {', '.join(pack_ids) if pack_ids else 'N/A'}"
                f"{pack_scores_text}"
                f"{failed_rules_text}"
                f"{trend_info}\n\n"
                f"Provide your analysis with EXACTLY these three section headers:\n\n"
                f"## EXECUTIVE SUMMARY\n"
                f"(2-3 paragraph overview of compliance posture, key risks, and overall assessment)\n\n"
                f"## REMEDIATION PLAN\n"
                f"(Prioritized list of fixes: rule ID, what to fix, why it matters, estimated effort)\n\n"
                f"## TREND ANALYSIS\n"
                f"(Score trajectory, new vs resolved failures, improvement recommendations)"
            )

            system_prompt = (
                "You are S.H.I.E.L.D. (Security Hardening, Inspection, Enforcement & Liability Detection), "
                "a compliance analysis agent. Provide clear, actionable security assessments with specific "
                "rule IDs and fix commands. Use markdown."
            )

            # Extract project_id from scan_data
            project_id = scan_data.get("project_id") if isinstance(scan_data, dict) else None

            # Dispatch to LLM via Bridge
            dispatcher = get_dispatcher()
            result = dispatcher.dispatch(
                capability="compliance_analysis",
                prompt=prompt,
                module_id="security-network",
                system_prompt=system_prompt,
                project_id=project_id,
            )

            response_text = result.get("response", "")
            model_used = result.get("model", "unknown")
            tokens_used = result.get("tokens_used", 0)

            # Parse sections by splitting on ## headers
            executive_summary = ""
            remediation_plan = ""
            trend_analysis = ""

            sections = response_text.split("## ")
            for section in sections:
                section_stripped = section.strip()
                if section_stripped.upper().startswith("EXECUTIVE SUMMARY"):
                    executive_summary = section_stripped[len("EXECUTIVE SUMMARY") :].strip()
                elif section_stripped.upper().startswith("REMEDIATION PLAN"):
                    remediation_plan = section_stripped[len("REMEDIATION PLAN") :].strip()
                elif section_stripped.upper().startswith("TREND ANALYSIS"):
                    trend_analysis = section_stripped[len("TREND ANALYSIS") :].strip()

            # If parsing failed, put everything in executive summary
            if not executive_summary and not remediation_plan:
                executive_summary = response_text

            # Store in DB
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO compliance_ai_analysis
                       (scan_target, scan_id, executive_summary, remediation_plan, trend_analysis, model_used, tokens_used)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        scan_target,
                        db_scan_id,
                        executive_summary,
                        remediation_plan,
                        trend_analysis,
                        model_used,
                        tokens_used,
                    ),
                )

            logger.info(
                "S.H.I.E.L.D. analysis complete for %s (scan_id=%s, model=%s, tokens=%s)",
                scan_target,
                db_scan_id,
                model_used,
                tokens_used,
            )

    except Exception as e:
        logger.error("S.H.I.E.L.D. analysis failed for %s: %s", scan_target, e)


@standalone_api_bp.route("/compliance-report", methods=["POST"])
def receive_compliance_report():
    """Receive and store a compliance scan report from a standalone product."""
    client, error = _authenticate_client()
    if error:
        return jsonify({"success": False, "error": error}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "error": "JSON body required"}), 400

    # Validate required fields
    scan_id = data.get("scan_id")
    if not scan_id:
        return jsonify({"success": False, "error": "scan_id is required"}), 400

    pack_ids = data.get("pack_ids", [])
    if not isinstance(pack_ids, list):
        return jsonify({"success": False, "error": "pack_ids must be an array"}), 400

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO compliance_scans
                   (scan_id, pack_ids, total_rules, passed, failed, errors,
                    not_applicable, manual, score, started_at, completed_at,
                    triggered_by, node_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (scan_id) DO UPDATE SET
                       total_rules = EXCLUDED.total_rules,
                       passed = EXCLUDED.passed,
                       failed = EXCLUDED.failed,
                       errors = EXCLUDED.errors,
                       not_applicable = EXCLUDED.not_applicable,
                       manual = EXCLUDED.manual,
                       score = EXCLUDED.score,
                       completed_at = EXCLUDED.completed_at
                   RETURNING id""",
                (
                    scan_id,
                    pack_ids,
                    data.get("total_rules", 0),
                    data.get("passed", 0),
                    data.get("failed", 0),
                    data.get("errors", 0),
                    data.get("not_applicable", 0),
                    data.get("manual", 0),
                    data.get("score"),
                    data.get("started_at"),
                    data.get("completed_at"),
                    data.get("triggered_by", f"standalone:{client[1]}"),
                    data.get("node_id", "standalone"),
                ),
            )
            row = cur.fetchone()
            db_id = row[0] if row else None

        logger.info(
            "Compliance report received: scan_id=%s from client=%s (db id=%s)",
            scan_id,
            client[1],
            db_id,
        )

        # Trigger S.H.I.E.L.D. AI analysis in background
        from flask import current_app

        product_name = data.get("scan_target", data.get("product_name", "unknown"))
        thread = threading.Thread(
            target=_run_shield_analysis,
            args=(current_app._get_current_object(), product_name, data, db_id),
            daemon=True,
        )
        thread.start()

        return jsonify({"success": True, "scan_id": db_id}), 201

    except Exception as e:
        logger.error("Failed to store compliance report: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


@standalone_api_bp.route("/compliance-analysis")
def get_compliance_analysis():
    """Fetch latest S.H.I.E.L.D. AI analysis for a standalone product."""
    client, error = _authenticate_client()
    if error:
        return jsonify({"success": False, "error": error}), 401

    scan_target = request.args.get("scan_target", "")
    if not scan_target:
        return jsonify({"success": False, "error": "scan_target parameter required"}), 400

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT executive_summary, remediation_plan, trend_analysis, model_used, generated_at
                   FROM compliance_ai_analysis
                   WHERE scan_target = %s
                   ORDER BY generated_at DESC LIMIT 1""",
                (scan_target,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": True, "analysis": None})

            return jsonify(
                {
                    "success": True,
                    "analysis": {
                        "executive_summary": row["executive_summary"],
                        "remediation_plan": row["remediation_plan"],
                        "trend_analysis": row["trend_analysis"],
                        "model_used": row["model_used"],
                        "generated_at": (row["generated_at"].isoformat() if row["generated_at"] else None),
                    },
                }
            )
    except Exception as e:
        logger.error("Failed to fetch compliance analysis: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


def init_standalone_api(app):
    """Register the standalone API blueprint."""
    app.register_blueprint(standalone_api_bp)
    logger.info("Standalone API initialized (compliance-report + compliance-analysis endpoints)")
