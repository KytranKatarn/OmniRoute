"""
Fleet Module — Fleet & Provider Routes
=======================================
Merged from starbase/fleet_routes.py and starbase/provider_routes.py.
Fleet map, cloud providers, budgets, ComfyUI, routing, node models, certs,
token generation, node registration, approval workflow, and app catalog.

ADR-045 pattern: register_fleet_routes(bp, auth_decorator)
"""

import hashlib
import json
import os
import secrets
import sys
import logging
from services.governance_hmac import sign_event
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras
import requests
import yaml
from flask import jsonify, request, send_from_directory
from flask_login import current_user, login_required
from psycopg2.extras import Json, RealDictCursor
from rbac import require_permission, Permission
from database import get_db_cursor

from .fleet_helpers import (
    OLLAMA_LOCAL_URL,
    DEFAULT_NODE_PORT,
    LEGACY_STATION_DEPARTMENT,
    DEPARTMENT_TO_STATION,
)

logger = logging.getLogger(__name__)

#: Cap on a usable latency sample. Measured cold, a 16b model took ~70s for twelve
#: tokens; allowing that into an average would let one outlier define the ranking.
_HEALTH_LATENCY_CEILING_MS = 60_000

VALID_NODE_TYPES = ("outpost", "starship", "satellite")
CATALOG_DIR = os.environ.get(
    "FLEET_CATALOG_DIR",
    "/mnt/archie_brain/fleet/catalog/apps",
)


