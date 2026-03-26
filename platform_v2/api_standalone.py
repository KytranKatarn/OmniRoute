"""
Standalone Product API — receives compliance scan results from standalone products.

Endpoints:
  POST /api/standalone/compliance-report — store compliance scan results

Auth: Bearer {base64(client_id:client_secret)} validated against oauth_clients table.
"""

import base64
import logging
from datetime import datetime

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
        return jsonify({"success": True, "scan_id": db_id}), 201

    except Exception as e:
        logger.error("Failed to store compliance report: %s", e)
        return jsonify({"success": False, "error": "Internal server error"}), 500


def init_standalone_api(app):
    """Register the standalone API blueprint."""
    app.register_blueprint(standalone_api_bp)
    logger.info("Standalone API initialized (compliance-report endpoint)")
