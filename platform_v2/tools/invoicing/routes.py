"""
Invoicing Routes
================
Invoice and subscription billing for A.R.C.H.I.E. Business Tools.

Features:
- Create and manage invoices
- Subscription billing with recurring invoices
- Payment tracking (Stripe, PayPal, manual)
- PDF generation
- Email invoice delivery
- Integration with CRM and Store

Author: A.R.C.H.I.E. Platform
Date: 2026-01-17
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta, date
import os
import json
from decimal import Decimal

# Import user context helpers
try:
    from user_context import is_admin_user
except ImportError:

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
invoicing_bp = Blueprint(
    "invoicing",
    __name__,
    url_prefix="/tools/invoicing",
    template_folder="../../templates/tools",
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def _serialize(data):
    """Pre-serialize data with json_serial for use with jsonify"""
    return json.loads(json.dumps(data, default=json_serial))


# ============================================================================
# MAIN PAGE
# ============================================================================


@invoicing_bp.route("/")
@login_required
def index():
    """Main Invoicing dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get invoice stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_invoices,
                COUNT(*) FILTER (WHERE status = 'draft') as draft,
                COUNT(*) FILTER (WHERE status = 'sent') as sent,
                COUNT(*) FILTER (WHERE status = 'paid') as paid,
                COUNT(*) FILTER (WHERE status = 'overdue') as overdue,
                COALESCE(SUM(total), 0) as total_value,
                COALESCE(SUM(total) FILTER (WHERE status = 'paid'), 0) as paid_value,
                COALESCE(SUM(balance_due) FILTER (WHERE status IN ('sent', 'overdue')), 0) as outstanding
            FROM invoices
            WHERE created_at > NOW() - INTERVAL '90 days' AND user_id = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Get recent invoices
        cur.execute(
            """
            SELECT i.*, c.email as customer_email,
                   c.first_name || ' ' || c.last_name as customer_name,
                   c.company as customer_company
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE i.user_id = %s
            ORDER BY i.created_at DESC
            LIMIT 10
        """,
            (current_user.id,),
        )
        recent_invoices = cur.fetchall()

        # Get invoice settings
        cur.execute("SELECT * FROM invoice_settings LIMIT 1")
        settings = cur.fetchone()

        # Get overdue invoices
        cur.execute(
            """
            SELECT i.*, c.email as customer_email,
                   c.first_name || ' ' || c.last_name as customer_name
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE i.status = 'sent' AND i.due_date < CURRENT_DATE AND i.user_id = %s
            ORDER BY i.due_date
            LIMIT 5
        """,
            (current_user.id,),
        )
        overdue_invoices = cur.fetchall()

        # Mark overdue invoices
        cur.execute(
            """
            UPDATE invoices
            SET status = 'overdue', updated_at = NOW()
            WHERE status = 'sent' AND due_date < CURRENT_DATE AND user_id = %s
        """,
            (current_user.id,),
        )
        conn.commit()

        return render_template(
            "invoicing.html",
            stats=stats,
            recent_invoices=recent_invoices,
            overdue_invoices=overdue_invoices,
            settings=settings,
            is_admin=is_admin_user(),
        )
    except Exception as e:
        current_app.logger.error(f"[Invoicing] Error loading dashboard: {e}")
        return render_template(
            "invoicing.html",
            stats={
                "total_invoices": 0,
                "draft": 0,
                "sent": 0,
                "paid": 0,
                "overdue": 0,
                "total_value": 0,
                "paid_value": 0,
                "outstanding": 0,
            },
            recent_invoices=[],
            overdue_invoices=[],
            settings=None,
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# INVOICE CRUD
# ============================================================================


@invoicing_bp.route("/api/invoices", methods=["GET"])
@login_required
def get_invoices():
    """Get all invoices with filtering"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        status = request.args.get("status", "")
        customer_id = request.args.get("customer_id", "")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        offset = (page - 1) * per_page

        where_clauses = ["i.user_id = %s"]
        params = [current_user.id]

        if status:
            where_clauses.append("i.status = %s")
            params.append(status)

        if customer_id:
            where_clauses.append("i.customer_id = %s")
            params.append(customer_id)

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM invoices i WHERE {where_sql}", params)
        total = cur.fetchone()["count"]

        # Get invoices
        cur.execute(
            f"""
            SELECT i.*, c.email as customer_email,
                   c.first_name || ' ' || c.last_name as customer_name,
                   c.company as customer_company
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE {where_sql}
            ORDER BY i.created_at DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )
        invoices = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "invoices": _serialize([dict(i) for i in invoices]),
                "total": total,
                "page": page,
                "pages": (total + per_page - 1) // per_page,
            },
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices", methods=["POST"])
@login_required
def create_invoice():
    """Create a new invoice"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generate invoice number
        cur.execute("SELECT generate_invoice_number() as num")
        invoice_number = cur.fetchone()["num"]

        # Get default settings
        cur.execute("SELECT default_tax_rate, default_terms FROM invoice_settings LIMIT 1")
        settings = cur.fetchone()

        # Calculate due date (default 30 days)
        due_days = data.get("due_days", 30)
        due_date = datetime.now().date() + timedelta(days=due_days)

        # Create invoice
        cur.execute(
            """
            INSERT INTO invoices
            (invoice_number, customer_id, order_id, subscription_id, status,
             issue_date, due_date, tax_rate, discount_amount, discount_description,
             notes, terms, currency, recurring, recurring_interval, created_by, user_id)
            VALUES (%s, %s, %s, %s, 'draft', CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                invoice_number,
                data.get("customer_id"),
                data.get("order_id"),
                data.get("subscription_id"),
                due_date,
                data.get("tax_rate", settings["default_tax_rate"] if settings else 13),
                data.get("discount_amount", 0),
                data.get("discount_description", ""),
                data.get("notes", ""),
                data.get("terms", settings["default_terms"] if settings else ""),
                data.get("currency", "CAD"),
                data.get("recurring", False),
                data.get("recurring_interval"),
                current_user.id,
                current_user.id,
            ),
        )
        invoice = cur.fetchone()

        # Add line items if provided
        items = data.get("items", [])
        for i, item in enumerate(items):
            amount = float(item.get("quantity", 1)) * float(item.get("unit_price", 0))
            cur.execute(
                """
                INSERT INTO invoice_items
                (invoice_id, description, quantity, unit_price, amount, product_id, subscription_tier, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    invoice["id"],
                    item.get("description", ""),
                    item.get("quantity", 1),
                    item.get("unit_price", 0),
                    amount,
                    item.get("product_id"),
                    item.get("subscription_tier"),
                    i,
                ),
            )

        # Log activity
        cur.execute(
            """
            INSERT INTO invoice_activities
            (invoice_id, activity_type, description, created_by)
            VALUES (%s, 'created', 'Invoice created', %s)
        """,
            (invoice["id"], current_user.id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "invoice": _serialize(dict(invoice)),
                "invoice_number": invoice_number,
                "message": f"Invoice {invoice_number} created",
            },
        )
    except Exception as e:
        current_app.logger.error(f"[Invoicing] Error creating invoice: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>", methods=["GET"])
@login_required
def get_invoice(invoice_id):
    """Get invoice details"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get invoice
        cur.execute(
            """
            SELECT i.*, c.email as customer_email,
                   c.first_name, c.last_name, c.company as customer_company,
                   c.address_line1, c.city, c.state, c.postal_code, c.country, c.phone
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE i.id = %s AND i.user_id = %s
        """,
            (invoice_id, current_user.id),
        )
        invoice = cur.fetchone()

        if not invoice:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        # Get line items
        cur.execute(
            """
            SELECT * FROM invoice_items
            WHERE invoice_id = %s
            ORDER BY sort_order
        """,
            (invoice_id,),
        )
        items = cur.fetchall()

        # Get payments
        cur.execute(
            """
            SELECT p.*, u.username as recorded_by
            FROM invoice_payments p
            LEFT JOIN users u ON p.created_by = u.id
            WHERE p.invoice_id = %s
            ORDER BY p.payment_date DESC
        """,
            (invoice_id,),
        )
        payments = cur.fetchall()

        # Get activities
        cur.execute(
            """
            SELECT a.*, u.username as by_user
            FROM invoice_activities a
            LEFT JOIN users u ON a.created_by = u.id
            WHERE a.invoice_id = %s
            ORDER BY a.created_at DESC
            LIMIT 20
        """,
            (invoice_id,),
        )
        activities = cur.fetchall()

        # Get company settings
        cur.execute("SELECT * FROM invoice_settings LIMIT 1")
        settings = cur.fetchone()

        return jsonify(
            {
                "success": True,
                "invoice": _serialize(dict(invoice)),
                "items": _serialize([dict(i) for i in items]),
                "payments": _serialize([dict(p) for p in payments]),
                "activities": _serialize([dict(a) for a in activities]),
                "settings": _serialize(dict(settings)) if settings else None,
            },
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>", methods=["PUT"])
@login_required
def update_invoice(invoice_id):
    """Update invoice"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Check invoice exists, is editable, and belongs to user
        cur.execute("SELECT status FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id))
        invoice = cur.fetchone()

        if not invoice:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        if invoice["status"] == "paid":
            return jsonify({"success": False, "error": "Cannot edit paid invoice"}), 400

        # Update invoice fields
        allowed_fields = [
            "customer_id",
            "due_date",
            "tax_rate",
            "discount_amount",
            "discount_description",
            "notes",
            "terms",
            "currency",
        ]
        updates = []
        params = []

        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                params.append(data[field])

        if updates:
            updates.append("updated_at = NOW()")
            params.extend([invoice_id, current_user.id])

            cur.execute(
                f"""
                UPDATE invoices
                SET {', '.join(updates)}
                WHERE id = %s AND user_id = %s
                RETURNING *
            """,
                params,
            )
            invoice = cur.fetchone()

        # Update items if provided
        if "items" in data:
            # Delete existing items
            cur.execute("DELETE FROM invoice_items WHERE invoice_id = %s", (invoice_id,))

            # Add new items
            for i, item in enumerate(data["items"]):
                amount = float(item.get("quantity", 1)) * float(item.get("unit_price", 0))
                cur.execute(
                    """
                    INSERT INTO invoice_items
                    (invoice_id, description, quantity, unit_price, amount, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    (
                        invoice_id,
                        item.get("description", ""),
                        item.get("quantity", 1),
                        item.get("unit_price", 0),
                        amount,
                        i,
                    ),
                )

        # Log activity
        cur.execute(
            """
            INSERT INTO invoice_activities
            (invoice_id, activity_type, description, created_by)
            VALUES (%s, 'updated', 'Invoice updated', %s)
        """,
            (invoice_id, current_user.id),
        )

        conn.commit()

        return jsonify(
            {"success": True, "invoice": _serialize(dict(invoice)), "message": "Invoice updated"},
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
@login_required
def delete_invoice(invoice_id):
    """Delete invoice (only drafts)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            "SELECT status, invoice_number FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id)
        )
        invoice = cur.fetchone()

        if not invoice:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        if invoice["status"] != "draft":
            return (
                jsonify({"success": False, "error": "Only draft invoices can be deleted"}),
                400,
            )

        cur.execute("DELETE FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id))
        conn.commit()

        return jsonify({"success": True, "message": f"Invoice {invoice['invoice_number']} deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# INVOICE ITEMS
# ============================================================================


@invoicing_bp.route("/api/invoices/<int:invoice_id>/items", methods=["POST"])
@login_required
def add_item(invoice_id):
    """Add item to invoice"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify invoice ownership
        cur.execute("SELECT id FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        amount = float(data.get("quantity", 1)) * float(data.get("unit_price", 0))

        cur.execute(
            """
            INSERT INTO invoice_items
            (invoice_id, description, quantity, unit_price, amount)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                invoice_id,
                data.get("description", ""),
                data.get("quantity", 1),
                data.get("unit_price", 0),
                amount,
            ),
        )
        item = cur.fetchone()

        conn.commit()

        return jsonify({"success": True, "item": _serialize(dict(item))})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>/items/<int:item_id>", methods=["DELETE"])
@login_required
def delete_item(invoice_id, item_id):
    """Delete item from invoice"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Verify invoice ownership
        cur.execute("SELECT id FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        cur.execute(
            "DELETE FROM invoice_items WHERE id = %s AND invoice_id = %s",
            (item_id, invoice_id),
        )
        conn.commit()

        return jsonify({"success": True, "message": "Item deleted"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# INVOICE ACTIONS
# ============================================================================


@invoicing_bp.route("/api/invoices/<int:invoice_id>/send", methods=["POST"])
@login_required
def send_invoice(invoice_id):
    """Send invoice to customer"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get invoice with customer email
        cur.execute(
            """
            SELECT i.*, c.email as customer_email, c.first_name
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE i.id = %s AND i.user_id = %s
        """,
            (invoice_id, current_user.id),
        )
        invoice = cur.fetchone()

        if not invoice:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        if not invoice["customer_email"]:
            return (
                jsonify({"success": False, "error": "Customer has no email address"}),
                400,
            )

        # Update status
        cur.execute(
            """
            UPDATE invoices
            SET status = 'sent', sent_at = NOW(), updated_at = NOW()
            WHERE id = %s
        """,
            (invoice_id,),
        )

        # Log activity
        cur.execute(
            """
            INSERT INTO invoice_activities
            (invoice_id, activity_type, description, created_by)
            VALUES (%s, 'sent', %s, %s)
        """,
            (
                invoice_id,
                f"Invoice sent to {invoice['customer_email']}",
                current_user.id,
            ),
        )

        conn.commit()

        # TODO: Actually send email via Email Manager
        # For now, just mark as sent

        return jsonify({"success": True, "message": f"Invoice sent to {invoice['customer_email']}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>/mark-paid", methods=["POST"])
@login_required
def mark_paid(invoice_id):
    """Mark invoice as paid"""
    try:
        data = request.get_json() or {}

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get invoice
        cur.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id))
        invoice = cur.fetchone()

        if not invoice:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        # Record payment
        payment_amount = data.get("amount", invoice["balance_due"])
        cur.execute(
            """
            INSERT INTO invoice_payments
            (invoice_id, amount, payment_method, payment_reference, payment_date, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                invoice_id,
                payment_amount,
                data.get("payment_method", "manual"),
                data.get("payment_reference", ""),
                data.get("payment_date", datetime.now().date()),
                data.get("notes", ""),
                current_user.id,
            ),
        )
        payment_id = cur.fetchone()["id"]

        # Check if fully paid
        cur.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total_paid FROM invoice_payments WHERE invoice_id = %s
        """,
            (invoice_id,),
        )
        total_paid = cur.fetchone()["total_paid"]

        new_status = "paid" if total_paid >= invoice["total"] else "sent"

        # Update invoice
        cur.execute(
            """
            UPDATE invoices
            SET status = %s,
                paid_at = CASE WHEN %s = 'paid' THEN NOW() ELSE paid_at END,
                payment_method = %s,
                payment_reference = %s,
                updated_at = NOW()
            WHERE id = %s
        """,
            (
                new_status,
                new_status,
                data.get("payment_method"),
                data.get("payment_reference"),
                invoice_id,
            ),
        )

        # Log activity
        cur.execute(
            """
            INSERT INTO invoice_activities
            (invoice_id, activity_type, description, metadata, created_by)
            VALUES (%s, 'paid', %s, %s, %s)
        """,
            (
                invoice_id,
                f"Payment of ${payment_amount:.2f} recorded",
                json.dumps({"payment_id": payment_id, "amount": float(payment_amount)}),
                current_user.id,
            ),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Payment of ${payment_amount:.2f} recorded",
                "status": new_status,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>/void", methods=["POST"])
@login_required
def void_invoice(invoice_id):
    """Void/cancel an invoice"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE invoices
            SET status = 'cancelled', updated_at = NOW()
            WHERE id = %s AND user_id = %s AND status != 'paid'
            RETURNING invoice_number
        """,
            (invoice_id, current_user.id),
        )
        invoice = cur.fetchone()

        if not invoice:
            cur.close()
            conn.close()
            return (
                jsonify({"success": False, "error": "Invoice not found or already paid"}),
                404,
            )

        cur.execute(
            """
            INSERT INTO invoice_activities
            (invoice_id, activity_type, description, created_by)
            VALUES (%s, 'cancelled', 'Invoice cancelled', %s)
        """,
            (invoice_id, current_user.id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"Invoice {invoice['invoice_number']} cancelled",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/invoices/<int:invoice_id>/duplicate", methods=["POST"])
@login_required
def duplicate_invoice(invoice_id):
    """Duplicate an invoice"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get original invoice
        cur.execute("SELECT * FROM invoices WHERE id = %s AND user_id = %s", (invoice_id, current_user.id))
        original = cur.fetchone()

        if not original:
            cur.close()
            conn.close()
            return jsonify({"success": False, "error": "Invoice not found"}), 404

        # Generate new invoice number
        cur.execute("SELECT generate_invoice_number() as num")
        new_number = cur.fetchone()["num"]

        # Create new invoice
        cur.execute(
            """
            INSERT INTO invoices
            (invoice_number, customer_id, status, issue_date, due_date,
             tax_rate, discount_amount, notes, terms, currency, created_by, user_id)
            VALUES (%s, %s, 'draft', CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days',
                    %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                new_number,
                original["customer_id"],
                original["tax_rate"],
                original["discount_amount"],
                original["notes"],
                original["terms"],
                original["currency"],
                current_user.id,
                current_user.id,
            ),
        )
        new_invoice_id = cur.fetchone()["id"]

        # Copy items
        cur.execute(
            """
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, amount, sort_order)
            SELECT %s, description, quantity, unit_price, amount, sort_order
            FROM invoice_items WHERE invoice_id = %s
        """,
            (new_invoice_id, invoice_id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "invoice_id": new_invoice_id,
                "invoice_number": new_number,
                "message": f"Invoice duplicated as {new_number}",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# SETTINGS
# ============================================================================


@invoicing_bp.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    """Get invoice settings"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM invoice_settings LIMIT 1")
        settings = cur.fetchone()

        return jsonify({"success": True, "settings": dict(settings) if settings else None})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/settings", methods=["PUT"])
@login_required
def update_settings():
    """Update invoice settings"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE invoice_settings
            SET company_name = COALESCE(%s, company_name),
                company_address = COALESCE(%s, company_address),
                company_phone = COALESCE(%s, company_phone),
                company_email = COALESCE(%s, company_email),
                logo_url = COALESCE(%s, logo_url),
                default_terms = COALESCE(%s, default_terms),
                default_notes = COALESCE(%s, default_notes),
                invoice_prefix = COALESCE(%s, invoice_prefix),
                default_tax_rate = COALESCE(%s, default_tax_rate),
                default_currency = COALESCE(%s, default_currency),
                payment_instructions = COALESCE(%s, payment_instructions),
                bank_details = COALESCE(%s, bank_details),
                footer_text = COALESCE(%s, footer_text),
                updated_at = NOW()
            RETURNING *
        """,
            (
                data.get("company_name"),
                data.get("company_address"),
                data.get("company_phone"),
                data.get("company_email"),
                data.get("logo_url"),
                data.get("default_terms"),
                data.get("default_notes"),
                data.get("invoice_prefix"),
                data.get("default_tax_rate"),
                data.get("default_currency"),
                data.get("payment_instructions"),
                data.get("bank_details"),
                data.get("footer_text"),
            ),
        )
        settings = cur.fetchone()

        conn.commit()

        return jsonify({"success": True, "settings": dict(settings)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# RECURRING INVOICES
# ============================================================================


@invoicing_bp.route("/api/recurring", methods=["GET"])
@login_required
def get_recurring():
    """Get recurring invoice schedules"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT r.*, c.email as customer_email,
                   c.first_name || ' ' || c.last_name as customer_name
            FROM recurring_invoices r
            LEFT JOIN crm_customers c ON r.customer_id = c.id
            WHERE r.status = 'active' AND r.created_by = %s
            ORDER BY r.next_invoice_date
        """,
            (current_user.id,),
        )
        recurring = cur.fetchall()

        return jsonify(
            {"success": True, "recurring": [dict(r) for r in recurring]},
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/recurring", methods=["POST"])
@login_required
def create_recurring():
    """Create recurring invoice schedule"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO recurring_invoices
            (customer_id, subscription_id, template_items, interval,
             next_invoice_date, auto_send, auto_charge, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                data["customer_id"],
                data.get("subscription_id"),
                json.dumps(data.get("items", [])),
                data["interval"],
                data.get("next_invoice_date", datetime.now().date()),
                data.get("auto_send", True),
                data.get("auto_charge", False),
                current_user.id,
            ),
        )
        recurring = cur.fetchone()

        conn.commit()

        return jsonify(
            {
                "success": True,
                "recurring": _serialize(dict(recurring)),
                "message": "Recurring invoice schedule created",
            },
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# QUICK CREATE (from other modules)
# ============================================================================


@invoicing_bp.route("/api/from-order", methods=["POST"])
@login_required
def create_from_order():
    """Create invoice from store order"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generate invoice number
        cur.execute("SELECT generate_invoice_number() as num")
        invoice_number = cur.fetchone()["num"]

        # Create invoice
        cur.execute(
            """
            INSERT INTO invoices
            (invoice_number, customer_id, order_id, status, issue_date, due_date,
             tax_rate, subtotal, tax_amount, total, balance_due, notes, created_by, user_id)
            VALUES (%s, %s, %s, 'sent', CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days',
                    %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                invoice_number,
                data.get("customer_id"),
                data.get("order_id"),
                data.get("tax_rate", 13),
                data.get("subtotal", 0),
                data.get("tax_amount", 0),
                data.get("total", 0),
                data.get("total", 0),
                f"Order #{data.get('order_id')}",
                current_user.id,
                current_user.id,
            ),
        )
        invoice_id = cur.fetchone()["id"]

        # Add items
        for item in data.get("items", []):
            amount = float(item.get("quantity", 1)) * float(item.get("price", 0))
            cur.execute(
                """
                INSERT INTO invoice_items
                (invoice_id, description, quantity, unit_price, amount, product_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    invoice_id,
                    item.get("name", item.get("description", "")),
                    item.get("quantity", 1),
                    item.get("price", 0),
                    amount,
                    item.get("product_id"),
                ),
            )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@invoicing_bp.route("/api/from-subscription", methods=["POST"])
@login_required
def create_from_subscription():
    """Create invoice from subscription renewal"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generate invoice number
        cur.execute("SELECT generate_invoice_number() as num")
        invoice_number = cur.fetchone()["num"]

        # Get tax rate
        cur.execute("SELECT default_tax_rate FROM invoice_settings LIMIT 1")
        settings = cur.fetchone()
        tax_rate = settings["default_tax_rate"] if settings else 13

        # Calculate amounts
        subtotal = float(data.get("amount", 0))
        tax_amount = subtotal * (float(tax_rate) / 100)
        total = subtotal + tax_amount

        # Create invoice
        cur.execute(
            """
            INSERT INTO invoices
            (invoice_number, customer_id, subscription_id, status, issue_date, due_date,
             tax_rate, subtotal, tax_amount, total, balance_due, recurring, recurring_interval,
             notes, created_by, user_id)
            VALUES (%s, %s, %s, 'sent', CURRENT_DATE, CURRENT_DATE,
                    %s, %s, %s, %s, %s, TRUE, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                invoice_number,
                data.get("customer_id"),
                data.get("subscription_id"),
                tax_rate,
                subtotal,
                tax_amount,
                total,
                total,
                data.get("interval", "monthly"),
                f"Subscription renewal - {data.get('tier', 'Standard')}",
                current_user.id,
                current_user.id,
            ),
        )
        invoice_id = cur.fetchone()["id"]

        # Add subscription item
        cur.execute(
            """
            INSERT INTO invoice_items
            (invoice_id, description, quantity, unit_price, amount, subscription_tier)
            VALUES (%s, %s, 1, %s, %s, %s)
        """,
            (
                invoice_id,
                f"{data.get('tier', 'Standard')} Subscription - {data.get('interval', 'Monthly')}",
                subtotal,
                subtotal,
                data.get("tier"),
            ),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "total": total,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATS & REPORTS
# ============================================================================


@invoicing_bp.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    """Get invoicing statistics"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Overall stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_invoices,
                COUNT(*) FILTER (WHERE status = 'draft') as draft,
                COUNT(*) FILTER (WHERE status = 'sent') as sent,
                COUNT(*) FILTER (WHERE status = 'paid') as paid,
                COUNT(*) FILTER (WHERE status = 'overdue') as overdue,
                COALESCE(SUM(total), 0) as total_invoiced,
                COALESCE(SUM(total) FILTER (WHERE status = 'paid'), 0) as total_collected,
                COALESCE(SUM(balance_due) FILTER (WHERE status IN ('sent', 'overdue')), 0) as total_outstanding
            FROM invoices
            WHERE user_id = %s
        """,
            (current_user.id,),
        )
        stats = cur.fetchone()

        # Monthly revenue trend
        cur.execute(
            """
            SELECT
                DATE_TRUNC('month', paid_at) as month,
                SUM(total) as revenue
            FROM invoices
            WHERE status = 'paid' AND paid_at > NOW() - INTERVAL '12 months' AND user_id = %s
            GROUP BY DATE_TRUNC('month', paid_at)
            ORDER BY month
        """,
            (current_user.id,),
        )
        monthly_revenue = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "stats": _serialize(dict(stats)),
                "monthly_revenue": _serialize([dict(m) for m in monthly_revenue]),
            },
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STATUS ENDPOINT
# ============================================================================


@invoicing_bp.route("/api/status")
def status():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) FROM invoices")
        invoice_count = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) FROM invoices WHERE status = 'overdue'")
        overdue_count = cur.fetchone()["count"]

        return jsonify(
            {
                "module": "invoicing",
                "status": "healthy",
                "healthy": True,
                "invoices": invoice_count,
                "overdue": overdue_count,
                "message": f"Invoicing operational with {invoice_count} invoices",
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "module": "invoicing",
                    "status": "error",
                    "healthy": False,
                    "message": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
