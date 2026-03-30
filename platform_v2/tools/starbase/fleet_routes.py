"""
Fleet Registration & Catalog Routes
====================================
Token generation, node registration, approval workflow, and app catalog.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-30
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import yaml
from flask import jsonify, request, send_from_directory
from flask_login import current_user
from psycopg2.extras import Json, RealDictCursor

from database import get_db_cursor

VALID_NODE_TYPES = ("outpost", "starship", "satellite")
CATALOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "fleet", "catalog", "apps")


def register_fleet_routes(bp, admin_required):
    """Register fleet registration, approval, and catalog routes."""

    # ------------------------------------------------------------------ #
    # Satellite PWA — serve static files
    # ------------------------------------------------------------------ #
    satellite_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static", "fleet", "satellite")

    @bp.route("/fleet/satellite/")
    @bp.route("/fleet/satellite/<path:filename>")
    def fleet_satellite(filename="index.html"):
        """Serve satellite PWA static files."""
        return send_from_directory(satellite_dir, filename)

    # ------------------------------------------------------------------ #
    # POST /api/fleet/token/generate — admin generates registration token
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet/token/generate", methods=["POST"])
    @admin_required
    def fleet_token_generate():
        try:
            data = request.get_json(silent=True) or {}
            node_type = data.get("node_type", "outpost")
            expires_in_hours = int(data.get("expires_in_hours", 24))

            if node_type not in VALID_NODE_TYPES:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Invalid node_type. Must be one of: {', '.join(VALID_NODE_TYPES)}",
                        }
                    ),
                    400,
                )

            if expires_in_hours < 1 or expires_in_hours > 720:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "expires_in_hours must be between 1 and 720",
                        }
                    ),
                    400,
                )

            token = secrets.token_urlsafe(32)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO fleet_registration_tokens
                        (token, node_type, created_by, expires_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (token, node_type, current_user.id, expires_at),
                )
                token_id = cur.fetchone()[0]

            return jsonify(
                {
                    "success": True,
                    "token": token,
                    "token_id": token_id,
                    "node_type": node_type,
                    "expires_at": expires_at.isoformat(),
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/fleet/register — node self-registration (no auth)
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet/register", methods=["POST"])
    def fleet_register():
        try:
            data = request.get_json(silent=True) or {}
            name = data.get("name", "").strip()
            node_type = data.get("type", "outpost")
            token_value = data.get("token")
            device_info = data.get("device_info", {})

            if not name:
                return jsonify({"success": False, "error": "name is required"}), 400

            if node_type not in VALID_NODE_TYPES:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Invalid type. Must be one of: {', '.join(VALID_NODE_TYPES)}",
                        }
                    ),
                    400,
                )

            approval_status = "pending"

            # Validate token if provided
            if token_value:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        SELECT id, node_type, used, expires_at
                        FROM fleet_registration_tokens
                        WHERE token = %s
                        """,
                        (token_value,),
                    )
                    tok = cur.fetchone()

                    if not tok:
                        return jsonify({"success": False, "error": "Invalid registration token"}), 403

                    tok_id, tok_type, tok_used, tok_expires = tok

                    if tok_used:
                        return jsonify({"success": False, "error": "Token already used"}), 403

                    if tok_expires < datetime.now(timezone.utc):
                        return jsonify({"success": False, "error": "Token has expired"}), 403

                    if tok_type != node_type:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Token is for '{tok_type}', not '{node_type}'",
                                }
                            ),
                            403,
                        )

                    # Mark token as used
                    cur.execute(
                        """
                        UPDATE fleet_registration_tokens
                        SET used = TRUE, used_at = NOW()
                        WHERE id = %s
                        """,
                        (tok_id,),
                    )
                    approval_status = "approved"

            # Generate node credentials
            node_id = "node_" + secrets.token_hex(12)
            api_key = secrets.token_urlsafe(48)
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO remote_nodes
                        (node_id, node_name, api_key_hash, hostname,
                         status, deployment_mode, approval_status,
                         registration_method, device_info)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        node_id,
                        name,
                        api_key_hash,
                        request.remote_addr or "unknown",
                        "offline",
                        node_type,
                        approval_status,
                        "token" if token_value else "manual",
                        Json(device_info),
                    ),
                )

            result = {
                "success": True,
                "node_id": node_id,
                "status": approval_status,
            }
            if approval_status == "approved":
                result["api_key"] = api_key

            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # GET /api/fleet/status/<node_id> — check registration status (polling)
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet/status/<node_id>", methods=["GET"])
    def fleet_status(node_id):
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT node_id, node_name, approval_status, status
                    FROM remote_nodes
                    WHERE node_id = %s
                    """,
                    (node_id,),
                )
                node = cur.fetchone()

            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            result = {
                "success": True,
                "status": node["approval_status"],
            }

            # If approved and caller needs a key, generate a fresh one
            need_key = request.args.get("need_key", "").lower() == "true"
            if need_key and node["approval_status"] == "approved":
                new_api_key = secrets.token_urlsafe(48)
                new_hash = hashlib.sha256(new_api_key.encode()).hexdigest()

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        UPDATE remote_nodes SET api_key_hash = %s
                        WHERE node_id = %s
                        """,
                        (new_hash, node_id),
                    )
                result["api_key"] = new_api_key

            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/fleet/approve/<node_id> — admin approves pending node
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet/approve/<node_id>", methods=["POST"])
    @admin_required
    def fleet_approve(node_id):
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET approval_status = 'approved'
                    WHERE node_id = %s AND approval_status = 'pending'
                    RETURNING node_id, node_name
                    """,
                    (node_id,),
                )
                row = cur.fetchone()

            if not row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Node not found or not in pending state",
                        }
                    ),
                    404,
                )

            return jsonify(
                {
                    "success": True,
                    "node_id": row[0],
                    "node_name": row[1],
                    "status": "approved",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/fleet/deny/<node_id> — admin denies pending node
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet/deny/<node_id>", methods=["POST"])
    @admin_required
    def fleet_deny(node_id):
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET approval_status = 'denied'
                    WHERE node_id = %s AND approval_status = 'pending'
                    RETURNING node_id, node_name
                    """,
                    (node_id,),
                )
                row = cur.fetchone()

            if not row:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Node not found or not in pending state",
                        }
                    ),
                    404,
                )

            return jsonify(
                {
                    "success": True,
                    "node_id": row[0],
                    "node_name": row[1],
                    "status": "denied",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # GET /api/fleet/catalog — return app catalog from YAML files
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet/catalog", methods=["GET"])
    def fleet_catalog():
        try:
            node_type_filter = request.args.get("node_type")
            apps = []

            catalog_path = os.path.normpath(CATALOG_DIR)
            if not os.path.isdir(catalog_path):
                return jsonify({"success": True, "apps": [], "count": 0})

            for filename in sorted(os.listdir(catalog_path)):
                if not filename.endswith((".yml", ".yaml")):
                    continue
                filepath = os.path.join(catalog_path, filename)
                try:
                    with open(filepath, "r") as f:
                        app_def = yaml.safe_load(f)
                    if not isinstance(app_def, dict):
                        continue

                    # Filter by node_type compatibility if requested
                    if node_type_filter:
                        compatible = app_def.get("compatible_node_types", [])
                        if compatible and node_type_filter not in compatible:
                            continue

                    apps.append(app_def)
                except Exception:
                    # Skip malformed YAML files
                    continue

            return jsonify({"success": True, "apps": apps, "count": len(apps)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
