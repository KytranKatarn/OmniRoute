"""Invoicing plugin routes — invoice CRUD, payments, line items, stats."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Invoicing routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("invoicing")
    def index():
        return render_template("invoicing.html")

    # ------------------------------------------------------------------
    # Helper — settings & invoice number generation
    # ------------------------------------------------------------------

    def _get_settings(cur):
        cur.execute("SELECT * FROM invoice_settings ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO invoice_settings DEFAULT VALUES RETURNING *"
            )
            row = cur.fetchone()
        return row

    def _next_invoice_number(cur):
        settings = _get_settings(cur)
        prefix = settings["invoice_prefix"] or "INV"
        num = settings["next_invoice_number"] or 1001
        cur.execute(
            "UPDATE invoice_settings SET next_invoice_number = next_invoice_number + 1 WHERE id = %s",
            (settings["id"],),
        )
        return f"{prefix}-{num:04d}"

    def _recalc(cur, invoice_id):
        """Recalculate subtotal/tax/total/balance_due from items."""
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) AS subtotal FROM invoice_items WHERE invoice_id = %s",
            (invoice_id,),
        )
        subtotal = cur.fetchone()["subtotal"]
        cur.execute(
            "SELECT tax_rate, amount_paid FROM invoices WHERE id = %s",
            (invoice_id,),
        )
        inv = cur.fetchone()
        tax_rate = inv["tax_rate"] or 0
        tax = round(float(subtotal) * float(tax_rate) / 100, 2)
        total = round(float(subtotal) + tax, 2)
        balance_due = round(total - float(inv["amount_paid"]), 2)
        cur.execute(
            """
            UPDATE invoices
            SET subtotal = %s, tax = %s, total = %s, balance_due = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (subtotal, tax, total, balance_due, invoice_id),
        )
        return {"subtotal": subtotal, "tax": tax, "total": total, "balance_due": balance_due}

    # ------------------------------------------------------------------
    # Invoice CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/invoices", methods=["GET"])
    @login_required
    @require_module("invoicing")
    def list_invoices():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ""
            params: list = []
            if status:
                where = "WHERE i.status = %s"
                params.append(status)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM invoices i {where}", params
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT i.id, i.invoice_number, i.customer_id,
                       c.name AS customer_name,
                       i.status, i.subtotal, i.tax, i.total,
                       i.amount_paid, i.balance_due, i.due_date,
                       i.created_at, i.updated_at
                FROM invoices i
                LEFT JOIN crm_customers c ON c.id = i.customer_id
                {where}
                ORDER BY i.created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            invoices = cur.fetchall()

        return jsonify(
            {
                "invoices": invoices,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/invoices", methods=["POST"])
    @login_required
    @require_module("invoicing")
    def create_invoice():
        data = request.get_json(force=True)
        items = data.get("items") or []

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            invoice_number = _next_invoice_number(cur)

            cur.execute(
                """
                INSERT INTO invoices (
                    invoice_number, customer_id, status, tax_rate,
                    due_date, payment_method, notes, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    invoice_number,
                    data.get("customer_id"),
                    data.get("status", "draft"),
                    data.get("tax_rate", 13.00),
                    data.get("due_date"),
                    data.get("payment_method"),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            invoice = cur.fetchone()
            invoice_id = invoice["id"]

            for item in items:
                qty = float(item.get("quantity", 1))
                price = float(item.get("unit_price", 0))
                amount = round(qty * price, 2)
                cur.execute(
                    """
                    INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, amount)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (invoice_id, item.get("description", ""), qty, price, amount),
                )

            _recalc(cur, invoice_id)

            cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
            invoice = cur.fetchone()

        event_bus.emit(
            "invoice.created",
            {
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "customer_id": invoice.get("customer_id"),
                "total": float(invoice.get("total", 0)),
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(invoice), 201

    @bp.route("/api/invoices/<int:invoice_id>", methods=["GET"])
    @login_required
    @require_module("invoicing")
    def get_invoice(invoice_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT i.*, c.name AS customer_name
                FROM invoices i
                LEFT JOIN crm_customers c ON c.id = i.customer_id
                WHERE i.id = %s
                """,
                (invoice_id,),
            )
            invoice = cur.fetchone()
            if not invoice:
                return jsonify({"error": "Invoice not found"}), 404

            cur.execute(
                "SELECT * FROM invoice_items WHERE invoice_id = %s ORDER BY id",
                (invoice_id,),
            )
            items = cur.fetchall()

        return jsonify({**invoice, "items": items})

    @bp.route("/api/invoices/<int:invoice_id>", methods=["PUT"])
    @login_required
    @require_module("invoicing")
    def update_invoice(invoice_id):
        data = request.get_json(force=True)

        allowed = {
            "customer_id", "status", "tax_rate", "due_date",
            "payment_method", "notes",
        }
        updates = {k: v for k, v in data.items() if k in allowed}
        if not updates:
            return jsonify({"error": "No updatable fields provided"}), 400

        set_clause = ", ".join(f"{k} = %s" for k in updates)
        values = list(updates.values()) + [invoice_id]

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"UPDATE invoices SET {set_clause}, updated_at = NOW() WHERE id = %s RETURNING *",
                values,
            )
            invoice = cur.fetchone()
            if not invoice:
                return jsonify({"error": "Invoice not found"}), 404

            if "tax_rate" in updates:
                _recalc(cur, invoice_id)
                cur.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
                invoice = cur.fetchone()

        return jsonify(invoice)

    @bp.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
    @login_required
    @require_module("invoicing")
    def delete_invoice(invoice_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT status FROM invoices WHERE id = %s", (invoice_id,)
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Invoice not found"}), 404
            if row["status"] != "draft":
                return jsonify({"error": "Only draft invoices can be deleted"}), 409

            cur.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))

        return jsonify({"deleted": True})

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @bp.route("/api/invoices/<int:invoice_id>/send", methods=["POST"])
    @login_required
    @require_module("invoicing")
    def send_invoice(invoice_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE invoices SET status = 'sent', updated_at = NOW() WHERE id = %s RETURNING *",
                (invoice_id,),
            )
            invoice = cur.fetchone()
            if not invoice:
                return jsonify({"error": "Invoice not found"}), 404

        event_bus.emit(
            "invoice.sent",
            {
                "invoice_id": invoice_id,
                "customer_id": invoice.get("customer_id"),
                "total": float(invoice.get("total", 0)),
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(invoice)

    @bp.route("/api/invoices/<int:invoice_id>/mark-paid", methods=["POST"])
    @login_required
    @require_module("invoicing")
    def mark_paid(invoice_id):
        data = request.get_json(force=True)
        amount = float(data.get("amount", 0))
        if amount <= 0:
            return jsonify({"error": "amount must be positive"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                "SELECT id, total, amount_paid, customer_id FROM invoices WHERE id = %s",
                (invoice_id,),
            )
            invoice = cur.fetchone()
            if not invoice:
                return jsonify({"error": "Invoice not found"}), 404

            cur.execute(
                """
                INSERT INTO invoice_payments (invoice_id, amount, payment_method, payment_reference)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    invoice_id,
                    amount,
                    data.get("payment_method"),
                    data.get("payment_reference"),
                ),
            )

            new_paid = float(invoice["amount_paid"]) + amount
            new_balance = round(float(invoice["total"]) - new_paid, 2)
            new_status = "paid" if new_balance <= 0 else "sent"

            cur.execute(
                """
                UPDATE invoices
                SET amount_paid = %s, balance_due = %s, status = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (new_paid, max(new_balance, 0), new_status, invoice_id),
            )
            updated = cur.fetchone()

        event_bus.emit(
            "payment.received",
            {
                "invoice_id": invoice_id,
                "amount": amount,
                "customer_id": invoice.get("customer_id"),
            },
            tenant_id=g.tenant_id,
        )
        if new_status == "paid":
            event_bus.emit(
                "invoice.paid",
                {
                    "invoice_id": invoice_id,
                    "customer_id": invoice.get("customer_id"),
                    "total": float(invoice.get("total", 0)),
                },
                tenant_id=g.tenant_id,
            )
        return jsonify(updated)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("invoicing")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_invoices,
                    COUNT(*) FILTER (WHERE status = 'paid') AS paid_count,
                    COALESCE(SUM(balance_due) FILTER (WHERE status IN ('sent','overdue')), 0) AS outstanding_total,
                    COUNT(*) FILTER (WHERE status = 'overdue') AS overdue_count
                FROM invoices
                """
            )
            row = cur.fetchone()
        return jsonify(row)


# ------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ------------------------------------------------------------------


def on_contact_created(data):
    """Placeholder — future auto-linking of contacts to invoices."""
    pass


def on_order_created(data):
    """Auto-create a draft invoice when an order is created with a customer_id."""
    customer_id = data.get("customer_id")
    tenant_id = data.get("_tenant_id")
    if not customer_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Get next invoice number from settings
            cur.execute("SELECT * FROM invoice_settings ORDER BY id LIMIT 1")
            settings = cur.fetchone()
            if not settings:
                return
            prefix = settings["invoice_prefix"] or "INV"
            num = settings["next_invoice_number"] or 1001
            invoice_number = f"{prefix}-{num:04d}"
            cur.execute(
                "UPDATE invoice_settings SET next_invoice_number = next_invoice_number + 1 WHERE id = %s",
                (settings["id"],),
            )

            cur.execute(
                """
                INSERT INTO invoices (invoice_number, customer_id, status, metadata)
                VALUES (%s, %s, 'draft', %s)
                """,
                (
                    invoice_number,
                    customer_id,
                    Json({"order_id": data.get("order_id"), "source": "event_bus"}),
                ),
            )
    except Exception:
        logger.exception(
            "Failed to auto-create invoice for order customer %s", customer_id
        )
