# CRM Billing Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Billing tab to the CRM module with revenue dashboard (MRR, churn, LTV charts), customer billing table with admin actions (create/cancel/change subscriptions), webhook handlers for Stripe events, and CRM-billing customer linking.

**Architecture:** New billing-specific route file in CRM module (keeps routes.py manageable). Billing service handles revenue calculations and Stripe API calls. Webhook handlers register with Stripe Core dispatcher. Linking table connects CRM contacts to billing customers. UI uses existing LCARS macro patterns with Chart.js for revenue charts.

**Tech Stack:** Python/Flask, Stripe SDK, PostgreSQL, Chart.js, LCARS macros (Jinja2)

---

## File Map

| Action | File | What |
|--------|------|------|
| Create | `database/migrations/205_crm_billing.sql` | crm_billing_link table |
| Create | `platform_v2/tools/crm/billing_routes.py` | Billing tab API routes |
| Create | `platform_v2/tools/crm/billing_service.py` | Revenue calculations + Stripe queries |
| Create | `platform_v2/tools/crm/billing_handlers.py` | Webhook event handlers |
| Modify | `platform_v2/tools/crm/__init__.py` | Register billing routes + handlers |
| Modify | `platform_v2/templates/tools/crm.html` | Add Billing tab UI |

---

### Task 1: Database Migration — CRM Billing Link

**Files:**
- Create: `database/migrations/205_crm_billing.sql`

- [ ] **Step 1: Create migration**

```sql
-- CRM ↔ Billing customer linking
-- Run: docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/205_crm_billing.sql

CREATE TABLE IF NOT EXISTS crm_billing_link (
    id SERIAL PRIMARY KEY,
    crm_customer_id INTEGER NOT NULL REFERENCES crm_customers(id),
    billing_customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
    linked_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(crm_customer_id),
    UNIQUE(billing_customer_id)
);
CREATE INDEX IF NOT EXISTS idx_crm_billing_crm ON crm_billing_link(crm_customer_id);
CREATE INDEX IF NOT EXISTS idx_crm_billing_billing ON crm_billing_link(billing_customer_id);
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/205_crm_billing.sql
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add database/migrations/205_crm_billing.sql
git commit -m "feat(crm): add crm_billing_link table for CRM ↔ Stripe customer linking"
```

---

### Task 2: Billing Service — Revenue Calculations + Stripe Queries

**Files:**
- Create: `platform_v2/tools/crm/billing_service.py`

- [ ] **Step 1: Create billing_service.py**

