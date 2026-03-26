"""
CRM Billing Service — revenue metrics, Stripe integration, subscription management.

Tables: billing_customers, billing_events, billing_products, crm_customers, crm_billing_link
"""

import csv
import io
import logging
from datetime import datetime, timedelta

import stripe

from database import get_db_cursor
from services.stripe_service import is_stripe_configured

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Revenue metrics
# ---------------------------------------------------------------------------


def get_revenue_metrics() -> dict:
    """Return dict with mrr, active_subscriptions, churn_rate, ltv,
    payment_success_rate, total_revenue — all from billing_events."""
    with get_db_cursor() as (conn, cur):
        # Total revenue from invoice.paid events
        cur.execute(
            """
            SELECT COALESCE(SUM((data->'object'->>'amount_paid')::numeric / 100), 0)
            FROM billing_events
            WHERE event_type = 'invoice.paid'
        """
        )
        total_revenue = float(cur.fetchone()[0])

        # MRR — sum of amount_paid from invoice.paid in the last 30 days
        cur.execute(
            """
            SELECT COALESCE(SUM((data->'object'->>'amount_paid')::numeric / 100), 0)
            FROM billing_events
            WHERE event_type = 'invoice.paid'
              AND received_at >= NOW() - INTERVAL '30 days'
        """
        )
        mrr = float(cur.fetchone()[0])

        # Active subscriptions from the latest subscription events
        cur.execute(
            """
            SELECT COUNT(DISTINCT data->'object'->>'id')
            FROM billing_events
            WHERE event_type IN (
                'customer.subscription.created',
                'customer.subscription.updated'
            )
              AND data->'object'->>'status' = 'active'
        """
        )
        active_subscriptions = cur.fetchone()[0] or 0

        # Churned subscriptions (canceled/deleted in last 90 days)
        cur.execute(
            """
            SELECT COUNT(DISTINCT data->'object'->>'id')
            FROM billing_events
            WHERE event_type = 'customer.subscription.deleted'
              AND received_at >= NOW() - INTERVAL '90 days'
        """
        )
        churned = cur.fetchone()[0] or 0

        # Churn rate = churned / (active + churned) over 90 days
        total_subs = active_subscriptions + churned
        churn_rate = round((churned / total_subs * 100) if total_subs > 0 else 0, 2)

        # LTV = total_revenue / total unique customers who paid
        cur.execute(
            """
            SELECT COUNT(DISTINCT data->'object'->>'customer')
            FROM billing_events
            WHERE event_type = 'invoice.paid'
        """
        )
        paying_customers = cur.fetchone()[0] or 0
        ltv = round(total_revenue / paying_customers, 2) if paying_customers > 0 else 0

        # Payment success rate
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE event_type = 'invoice.paid') AS paid,
                COUNT(*) FILTER (WHERE event_type IN ('invoice.paid', 'invoice.payment_failed')) AS total
            FROM billing_events
            WHERE event_type IN ('invoice.paid', 'invoice.payment_failed')
        """
        )
        row = cur.fetchone()
        paid_count, total_attempts = row[0] or 0, row[1] or 0
        payment_success_rate = round((paid_count / total_attempts * 100) if total_attempts > 0 else 100, 2)

    return {
        "mrr": mrr,
        "active_subscriptions": active_subscriptions,
        "churn_rate": churn_rate,
        "ltv": ltv,
        "payment_success_rate": payment_success_rate,
        "total_revenue": total_revenue,
    }


# ---------------------------------------------------------------------------
# 2. Revenue by month
# ---------------------------------------------------------------------------


def get_revenue_by_month(months: int = 12) -> list[dict]:
    """Aggregate invoice.paid amounts by month for chart display."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT
                TO_CHAR(received_at, 'YYYY-MM') AS month,
                COALESCE(SUM((data->'object'->>'amount_paid')::numeric / 100), 0) AS revenue
            FROM billing_events
            WHERE event_type = 'invoice.paid'
              AND received_at >= NOW() - INTERVAL '%s months'
            GROUP BY month
            ORDER BY month
        """,
            (months,),
        )
        rows = cur.fetchall()
    return [{"month": r[0], "revenue": float(r[1])} for r in rows]


# ---------------------------------------------------------------------------
# 3. Subscription distribution
# ---------------------------------------------------------------------------


def get_subscription_distribution() -> list[dict]:
    """Count active subscriptions grouped by product module + name."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT bp.module, bp.name, COUNT(*) AS count
            FROM billing_events be
            JOIN billing_products bp
              ON bp.stripe_price_id = be.data->'object'->'items'->'data'->0->>'price'
            WHERE be.event_type IN (
                'customer.subscription.created',
                'customer.subscription.updated'
            )
              AND be.data->'object'->>'status' = 'active'
            GROUP BY bp.module, bp.name
            ORDER BY count DESC
        """
        )
        rows = cur.fetchall()
    return [{"module": r[0], "name": r[1], "count": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# 4. Billing customers (paginated)
# ---------------------------------------------------------------------------


def get_billing_customers(page: int = 1, per_page: int = 25, search: str = "") -> dict:
    """Paginated billing customers with LEFT JOIN to crm_billing_link and crm_customers."""
    offset = (page - 1) * per_page
    base_where = ""
    params: list = []

    if search:
        base_where = """
            WHERE bc.email ILIKE %s
               OR bc.name ILIKE %s
               OR bc.stripe_customer_id ILIKE %s
        """
        like = f"%{search}%"
        params = [like, like, like]

    count_sql = f"""
        SELECT COUNT(*)
        FROM billing_customers bc
        {base_where}
    """
    data_sql = f"""
        SELECT
            bc.id, bc.user_id, bc.stripe_customer_id, bc.email, bc.name,
            bc.created_at, bc.updated_at,
            cc.id AS crm_customer_id, cc.first_name, cc.last_name, cc.company
        FROM billing_customers bc
        LEFT JOIN crm_billing_link cbl ON cbl.billing_customer_id = bc.id
        LEFT JOIN crm_customers cc ON cc.id = cbl.crm_customer_id
        {base_where}
        ORDER BY bc.created_at DESC
        LIMIT %s OFFSET %s
    """

    with get_db_cursor() as (conn, cur):
        cur.execute(count_sql, params)
        total = cur.fetchone()[0]

        cur.execute(data_sql, params + [per_page, offset])
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    customers = [dict(zip(cols, row)) for row in rows]
    return {"customers": customers, "total": total, "page": page, "per_page": per_page}


# ---------------------------------------------------------------------------
# 5. Create subscription
# ---------------------------------------------------------------------------


def create_subscription_for_customer(billing_customer_id: int, price_id: str) -> dict:
    """Lookup stripe_customer_id and create a Stripe subscription."""
    if not is_stripe_configured():
        return {"error": "Stripe is not configured"}

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE id = %s",
            (billing_customer_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": f"Billing customer {billing_customer_id} not found"}
        stripe_customer_id = row[0]

    try:
        sub = stripe.Subscription.create(
            customer=stripe_customer_id,
            items=[{"price": price_id}],
        )
        return {"subscription": sub.to_dict()}
    except stripe.error.StripeError as e:
        log.error("Stripe subscription create failed: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 6. Cancel subscription
# ---------------------------------------------------------------------------


def cancel_subscription(subscription_id: str) -> dict:
    """Cancel a Stripe subscription."""
    if not is_stripe_configured():
        return {"error": "Stripe is not configured"}

    try:
        sub = stripe.Subscription.cancel(subscription_id)
        return {"subscription": sub.to_dict()}
    except stripe.error.StripeError as e:
        log.error("Stripe subscription cancel failed: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 7. Change subscription tier
# ---------------------------------------------------------------------------


def change_subscription_tier(subscription_id: str, new_price_id: str) -> dict:
    """Modify a Stripe subscription to a new price."""
    if not is_stripe_configured():
        return {"error": "Stripe is not configured"}

    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        if not sub.get("items", {}).get("data"):
            return {"error": "Subscription has no items"}

        item_id = sub["items"]["data"][0]["id"]
        updated = stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
        )
        return {"subscription": updated.to_dict()}
    except stripe.error.StripeError as e:
        log.error("Stripe subscription modify failed: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 8. Customer Stripe detail (live)
# ---------------------------------------------------------------------------


def get_customer_stripe_detail(stripe_customer_id: str) -> dict:
    """Fetch live Stripe data: subscriptions + recent invoices."""
    if not is_stripe_configured():
        return {"error": "Stripe is not configured"}

    try:
        subscriptions = stripe.Subscription.list(customer=stripe_customer_id, limit=10)
        invoices = stripe.Invoice.list(customer=stripe_customer_id, limit=20)
        return {
            "subscriptions": [s.to_dict() for s in subscriptions.auto_paging_iter()],
            "invoices": [i.to_dict() for i in invoices.auto_paging_iter()],
        }
    except stripe.error.StripeError as e:
        log.error("Stripe customer detail failed: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 9. Link CRM customer to billing customer
# ---------------------------------------------------------------------------


def link_crm_customer(crm_customer_id: int, billing_customer_id: int) -> dict:
    """Upsert a row into crm_billing_link."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Ensure table exists
        _ensure_crm_billing_link_table(cur)

        cur.execute(
            """
            INSERT INTO crm_billing_link (crm_customer_id, billing_customer_id)
            VALUES (%s, %s)
            ON CONFLICT (billing_customer_id)
            DO UPDATE SET crm_customer_id = EXCLUDED.crm_customer_id,
                          linked_at = NOW()
            RETURNING id, crm_customer_id, billing_customer_id, linked_at
        """,
            (crm_customer_id, billing_customer_id),
        )
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# 10. Auto-link by email
# ---------------------------------------------------------------------------


