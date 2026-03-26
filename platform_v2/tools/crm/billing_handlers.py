"""
CRM Billing Webhook Handlers

Handles Stripe webhook events for CRM integration:
subscription lifecycle, invoices, payments, and customer sync.
"""

import logging
from datetime import datetime, timezone

from database import get_db_cursor
from services.billing_webhook import register_billing_handler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_notification(cur, ntype, title, message, priority="normal"):
    """Insert a system_notification row."""
    cur.execute(
        """INSERT INTO system_notifications
               (type, title, message, source, priority, visibility, is_read, created_at)
           VALUES (%s, %s, %s, 'crm_billing', %s, 'admin', false, %s)""",
        (ntype, title, message, priority, datetime.now(timezone.utc)),
    )


# ---------------------------------------------------------------------------
# 1. Subscription Created
# ---------------------------------------------------------------------------


def handle_subscription_created(event):
    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    customer_email = obj.get("customer_email") or obj.get("customer_details", {}).get("email")
    plan = obj.get("plan", {}).get("nickname") or obj.get("items", {}).get("data", [{}])[0].get("plan", {}).get(
        "nickname", "unknown"
    )

    with get_db_cursor(commit=True) as (conn, cur):
        logger.info("subscription_created: customer=%s email=%s plan=%s", customer_id, customer_email, plan)

        # Auto-link CRM contacts by email
        if customer_email:
            cur.execute(
                """UPDATE crm_customers
                      SET stripe_customer_id = %s,
                          updated_at = %s
                    WHERE LOWER(email) = LOWER(%s)
                      AND stripe_customer_id IS NULL""",
                (customer_id, datetime.now(timezone.utc), customer_email),
            )
            linked = cur.rowcount
            if linked:
                logger.info("Auto-linked %d CRM contact(s) to Stripe customer %s", linked, customer_id)

    return "subscription_created"


# ---------------------------------------------------------------------------
# 2. Subscription Updated
# ---------------------------------------------------------------------------


def handle_subscription_updated(event):
    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    status = obj.get("status")
    plan = obj.get("plan", {}).get("nickname") or obj.get("items", {}).get("data", [{}])[0].get("plan", {}).get(
        "nickname", "unknown"
    )

    with get_db_cursor(commit=True) as (conn, cur):
        logger.info(
            "subscription_updated: customer=%s status=%s plan=%s",
            customer_id,
            status,
            plan,
        )

    return "subscription_updated"


# ---------------------------------------------------------------------------
# 3. Subscription Deleted
# ---------------------------------------------------------------------------


def handle_subscription_deleted(event):
    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    customer_email = obj.get("customer_email") or ""

    with get_db_cursor(commit=True) as (conn, cur):
        logger.warning(
            "subscription_deleted: customer=%s email=%s",
            customer_id,
            customer_email,
        )
        _create_notification(
            cur,
            "warning",
            "Subscription Cancelled",
            f"Stripe customer {customer_id} ({customer_email}) cancelled their subscription.",
        )

    return "subscription_deleted"


# ---------------------------------------------------------------------------
# 4. Invoice Paid
# ---------------------------------------------------------------------------


def handle_invoice_paid(event):
    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    amount = obj.get("amount_paid", 0)
    currency = obj.get("currency", "usd").upper()
    invoice_id = obj.get("id")

    with get_db_cursor(commit=True) as (conn, cur):
        logger.info(
            "invoice_paid: invoice=%s customer=%s amount=%s %s",
            invoice_id,
            customer_id,
            amount / 100,
            currency,
        )

    return "invoice_paid"


# ---------------------------------------------------------------------------
# 5. Payment Failed
# ---------------------------------------------------------------------------


def handle_payment_failed(event):
    obj = event["data"]["object"]
    customer_id = obj.get("customer")
    customer_email = obj.get("customer_email") or ""
    amount = obj.get("amount_due", 0)
    currency = obj.get("currency", "usd").upper()

    with get_db_cursor(commit=True) as (conn, cur):
        logger.warning(
            "payment_failed: customer=%s email=%s amount=%s %s",
            customer_id,
            customer_email,
            amount / 100,
            currency,
        )
        _create_notification(
            cur,
            "alert",
            "Payment Failed",
            f"Payment of {amount / 100} {currency} failed for customer {customer_id} ({customer_email}).",
            priority="high",
        )

    return "payment_failed"


# ---------------------------------------------------------------------------
# 6. Customer Created
# ---------------------------------------------------------------------------


def handle_customer_created(event):
    obj = event["data"]["object"]
    customer_id = obj.get("id")
    email = obj.get("email", "")
    name = obj.get("name", "")

    with get_db_cursor(commit=True) as (conn, cur):
        logger.info(
            "customer_created: id=%s email=%s name=%s",
            customer_id,
            email,
            name,
        )

    return "customer_created"


# ---------------------------------------------------------------------------
# 7. Customer Updated
# ---------------------------------------------------------------------------


def handle_customer_updated(event):
    obj = event["data"]["object"]
    customer_id = obj.get("id")
    email = obj.get("email")
    name = obj.get("name")

    with get_db_cursor(commit=True) as (conn, cur):
        updates = []
        params = []

        if email is not None:
            updates.append("email = %s")
            params.append(email)
        if name is not None:
            updates.append("name = %s")
            params.append(name)

        if updates:
            updates.append("updated_at = %s")
            params.append(datetime.now(timezone.utc))
            params.append(customer_id)

            cur.execute(
                f"""UPDATE billing_customers
                       SET {', '.join(updates)}
                     WHERE stripe_customer_id = %s""",
                params,
            )
            logger.info(
                "customer_updated: id=%s rows=%d",
                customer_id,
                cur.rowcount,
            )
        else:
            logger.info("customer_updated: id=%s (no email/name changes)", customer_id)

    return "customer_updated"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_crm_billing_handlers():
    """Register all CRM billing webhook handlers with the dispatcher."""
    register_billing_handler("customer.subscription.created", handle_subscription_created)
    register_billing_handler("customer.subscription.updated", handle_subscription_updated)
    register_billing_handler("customer.subscription.deleted", handle_subscription_deleted)
    register_billing_handler("invoice.payment_succeeded", handle_invoice_paid)
    register_billing_handler("invoice.payment_failed", handle_payment_failed)
    register_billing_handler("customer.created", handle_customer_created)
    register_billing_handler("customer.updated", handle_customer_updated)
    logger.info("Registered 7 CRM billing webhook handlers")
