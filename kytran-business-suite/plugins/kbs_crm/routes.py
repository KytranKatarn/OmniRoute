"""CRM plugin routes — contacts CRUD, segments, interactions, search."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module
from plugins.kbs_crm.search import build_search_conditions

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all CRM routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("crm")
    def index():
        return render_template("crm.html")

    # ------------------------------------------------------------------
    # Customer CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/customers", methods=["GET"])
    @login_required
    @require_module("crm")
    def list_customers():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        offset = (page - 1) * per_page
        search = request.args.get("search", "").strip()
        segment_id = request.args.get("segment_id", type=int)
        conditions, search_params = build_search_conditions(
            search=search or None, segment_id=segment_id
        )
        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            base_params: list = list(search_params)
            if status:
                if where_clause:
                    where_clause += " AND c.status = %s"
                else:
                    where_clause = "WHERE c.status = %s"
                base_params.append(status)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM crm_customers c {where_clause}",
                base_params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT c.id, c.name, c.email, c.phone, c.company, c.status, c.source,
                       c.notes, c.tags, c.metadata, c.created_at, c.updated_at
                FROM crm_customers c {where_clause}
                ORDER BY c.created_at DESC
                LIMIT %s OFFSET %s
                """,
                base_params + [per_page, offset],
            )
            customers = cur.fetchall()

        return jsonify(
            {
                "customers": customers,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/customers", methods=["POST"])
    @login_required
    @require_module("crm")
    def create_customer():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO crm_customers (name, email, phone, company, status, source, notes, tags, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, email, phone, company, status, source, notes, tags, metadata, created_at, updated_at
                """,
                (
                    name,
                    data.get("email"),
                    data.get("phone"),
                    data.get("company"),
                    data.get("status", "active"),
                    data.get("source"),
                    data.get("notes"),
                    Json(data.get("tags", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            customer = cur.fetchone()

        event_bus.emit(
            "contact.created",
            {"customer_id": customer["id"], "name": customer["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(customer), 201

    @bp.route("/api/customers/<int:customer_id>", methods=["GET"])
    @login_required
    @require_module("crm")
    def get_customer(customer_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, email, phone, company, status, source,
                       notes, tags, metadata, created_at, updated_at
                FROM crm_customers WHERE id = %s
                """,
                (customer_id,),
            )
            customer = cur.fetchone()

        if customer is None:
            return jsonify({"error": "customer not found"}), 404
        return jsonify(customer)

    @bp.route("/api/customers/<int:customer_id>", methods=["PUT"])
    @login_required
    @require_module("crm")
    def update_customer(customer_id):
        data = request.get_json(force=True)

        allowed = ("name", "email", "phone", "company", "status", "source", "notes")
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
        params.append(customer_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE crm_customers SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, name, email, phone, company, status, source,
                          notes, tags, metadata, created_at, updated_at
                """,
                params,
            )
            customer = cur.fetchone()

        if customer is None:
            return jsonify({"error": "customer not found"}), 404

        event_bus.emit(
            "contact.updated",
            {"customer_id": customer["id"], "name": customer["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(customer)

    @bp.route("/api/customers/<int:customer_id>", methods=["DELETE"])
    @login_required
    @require_module("crm")
    def delete_customer(customer_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM crm_customers WHERE id = %s RETURNING id, name",
                (customer_id,),
            )
            deleted = cur.fetchone()

        if deleted is None:
            return jsonify({"error": "customer not found"}), 404

        event_bus.emit(
            "contact.deleted",
            {"customer_id": deleted["id"], "name": deleted["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify({"deleted": True, "id": deleted["id"]})

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    @bp.route("/api/search", methods=["GET"])
    @login_required
    @require_module("crm")
    def search_customers():
        q = request.args.get("q", "").strip()
        if not q:
            return jsonify({"customers": []})

        pattern = f"%{q}%"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, email, phone, company, status, created_at
                FROM crm_customers
                WHERE name ILIKE %s OR email ILIKE %s OR company ILIKE %s
                ORDER BY name
                LIMIT 20
                """,
                (pattern, pattern, pattern),
            )
            customers = cur.fetchall()

        return jsonify({"customers": customers})

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("crm")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_customers,
                    COUNT(*) FILTER (WHERE status = 'active') AS active_customers,
                    COUNT(*) FILTER (WHERE status = 'lead') AS leads,
                    COUNT(*) FILTER (WHERE created_at >= date_trunc('month', CURRENT_DATE)) AS new_this_month
                FROM crm_customers
                """
            )
            row = cur.fetchone()

        return jsonify(row)

    # ------------------------------------------------------------------
    # Segments
    # ------------------------------------------------------------------

    @bp.route("/api/segments", methods=["GET"])
    @login_required
    @require_module("crm")
    def list_segments():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, name, description, rules, is_dynamic, created_at FROM crm_segments ORDER BY name"
            )
            segments = cur.fetchall()
        return jsonify({"segments": segments})

    @bp.route("/api/segments", methods=["POST"])
    @login_required
    @require_module("crm")
    def create_segment():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO crm_segments (name, description, rules, is_dynamic)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, description, rules, is_dynamic, created_at
                """,
                (
                    name,
                    data.get("description"),
                    Json(data.get("rules", {})),
                    data.get("is_dynamic", False),
                ),
            )
            segment = cur.fetchone()

        return jsonify(segment), 201

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    @bp.route("/api/customers/<int:customer_id>/interactions", methods=["GET"])
    @login_required
    @require_module("crm")
    def list_interactions(customer_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, customer_id, type, subject, content, metadata, created_at
                FROM crm_interactions
                WHERE customer_id = %s
                ORDER BY created_at DESC
                """,
                (customer_id,),
            )
            interactions = cur.fetchall()
        return jsonify({"interactions": interactions})

    @bp.route("/api/customers/<int:customer_id>/interactions", methods=["POST"])
    @login_required
    @require_module("crm")
    def create_interaction(customer_id):
        data = request.get_json(force=True)
        itype = (data.get("type") or "").strip()
        if not itype:
            return jsonify({"error": "type is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Verify customer exists
            cur.execute("SELECT id FROM crm_customers WHERE id = %s", (customer_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "customer not found"}), 404

            cur.execute(
                """
                INSERT INTO crm_interactions (customer_id, type, subject, content, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, customer_id, type, subject, content, metadata, created_at
                """,
                (
                    customer_id,
                    itype,
                    data.get("subject"),
                    data.get("content"),
                    Json(data.get("metadata", {})),
                ),
            )
            interaction = cur.fetchone()

        event_bus.emit(
            "interaction.logged",
            {
                "customer_id": customer_id,
                "interaction_id": interaction["id"],
                "type": itype,
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(interaction), 201


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------


def on_order_created(data):
    """Log an 'order' interaction when an order is created."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO crm_interactions (customer_id, type, subject, content, metadata)
                VALUES (%s, 'order', %s, %s, %s)
                """,
                (
                    customer_id,
                    data.get("subject", "Order placed"),
                    data.get("content", ""),
                    Json({"order_id": data.get("order_id"), "source": "event_bus"}),
                ),
            )
    except Exception:
        logger.exception("Failed to log order interaction for customer %s", customer_id)


def on_invoice_paid(data):
    """Log an 'invoice' interaction when an invoice is paid."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO crm_interactions (customer_id, type, subject, content, metadata)
                VALUES (%s, 'invoice', %s, %s, %s)
                """,
                (
                    customer_id,
                    data.get("subject", "Invoice paid"),
                    data.get("content", ""),
                    Json({"invoice_id": data.get("invoice_id"), "source": "event_bus"}),
                ),
            )
    except Exception:
        logger.exception("Failed to log invoice interaction for customer %s", customer_id)


def on_payment_received(data):
    """Log a 'payment' interaction when a payment is received (any source)."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return
    try:
        amount = data.get("amount", 0)
        method = data.get("payment_method", "unknown")
        reference = data.get("payment_reference", "")
        invoice_id = data.get("invoice_id")
        order_id = data.get("order_id")

        subject = f"Payment received: ${amount:,.2f} via {method}"
        if invoice_id:
            content = f"Payment of ${amount:,.2f} received for invoice #{invoice_id} via {method}. Reference: {reference}"
        elif order_id:
            content = f"Payment of ${amount:,.2f} received for order #{order_id} via {method}. Reference: {reference}"
        else:
            content = f"Payment of ${amount:,.2f} received via {method}. Reference: {reference}"

        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO crm_interactions (customer_id, type, subject, content, metadata)
                VALUES (%s, 'payment', %s, %s, %s)
                """,
                (
                    customer_id,
                    subject,
                    content,
                    Json({
                        "amount": amount,
                        "payment_method": method,
                        "payment_reference": reference,
                        "invoice_id": invoice_id,
                        "order_id": order_id,
                        "source": "event_bus",
                    }),
                ),
            )
    except Exception:
        logger.exception("Failed to log payment interaction for customer %s", customer_id)
