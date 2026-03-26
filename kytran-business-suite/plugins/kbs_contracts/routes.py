"""Contracts & Legal plugin routes — templates, contracts CRUD, versioning, signing, renewal."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def _next_contract_number(cur):
    """Generate the next contract number in CTR-NNNN format."""
    cur.execute("SELECT COUNT(*) AS cnt FROM contracts")
    n = cur.fetchone()["cnt"] + 1
    return f"CTR-{n:04d}"


def _log_activity(cur, contract_id, activity_type, description=None, metadata=None):
    cur.execute(
        """
        INSERT INTO contract_activities (contract_id, activity_type, description, metadata)
        VALUES (%s, %s, %s, %s)
        """,
        (contract_id, activity_type, description, Json(metadata or {})),
    )


def register_routes(bp):
    """Attach all Contracts routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("contracts")
    def index():
        return render_template("contracts.html")

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @bp.route("/api/templates", methods=["GET"])
    @login_required
    @require_module("contracts")
    def list_templates():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, content, doc_type, variables, is_active, created_at
                FROM contract_templates
                WHERE is_active = TRUE
                ORDER BY name
                """
            )
            templates = cur.fetchall()
        return jsonify({"templates": templates})

    @bp.route("/api/templates", methods=["POST"])
    @login_required
    @require_module("contracts")
    def create_template():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO contract_templates (name, description, content, doc_type, variables, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, name, description, content, doc_type, variables, is_active, created_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("content", ""),
                    data.get("doc_type", "contract"),
                    Json(data.get("variables", [])),
                    data.get("is_active", True),
                ),
            )
            template = cur.fetchone()

        return jsonify(template), 201

    @bp.route("/api/templates/<int:template_id>", methods=["GET"])
    @login_required
    @require_module("contracts")
    def get_template(template_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, content, doc_type, variables, is_active, created_at
                FROM contract_templates WHERE id = %s
                """,
                (template_id,),
            )
            template = cur.fetchone()

        if template is None:
            return jsonify({"error": "template not found"}), 404
        return jsonify(template)

    @bp.route("/api/templates/<int:template_id>", methods=["PUT"])
    @login_required
    @require_module("contracts")
    def update_template(template_id):
        data = request.get_json(force=True)

        allowed = ("name", "description", "content", "doc_type", "is_active")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "variables" in data:
            sets.append("variables = %s")
            params.append(Json(data["variables"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(template_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE contract_templates SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, description, content, doc_type, variables, is_active, created_at
                """,
                params,
            )
            template = cur.fetchone()

        if template is None:
            return jsonify({"error": "template not found"}), 404
        return jsonify(template)

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------

    @bp.route("/api/contracts", methods=["GET"])
    @login_required
    @require_module("contracts")
    def list_contracts():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ""
            params: list = []
            if status:
                where = "WHERE status = %s"
                params.append(status)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM contracts {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, contract_number, template_id, customer_id, title, status,
                       value, start_date, end_date, signed_at, signed_by,
                       renewal_type, renewal_reminder_days, tags, metadata,
                       created_at, updated_at
                FROM contracts {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            contracts = cur.fetchall()

        return jsonify(
            {
                "contracts": contracts,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/contracts", methods=["POST"])
    @login_required
    @require_module("contracts")
    def create_contract():
        data = request.get_json(force=True)
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "title is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            contract_number = _next_contract_number(cur)

            cur.execute(
                """
                INSERT INTO contracts (
                    contract_number, template_id, customer_id, title, content,
                    status, value, start_date, end_date,
                    renewal_type, renewal_reminder_days, tags, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, contract_number, template_id, customer_id, title, content,
                          status, value, start_date, end_date, signed_at, signed_by,
                          renewal_type, renewal_reminder_days, tags, metadata,
                          created_at, updated_at
                """,
                (
                    contract_number,
                    data.get("template_id"),
                    data.get("customer_id"),
                    title,
                    data.get("content", ""),
                    data.get("status", "draft"),
                    data.get("value"),
                    data.get("start_date"),
                    data.get("end_date"),
                    data.get("renewal_type", "manual"),
                    data.get("renewal_reminder_days", 30),
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            contract = cur.fetchone()
            contract_id = contract["id"]

            # Initial version
            cur.execute(
                """
                INSERT INTO contract_versions (contract_id, version_number, content, change_notes, created_by)
                VALUES (%s, 1, %s, 'Initial version', %s)
                """,
                (contract_id, contract["content"], data.get("created_by")),
            )

            # Activity log
            _log_activity(cur, contract_id, "created", f"Contract {contract_number} created")

        event_bus.emit(
            "contract.created",
            {"contract_id": contract_id, "contract_number": contract_number, "title": title},
            tenant_id=g.tenant_id,
        )
        return jsonify(contract), 201

    @bp.route("/api/contracts/<int:contract_id>", methods=["GET"])
    @login_required
    @require_module("contracts")
    def get_contract(contract_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT id, contract_number, template_id, customer_id, title, content,
                       status, value, start_date, end_date, signed_at, signed_by,
                       renewal_type, renewal_reminder_days, tags, metadata,
                       created_at, updated_at
                FROM contracts WHERE id = %s
                """,
                (contract_id,),
            )
            contract = cur.fetchone()

            if contract is None:
                return jsonify({"error": "contract not found"}), 404

            cur.execute(
                """
                SELECT id, version_number, content, change_notes, created_by, created_at
                FROM contract_versions WHERE contract_id = %s ORDER BY version_number DESC
                """,
                (contract_id,),
            )
            versions = cur.fetchall()

            cur.execute(
                """
                SELECT id, activity_type, description, metadata, created_at
                FROM contract_activities WHERE contract_id = %s ORDER BY created_at DESC
                """,
                (contract_id,),
            )
            activities = cur.fetchall()

        return jsonify({**contract, "versions": versions, "activities": activities})

    @bp.route("/api/contracts/<int:contract_id>", methods=["PUT"])
    @login_required
    @require_module("contracts")
    def update_contract(contract_id):
        data = request.get_json(force=True)

        allowed = ("title", "content", "status", "value", "start_date", "end_date",
                   "renewal_type", "renewal_reminder_days", "signed_at", "signed_by",
                   "customer_id", "template_id")
        sets = []
        params = []
        for field in allowed:
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "tags" in data:
            sets.append("tags = %s")
            params.append(Json(data["tags"]))
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        sets.append("updated_at = NOW()")
        params.append(contract_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE contracts SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, contract_number, template_id, customer_id, title, content,
                          status, value, start_date, end_date, signed_at, signed_by,
                          renewal_type, renewal_reminder_days, tags, metadata,
                          created_at, updated_at
                """,
                params,
            )
            contract = cur.fetchone()

            if contract is None:
                return jsonify({"error": "contract not found"}), 404

            # Create new version when content changes
            if "content" in data:
                cur.execute(
                    """
                    SELECT COALESCE(MAX(version_number), 0) + 1 AS next_v
                    FROM contract_versions WHERE contract_id = %s
                    """,
                    (contract_id,),
                )
                next_v = cur.fetchone()["next_v"]
                cur.execute(
                    """
                    INSERT INTO contract_versions (contract_id, version_number, content, change_notes, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (contract_id, next_v, data["content"],
                     data.get("change_notes", "Content updated"),
                     data.get("updated_by")),
                )

            _log_activity(cur, contract_id, "edited", "Contract updated")

        return jsonify(contract)

    # ------------------------------------------------------------------
    # Actions: send, sign, cancel, renew
    # ------------------------------------------------------------------

    @bp.route("/api/contracts/<int:contract_id>/send", methods=["POST"])
    @login_required
    @require_module("contracts")
    def send_contract(contract_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE contracts SET status = 'sent', updated_at = NOW()
                WHERE id = %s
                RETURNING id, contract_number, title, status
                """,
                (contract_id,),
            )
            contract = cur.fetchone()
            if contract is None:
                return jsonify({"error": "contract not found"}), 404
            _log_activity(cur, contract_id, "sent", "Contract sent for signature")

        event_bus.emit(
            "contract.sent",
            {"contract_id": contract_id, "contract_number": contract["contract_number"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(contract)

    @bp.route("/api/contracts/<int:contract_id>/sign", methods=["POST"])
    @login_required
    @require_module("contracts")
    def sign_contract(contract_id):
        data = request.get_json(force=True) or {}
        signed_by = (data.get("signed_by") or "").strip()

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE contracts
                SET status = 'signed', signed_at = NOW(), signed_by = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, contract_number, title, status, signed_at, signed_by
                """,
                (signed_by or None, contract_id),
            )
            contract = cur.fetchone()
            if contract is None:
                return jsonify({"error": "contract not found"}), 404
            _log_activity(cur, contract_id, "signed",
                          f"Contract signed by {signed_by}" if signed_by else "Contract signed")

        event_bus.emit(
            "contract.signed",
            {"contract_id": contract_id, "contract_number": contract["contract_number"],
             "signed_by": signed_by},
            tenant_id=g.tenant_id,
        )
        return jsonify(contract)

    @bp.route("/api/contracts/<int:contract_id>/cancel", methods=["POST"])
    @login_required
    @require_module("contracts")
    def cancel_contract(contract_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE contracts SET status = 'cancelled', updated_at = NOW()
                WHERE id = %s
                RETURNING id, contract_number, title, status
                """,
                (contract_id,),
            )
            contract = cur.fetchone()
            if contract is None:
                return jsonify({"error": "contract not found"}), 404
            _log_activity(cur, contract_id, "commented", "Contract cancelled")

        return jsonify(contract)

    @bp.route("/api/contracts/<int:contract_id>/renew", methods=["POST"])
    @login_required
    @require_module("contracts")
    def renew_contract(contract_id):
        data = request.get_json(force=True) or {}

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Fetch original
            cur.execute(
                """
                SELECT * FROM contracts WHERE id = %s
                """,
                (contract_id,),
            )
            original = cur.fetchone()
            if original is None:
                return jsonify({"error": "contract not found"}), 404

            new_number = _next_contract_number(cur)

            cur.execute(
                """
                INSERT INTO contracts (
                    contract_number, template_id, customer_id, title, content,
                    status, value, start_date, end_date,
                    renewal_type, renewal_reminder_days, tags, metadata
                )
                VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, contract_number, template_id, customer_id, title, content,
                          status, value, start_date, end_date, signed_at, signed_by,
                          renewal_type, renewal_reminder_days, tags, metadata,
                          created_at, updated_at
                """,
                (
                    new_number,
                    original["template_id"],
                    original["customer_id"],
                    data.get("title", f"{original['title']} (Renewal)"),
                    original["content"],
                    original["value"],
                    data.get("start_date", original["end_date"]),
                    data.get("end_date"),
                    original["renewal_type"],
                    original["renewal_reminder_days"],
                    original["tags"],
                    original["metadata"],
                ),
            )
            new_contract = cur.fetchone()
            new_id = new_contract["id"]

            # Initial version for renewal
            cur.execute(
                """
                INSERT INTO contract_versions (contract_id, version_number, content, change_notes, created_by)
                VALUES (%s, 1, %s, %s, %s)
                """,
                (new_id, new_contract["content"],
                 f"Renewed from contract #{original['contract_number']}",
                 data.get("created_by")),
            )

            _log_activity(cur, new_id, "created",
                          f"Renewed from {original['contract_number']}")

            # Mark original as renewed
            cur.execute(
                """
                UPDATE contracts SET status = 'renewed', updated_at = NOW() WHERE id = %s
                """,
                (contract_id,),
            )
            _log_activity(cur, contract_id, "renewed",
                          f"Renewed as {new_number}")

        event_bus.emit(
            "contract.renewed",
            {"original_id": contract_id, "new_id": new_id,
             "new_contract_number": new_number},
            tenant_id=g.tenant_id,
        )
        return jsonify(new_contract), 201

    # ------------------------------------------------------------------
    # Versions & Activities
    # ------------------------------------------------------------------

    @bp.route("/api/contracts/<int:contract_id>/versions", methods=["GET"])
    @login_required
    @require_module("contracts")
    def list_versions(contract_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, version_number, content, change_notes, created_by, created_at
                FROM contract_versions WHERE contract_id = %s ORDER BY version_number DESC
                """,
                (contract_id,),
            )
            versions = cur.fetchall()
        return jsonify({"versions": versions})

    @bp.route("/api/contracts/<int:contract_id>/activities", methods=["GET"])
    @login_required
    @require_module("contracts")
    def list_activities(contract_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, activity_type, description, metadata, created_at
                FROM contract_activities WHERE contract_id = %s ORDER BY created_at DESC
                """,
                (contract_id,),
            )
            activities = cur.fetchall()
        return jsonify({"activities": activities})

    # ------------------------------------------------------------------
    # Expiring & Stats
    # ------------------------------------------------------------------

    @bp.route("/api/expiring", methods=["GET"])
    @login_required
    @require_module("contracts")
    def expiring_contracts():
        days = request.args.get("days", 30, type=int)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, contract_number, customer_id, title, status,
                       value, end_date, renewal_type, created_at
                FROM contracts
                WHERE status NOT IN ('expired','cancelled','renewed')
                  AND end_date IS NOT NULL
                  AND end_date <= CURRENT_DATE + INTERVAL '%s days'
                  AND end_date >= CURRENT_DATE
                ORDER BY end_date ASC
                """,
                (days,),
            )
            contracts = cur.fetchall()

        return jsonify({"contracts": contracts, "days": days})

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("contracts")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_contracts,
                    COUNT(*) FILTER (WHERE status IN ('draft','sent','viewed','signed')) AS active_count,
                    COUNT(*) FILTER (
                        WHERE status NOT IN ('expired','cancelled','renewed')
                          AND end_date IS NOT NULL
                          AND end_date <= CURRENT_DATE + INTERVAL '30 days'
                          AND end_date >= CURRENT_DATE
                    ) AS expiring_soon,
                    COALESCE(SUM(value) FILTER (WHERE status = 'signed'), 0) AS total_value
                FROM contracts
                """
            )
            row = cur.fetchone()

        return jsonify(row)


# ----------------------------------------------------------------------
# Event consumers
# ----------------------------------------------------------------------


def on_contact_created(data):
    """Placeholder — no action needed when a contact is created."""
    pass