```python
"""CRM Billing Service — revenue calculations, Stripe queries, subscription management."""

import logging
from datetime import datetime, timedelta
from database import get_db_cursor

logger = logging.getLogger(__name__)


def get_revenue_metrics():
    """Calculate all revenue dashboard metrics."""
    with get_db_cursor() as (conn, cur):
        now = datetime.utcnow()
        thirty_days_ago = now - timedelta(days=30)

        # MRR — sum of active subscription amounts
        cur.execute("""
            SELECT COALESCE(SUM(bp.amount_cents), 0) as mrr_cents
            FROM billing_events be
            JOIN billing_products bp ON bp.stripe_price_id = (be.data->'object'->>'price')
            WHERE be.event_type = 'customer.subscription.created'
            AND NOT EXISTS (
                SELECT 1 FROM billing_events be2
                WHERE be2.event_type = 'customer.subscription.deleted'
                AND be2.data->'object'->>'id' = be.data->'object'->>'id'
            )
        """)
        row = cur.fetchone()
        mrr_cents = row["mrr_cents"] if row else 0

        # Active subscriptions count
        cur.execute("""
            SELECT COUNT(DISTINCT be.data->'object'->>'id') as count
            FROM billing_events be
            WHERE be.event_type = 'customer.subscription.created'
            AND NOT EXISTS (
                SELECT 1 FROM billing_events be2
                WHERE be2.event_type = 'customer.subscription.deleted'
                AND be2.data->'object'->>'id' = be.data->'object'->>'id'
            )
        """)
        active_subs = cur.fetchone()["count"] if cur.fetchone else 0
        row = cur.fetchone()
        active_subs = row["count"] if row else 0

        # Churn rate (last 30 days)
        cur.execute("""
            SELECT COUNT(*) as cancelled
            FROM billing_events
            WHERE event_type = 'customer.subscription.deleted'
            AND received_at >= %s
        """, (thirty_days_ago,))
        cancelled = cur.fetchone()["cancelled"] or 0
        churn_rate = round(cancelled / max(active_subs + cancelled, 1) * 100, 1)

        # Total revenue (all invoice.paid events)
        cur.execute("""
            SELECT COALESCE(SUM((data->'object'->>'amount_paid')::integer), 0) as total_cents
            FROM billing_events
            WHERE event_type = 'invoice.paid'
        """)
        total_revenue_cents = cur.fetchone()["total_cents"] or 0

        # Unique paying customers
        cur.execute("""
            SELECT COUNT(DISTINCT data->'object'->>'customer') as count
            FROM billing_events
            WHERE event_type = 'invoice.paid'
        """)
        total_customers = cur.fetchone()["count"] or 1

        ltv = round(total_revenue_cents / max(total_customers, 1) / 100, 2)

        # Payment success rate (last 30 days)
        cur.execute("""
            SELECT
                SUM(CASE WHEN event_type = 'invoice.paid' THEN 1 ELSE 0 END) as paid,
                SUM(CASE WHEN event_type = 'invoice.payment_failed' THEN 1 ELSE 0 END) as failed
            FROM billing_events
            WHERE event_type IN ('invoice.paid', 'invoice.payment_failed')
            AND received_at >= %s
        """, (thirty_days_ago,))
        row = cur.fetchone()
        paid = (row["paid"] or 0) if row else 0
        failed = (row["failed"] or 0) if row else 0
        success_rate = round(paid / max(paid + failed, 1) * 100, 1)

        return {
            "mrr": round(mrr_cents / 100, 2),
            "active_subscriptions": active_subs,
            "churn_rate": churn_rate,
            "ltv": ltv,
            "payment_success_rate": success_rate,
            "total_revenue": round(total_revenue_cents / 100, 2),
        }


def get_revenue_by_month(months=12):
    """Aggregate monthly revenue for charts."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT
                DATE_TRUNC('month', received_at) as month,
                SUM((data->'object'->>'amount_paid')::integer) as revenue_cents,
                COUNT(*) as payment_count
            FROM billing_events
            WHERE event_type = 'invoice.paid'
            AND received_at >= NOW() - INTERVAL '%s months'
            GROUP BY month
            ORDER BY month
        """, (months,))
        return [
            {
                "month": row["month"].isoformat() if row["month"] else None,
                "revenue": round((row["revenue_cents"] or 0) / 100, 2),
                "payments": row["payment_count"],
            }
            for row in cur.fetchall()
        ]


def get_subscription_distribution():
    """Count active subscriptions by product and tier."""
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT bp.module, bp.name, bp.amount_cents, COUNT(*) as count
            FROM billing_events be
            JOIN billing_products bp ON bp.stripe_price_id = (be.data->'object'->'items'->'data'->0->>'price')
            WHERE be.event_type = 'customer.subscription.created'
            AND NOT EXISTS (
                SELECT 1 FROM billing_events be2
                WHERE be2.event_type = 'customer.subscription.deleted'
                AND be2.data->'object'->>'id' = be.data->'object'->>'id'
            )
            GROUP BY bp.module, bp.name, bp.amount_cents
            ORDER BY bp.amount_cents
        """)
        return [dict(row) for row in cur.fetchall()]


def get_billing_customers(page=1, per_page=25, status=None, search=None):
    """List billing customers with subscription and payment data."""
    with get_db_cursor() as (conn, cur):
        conditions = []
        params = []

        if search:
            conditions.append("(bc.email ILIKE %s OR bc.name ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        offset = (page - 1) * per_page

        cur.execute(f"""
            SELECT bc.id, bc.user_id, bc.stripe_customer_id, bc.email, bc.name,
                   bc.created_at,
                   cbl.crm_customer_id,
                   cc.first_name as crm_first_name, cc.last_name as crm_last_name
            FROM billing_customers bc
            LEFT JOIN crm_billing_link cbl ON cbl.billing_customer_id = bc.id
            LEFT JOIN crm_customers cc ON cc.id = cbl.crm_customer_id
            {where}
            ORDER BY bc.created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])
        customers = [dict(row) for row in cur.fetchall()]

        cur.execute(f"SELECT COUNT(*) FROM billing_customers bc {where}", params)
        total = cur.fetchone()["count"]

        return {"customers": customers, "total": total, "page": page, "per_page": per_page}


def create_subscription_for_customer(billing_customer_id, price_id):
    """Create a Stripe subscription for a billing customer."""
    import stripe
    from services.stripe_service import is_stripe_configured

    if not is_stripe_configured():
        return {"error": "Stripe not configured"}

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE id = %s",
            (billing_customer_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Customer not found"}
        cus_id = row["stripe_customer_id"]

    try:
        subscription = stripe.Subscription.create(
            customer=cus_id,
            items=[{"price": price_id}],
        )
        return {"success": True, "subscription_id": subscription.id, "status": subscription.status}
    except stripe.error.StripeError as e:
        return {"error": str(e)}


def cancel_subscription(subscription_id):
    """Cancel a Stripe subscription."""
    import stripe
    try:
        sub = stripe.Subscription.cancel(subscription_id)
        return {"success": True, "status": sub.status}
    except stripe.error.StripeError as e:
        return {"error": str(e)}


def change_subscription_tier(subscription_id, new_price_id):
    """Change a subscription to a different price/tier."""
    import stripe
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        item_id = sub["items"]["data"][0]["id"]
        updated = stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
        )
        return {"success": True, "status": updated.status}
    except stripe.error.StripeError as e:
        return {"error": str(e)}


def get_customer_stripe_detail(stripe_customer_id):
    """Fetch live Stripe data for a customer (subscriptions, invoices)."""
    import stripe
    from services.stripe_service import is_stripe_configured

    if not is_stripe_configured():
        return None

    try:
        subscriptions = stripe.Subscription.list(customer=stripe_customer_id, limit=10)
        invoices = stripe.Invoice.list(customer=stripe_customer_id, limit=10)
        return {
            "subscriptions": [dict(s) for s in subscriptions.data],
            "invoices": [{"id": i.id, "amount": i.amount_paid, "status": i.status, "created": i.created} for i in invoices.data],
        }
    except stripe.error.StripeError as e:
        logger.error("Stripe detail fetch failed: %s", e)
        return None


def link_crm_customer(crm_customer_id, billing_customer_id):
    """Link a CRM contact to a billing customer."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO crm_billing_link (crm_customer_id, billing_customer_id)
               VALUES (%s, %s)
               ON CONFLICT (crm_customer_id) DO UPDATE SET billing_customer_id = %s""",
            (crm_customer_id, billing_customer_id, billing_customer_id),
        )


def auto_link_by_email():
    """Auto-link billing customers to CRM contacts by matching email."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("""
            INSERT INTO crm_billing_link (crm_customer_id, billing_customer_id)
            SELECT cc.id, bc.id
            FROM crm_customers cc
            JOIN billing_customers bc ON LOWER(cc.email) = LOWER(bc.email)
            WHERE NOT EXISTS (
                SELECT 1 FROM crm_billing_link cbl WHERE cbl.billing_customer_id = bc.id
            )
            AND NOT EXISTS (
                SELECT 1 FROM crm_billing_link cbl WHERE cbl.crm_customer_id = cc.id
            )
            ON CONFLICT DO NOTHING
        """)
        return cur.rowcount


def export_billing_csv():
    """Export billing customers as CSV data."""
    import csv
    import io
    with get_db_cursor() as (conn, cur):
        cur.execute("""
            SELECT bc.stripe_customer_id, bc.email, bc.name, bc.created_at,
                   cc.first_name as crm_first_name, cc.last_name as crm_last_name, cc.company as crm_company
            FROM billing_customers bc
            LEFT JOIN crm_billing_link cbl ON cbl.billing_customer_id = bc.id
            LEFT JOIN crm_customers cc ON cc.id = cbl.crm_customer_id
            ORDER BY bc.created_at DESC
        """)
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Stripe ID", "Email", "Name", "Created", "CRM First Name", "CRM Last Name", "Company"])
    for r in rows:
        writer.writerow([r["stripe_customer_id"], r["email"], r["name"], r["created_at"],
                         r.get("crm_first_name", ""), r.get("crm_last_name", ""), r.get("crm_company", "")])
    return output.getvalue()
```