def register_fleet_routes(bp, auth_decorator):
    """Register fleet registration, approval, catalog, provider, and model routes."""

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
    @auth_decorator
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
    @auth_decorator
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
    @auth_decorator
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
    @auth_decorator
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
    @auth_decorator
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
    @auth_decorator
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
    def _record_switch(cur, provider_key, switch_name, from_value, to_value):
        """Append one row to the operator audit trail. Never raises.

        A failed audit write must not roll back the operator's actual decision. Losing the flip
        because the record failed would be a worse outcome than losing the record, so this
        swallows and logs — the same trade `record_observation` makes in the health service.
        """
        try:
            actor = None
            if current_user and getattr(current_user, "is_authenticated", False):
                actor = getattr(current_user, "username", None)
            cur.execute(
                """
                INSERT INTO contractor_switch_audit
                    (provider_key, switch_name, from_value, to_value, actor)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (provider_key, switch_name, from_value, to_value, actor),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "contractor switch audit: write failed for %s/%s (%s: %s) — " "the switch itself still moved",
                provider_key,
                switch_name,
                exc.__class__.__name__,
                exc,
            )

    @bp.route("/api/providers/<provider_key>/toggle", methods=["POST"])
    @auth_decorator
    def api_toggle_provider(provider_key):
        """Toggle a provider active/inactive — and keep the legacy key table in step.

        `contractor_providers.is_active` is the authority the tab now renders. But
        `external_providers._get_api_key` still gates key material on
        `external_api_keys.is_active = TRUE`, so flipping only the authority column would
        leave a trap: re-enable a provider whose legacy row says inactive and the selector
        happily picks it, then finds no key to call it with. That is a silent failure at the
        worst moment — the moment an operator deliberately switched a contractor back on.

        So both are written, in the same transaction, from the same computed value. A
        provider with no legacy row simply has nothing to update, which is the normal case
        for anything registered after the DS9 migration.

        (The older POST /api/external-providers/<provider>/toggle still flips only the legacy
        column. Nothing in the Contractors tab calls it; it should be deprecated rather than
        left as a second way to desync the pair.)
        """
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "SELECT is_active FROM contractor_providers WHERE provider_key = %s",
                    (provider_key,),
                )
                before = cur.fetchone()
                if before is None:
                    return jsonify({"error": "Provider not found"}), 404

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
                _record_switch(cur, provider_key, "is_active", before["is_active"], row["is_active"])

                cur.execute(
                    """
                    UPDATE external_api_keys
                    SET is_active = %s, updated_at = NOW()
                    WHERE provider = %s
                    """,
                    (row["is_active"], provider_key),
                )
                synced = cur.rowcount

                return jsonify(
                    {
                        "success": True,
                        "provider_key": provider_key,
                        "is_active": row["is_active"],
                        "legacy_rows_synced": synced,
                    }
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/providers/<key>/dispatchable — toggle the ROUTING switch (DS9 PR 1)
    # ------------------------------------------------------------------ #
    @bp.route("/api/providers/<provider_key>/switch-history")
    @auth_decorator
    def api_provider_switch_history(provider_key):
        """Recent operator switch changes for one provider, newest first.

        Read side of `contractor_switch_audit`. Written without this, the table would be a log
        nobody can open — and the question it exists to answer ("who turned routing on for this
        paid provider, and when") is only useful if the answer is reachable from the tab.

        Degrades to an empty list if the table is absent, for the same reason the listing's
        health read does: the audit trail is observability, and observability must not be the
        thing that takes the tab down.
        """
        try:
            limit = min(max(request.args.get("limit", 20, type=int), 1), 200)
        except Exception:  # noqa: BLE001
            limit = 20

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT switch_name, from_value, to_value, actor, created_at
                      FROM contractor_switch_audit
                     WHERE provider_key = %s
                     ORDER BY created_at DESC, id DESC
                     LIMIT %s
                    """,
                    (provider_key, limit),
                )
                rows = cur.fetchall()
            return jsonify(
                {
                    "success": True,
                    "provider_key": provider_key,
                    "events": [
                        {
                            "switch": r["switch_name"],
                            "from": r["from_value"],
                            "to": r["to_value"],
                            "actor": r["actor"],
                            "at": r["created_at"].isoformat() if r["created_at"] else None,
                        }
                        for r in rows
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "contractor switch history: read failed for %s (%s: %s)",
                provider_key,
                exc.__class__.__name__,
                exc,
            )
            return jsonify({"success": True, "provider_key": provider_key, "events": []})

    @bp.route("/api/providers/<provider_key>/dispatchable", methods=["POST"])
    @auth_decorator
    def api_toggle_provider_dispatchable(provider_key):
        """Flip `dispatchable`, the switch that means "the dispatcher may route here".

        Separate from `is_active` on purpose. `is_active` says the provider is CONFIGURED —
        key present, endpoint reachable, probe passing. `dispatchable` says an operator has
        allowed traffic. A paid provider must never be dispatched unless this is flipped, so
        the two states have to be distinguishable in the UI: otherwise "configured but idle"
        cannot be expressed, and enabling one is indistinguishable from setting it up.

        Guarded: a paid provider cannot be switched on while its class is unmeasured, because
        the class is what makes "paid" a policy rather than a label.
        """
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    SELECT provider_class, dispatchable
                      FROM contractor_providers
                     WHERE provider_key = %s
                    """,
                    (provider_key,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "Provider not found"}), 404

                now = not bool(row["dispatchable"])
                cls = row["provider_class"]
                if now and cls is None:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": (
                                    "provider_class is unmeasured — the health probe has not "
                                    "classified this provider yet, so it cannot be enabled "
                                    "safely"
                                ),
                            }
                        ),
                        409,
                    )

                cur.execute(
                    """
                    UPDATE contractor_providers
                       SET dispatchable = %s, updated_at = NOW()
                     WHERE provider_key = %s
                     RETURNING dispatchable
                    """,
                    (now, provider_key),
                )
                updated = cur.fetchone()
                _record_switch(
                    cur,
                    provider_key,
                    "dispatchable",
                    row["dispatchable"],
                    updated["dispatchable"],
                )

            # NOTE: this deliberately writes NO row to contractor_health.
            #
            # It did once, as probe_kind='health', status='ok'. That was wrong twice over:
            # contractor_health is a history of PROBE OBSERVATIONS, and an operator flipping a
            # routing switch is not one. So flipping the switch on a provider whose last real
            # probe was `unreachable` replaced that finding with 'ok' — the tab showed a green
            # badge and the ranking counted a healthy provider that had never answered. The
            # schema agrees: probe_kind is CHECK-constrained to ('health','latency','full'), so
            # there is no honest way to record an operator action here either.
            #
            # The decision is not lost: it is the column itself, visible in this tab, and it
            # only takes effect through the selector gate. A real operator audit trail needs a
            # separate table with an 'operator' kind — not a forged probe.
            return jsonify(
                {
                    "success": True,
                    "provider_key": provider_key,
                    "dispatchable": updated["dispatchable"],
                    "provider_class": cls,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # POST /api/providers/<key>/budget — update provider budget
    # ------------------------------------------------------------------ #
    @bp.route("/api/providers/<provider_key>/budget", methods=["POST"])
    @auth_decorator
    def api_update_provider_budget(provider_key):
        """Update a provider's monthly budget."""
        try:
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

    # -- Cloud Provider CRUD -------------------------------------------------

    @bp.route("/api/cloud-providers")
    @auth_decorator
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
    @auth_decorator
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
    @auth_decorator
    def api_toggle_cloud_provider(provider_id):
        try:
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
    @auth_decorator
    def api_update_cloud_provider_budget(provider_id):
        try:
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
    @auth_decorator
    def api_cloud_provider_usage(provider_id):
        try:
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

    # -- Cert Distribution ---------------------------------------------------

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

    # ======================================================================
    # BRIDGE MODEL ROUTING (from provider_routes.py)
    # ======================================================================

    @bp.route("/api/nodes/<node_id>/bridge-sharing", methods=["PUT"])
    @login_required
    def toggle_bridge_sharing(node_id):
        """Enable or disable a node's model sharing with Bridge"""
        data = request.get_json() or {}
        enabled = data.get("enabled", False)
        priority = data.get("priority", 50)

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):

                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET bridge_enabled = %s,
                        bridge_priority = %s,
                        updated_at = NOW()
                    WHERE node_id = %s
                    RETURNING node_name
                """,
                    (enabled, priority, node_id),
                )

                result = cur.fetchone()
                if not result:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Log to governance audit
                action_val = "enable" if enabled else "disable"
                cur.execute(
                    """
                    INSERT INTO governance_audit_log (
                        event_type, event_category, agent_id, action, new_value, reason, outcome
                    ) VALUES (
                        'node_bridge_sharing', 'autonomy', NULL, %s, %s, %s, 'success'
                    )
                    RETURNING id, timestamp
                """,
                    (
                        action_val,
                        f'{{"node_id": "{node_id}", "priority": {priority}}}',
                        f"Bridge sharing {'enabled' if enabled else 'disabled'} for node {result[0]}",
                    ),
                )
                gov_row = cur.fetchone()
                if gov_row:
                    eid, ts = gov_row[0], gov_row[1]
                    sig = sign_event(
                        event_id=eid,
                        event_type="node_bridge_sharing",
                        event_category="autonomy",
                        agent_id=None,
                        user_id=None,
                        action=action_val,
                        target_table="remote_nodes",
                        target_id=None,
                        outcome="success",
                        timestamp_iso=ts.isoformat() if ts else "",
                    )
                    if sig:
                        cur.execute(
                            "UPDATE governance_audit_log SET hmac_sig=%s WHERE id=%s",
                            (sig, eid),
                        )

                return jsonify({"success": True, "bridge_enabled": enabled, "bridge_priority": priority})

        except Exception as e:
            logger.error(f"Toggle bridge sharing error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/models")
    @login_required
    def get_bridge_available_models():
        """Get all models available across bridge-enabled nodes, split local vs remote"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get per-model detail with id, node_id, is_available for toggle support
                cur.execute(
                    """
                    SELECT m.id, m.node_id, n.node_name, m.model_name, m.model_family,
                           m.parameter_size, m.model_size_gb, m.is_available,
                           m.total_requests, m.avg_response_ms,
                           n.bridge_enabled, n.status as node_status
                    FROM node_ollama_models m
                    JOIN remote_nodes n ON m.node_id = n.node_id
                    WHERE n.status = 'online' AND n.approval_status = 'approved'
                    ORDER BY m.model_name
                """
                )
                all_models = cur.fetchall()

                # Get aggregated view for summary
                cur.execute(
                    """
                    SELECT * FROM v_bridge_available_models
                """
                )
                aggregated = cur.fetchall()

                # Get summary stats
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT m.model_name) as total_models,
                        COUNT(DISTINCT n.node_id) as total_nodes,
                        SUM(m.total_requests) as total_requests
                    FROM node_ollama_models m
                    JOIN remote_nodes n ON m.node_id = n.node_id
                    WHERE n.bridge_enabled = true AND n.status = 'online'
                """
                )
                summary = cur.fetchone()

                # Get local Ollama models (this host)
                local_models = []
                try:
                    _oh = os.environ.get("OLLAMA_HOST", OLLAMA_LOCAL_URL)
                    if not _oh.startswith("http"):
                        _oh = f"http://{_oh}"
                    resp = requests.get(f"{_oh}/api/tags", timeout=5)
                    if resp.status_code == 200:
                        for m in resp.json().get("models", []):
                            size_gb = round(m.get("size", 0) / 1e9, 1)
                            local_models.append(
                                {
                                    "name": m["name"],
                                    "family": m.get("details", {}).get("family", ""),
                                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                                    "size_gb": size_gb,
                                }
                            )
                except Exception:
                    pass  # Local Ollama unreachable — just skip

                return jsonify(
                    {
                        "success": True,
                        "models": aggregated,
                        "all_models": all_models,
                        "local_models": local_models,
                        "summary": summary,
                    }
                )

        except Exception as e:
            logger.error(f"Get bridge models error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/models")
    @login_required
    def get_node_models(node_id):
        """Get Ollama models available on a specific node"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get node info
                cur.execute(
                    """
                    SELECT node_name, bridge_enabled, bridge_priority, last_model_sync, status
                    FROM remote_nodes WHERE node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get models
                cur.execute(
                    """
                    SELECT id, model_name, model_family, parameter_size, model_size_gb,
                           is_available, total_requests, avg_response_ms,
                           context_length, quantization, updated_at
                    FROM node_ollama_models
                    WHERE node_id = %s
                    ORDER BY model_name
                """,
                    (node_id,),
                )
                models = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "node": node,
                        "models": models,
                        "model_count": len(models),
                    }
                )

        except Exception as e:
            logger.error(f"Get node models error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/models/sync", methods=["POST"])
    @login_required
    def sync_node_models_api(node_id):
        """Manually trigger model sync for a node (fetches from node's Ollama)"""
        try:
            with get_db_cursor() as (conn, cur):

                # Get node info
                cur.execute(
                    """
                    SELECT vpn_ip, port, ollama_available FROM remote_nodes WHERE node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                if not node["ollama_available"]:
                    return (
                        jsonify({"success": False, "error": "Node does not have Ollama"}),
                        400,
                    )

                # Fetch models from node's Ollama
                import requests as req

                ollama_url = f"http://{node['vpn_ip']}:{node.get('port', DEFAULT_NODE_PORT)}/api/tags"

                try:
                    resp = req.get(ollama_url, timeout=10)
                    if resp.status_code != 200:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": f"Ollama returned {resp.status_code}",
                                }
                            ),
                            502,
                        )

                    models = resp.json().get("models", [])

                except req.exceptions.RequestException as e:
                    return (
                        jsonify({"success": False, "error": f"Cannot reach node Ollama: {e}"}),
                        502,
                    )

                # Sync models using database function
                cur.execute(
                    """
                    SELECT sync_node_models(%s, %s::jsonb)
                """,
                    (node_id, psycopg2.extras.Json(models)),
                )
                result = cur.fetchone()
                models_synced = result[0] if result else 0

                return jsonify(
                    {
                        "success": True,
                        "models_synced": models_synced,
                        "message": f"Synced {models_synced} models from node",
                    }
                )

        except Exception as e:
            logger.error(f"Manual model sync error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/models/<int:model_id>/toggle", methods=["PUT"])
    @login_required
    def toggle_model_availability(node_id, model_id):
        """Enable or disable a specific model on a node for bridge routing"""
        data = request.get_json() or {}
        enabled = data.get("enabled", True)

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):

                cur.execute(
                    """
                    UPDATE node_ollama_models
                    SET is_available = %s, updated_at = NOW()
                    WHERE id = %s AND node_id = %s
                    RETURNING model_name
                """,
                    (enabled, model_id, node_id),
                )

                result = cur.fetchone()
                if not result:
                    return jsonify({"success": False, "error": "Model not found"}), 404

                return jsonify(
                    {
                        "success": True,
                        "model_name": result[0],
                        "is_available": enabled,
                    }
                )

        except Exception as e:
            logger.error(f"Toggle model availability error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/select-node", methods=["POST"])
    @login_required
    def select_node_for_model():
        """Select the best available node for a specific model"""
        data = request.get_json() or {}
        model_name = data.get("model_name")
        prefer_gpu = data.get("prefer_gpu", True)

        if not model_name:
            return jsonify({"success": False, "error": "model_name required"}), 400

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT * FROM select_node_for_model(%s, %s) LIMIT 1
                """,
                    (model_name, prefer_gpu),
                )
                node = cur.fetchone()

                if not node:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"No bridge-enabled node has model {model_name}",
                            }
                        ),
                        404,
                    )

                return jsonify(
                    {
                        "success": True,
                        "node": node,
                        "ollama_url": f"http://{node['vpn_ip']}:{node['port']}",
                    }
                )

        except Exception as e:
            logger.error(f"Select node for model error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ======================================================================
    # COMFYUI MODEL CONTROL
    # ======================================================================

    @bp.route("/api/bridge/comfyui/models")
    @login_required
    def comfyui_models():
        """List ComfyUI checkpoint models and current service status."""
        try:
            from ai_bridge.comfyui_service import get_comfyui_service

            svc = get_comfyui_service()
            healthy = svc.health_check()
            if not healthy:
                return jsonify(
                    {
                        "success": True,
                        "online": False,
                        "models": [],
                        "queue": {"running": 0, "pending": 0},
                    }
                )

            models_data = svc.get_models()
            queue = svc.get_queue_status()
            stats = svc.get_system_stats()

            # Determine which model is currently loaded in VRAM
            loaded_model = None
            vram_used_gb = 0
            if stats:
                devices = stats.get("devices", [])
                for dev in devices:
                    if dev.get("type") == "cuda":
                        alloc = dev.get("vram_total", 0) - dev.get("vram_free", 0)
                        vram_used_gb = round(alloc / (1024**3), 2)
                        # If significant VRAM allocated, a model is loaded
                        if vram_used_gb > 0.5:
                            loaded_model = models_data.get("current")

            return jsonify(
                {
                    "success": True,
                    "online": True,
                    "models": models_data.get("installed", []),
                    "current_model": loaded_model,
                    "vram_used_gb": vram_used_gb,
                    "queue": {
                        "running": queue.get("running", 0),
                        "pending": queue.get("pending", 0),
                    },
                }
            )
        except Exception as e:
            logger.error(f"comfyui_models error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/comfyui/control", methods=["POST"])
    @login_required
    def comfyui_control():
        """Load (warmup) or unload a ComfyUI checkpoint model.

        Body: { "model": "sd_xl_base_1.0.safetensors", "action": "load"|"unload" }
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            from ai_bridge.comfyui_service import get_comfyui_service

            svc = get_comfyui_service()
            if not svc.health_check():
                return jsonify({"success": False, "error": "ComfyUI is offline"}), 503

            data = request.get_json() or {}
            model_name = data.get("model", "").strip()
            action = data.get("action", "").strip()

            if not model_name or action not in ("load", "unload"):
                return jsonify({"success": False, "error": "model and action (load|unload) required"}), 400

            comfyui_host = svc.host

            if action == "unload":
                # Free all models from VRAM
                resp = requests.post(
                    f"{comfyui_host}/free",
                    json={"unload_models": True},
                    timeout=10,
                )
                if resp.status_code == 200:
                    return jsonify({"success": True, "message": "ComfyUI VRAM freed"})
                return jsonify({"success": False, "error": f"ComfyUI returned {resp.status_code}"}), 502

            # action == "load" — warmup the checkpoint via minimal generation
            logger.info(f"ComfyUI model load requested: {model_name}")
            ok = svc.warmup(model=model_name)
            if ok:
                return jsonify({"success": True, "message": f"{model_name} loaded into VRAM"})
            return jsonify({"success": False, "error": f"Failed to warmup {model_name}"}), 502

        except requests.Timeout:
            return jsonify({"success": False, "error": "ComfyUI warmup timed out"}), 504
        except Exception as e:
            logger.error(f"comfyui_control error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/bridge/reassign", methods=["POST"])
    @login_required
    def reassign_agent():
        """Manually reassign an agent to a different department (admin only).

        Accepts station_code (mapped via LEGACY_STATION_DEPARTMENT) or department name.
        station_assignments table is DROPPED — updates agents.department directly.
        """
        try:
            if not current_user.is_admin:
                return jsonify({"success": False, "error": "Admin access required"}), 403

            data = request.get_json() or {}
            agent_id = data.get("agent_id")
            new_station_code = data.get("station_code")
            department = data.get("department")

            # Map station_code to department if needed
            if not department and new_station_code:
                depts = LEGACY_STATION_DEPARTMENT.get(new_station_code.upper(), [])
                department = depts[0] if depts else None

            if not agent_id or not department:
                return jsonify({"success": False, "error": "agent_id and (station_code or department) required"}), 400

            with get_db_cursor() as (conn, cur):
                cur.execute("SELECT id, name FROM agents WHERE id = %s AND status = 'active'", (agent_id,))
                agent = cur.fetchone()
            if not agent:
                return jsonify({"success": False, "error": "Agent not found or inactive"}), 404

            # Single-writer path: department reassignment goes through
            # agent_service.update_agent which auto-derives the floor
            # from DEPARTMENT_FLOOR_MAP and stamps updated_at (Project
            # #241 Track C.1).
            from services import agent_service

            try:
                agent_service.update_agent(agent_id, department=department)
            except ValueError as ve:
                return jsonify({"success": False, "error": str(ve)}), 400

            logger.info(f"Agent {agent['name']} reassigned to {department} by {current_user.username}")

            return jsonify(
                {
                    "success": True,
                    "message": f"{agent['name']} reassigned to {department}",
                    "agent_id": agent_id,
                    "station_code": DEPARTMENT_TO_STATION.get(department, new_station_code or ""),
                    "department": department,
                }
            )

        except Exception as e:
            logger.error(f"Error reassigning agent: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ======================================================================
    # ROUTING MODE & ESCALATION LOG API
    # ======================================================================

    @bp.route("/api/routing-mode", methods=["GET"])
    @login_required
    def get_routing_mode():
        """Get current bridge routing mode."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'routing_mode'")
                row = cur.fetchone()
                return jsonify({"success": True, "routing_mode": row["value"] if row else "full"})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/routing-mode", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def set_routing_mode():
        """Set bridge routing mode: local_only, local_cloud, or full."""
        data = request.get_json() or {}
        mode = data.get("routing_mode", "full")
        if mode not in ("local_only", "local_cloud", "full"):
            return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES ('routing_mode', %s, 'string', 'Bridge routing mode', NOW())
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
                """,
                    (mode, mode),
                )
                logger.info(f"[Bridge] Routing mode changed to: {mode}")
                return jsonify({"success": True, "routing_mode": mode})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/escalation-mode", methods=["GET"])
    @login_required
    def get_escalation_mode():
        """Get current bridge escalation mode."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT value FROM platform_settings WHERE key = 'escalation_mode'")
                row = cur.fetchone()
                # Sovereign-by-default (#4659): no row → cloud OFF, not auto.
                return jsonify({"success": True, "escalation_mode": row["value"] if row else "local_only"})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/escalation-mode", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def set_escalation_mode():
        """Set bridge escalation mode: auto, ask_first, or local_only."""
        data = request.get_json() or {}
        mode = data.get("escalation_mode", "auto")
        if mode not in ("auto", "ask_first", "local_only"):
            return jsonify({"success": False, "error": f"Invalid mode: {mode}"}), 400
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES ('escalation_mode', %s, 'string', 'Throughput escalation mode', NOW())
                    ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW()
                """,
                    (mode, mode),
                )
                logger.info(f"[Bridge] Escalation mode changed to: {mode}")
                return jsonify({"success": True, "escalation_mode": mode})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/escalation-log", methods=["GET"])
    @login_required
    def get_escalation_log():
        """Get recent escalation events."""
        limit = request.args.get("limit", 20, type=int)
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT del.*, a.name as agent_name
                    FROM dispatch_escalation_log del
                    LEFT JOIN agents a ON a.id = del.original_agent_id
                    ORDER BY del.created_at DESC
                    LIMIT %s
                """,
                    (limit,),
                )
                rows = cur.fetchall()
                # Convert datetime objects for JSON serialization
                result = []
                for r in rows:
                    d = dict(r)
                    for k, v in d.items():
                        if hasattr(v, "isoformat"):
                            d[k] = v.isoformat()
                    result.append(d)
                return jsonify({"success": True, "escalations": result})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ======================================================================
    # EXTERNAL PROVIDER KEY MANAGEMENT
    # ======================================================================

    @bp.route("/api/external-providers", methods=["GET"])
    @login_required
    def fleet_get_external_providers():
        """List external AI providers with 24h stats, model breakdowns, and tier positions.
        All provider metadata now comes from the contractor_providers table (dynamic)."""
        # Latest probe per provider (DS9 PR 3).
        #
        # Hoisted ABOVE the main query and wrapped in its own try, deliberately. It was
        # originally inside the listing's try block, where its guard caught the missing
        # table, logged it, and then let the OUTER handler return 500 anyway — verified:
        # `health read unavailable (UndefinedTable ...)` in the log and a 500 on the wire,
        # with zero rows rendered. A guard that logs and then fails the request is not a
        # guard. This tab is where an operator looks to find out whether something is
        # wrong; it must survive its own observability table being absent.
        _health_status = {}
        _health_latency = {}
        _health_observed = {}
        _health_checked = {}
        try:
            with get_db_cursor(commit=False) as (_hc, hcur):
                hcur.execute(
                    """
                    SELECT DISTINCT ON (provider_key)
                           provider_key, status, observed_model, created_at
                      FROM contractor_health
                     ORDER BY provider_key, created_at DESC
                    """
                )
                for _h in hcur.fetchall():
                    _k = _h["provider_key"]
                    _health_status[_k] = _h["status"]
                    _health_observed[_k] = _h["observed_model"]
                    _health_checked[_k] = _h["created_at"]

                # Latency has its own read, restricted to rows that HAVE one. The most
                # recent row is usually a 1-token health probe whose latency says nothing
                # useful about the provider, so ranking must not pick that up.
                hcur.execute(
                    """
                    SELECT DISTINCT ON (provider_key)
                           provider_key, latency_ms
                      FROM contractor_health
                     WHERE latency_ms IS NOT NULL
                       AND probe_kind IN ('latency', 'full')
                       AND latency_ms <= %s
                     ORDER BY provider_key, created_at DESC
                    """,
                    (_HEALTH_LATENCY_CEILING_MS,),
                )
                for _h in hcur.fetchall():
                    _health_latency[_h["provider_key"]] = _h["latency_ms"]
        except Exception as _exc:  # noqa: BLE001 - observability must not break listing
            logger.warning(
                "external-providers: health read unavailable (%s: %s) — "
                "the tab will show UNKNOWN until the probe table exists",
                _exc.__class__.__name__,
                _exc,
            )

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # 1. Fetch all contractor_providers (single source of truth)
                cur.execute(
                    """
                    SELECT provider_key, display_name, base_url, default_model,
                           auth_method, auth_env_var, is_cloud_proxy, tier_position,
                           models, rate_limits, is_active, dispatchable, provider_class
                    FROM contractor_providers
                    ORDER BY tier_position
                """
                )
                cp_rows = cur.fetchall()
                contractor_providers = {row["provider_key"]: dict(row) for row in cp_rows}

                # 2. Fetch DB-managed API keys from external_api_keys
                cur.execute(
                    """
                    SELECT id, provider, is_active, monthly_budget_usd, current_month_cost_usd,
                           budget_reset_day, account_tier, created_at, updated_at,
                           CASE WHEN api_key_encrypted IS NOT NULL AND api_key_encrypted != ''
                                THEN '****' || RIGHT(api_key_encrypted, 4) ELSE NULL END as key_hint
                    FROM external_api_keys
                    ORDER BY provider
                """
                )
                db_keys = {row["provider"]: dict(row) for row in cur.fetchall()}

                # 3. Fetch 24h usage stats grouped by model
                cur.execute(
                    """
                    SELECT model_name, provider,
                           COUNT(*) as requests,
                           COALESCE(SUM(cost_usd), 0) as cost,
                           COALESCE(AVG(response_ms), 0) as avg_latency_ms,
                           ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                                 / NULLIF(COUNT(*), 0), 1) as success_rate
                    FROM cloud_model_usage
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                    GROUP BY model_name, provider
                """
                )
                stats_by_model = {}
                for row in cur.fetchall():
                    stats_by_model[row["model_name"]] = {
                        "requests": row["requests"],
                        "cost": float(row["cost"]),
                        "avg_latency_ms": round(float(row["avg_latency_ms"]), 1),
                        "success_rate": float(row["success_rate"]) if row["success_rate"] is not None else 100.0,
                    }

                # 3b. Session (2h) and weekly (7d) usage windows
                cur.execute(
                    """
                    SELECT model_name,
                           COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '2 hours') as session_requests,
                           COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') as weekly_requests
                    FROM cloud_model_usage
                    GROUP BY model_name
                """
                )
                usage_windows = {}
                for row in cur.fetchall():
                    usage_windows[row["model_name"]] = {
                        "session_2h": row["session_requests"],
                        "weekly_7d": row["weekly_requests"],
                    }

                # 3c. All-time usage stats
                cur.execute(
                    """
                    SELECT model_name,
                           COUNT(*) as requests,
                           COALESCE(SUM(cost_usd), 0) as cost,
                           COALESCE(AVG(response_ms), 0) as avg_latency_ms,
                           ROUND(100.0 * SUM(CASE WHEN success THEN 1 ELSE 0 END)
                                 / NULLIF(COUNT(*), 0), 1) as success_rate,
                           MIN(created_at) as first_used,
                           MAX(created_at) as last_used
                    FROM cloud_model_usage
                    GROUP BY model_name
                """
                )
                alltime_by_model = {}
                for row in cur.fetchall():
                    alltime_by_model[row["model_name"]] = {
                        "requests": row["requests"],
                        "cost": float(row["cost"]),
                        "avg_latency_ms": round(float(row["avg_latency_ms"]), 1),
                        "success_rate": float(row["success_rate"]) if row["success_rate"] is not None else 100.0,
                        "first_used": row["first_used"].isoformat() if row["first_used"] else None,
                        "last_used": row["last_used"].isoformat() if row["last_used"] else None,
                    }

                # 4. Per-model disabled state from platform_settings
                cur.execute(
                    """
                    SELECT key, value FROM platform_settings
                    WHERE key LIKE 'model_disabled:%%'
                """
                )
                disabled_models = set()
                for row in cur.fetchall():
                    model_name = row["key"].replace("model_disabled:", "", 1)
                    if row["value"].lower() == "true":
                        disabled_models.add(model_name)

                # 5. C.R.E.E.D. governance events from last 24h
                cur.execute(
                    """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN outcome = 'blocked' THEN 1 ELSE 0 END) as blocked
                    FROM governance_audit_log
                    WHERE timestamp >= NOW() - INTERVAL '24 hours'
                """
                )
                creed_row = cur.fetchone()
                creed_total_24h = creed_row["total"] if creed_row else 0
                creed_blocked_24h = creed_row["blocked"] if creed_row and creed_row["blocked"] else 0

                # 6. Ollama cloud API key check
                ollama_api_key_set = bool(os.environ.get("OLLAMA_API_KEY", "").strip())

                # 7. Build unified response — iterate all contractor_providers
                result = []
                for provider_key, cp in contractor_providers.items():
                    db_row = db_keys.get(provider_key)
                    models_def = cp.get("models") or []
                    if isinstance(models_def, str):
                        models_def = json.loads(models_def)
                    rate_limits_def = cp.get("rate_limits") or {}
                    if isinstance(rate_limits_def, str):
                        rate_limits_def = json.loads(rate_limits_def)
                    tier_pos = cp.get("tier_position", 99)

                    # Determine active state + budget
                    account_tier = db_row.get("account_tier", "free") if db_row else "free"
                    rate_limits = rate_limits_def.get(account_tier, rate_limits_def.get("free", {}))

                    if cp.get("is_cloud_proxy"):
                        is_active = bool(cp.get("is_active", False)) and ollama_api_key_set
                        auth_method = "OLLAMA_API_KEY env var"
                        source = "cloud_config"
                    else:
                        # contractor_providers.is_active is the ONLY authority here.
                        #
                        # This used to read external_api_keys.is_active whenever a legacy row
                        # existed, which made the tab contradict itself: the Disable button
                        # writes contractor_providers (POST /api/providers/<key>/toggle), so
                        # clicking it flipped one table while the badge kept rendering the
                        # other. Measured on the live roster — 4 of the 8 providers with a
                        # legacy key row disagreed with themselves, and cerebras showed
                        # INACTIVE while its own column said active.
                        #
                        # external_api_keys is pre-DS9 state and is still consulted for the
                        # things only it knows: the budget, the account tier and the key hint.
                        # It is no longer consulted for whether the contractor is configured.
                        is_active = bool(cp.get("is_active", False))
                        auth_method = (cp.get("auth_method") or "api_key").replace("_", " ").title()
                        source = "db"

                    monthly_budget = (
                        float(db_row["monthly_budget_usd"]) if db_row and db_row.get("monthly_budget_usd") else 0.0
                    )
                    current_cost = (
                        float(db_row["current_month_cost_usd"])
                        if db_row and db_row.get("current_month_cost_usd")
                        else 0.0
                    )
                    budget_pct = round((current_cost / monthly_budget) * 100, 1) if monthly_budget > 0 else 0.0

                    # Build per-model output
                    provider_requests = 0
                    provider_cost = 0.0
                    provider_latency_sum = 0.0
                    provider_success_sum = 0.0
                    provider_models_with_stats = 0

                    models_out = []
                    tier_positions = {}
                    for m in models_def:
                        m_name = m["name"]
                        m_stats = stats_by_model.get(
                            m_name,
                            {"requests": 0, "cost": 0.0, "avg_latency_ms": 0.0, "success_rate": 100.0},
                        )
                        m_alltime = alltime_by_model.get(m_name, None)
                        m_windows = usage_windows.get(m_name, None)
                        if m_windows and rate_limits:
                            m_windows["session_limit"] = rate_limits.get("session_limit")
                            m_windows["weekly_limit"] = rate_limits.get("weekly_limit")
                        elif rate_limits:
                            m_windows = {
                                "session_2h": 0,
                                "weekly_7d": 0,
                                "session_limit": rate_limits.get("session_limit"),
                                "weekly_limit": rate_limits.get("weekly_limit"),
                            }
                        models_out.append(
                            {
                                "name": m_name,
                                "tier": provider_key,
                                "tier_position": tier_pos,
                                "enabled": m_name not in disabled_models,
                                "stats_24h": m_stats,
                                "stats_alltime": m_alltime,
                                "usage_windows": m_windows,
                            }
                        )
                        tier_positions[m_name] = tier_pos

                        provider_requests += m_stats["requests"]
                        provider_cost += m_stats["cost"]
                        if m_stats["requests"] > 0:
                            provider_latency_sum += m_stats["avg_latency_ms"]
                            provider_success_sum += m_stats["success_rate"]
                            provider_models_with_stats += 1

                    avg_latency = (
                        round(provider_latency_sum / provider_models_with_stats, 1)
                        if provider_models_with_stats > 0
                        else 0.0
                    )
                    avg_success = (
                        round(provider_success_sum / provider_models_with_stats, 1)
                        if provider_models_with_stats > 0
                        else 100.0
                    )

                    # Use DB cost if available, else aggregated
                    if not current_cost and provider_cost > 0:
                        current_cost = round(provider_cost, 6)
                        budget_pct = round((current_cost / monthly_budget) * 100, 1) if monthly_budget > 0 else 0.0

                    entry = {
                        "provider": provider_key,
                        "display_name": cp.get("display_name", provider_key),
                        "is_active": is_active,
                        "account_tier": account_tier,
                        "monthly_budget_usd": monthly_budget,
                        "current_month_cost_usd": current_cost,
                        "budget_pct": budget_pct,
                        "source": source,
                        "auth_method": auth_method,
                        "key_hint": db_row.get("key_hint") if db_row else None,
                        "tier_positions": tier_positions,
                        "tier_position": tier_pos,
                        "is_cloud_proxy": cp.get("is_cloud_proxy", False),
                        "stats_24h": {
                            "requests": provider_requests,
                            "cost": round(provider_cost, 6),
                            "success_rate": avg_success,
                            "avg_latency_ms": avg_latency,
                        },
                        "models": models_out,
                        # DS9 PR 1+3 — the operator switch and what the probe measured.
                        # `dispatchable` is deliberately separate from `is_active`: a
                        # provider can be configured, holding a key and passing its probe
                        # while still receiving nothing. Collapsing them would make
                        # "never dispatch a paid provider unless enabled" unrepresentable.
                        "dispatchable": bool(cp.get("dispatchable", False)),
                        "provider_class": cp.get("provider_class"),
                        # None means "never probed" and is NOT the same as 0. The tab shows
                        # unknown rather than inventing a latency.
                        "health_status": _health_status.get(provider_key),
                        "health_latency_ms": _health_latency.get(provider_key),
                        "health_observed_model": _health_observed.get(provider_key),
                        "health_checked_at": _health_checked.get(provider_key),
                    }
                    result.append(entry)

                return jsonify(
                    {
                        "success": True,
                        "providers": result,
                        "creed_total_24h": creed_total_24h,
                        "creed_blocked_24h": creed_blocked_24h,
                    }
                )
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/external-providers", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def fleet_upsert_external_provider():
        """Add or update an external AI provider API key. Validates against contractor_providers table."""
        data = request.get_json() or {}
        provider = data.get("provider", "").strip().lower()
        api_key = data.get("api_key", "").strip()

        try:
            with get_db_cursor() as (conn, cur):
                # Validate provider exists in contractor_providers
                cur.execute(
                    "SELECT provider_key, is_cloud_proxy FROM contractor_providers WHERE provider_key = %s",
                    (provider,),
                )
                cp_row = cur.fetchone()
                if not cp_row:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Unknown provider: {provider}. Add it to Contractor Providers first.",
                            }
                        ),
                        400,
                    )

                # Cloud providers use OLLAMA_API_KEY from env
                if cp_row["is_cloud_proxy"]:
                    api_key = "OLLAMA_API_KEY"
                elif not api_key:
                    # Check if key already exists (edit mode — keep existing)
                    cur.execute(
                        "SELECT api_key_encrypted FROM external_api_keys WHERE provider = %s",
                        (provider,),
                    )
                    existing = cur.fetchone()
                    if not existing or not existing["api_key_encrypted"]:
                        return jsonify({"success": False, "error": "API key required"}), 400
                    api_key = existing["api_key_encrypted"]

                budget = data.get("monthly_budget_usd", 10.0)
                account_tier = data.get("account_tier", "free").strip().lower()
                valid_tiers = ("free", "pro", "pay_as_you_go", "enterprise", "max")
                if account_tier not in valid_tiers:
                    account_tier = "free"

                cur.execute(
                    """
                    INSERT INTO external_api_keys (provider, api_key_encrypted, monthly_budget_usd, account_tier, is_active)
                    VALUES (%s, %s, %s, %s, TRUE)
                    ON CONFLICT (provider) DO UPDATE SET
                        api_key_encrypted = %s, monthly_budget_usd = %s, account_tier = %s,
                        is_active = TRUE, updated_at = NOW()
                    RETURNING id, provider, is_active, monthly_budget_usd, account_tier
                """,
                    (provider, api_key, budget, account_tier, api_key, budget, account_tier),
                )
                row = cur.fetchone()

                # Invalidate external_providers cache
                try:
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))
                    from external_providers import invalidate_provider_cache

                    invalidate_provider_cache()
                except ImportError:
                    logger.warning("external_providers module not available for cache invalidation")

                return jsonify({"success": True, "provider": dict(row)})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/external-providers/<provider>/toggle", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def fleet_toggle_external_provider(provider):
        """Enable/disable an external provider."""
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                cur.execute(
                    "UPDATE external_api_keys SET is_active = NOT is_active, updated_at = NOW() WHERE provider = %s",
                    (provider,),
                )
                return jsonify({"success": True})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route(
        "/api/external-providers/<provider>/models/<path:model_name>/toggle",
        methods=["PUT"],
    )
    @login_required
    def fleet_toggle_provider_model(provider, model_name):
        """Enable/disable a specific model under a provider for routing."""
        data = request.get_json() or {}
        enabled = data.get("enabled")

        if enabled is None or not isinstance(enabled, bool):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Request body must include 'enabled' (boolean)",
                    }
                ),
                400,
            )

        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):
                setting_key = f"model_disabled:{model_name}"
                # Store as disabled flag: enabled=True means NOT disabled, so value="false"
                disabled_value = "false" if enabled else "true"
                cur.execute(
                    """
                    INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                    VALUES (%s, %s, 'boolean', %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (
                        setting_key,
                        disabled_value,
                        f"Model routing toggle for {model_name} (provider: {provider})",
                    ),
                )
                return jsonify({"success": True, "model": model_name, "enabled": enabled})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ======================================================================
    # CONTRACTOR PROVIDER DEFINITIONS API (dynamic provider management)
    # ======================================================================

    @bp.route("/api/contractor-providers", methods=["GET"])
    @login_required
    def fleet_list_contractor_providers():
        """List all contractor provider definitions (for UI dropdowns and admin)."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, provider_key, display_name, base_url, default_model,
                           auth_method, auth_env_var, is_cloud_proxy, tier_position,
                           models, rate_limits, is_active, created_at, updated_at
                    FROM contractor_providers
                    ORDER BY tier_position
                """
                )
                rows = cur.fetchall()
                providers = []
                for row in rows:
                    d = dict(row)
                    d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
                    d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
                    providers.append(d)
                return jsonify({"success": True, "providers": providers})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/contractor-providers", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def fleet_upsert_contractor_provider():
        """Create or update a contractor provider definition."""
        data = request.get_json() or {}
        provider_key = data.get("provider_key", "").strip().lower()
        if not provider_key:
            return jsonify({"success": False, "error": "provider_key is required"}), 400

        display_name = data.get("display_name", provider_key.replace("_", " ").title())
        base_url = data.get("base_url", "").strip()
        if not base_url:
            return jsonify({"success": False, "error": "base_url is required"}), 400

        default_model = data.get("default_model", "").strip() or None
        auth_method = data.get("auth_method", "api_key").strip()
        auth_env_var = data.get("auth_env_var", "").strip() or None
        is_cloud_proxy = bool(data.get("is_cloud_proxy", False))
        tier_position = int(data.get("tier_position", 99))
        models = data.get("models", [])
        rate_limits = data.get("rate_limits", {})
        is_active = bool(data.get("is_active", False))

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO contractor_providers
                        (provider_key, display_name, base_url, default_model, auth_method,
                         auth_env_var, is_cloud_proxy, tier_position, models, rate_limits, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        base_url = EXCLUDED.base_url,
                        default_model = EXCLUDED.default_model,
                        auth_method = EXCLUDED.auth_method,
                        auth_env_var = EXCLUDED.auth_env_var,
                        is_cloud_proxy = EXCLUDED.is_cloud_proxy,
                        tier_position = EXCLUDED.tier_position,
                        models = EXCLUDED.models,
                        rate_limits = EXCLUDED.rate_limits,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    RETURNING id, provider_key, display_name
                """,
                    (
                        provider_key,
                        display_name,
                        base_url,
                        default_model,
                        auth_method,
                        auth_env_var,
                        is_cloud_proxy,
                        tier_position,
                        json.dumps(models),
                        json.dumps(rate_limits),
                        is_active,
                    ),
                )
                row = cur.fetchone()

                # Invalidate external_providers cache
                try:
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))
                    from external_providers import invalidate_provider_cache

                    invalidate_provider_cache()
                except ImportError:
                    logger.warning("external_providers module not available for cache invalidation")

                return jsonify({"success": True, "provider": dict(row)})
        except Exception:
            return jsonify({"success": False, "error": "Internal server error"}), 500