def auto_link_by_email() -> int:
    """JOIN crm_customers and billing_customers on email, insert links. Return count."""
    with get_db_cursor(commit=True) as (conn, cur):
        _ensure_crm_billing_link_table(cur)

        cur.execute(
            """
            INSERT INTO crm_billing_link (crm_customer_id, billing_customer_id)
            SELECT cc.id, bc.id
            FROM crm_customers cc
            JOIN billing_customers bc ON LOWER(bc.email) = LOWER(cc.email)
            WHERE NOT EXISTS (
                SELECT 1 FROM crm_billing_link cbl
                WHERE cbl.crm_customer_id = cc.id
                  AND cbl.billing_customer_id = bc.id
            )
            ON CONFLICT (billing_customer_id) DO NOTHING
        """
        )
        count = cur.rowcount
    return count


# ---------------------------------------------------------------------------
# 11. Export billing CSV
# ---------------------------------------------------------------------------


def export_billing_csv() -> str:
    """Return CSV string of all billing customers."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT
                bc.id, bc.user_id, bc.stripe_customer_id, bc.email, bc.name,
                bc.created_at, bc.updated_at,
                cc.id AS crm_customer_id,
                cc.first_name AS crm_first_name,
                cc.last_name AS crm_last_name,
                cc.company AS crm_company
            FROM billing_customers bc
            LEFT JOIN crm_billing_link cbl ON cbl.billing_customer_id = bc.id
            LEFT JOIN crm_customers cc ON cc.id = cbl.crm_customer_id
            ORDER BY bc.id
        """
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(cols)
    for row in rows:
        writer.writerow([v.isoformat() if isinstance(v, datetime) else v for v in row])
    return output.getvalue()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_crm_billing_link_table(cur):
    """Create crm_billing_link table if it doesn't exist."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS crm_billing_link (
            id              SERIAL PRIMARY KEY,
            crm_customer_id INTEGER NOT NULL REFERENCES crm_customers(id),
            billing_customer_id INTEGER NOT NULL REFERENCES billing_customers(id),
            linked_at       TIMESTAMP DEFAULT NOW(),
            UNIQUE (billing_customer_id)
        )
    """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_crm_billing_link_crm
        ON crm_billing_link (crm_customer_id)
    """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_crm_billing_link_billing
        ON crm_billing_link (billing_customer_id)
    """
    )