IMPORTANT: Read the existing CRM routes.py to confirm the DB table column names for `crm_customers` (might be `first_name`/`last_name` or `name`, `email` column name). Adapt the JOIN queries to match.

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/crm/billing_service.py
git commit -m "feat(crm): add billing service — revenue metrics, Stripe queries, subscription management"
```

---

### Task 3: Webhook Event Handlers

**Files:**
- Create: `platform_v2/tools/crm/billing_handlers.py`

- [ ] **Step 1: Create billing_handlers.py**

```python
"""CRM webhook handlers for Stripe billing events."""

import logging
from database import get_db_cursor

logger = logging.getLogger(__name__)


def handle_subscription_created(event):
    """customer.subscription.created — log new subscription."""
    obj = event["data"]["object"]
    customer_id = obj.get("customer", "")
    logger.info("[CRM Billing] New subscription for %s: %s", customer_id, obj.get("id"))

    # Auto-link to CRM contact if email matches
    try:
        from tools.crm.billing_service import auto_link_by_email
        auto_link_by_email()
    except Exception as e:
        logger.warning("Auto-link failed: %s", e)

    return "subscription_created"


def handle_subscription_updated(event):
    """customer.subscription.updated — tier/status change."""
    obj = event["data"]["object"]
    logger.info("[CRM Billing] Subscription updated %s: status=%s", obj.get("id"), obj.get("status"))
    return "subscription_updated"


