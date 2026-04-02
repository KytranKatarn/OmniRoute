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
CATALOG_DIR = os.environ.get(
    "FLEET_CATALOG_DIR",
    "/mnt/archie_brain/fleet/catalog/apps",
)


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
                        SELECT id, node_type, used, expires_at, created_by
                        FROM fleet_registration_tokens
                        WHERE token = %s
                        """,
                        (token_value,),
                    )
                    tok = cur.fetchone()

                    if not tok:
                        return jsonify({"success": False, "error": "Invalid registration token"}), 403

                    tok_id, tok_type, tok_used, tok_expires, tok_created_by = tok

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
                         registration_method, device_info,
                         approved_by, approved_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, CASE WHEN %s = 'approved' THEN NOW() ELSE NULL END)
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
                        tok_created_by if token_value and approval_status == "approved" else None,
                        approval_status,
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
                        compatible = app_def.get("compatible_nodes", [])
                        if compatible and node_type_filter not in compatible:
                            continue

                    apps.append(app_def)
                except Exception:
                    # Skip malformed YAML files
                    continue

            return jsonify({"success": True, "apps": apps, "count": len(apps)})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # GET /api/fleet-map — fleet map data (hub + nodes + cloud providers)
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet-map")
    @admin_required
    def api_fleet_map():
        """Fleet map data: hub + nodes + cloud providers with coordinates."""
        try:
            from services.fleet_service import get_fleet_map_data

            data = get_fleet_map_data()
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # GET /api/fleet-usage — cloud provider usage summary
    # ------------------------------------------------------------------ #
    @bp.route("/api/fleet-usage")
    @admin_required
    def api_fleet_usage():
        """Cloud provider usage summary."""
        try:
            from services.fleet_service import get_usage_summary

            provider = request.args.get("provider")
            days = int(request.args.get("days", 30))
            data = get_usage_summary(provider_key=provider, days=days)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # GET /api/providers — list all cloud providers
    # ------------------------------------------------------------------ #
    @bp.route("/api/providers")
    @admin_required
    def api_list_providers():
        """List all cloud providers."""
        try:
            from services.fleet_service import list_providers

            return jsonify({"providers": list_providers()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/providers/<key>/toggle — toggle provider active/inactive
    # ------------------------------------------------------------------ #
    @bp.route("/api/providers/<provider_key>/toggle", methods=["POST"])
    @admin_required
    def api_toggle_provider(provider_key):
        """Toggle a provider active/inactive."""
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE contractor_providers
                    SET is_active = NOT is_active
                    WHERE provider_key = %s
                    RETURNING is_active
                    """,
                    (provider_key,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Provider not found"}), 404
                return jsonify(
                    {
                        "success": True,
                        "provider_key": provider_key,
                        "is_active": row["is_active"],
                    }
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/providers/<key>/budget — update provider budget
    # ------------------------------------------------------------------ #
    @bp.route("/api/providers/<provider_key>/budget", methods=["POST"])
    @admin_required
    def api_update_provider_budget(provider_key):
        """Update a provider's monthly budget."""
        try:
            from database import get_db_cursor

            data = request.get_json() or {}
            budget = float(data.get("monthly_budget_usd", 0))
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE external_api_keys
                    SET monthly_budget_usd = %s
                    WHERE provider = %s
                    RETURNING monthly_budget_usd
                    """,
                    (budget, provider_key),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Provider not found in api_keys"}), 404
                return jsonify(
                    {
                        "success": True,
                        "monthly_budget_usd": float(row["monthly_budget_usd"]),
                    }
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Cloud Provider CRUD ──────────────────────────────────────────

    @bp.route("/api/cloud-providers")
    @admin_required
    def api_list_cloud_providers():
        try:
            from services.fleet_service import list_cloud_providers

            providers = list_cloud_providers()
            for p in providers:
                for key in ("latitude", "longitude", "monthly_budget", "monthly_usage"):
                    if p.get(key) is not None:
                        p[key] = float(p[key])
            return jsonify({"providers": providers})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/cloud-providers", methods=["POST"])
    @admin_required
    def api_create_cloud_provider():
        try:
            from services.fleet_service import register_provider

            data = request.get_json() or {}
            name = data.get("name", "").strip()
            if not name:
                return jsonify({"error": "name is required"}), 400
            pid = register_provider(
                name=name,
                provider_type=data.get("provider_type", "cloud"),
                api_key_env_var=data.get("api_key_env_var", ""),
                tier=data.get("tier", "free"),
                capabilities=data.get("capabilities", []),
                models_available=data.get("models_available", []),
                api_endpoint=data.get("api_endpoint", ""),
                headquarters_city=data.get("headquarters_city", ""),
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                monthly_budget=data.get("monthly_budget", 0),
            )
            return jsonify({"success": True, "id": pid})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/cloud-providers/<int:provider_id>/toggle", methods=["POST"])
    @admin_required
    def api_toggle_cloud_provider(provider_id):
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE cloud_providers
                       SET status = CASE WHEN status = 'active' THEN 'inactive' ELSE 'active' END,
                           updated_at = NOW()
                       WHERE id = %s RETURNING id, name, status""",
                    (provider_id,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Provider not found"}), 404
                return jsonify(
                    {
                        "success": True,
                        "id": row["id"],
                        "name": row["name"],
                        "status": row["status"],
                    }
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/cloud-providers/<int:provider_id>/budget", methods=["POST"])
    @admin_required
    def api_update_cloud_provider_budget(provider_id):
        try:
            from database import get_db_cursor

            data = request.get_json() or {}
            budget = data.get("monthly_budget")
            if budget is None:
                return jsonify({"error": "monthly_budget is required"}), 400
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE cloud_providers SET monthly_budget = %s, updated_at = NOW()
                       WHERE id = %s RETURNING id, name, monthly_budget""",
                    (budget, provider_id),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"error": "Provider not found"}), 404
                return jsonify(
                    {
                        "success": True,
                        "id": row["id"],
                        "monthly_budget": float(row["monthly_budget"]),
                    }
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/api/cloud-providers/<int:provider_id>/usage")
    @admin_required
    def api_cloud_provider_usage(provider_id):
        try:
            from database import get_db_cursor

            days = int(request.args.get("days", 30))
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT model_name, COUNT(*) AS calls,
                              SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out,
                              SUM(estimated_cost) AS total_cost
                       FROM cloud_usage_log
                       WHERE provider_id = %s AND created_at > NOW() - INTERVAL '%s days'
                       GROUP BY model_name ORDER BY total_cost DESC""",
                    (provider_id, days),
                )
                rows = cur.fetchall()
                return jsonify(
                    {
                        "provider_id": provider_id,
                        "days": days,
                        "by_model": [
                            {
                                "model": r["model_name"],
                                "calls": r["calls"],
                                "tokens_in": r["tokens_in"] or 0,
                                "tokens_out": r["tokens_out"] or 0,
                                "cost": float(r["total_cost"] or 0),
                            }
                            for r in rows
                        ],
                    }
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Cert Distribution ────────────────────────────────────────────

    WILDCARD_CERT_DIR = os.path.join(os.environ.get("FLEET_CERT_DIR", "/opt/archie-fleet/certs"), "wildcard")

    @bp.route("/api/fleet/certs/wildcard/check", methods=["GET"])
    def fleet_cert_check():
        """Lightweight cert metadata check for fleet nodes."""
        remote_ip = request.remote_addr or ""
        if not remote_ip.startswith("100.64."):
            api_key = request.headers.get("X-Node-API-Key")
            if not api_key:
                return jsonify({"success": False, "error": "Mesh or API key required"}), 403

        cert_path = os.path.join(WILDCARD_CERT_DIR, "fullchain.pem")
        if not os.path.exists(cert_path):
            return jsonify({"success": False, "error": "No wildcard cert available"}), 404

        try:
            from cryptography import x509 as x509_mod

            with open(cert_path, "rb") as f:
                cert_pem = f.read()
            cert = x509_mod.load_pem_x509_certificate(cert_pem)
            cert_hash = hashlib.sha256(cert_pem).hexdigest()

            return jsonify(
                {
                    "success": True,
                    "expires_at": cert.not_valid_after_utc.isoformat(),
                    "sha256": cert_hash,
                    "domain": "*.kytranempowerment.com",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/fleet/certs/wildcard", methods=["GET"])
    def fleet_cert_download():
        """Full cert + key download for fleet nodes. Mesh-only or API key required."""
        remote_ip = request.remote_addr or ""
        if not remote_ip.startswith("100.64."):
            api_key = request.headers.get("X-Node-API-Key")
            if not api_key:
                return jsonify({"success": False, "error": "Mesh or API key required"}), 403

        cert_path = os.path.join(WILDCARD_CERT_DIR, "fullchain.pem")
        key_path = os.path.join(WILDCARD_CERT_DIR, "privkey.pem")

        if not os.path.exists(cert_path) or not os.path.exists(key_path):
            return jsonify({"success": False, "error": "No wildcard cert available"}), 404

        try:
            from cryptography import x509 as x509_mod

            with open(cert_path, "rb") as f:
                cert_pem = f.read()
            with open(key_path, "rb") as f:
                key_pem = f.read()

            cert = x509_mod.load_pem_x509_certificate(cert_pem)
            cert_hash = hashlib.sha256(cert_pem).hexdigest()

            return jsonify(
                {
                    "success": True,
                    "cert_pem": cert_pem.decode(),
                    "key_pem": key_pem.decode(),
                    "expires_at": cert.not_valid_after_utc.isoformat(),
                    "sha256": cert_hash,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
