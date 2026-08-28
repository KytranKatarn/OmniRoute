"""
A.R.C.H.I.E. MCP Server - Business Tools
Phase 50.4: AI Integration Hub

Tools for invoicing, email, scheduling, CRM, and e-commerce
via Model Context Protocol.
"""

import os
from database import _get_db_password
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Dict, Any

from . import register_tool

logger = logging.getLogger("archie_mcp.tools.business")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": _get_db_password(),
}

# Platform URL for HTTP calls
PLATFORM_URL = os.getenv("ARCHIE_PLATFORM_URL", "http://localhost:3000")


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None, None


# ============================================================================
# CREATE INVOICE TOOL
# ============================================================================


async def create_invoice_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new invoice for a customer

    Generates an invoice with line items, calculates totals with tax,
    and optionally sends it to the customer.
    """
    customer_id = arguments.get("customer_id")
    customer_email = arguments.get("customer_email")
    items = arguments.get("items", [])
    due_days = arguments.get("due_days", 30)
    tax_rate = arguments.get("tax_rate", 0)
    notes = arguments.get("notes", "")
    send_email = arguments.get("send_email", False)
    user_id = arguments.get("user_id", 2)

    if not items:
        return {"success": False, "error": "At least one item is required"}

    if not customer_id and not customer_email:
        return {
            "success": False,
            "error": "Either customer_id or customer_email is required",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Find or create customer
        if customer_id:
            cur.execute(
                "SELECT id, email, first_name, last_name FROM crm_customers WHERE id = %s",
                (customer_id,),
            )
            customer = cur.fetchone()
            if not customer:
                cur.close()
                conn.close()
                return {"success": False, "error": f"Customer {customer_id} not found"}
        else:
            # Look up by email or create new customer
            cur.execute(
                "SELECT id, email, first_name, last_name FROM crm_customers WHERE email = %s",
                (customer_email,),
            )
            customer = cur.fetchone()
            if not customer:
                # Create new customer
                cur.execute(
                    """
                    INSERT INTO crm_customers (email, source, created_at)
                    VALUES (%s, 'mcp_invoice', NOW())
                    RETURNING id, email, first_name, last_name
                """,
                    (customer_email,),
                )
                customer = cur.fetchone()
                conn.commit()

        customer = dict(customer)

        # Generate invoice number
        cur.execute("SELECT MAX(id) FROM invoices")
        max_id = cur.fetchone()["max"] or 0
        invoice_number = f"INV-{datetime.now().strftime('%Y%m')}-{max_id + 1:04d}"

        # Calculate totals
        subtotal = sum(float(item.get("price", 0)) * int(item.get("quantity", 1)) for item in items)
        tax_amount = subtotal * (float(tax_rate) / 100) if tax_rate else 0
        total = subtotal + tax_amount

        # Set due date
        due_date = datetime.now() + timedelta(days=due_days)

        # Create invoice
        cur.execute(
            """
            INSERT INTO invoices
            (user_id, customer_id, invoice_number, subtotal, tax_rate, tax_amount,
             amount_total, amount_due, status, due_date, description, issue_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s, CURRENT_DATE)
            RETURNING id, invoice_number, amount_total, status, due_date, created_at
        """,
            (
                user_id,
                customer["id"],
                invoice_number,
                subtotal,
                tax_rate,
                tax_amount,
                total,
                total,
                due_date,
                notes,
            ),
        )

        invoice = dict(cur.fetchone())
        invoice_id = invoice["id"]

        # Add line items
        for item in items:
            cur.execute(
                """
                INSERT INTO invoice_items
                (invoice_id, description, quantity, unit_price, amount)
                VALUES (%s, %s, %s, %s, %s)
            """,
                (
                    invoice_id,
                    item.get("description", "Item"),
                    item.get("quantity", 1),
                    item.get("price", 0),
                    float(item.get("price", 0)) * int(item.get("quantity", 1)),
                ),
            )

        conn.commit()

        # Log activity
        cur.execute(
            """
            INSERT INTO invoice_activities (invoice_id, activity_type, description, created_by)
            VALUES (%s, 'created', 'Invoice created via MCP', %s)
        """,
            (invoice_id, user_id),
        )
        conn.commit()

        # Optionally send email
        email_sent = False
        if send_email and customer.get("email"):
            try:
                # Queue email
                cur.execute(
                    """
                    INSERT INTO email_queue
                    (recipient, subject, body_html, status, scheduled_for)
                    VALUES (%s, %s, %s, 'pending', NOW())
                """,
                    (
                        customer["email"],
                        f"Invoice {invoice_number}",
                        f"<p>Your invoice {invoice_number} for ${total:.2f} is ready.</p>",
                    ),
                )
                conn.commit()
                email_sent = True
            except Exception as e:
                logger.warning(f"Failed to queue invoice email: {e}")

        cur.close()
        conn.close()

        logger.info(f"Created invoice {invoice_number} for ${total:.2f}")

        return {
            "success": True,
            "invoice": {
                "id": invoice_id,
                "number": invoice_number,
                "subtotal": float(subtotal),
                "tax": float(tax_amount),
                "total": float(total),
                "status": "draft",
                "due_date": due_date.isoformat(),
            },
            "customer": {
                "id": customer["id"],
                "email": customer.get("email"),
                "name": f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip(),
            },
            "items_count": len(items),
            "email_sent": email_sent,
            "message": f"Invoice {invoice_number} created for ${total:.2f}",
        }

    except Exception as e:
        logger.error(f"Error creating invoice: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# LIST INVOICES TOOL
# ============================================================================


async def list_invoices_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List invoices with optional filters

    Returns invoices for a user with status and payment info.
    """
    user_id = arguments.get("user_id", 2)
    status = arguments.get("status")  # draft, sent, paid, overdue, cancelled
    customer_id = arguments.get("customer_id")
    limit = min(arguments.get("limit", 20), 100)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        conditions = ["i.user_id = %s"]
        params = [user_id]

        if status:
            conditions.append("i.status = %s")
            params.append(status)

        if customer_id:
            conditions.append("i.customer_id = %s")
            params.append(customer_id)

        where_clause = " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT i.*, c.email as customer_email,
                   CONCAT(c.first_name, ' ', c.last_name) as customer_name
            FROM invoices i
            LEFT JOIN crm_customers c ON i.customer_id = c.id
            WHERE {where_clause}
            ORDER BY i.created_at DESC
            LIMIT %s
        """,
            params + [limit],
        )

        invoices = [dict(inv) for inv in cur.fetchall()]

        # Get summary stats
        cur.execute(
            """
            SELECT status, COUNT(*) as count, SUM(amount_total) as total
            FROM invoices WHERE user_id = %s
            GROUP BY status
        """,
            (user_id,),
        )
        stats = {row["status"]: {"count": row["count"], "total": float(row["total"] or 0)} for row in cur.fetchall()}

        cur.close()
        conn.close()

        return {
            "success": True,
            "total": len(invoices),
            "invoices": invoices,
            "stats": stats,
            "filters_applied": {"status": status, "customer_id": customer_id},
        }

    except Exception as e:
        logger.error(f"Error listing invoices: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# SEND EMAIL TOOL
# ============================================================================


async def send_email_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send an email through A.R.C.H.I.E.'s email system

    Supports templates, attachments, and scheduled sending.
    """
    to = arguments.get("to", "")
    subject = arguments.get("subject", "")
    body = arguments.get("body", "")
    template_id = arguments.get("template_id")
    template_vars = arguments.get("template_vars", {})
    send_at = arguments.get("send_at")  # ISO datetime for scheduled send
    arguments.get("user_id", 2)

    if not to:
        return {"success": False, "error": "Recipient email (to) is required"}
    if not subject and not template_id:
        return {"success": False, "error": "Either subject or template_id is required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # If using template, fetch and render it
        if template_id:
            cur.execute(
                """
                SELECT name, subject, body_html, body_text
                FROM email_templates WHERE id = %s
            """,
                (template_id,),
            )
            template = cur.fetchone()
            if not template:
                cur.close()
                conn.close()
                return {"success": False, "error": f"Template {template_id} not found"}

            template = dict(template)
            subject = subject or template["subject"]
            body = template.get("body_html") or template.get("body_text", "")

            # Simple variable substitution
            for key, value in template_vars.items():
                body = body.replace(f"{{{{{key}}}}}", str(value))
                subject = subject.replace(f"{{{{{key}}}}}", str(value))

        # Determine status based on scheduling
        status = "pending"
        scheduled_for = None
        if send_at:
            try:
                scheduled_for = datetime.fromisoformat(send_at.replace("Z", "+00:00"))
                status = "scheduled"
            except ValueError:
                pass

        # Queue the email
        cur.execute(
            """
            INSERT INTO email_queue
            (recipient, subject, body_html, status, scheduled_for)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, status
        """,
            (to, subject, body, status, scheduled_for),
        )

        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Record not found"}
        result = dict(row)
        email_id = result["id"]

        # Log the email
        cur.execute(
            """
            INSERT INTO email_logs
            (recipient, subject, body_preview, status, sent_at)
            VALUES (%s, %s, %s, %s, %s)
        """,
            (
                to,
                subject,
                body[:200] if body else None,
                status,
                datetime.now() if status == "pending" else None,
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Queued email to {to}: {subject[:50]}...")

        return {
            "success": True,
            "email_id": email_id,
            "to": to,
            "subject": subject,
            "status": status,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "message": f"Email {'scheduled' if scheduled_for else 'queued'} successfully",
        }

    except Exception as e:
        logger.error(f"Error sending email: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# SCHEDULE EVENT TOOL
# ============================================================================


async def schedule_event_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Schedule an event or task in A.R.C.H.I.E.'s scheduler

    Supports one-time and recurring events with various task types.
    """
    name = arguments.get("name", "")
    description = arguments.get("description", "")
    task_type = arguments.get("task_type", "reminder")
    scheduled_for = arguments.get("scheduled_for", "")
    is_recurring = arguments.get("is_recurring", False)
    recurrence_rule = arguments.get("recurrence_rule")  # e.g., "FREQ=DAILY;INTERVAL=1"
    action_config = arguments.get("action_config", {})
    arguments.get("user_id", 2)

    if not name:
        return {"success": False, "error": "Event name is required"}
    if not scheduled_for:
        return {"success": False, "error": "scheduled_for datetime is required"}

    # Valid task types
    valid_types = [
        "reminder",
        "email",
        "backup",
        "report",
        "webhook",
        "maintenance",
        "custom",
    ]
    if task_type not in valid_types:
        return {
            "success": False,
            "error": f"Invalid task_type. Must be one of: {valid_types}",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Parse scheduled time
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        except ValueError:
            cur.close()
            conn.close()
            return {
                "success": False,
                "error": "Invalid scheduled_for datetime format. Use ISO format.",
            }

        # Create scheduled task
        cur.execute(
            """
            INSERT INTO scheduled_tasks
            (name, description, task_type, scheduled_for, is_recurring,
             recurrence_rule, action_config, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
            RETURNING id, name, task_type, scheduled_for, status
        """,
            (
                name,
                description,
                task_type,
                scheduled_dt,
                is_recurring,
                recurrence_rule,
                json.dumps(action_config),
            ),
        )

        task = dict(cur.fetchone())

        # If recurring, calculate next run
        if is_recurring:
            cur.execute(
                """
                UPDATE scheduled_tasks SET next_run = scheduled_for
                WHERE id = %s
            """,
                (task["id"],),
            )

        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"Scheduled task '{name}' for {scheduled_dt}")

        return {
            "success": True,
            "task": task,
            "is_recurring": is_recurring,
            "recurrence_rule": recurrence_rule,
            "message": f"Event '{name}' scheduled for {scheduled_dt.isoformat()}",
        }

    except Exception as e:
        logger.error(f"Error scheduling event: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# MANAGE CONTACTS (CRM) TOOL
# ============================================================================


async def manage_contacts_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Manage CRM contacts - create, update, list, or search

    Full CRM functionality for customer management.
    """
    action = arguments.get("action", "list")  # list, create, update, search, get
    contact_id = arguments.get("contact_id")
    email = arguments.get("email")
    first_name = arguments.get("first_name")
    last_name = arguments.get("last_name")
    phone = arguments.get("phone")
    company = arguments.get("company")
    tags = arguments.get("tags", [])
    search_query = arguments.get("search_query")
    limit = min(arguments.get("limit", 20), 100)

    valid_actions = ["list", "create", "update", "search", "get"]
    if action not in valid_actions:
        return {
            "success": False,
            "error": f"Invalid action. Must be one of: {valid_actions}",
        }

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        if action == "list":
            cur.execute(
                """
                SELECT c.*, COUNT(i.id) as invoice_count,
                       SUM(CASE WHEN i.status = 'paid' THEN i.amount_total ELSE 0 END) as total_paid
                FROM crm_customers c
                LEFT JOIN invoices i ON c.id = i.customer_id
                GROUP BY c.id
                ORDER BY c.created_at DESC
                LIMIT %s
            """,
                (limit,),
            )
            contacts = [dict(c) for c in cur.fetchall()]

            cur.close()
            conn.close()

            return {
                "success": True,
                "action": "list",
                "total": len(contacts),
                "contacts": contacts,
            }

        elif action == "create":
            if not email:
                cur.close()
                conn.close()
                return {
                    "success": False,
                    "error": "Email is required for creating a contact",
                }

            cur.execute(
                """
                INSERT INTO crm_customers
                (email, first_name, last_name, phone, company, tags, source, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'mcp', NOW())
                RETURNING id, email, first_name, last_name, company, created_at
            """,
                (email, first_name, last_name, phone, company, tags),
            )

            contact = dict(cur.fetchone())
            conn.commit()

            # Log activity
            cur.execute(
                """
                INSERT INTO crm_activity_log (customer_id, activity_type, activity_data, created_at)
                VALUES (%s, 'contact_created', '{"source": "mcp"}'::jsonb, NOW())
            """,
                (contact["id"],),
            )
            conn.commit()

            cur.close()
            conn.close()

            return {
                "success": True,
                "action": "create",
                "contact": contact,
                "message": f"Contact {email} created successfully",
            }

        elif action == "update":
            if not contact_id:
                cur.close()
                conn.close()
                return {"success": False, "error": "contact_id is required for update"}

            # Build update query dynamically
            updates = []
            params = []
            if email:
                updates.append("email = %s")
                params.append(email)
            if first_name:
                updates.append("first_name = %s")
                params.append(first_name)
            if last_name:
                updates.append("last_name = %s")
                params.append(last_name)
            if phone:
                updates.append("phone = %s")
                params.append(phone)
            if company:
                updates.append("company = %s")
                params.append(company)
            if tags:
                updates.append("tags = %s")
                params.append(tags)

            if not updates:
                cur.close()
                conn.close()
                return {"success": False, "error": "No fields to update"}

            updates.append("updated_at = NOW()")
            params.append(contact_id)

            cur.execute(
                f"""
                UPDATE crm_customers
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING id, email, first_name, last_name, company, updated_at
            """,
                params,
            )

            contact = cur.fetchone()
            if not contact:
                cur.close()
                conn.close()
                return {"success": False, "error": f"Contact {contact_id} not found"}

            conn.commit()
            cur.close()
            conn.close()

            return {
                "success": True,
                "action": "update",
                "contact": dict(contact),
                "message": f"Contact {contact_id} updated successfully",
            }

        elif action == "search":
            if not search_query:
                cur.close()
                conn.close()
                return {"success": False, "error": "search_query is required"}

            cur.execute(
                """
                SELECT * FROM crm_customers
                WHERE email ILIKE %s
                   OR first_name ILIKE %s
                   OR last_name ILIKE %s
                   OR company ILIKE %s
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                    limit,
                ),
            )

            contacts = [dict(c) for c in cur.fetchall()]
            cur.close()
            conn.close()

            return {
                "success": True,
                "action": "search",
                "query": search_query,
                "total": len(contacts),
                "contacts": contacts,
            }

        elif action == "get":
            if not contact_id:
                cur.close()
                conn.close()
                return {"success": False, "error": "contact_id is required"}

            cur.execute(
                """
                SELECT c.*,
                       (SELECT COUNT(*) FROM invoices WHERE customer_id = c.id) as invoice_count,
                       (SELECT SUM(amount_total) FROM invoices WHERE customer_id = c.id AND status = 'paid') as total_paid
                FROM crm_customers c
                WHERE c.id = %s
            """,
                (contact_id,),
            )

            contact = cur.fetchone()
            if not contact:
                cur.close()
                conn.close()
                return {"success": False, "error": f"Contact {contact_id} not found"}

            # Get recent interactions
            cur.execute(
                """
                SELECT * FROM crm_interactions
                WHERE customer_id = %s
                ORDER BY created_at DESC LIMIT 5
            """,
                (contact_id,),
            )
            interactions = [dict(i) for i in cur.fetchall()]

            cur.close()
            conn.close()

            return {
                "success": True,
                "action": "get",
                "contact": dict(contact),
                "recent_interactions": interactions,
            }

    except Exception as e:
        logger.error(f"Error managing contacts: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# CREATE STORE PRODUCT TOOL
# ============================================================================


async def create_store_product_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new product in the e-commerce store

    Adds a product with pricing, inventory, and optional variations.
    """
    name = arguments.get("name", "")
    description = arguments.get("description", "")
    price = arguments.get("price", 0)
    compare_at_price = arguments.get("compare_at_price")
    sku = arguments.get("sku")
    inventory = arguments.get("inventory", 0)
    category_id = arguments.get("category_id")
    images = arguments.get("images", [])
    store_id = arguments.get("store_id")
    user_id = arguments.get("user_id", 2)

    if not name:
        return {"success": False, "error": "Product name is required"}
    if price <= 0:
        return {"success": False, "error": "Price must be greater than 0"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        # Get or create default store for user
        if not store_id:
            cur.execute(
                """
                SELECT id FROM user_stores WHERE user_id = %s LIMIT 1
            """,
                (user_id,),
            )
            store = cur.fetchone()
            if store:
                store_id = store["id"]
            else:
                # Create default store
                cur.execute(
                    """
                    INSERT INTO user_stores (user_id, name, status, created_at)
                    VALUES (%s, 'Default Store', 'active', NOW())
                    RETURNING id
                """,
                    (user_id,),
                )
                store_id = cur.fetchone()["id"]
                conn.commit()

        # Generate SKU if not provided
        if not sku:
            cur.execute("SELECT MAX(id) FROM store_products")
            max_id = cur.fetchone()["max"] or 0
            sku = f"PROD-{max_id + 1:05d}"

        # Generate slug from name
        slug = name.lower().replace(" ", "-").replace("'", "")[:255]

        # Create product
        cur.execute(
            """
            INSERT INTO store_products
            (store_id, user_id, name, slug, description, sku, price,
             compare_at_price, inventory, category_id, images, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', NOW())
            RETURNING id, name, slug, sku, price, inventory, status, created_at
        """,
            (
                store_id,
                user_id,
                name,
                slug,
                description,
                sku,
                price,
                compare_at_price,
                inventory,
                category_id,
                json.dumps(images),
            ),
        )

        product = dict(cur.fetchone())
        conn.commit()

        cur.close()
        conn.close()

        logger.info(f"Created product '{name}' (SKU: {sku}) at ${price}")

        return {
            "success": True,
            "product": product,
            "store_id": store_id,
            "message": f"Product '{name}' created with SKU {sku}",
        }

    except psycopg2.errors.UniqueViolation:
        if conn:
            conn.rollback()
            conn.close()
        return {
            "success": False,
            "error": "Product with this SKU or slug already exists",
        }
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# LIST PRODUCTS TOOL
# ============================================================================


async def list_products_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List products from the e-commerce store

    Returns products with inventory and sales info.
    """
    store_id = arguments.get("store_id")
    category_id = arguments.get("category_id")
    status = arguments.get("status")  # active, draft, archived
    search = arguments.get("search")
    limit = min(arguments.get("limit", 20), 100)
    user_id = arguments.get("user_id", 2)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        conditions = ["p.user_id = %s"]
        params = [user_id]

        if store_id:
            conditions.append("p.store_id = %s")
            params.append(store_id)

        if category_id:
            conditions.append("p.category_id = %s")
            params.append(category_id)

        if status:
            conditions.append("p.status = %s")
            params.append(status)

        if search:
            conditions.append("(p.name ILIKE %s OR p.sku ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = " AND ".join(conditions)

        cur.execute(
            f"""
            SELECT p.*, c.name as category_name,
                   COALESCE(
                       (SELECT SUM(quantity) FROM store_order_items WHERE product_id = p.id), 0
                   ) as total_sold
            FROM store_products p
            LEFT JOIN store_categories c ON p.category_id = c.id
            WHERE {where_clause}
            ORDER BY p.created_at DESC
            LIMIT %s
        """,
            params + [limit],
        )

        products = [dict(p) for p in cur.fetchall()]

        # Get inventory summary
        cur.execute(
            """
            SELECT COUNT(*) as total_products,
                   SUM(inventory) as total_inventory,
                   SUM(CASE WHEN inventory = 0 THEN 1 ELSE 0 END) as out_of_stock
            FROM store_products WHERE user_id = %s
        """,
            (user_id,),
        )
        summary = dict(cur.fetchone())

        cur.close()
        conn.close()

        return {
            "success": True,
            "total": len(products),
            "products": products,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Error listing products: {e}")
        if conn:
            conn.close()
        return {"success": False, "error": str(e)}


# ============================================================================
# TOOL REGISTRATION
# ============================================================================


def register_business_tools():
    """Register all business tools with the MCP server"""

    # Create Invoice
    register_tool(
        name="create_invoice",
        category="business",
        description="Create a new invoice for a customer with line items, tax calculation, and optional email notification.",
        input_schema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "Existing customer ID",
                },
                "customer_email": {
                    "type": "string",
                    "description": "Customer email (creates new customer if not found)",
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "integer"},
                            "price": {"type": "number"},
                        },
                    },
                    "description": "Line items with description, quantity, and price",
                },
                "due_days": {
                    "type": "integer",
                    "description": "Days until due (default: 30)",
                    "default": 30,
                },
                "tax_rate": {
                    "type": "number",
                    "description": "Tax rate percentage (default: 0)",
                    "default": 0,
                },
                "notes": {"type": "string", "description": "Invoice notes/description"},
                "send_email": {
                    "type": "boolean",
                    "description": "Send invoice email to customer",
                    "default": False,
                },
            },
            "required": ["items"],
        },
        handler=create_invoice_handler,
        requires_permission="write",
    )

    # List Invoices
    register_tool(
        name="list_invoices",
        category="business",
        description="List invoices with optional status and customer filters.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["draft", "sent", "paid", "overdue", "cancelled"],
                    "description": "Filter by invoice status",
                },
                "customer_id": {"type": "integer", "description": "Filter by customer"},
                "limit": {
                    "type": "integer",
                    "description": "Max invoices to return",
                    "default": 20,
                },
            },
        },
        handler=list_invoices_handler,
        requires_permission="read",
    )

    # Send Email
    register_tool(
        name="send_email",
        category="business",
        description="Send an email through A.R.C.H.I.E. Supports templates and scheduled sending.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address (required)",
                },
                "subject": {"type": "string", "description": "Email subject"},
                "body": {
                    "type": "string",
                    "description": "Email body (HTML or plain text)",
                },
                "template_id": {
                    "type": "integer",
                    "description": "Email template ID to use",
                },
                "template_vars": {
                    "type": "object",
                    "description": "Variables to substitute in template",
                },
                "send_at": {
                    "type": "string",
                    "description": "ISO datetime to schedule email (optional)",
                },
            },
            "required": ["to"],
        },
        handler=send_email_handler,
        requires_permission="write",
    )

    # Schedule Event
    register_tool(
        name="schedule_event",
        category="business",
        description="Schedule an event or task. Supports one-time and recurring schedules.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Event name (required)"},
                "description": {"type": "string", "description": "Event description"},
                "task_type": {
                    "type": "string",
                    "enum": [
                        "reminder",
                        "email",
                        "backup",
                        "report",
                        "webhook",
                        "maintenance",
                        "custom",
                    ],
                    "description": "Type of task",
                    "default": "reminder",
                },
                "scheduled_for": {
                    "type": "string",
                    "description": "ISO datetime to schedule for (required)",
                },
                "is_recurring": {
                    "type": "boolean",
                    "description": "Is this a recurring event",
                    "default": False,
                },
                "recurrence_rule": {
                    "type": "string",
                    "description": "iCal RRULE format (e.g., FREQ=DAILY;INTERVAL=1)",
                },
                "action_config": {
                    "type": "object",
                    "description": "Additional configuration for the task",
                },
            },
            "required": ["name", "scheduled_for"],
        },
        handler=schedule_event_handler,
        requires_permission="write",
    )

    # Manage Contacts (CRM)
    register_tool(
        name="manage_contacts",
        category="business",
        description="Manage CRM contacts - create, update, list, search, or get details.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "update", "search", "get"],
                    "description": "Action to perform",
                    "default": "list",
                },
                "contact_id": {
                    "type": "integer",
                    "description": "Contact ID for get/update actions",
                },
                "email": {
                    "type": "string",
                    "description": "Contact email (required for create)",
                },
                "first_name": {"type": "string", "description": "First name"},
                "last_name": {"type": "string", "description": "Last name"},
                "phone": {"type": "string", "description": "Phone number"},
                "company": {"type": "string", "description": "Company name"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization",
                },
                "search_query": {
                    "type": "string",
                    "description": "Search query for search action",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for list/search",
                    "default": 20,
                },
            },
        },
        handler=manage_contacts_handler,
        requires_permission="write",
    )

    # Create Store Product
    register_tool(
        name="create_store_product",
        category="business",
        description="Create a new product in the e-commerce store with pricing and inventory.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Product name (required)"},
                "description": {"type": "string", "description": "Product description"},
                "price": {
                    "type": "number",
                    "description": "Product price (required, must be > 0)",
                },
                "compare_at_price": {
                    "type": "number",
                    "description": "Original/compare price for showing discount",
                },
                "sku": {
                    "type": "string",
                    "description": "SKU (auto-generated if not provided)",
                },
                "inventory": {
                    "type": "integer",
                    "description": "Initial inventory count",
                    "default": 0,
                },
                "category_id": {
                    "type": "integer",
                    "description": "Product category ID",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of image URLs",
                },
                "store_id": {
                    "type": "integer",
                    "description": "Store ID (uses default store if not specified)",
                },
            },
            "required": ["name", "price"],
        },
        handler=create_store_product_handler,
        requires_permission="write",
    )

    # List Products
    register_tool(
        name="list_products",
        category="business",
        description="List products from the e-commerce store with filters.",
        input_schema={
            "type": "object",
            "properties": {
                "store_id": {"type": "integer", "description": "Filter by store"},
                "category_id": {"type": "integer", "description": "Filter by category"},
                "status": {
                    "type": "string",
                    "enum": ["active", "draft", "archived"],
                    "description": "Filter by status",
                },
                "search": {"type": "string", "description": "Search by name or SKU"},
                "limit": {
                    "type": "integer",
                    "description": "Max products to return",
                    "default": 20,
                },
            },
        },
        handler=list_products_handler,
        requires_permission="read",
    )

    logger.info(
        "Registered 7 business tools: create_invoice, list_invoices, send_email, schedule_event, manage_contacts, create_store_product, list_products"
    )


# Auto-register when module is imported
register_business_tools()