def handle_subscription_deleted(event):
    """customer.subscription.deleted — cancellation."""
    obj = event["data"]["object"]
    customer_id = obj.get("customer", "")
    logger.info("[CRM Billing] Subscription cancelled for %s", customer_id)

    # System notification
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO system_notifications
                   (type, title, message, source, priority, visibility, is_read, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, FALSE, NOW())""",
                ("warning", "Subscription Cancelled",
                 f"Customer {customer_id} cancelled their subscription.",
                 "stripe", "normal", "admin"),
            )
    except Exception as e:
        logger.warning("Notification failed: %s", e)

    return "subscription_deleted"


def handle_invoice_paid(event):
    """invoice.paid — record successful payment."""
    obj = event["data"]["object"]
    amount = obj.get("amount_paid", 0)
    customer_id = obj.get("customer", "")
    logger.info("[CRM Billing] Payment received: %s from %s", amount, customer_id)
    return "invoice_paid"


def handle_payment_failed(event):
    """invoice.payment_failed — flag customer, alert admin."""
    obj = event["data"]["object"]
    customer_id = obj.get("customer", "")
    logger.warning("[CRM Billing] Payment FAILED for %s", customer_id)

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO system_notifications
                   (type, title, message, source, priority, visibility, is_read, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, FALSE, NOW())""",
                ("alert", "Payment Failed",
                 f"Payment failed for customer {customer_id}. Action required.",
                 "stripe", "high", "admin"),
            )
    except Exception as e:
        logger.warning("Notification failed: %s", e)

    return "payment_failed"


def handle_customer_created(event):
    """customer.created — sync to billing_customers."""
    obj = event["data"]["object"]
    logger.info("[CRM Billing] Stripe customer created: %s", obj.get("id"))
    return "customer_synced"


def handle_customer_updated(event):
    """customer.updated — sync email/name changes."""
    obj = event["data"]["object"]
    stripe_id = obj.get("id", "")
    email = obj.get("email", "")
    name = obj.get("name", "")

    if stripe_id:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE billing_customers SET email = %s, name = %s, updated_at = NOW()
                       WHERE stripe_customer_id = %s""",
                    (email, name, stripe_id),
                )
        except Exception as e:
            logger.warning("Customer sync failed: %s", e)

    return "customer_updated"


def register_crm_billing_handlers():
    """Register all CRM billing handlers with Stripe Core dispatcher."""
    from services.billing_webhook import register_billing_handler

    register_billing_handler("customer.subscription.created", handle_subscription_created)
    register_billing_handler("customer.subscription.updated", handle_subscription_updated)
    register_billing_handler("customer.subscription.deleted", handle_subscription_deleted)
    register_billing_handler("invoice.paid", handle_invoice_paid)
    register_billing_handler("invoice.payment_failed", handle_payment_failed)
    register_billing_handler("customer.created", handle_customer_created)
    register_billing_handler("customer.updated", handle_customer_updated)

    logger.info("CRM billing handlers registered (7 event types)")
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/crm/billing_handlers.py
git commit -m "feat(crm): add Stripe webhook handlers for billing events"
```

---

### Task 4: Billing Routes for CRM

**Files:**
- Create: `platform_v2/tools/crm/billing_routes.py`
- Modify: `platform_v2/tools/crm/__init__.py`

- [ ] **Step 1: Read CRM __init__.py**

Read `/mnt/archie_brain/platform_v2/tools/crm/__init__.py` to understand the blueprint and route registration pattern.

- [ ] **Step 2: Create billing_routes.py**

```python
"""CRM Billing tab API routes."""

import logging
from flask import jsonify, request, Response
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


def register_billing_routes(bp, admin_required):

    @bp.route("/api/billing/metrics")
    @login_required
    @admin_required
    def billing_metrics():
        """Revenue dashboard metrics."""
        from tools.crm.billing_service import get_revenue_metrics
        return jsonify(get_revenue_metrics())

    @bp.route("/api/billing/revenue-by-month")
    @login_required
    @admin_required
    def billing_revenue_by_month():
        """Monthly revenue for chart."""
        from tools.crm.billing_service import get_revenue_by_month
        months = request.args.get("months", 12, type=int)
        return jsonify({"data": get_revenue_by_month(months)})

    @bp.route("/api/billing/distribution")
    @login_required
    @admin_required
    def billing_distribution():
        """Subscription distribution for chart."""
        from tools.crm.billing_service import get_subscription_distribution
        return jsonify({"data": get_subscription_distribution()})

    @bp.route("/api/billing/customers")
    @login_required
    @admin_required
    def billing_customers():
        """List billing customers with pagination."""
        from tools.crm.billing_service import get_billing_customers
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 25, type=int), 100)
        search = request.args.get("search", "").strip()
        return jsonify(get_billing_customers(page, per_page, search=search or None))

    @bp.route("/api/billing/customers/<int:billing_customer_id>/detail")
    @login_required
    @admin_required
    def billing_customer_detail(billing_customer_id):
        """Fetch live Stripe data for a customer."""
        from database import get_db_cursor
        from tools.crm.billing_service import get_customer_stripe_detail

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT stripe_customer_id FROM billing_customers WHERE id = %s", (billing_customer_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Customer not found"}), 404

        detail = get_customer_stripe_detail(row["stripe_customer_id"])
        return jsonify(detail or {"error": "Stripe not available"})

    @bp.route("/api/billing/subscribe", methods=["POST"])
    @login_required
    @admin_required
    def billing_create_subscription():
        """Create subscription for a customer."""
        from tools.crm.billing_service import create_subscription_for_customer
        data = request.get_json() or {}
        billing_customer_id = data.get("billing_customer_id")
        price_id = data.get("price_id")
        if not billing_customer_id or not price_id:
            return jsonify({"error": "billing_customer_id and price_id required"}), 400
        result = create_subscription_for_customer(billing_customer_id, price_id)
        return jsonify(result), 200 if result.get("success") else 400

    @bp.route("/api/billing/cancel", methods=["POST"])
    @login_required
    @admin_required
    def billing_cancel_subscription():
        """Cancel a subscription."""
        from tools.crm.billing_service import cancel_subscription
        data = request.get_json() or {}
        sub_id = data.get("subscription_id")
        if not sub_id:
            return jsonify({"error": "subscription_id required"}), 400
        result = cancel_subscription(sub_id)
        return jsonify(result), 200 if result.get("success") else 400

    @bp.route("/api/billing/change-tier", methods=["POST"])
    @login_required
    @admin_required
    def billing_change_tier():
        """Change subscription tier."""
        from tools.crm.billing_service import change_subscription_tier
        data = request.get_json() or {}
        sub_id = data.get("subscription_id")
        new_price_id = data.get("new_price_id")
        if not sub_id or not new_price_id:
            return jsonify({"error": "subscription_id and new_price_id required"}), 400
        result = change_subscription_tier(sub_id, new_price_id)
        return jsonify(result), 200 if result.get("success") else 400

    @bp.route("/api/billing/link", methods=["POST"])
    @login_required
    @admin_required
    def billing_link_customer():
        """Link CRM contact to billing customer."""
        from tools.crm.billing_service import link_crm_customer
        data = request.get_json() or {}
        crm_id = data.get("crm_customer_id")
        billing_id = data.get("billing_customer_id")
        if not crm_id or not billing_id:
            return jsonify({"error": "crm_customer_id and billing_customer_id required"}), 400
        link_crm_customer(crm_id, billing_id)
        return jsonify({"success": True})

    @bp.route("/api/billing/auto-link", methods=["POST"])
    @login_required
    @admin_required
    def billing_auto_link():
        """Auto-link billing customers to CRM contacts by email."""
        from tools.crm.billing_service import auto_link_by_email
        linked = auto_link_by_email()
        return jsonify({"success": True, "linked": linked})

    @bp.route("/api/billing/export")
    @login_required
    @admin_required
    def billing_export():
        """Export billing customers as CSV."""
        from tools.crm.billing_service import export_billing_csv
        csv_data = export_billing_csv()
        return Response(csv_data, mimetype="text/csv", headers={
            "Content-Disposition": "attachment; filename=billing_customers.csv"
        })

    @bp.route("/api/billing/products")
    @login_required
    @admin_required
    def billing_products_list():
        """List all billing products across modules."""
        from services.stripe_service import list_module_products
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT DISTINCT module FROM billing_products WHERE is_active = TRUE")
            modules = [r["module"] for r in cur.fetchall()]
        all_products = {}
        for m in modules:
            all_products[m] = list_module_products(m)
        return jsonify({"products": all_products})
```

- [ ] **Step 3: Register billing routes + handlers in __init__.py**

Read the CRM `__init__.py` to understand the registration pattern. Add:

```python
from tools.crm.billing_routes import register_billing_routes
register_billing_routes(bp, admin_required)

# Register Stripe webhook handlers
from tools.crm.billing_handlers import register_crm_billing_handlers
register_crm_billing_handlers()
```

IMPORTANT: Read the file first — the pattern might use `register_*_routes(bp, admin_required)` or a different signature. Match exactly.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/crm/billing_routes.py platform_v2/tools/crm/__init__.py
git commit -m "feat(crm): add billing tab API routes + register webhook handlers"
```

---

### Task 5: Billing Tab UI in CRM Template

**Files:**
- Modify: `platform_v2/templates/tools/crm.html`

- [ ] **Step 1: Read current CRM template**

Read `/mnt/archie_brain/platform_v2/templates/tools/crm.html` — find the tab navigation structure and how existing tabs are defined. Look for the pattern: tab buttons + tab panels.

- [ ] **Step 2: Add Billing tab button**

In the tab navigation, add a "Billing" tab button matching the existing pattern.

- [ ] **Step 3: Add Billing tab panel**

Add a new tab panel with:

1. **Revenue cards row**: 6 stat cards (MRR, Active Subs, Churn, LTV, Success Rate, Total Revenue). Load via fetch to `/tools/crm/api/billing/metrics`.

2. **Charts row**: Two charts side-by-side:
   - Revenue Over Time (line chart, Chart.js) — data from `/tools/crm/api/billing/revenue-by-month`
   - Subscription Distribution (donut chart) — data from `/tools/crm/api/billing/distribution`

3. **Customer billing table**: Loaded from `/tools/crm/api/billing/customers`. Columns: Name, Email, Product, MRR, Status, Last Payment, Actions. Action buttons: View Detail, Create Sub, Cancel, Change Tier, Link to CRM.

4. **Action buttons**: Auto-Link by Email, Export CSV.

**Styling**: Match existing CRM tab styling. Use LCARS dark theme, glass cards. Charts use Chart.js (already loaded in the platform). Revenue cards similar to Code Health stat cards.

**JavaScript**:
- `loadBillingTab()` — fetches metrics + customers, renders charts
- `createSubscription(customerId)` — modal with product/price selection
- `cancelSubscription(subId)` — confirm dialog
- `changeTier(subId)` — modal with tier selection
- `exportBillingCSV()` — triggers download
- `autoLinkCustomers()` — calls auto-link endpoint

IMPORTANT: Read the existing template FIRST. Match the exact tab pattern, LCARS macro usage, and JS patterns. The template may be very large — focus on the tab nav and one existing tab panel for the pattern.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/templates/tools/crm.html
git commit -m "feat(crm): add Billing tab with revenue dashboard, charts, and customer table"
```

---

### Task 6: Deploy + Verify

**Files:** None (deployment + testing)

- [ ] **Step 1: Deploy**

```bash
cd /mnt/archie_brain
docker compose restart archie_platform
```

- [ ] **Step 2: Verify billing metrics endpoint**

```bash
# Needs auth — check if it responds
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.200:3000/tools/crm/api/billing/metrics
```

Expected: 302 (needs login)

- [ ] **Step 3: Verify billing tables**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt crm_billing_link"
```

- [ ] **Step 4: Verify webhook handlers registered**

```bash
docker logs archie_platform 2>&1 | grep "CRM billing handlers" | tail -1
```

Expected: "CRM billing handlers registered (7 event types)"

- [ ] **Step 5: Log decision**

```python
mcp__archie__log_decision(
    title="CRM Billing Integration Complete — Revenue Dashboard + Subscription Management",
    decision="CRM Billing tab with 6 revenue metrics, revenue/distribution charts, customer billing table, admin subscription management (create/cancel/change tier), webhook handlers for 7 Stripe event types, CRM-billing auto-linking by email, CSV export.",
    project_id=195
)
```

---

## Task Summary

| Task | Description | Est. |
|------|-------------|------|
| 1 | DB migration — crm_billing_link table | 2 min |
| 2 | Billing service — metrics, Stripe queries, subscription mgmt | 8 min |
| 3 | Webhook handlers — 7 event types | 5 min |
| 4 | Billing routes + registration | 5 min |
| 5 | Billing tab UI (template + JS) | 15 min |
| 6 | Deploy + verify | 5 min |

**Total: 6 tasks, ~40 minutes**
