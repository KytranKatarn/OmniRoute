"""
Stripe billing integration — tier management, module activation, webhook handling.
"""

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional, Tuple

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier → module mapping
# ---------------------------------------------------------------------------

_FREE_MODULES = {"crm", "invoicing", "store", "automations"}

_BUSINESS_MODULES = _FREE_MODULES | {
    "appointments",
    "content-studio",
    "social-media",
    "website-builder",
    "marketing",
    "help-desk",
    "accounting",
}

_ENTERPRISE_MODULES = _BUSINESS_MODULES | {
    "call-center",
    "automations-ui",
    "contracts",
}

TIER_MODULES = {
    "free": _FREE_MODULES,
    "business": _BUSINESS_MODULES,
    "enterprise": _ENTERPRISE_MODULES,
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_modules_for_tier(tier: str) -> set:
    """Return the set of module slugs included in *tier*.

    Falls back to the free tier if the tier name is unknown.
    """
    return TIER_MODULES.get(tier, _FREE_MODULES)


def activate_module(
    tenant_id: int,
    module_slug: str,
    source: str = "tier_included",
) -> None:
    """Insert a tenant_modules row (or re-enable if previously disabled)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled, source, activated_at)
            VALUES (%s, %s, TRUE, %s, NOW())
            ON CONFLICT (tenant_id, module_slug)
            DO UPDATE SET
                enabled = TRUE,
                source = EXCLUDED.source,
                activated_at = NOW(),
                deactivated_at = NULL
            """,
            (tenant_id, module_slug, source),
        )


def deactivate_module(tenant_id: int, module_slug: str) -> None:
    """Set enabled=false and record deactivation timestamp."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE tenant_modules
            SET enabled = FALSE, deactivated_at = NOW()
            WHERE tenant_id = %s AND module_slug = %s
            """,
            (tenant_id, module_slug),
        )


def sync_tier_modules(tenant_id: int, tier: str) -> None:
    """Enable all modules included in *tier* for *tenant_id*."""
    for slug in get_modules_for_tier(tier):
        activate_module(tenant_id, slug, source="tier_included")


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------


def _get_stripe_webhook_secret() -> str:
    return os.getenv("KBS_STRIPE_WEBHOOK_SECRET", "")


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Validate Stripe-Signature header using HMAC-SHA256."""
    try:
        pairs = {k: v for k, v in (p.split("=", 1) for p in sig_header.split(","))}
        timestamp = pairs.get("t", "")
        v1_sig = pairs.get("v1", "")
        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1_sig)
    except Exception:
        return False


def _log_stripe_event(
    stripe_event_id: str,
    event_type: str,
    tenant_id: Optional[int],
    payload: dict,
) -> None:
    """Write event to stripe_events table (idempotent — ON CONFLICT DO NOTHING)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO stripe_events
                (stripe_event_id, event_type, tenant_id, payload, processed, created_at)
            VALUES (%s, %s, %s, %s::jsonb, FALSE, NOW())
            ON CONFLICT (stripe_event_id) DO NOTHING
            """,
            (stripe_event_id, event_type, tenant_id, json.dumps(payload)),
        )


def _mark_event_processed(stripe_event_id: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE stripe_events SET processed = TRUE WHERE stripe_event_id = %s",
            (stripe_event_id,),
        )


def _get_tenant_by_stripe_customer(stripe_customer_id: str) -> Optional[dict]:
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id, tier FROM tenants WHERE stripe_customer_id = %s LIMIT 1",
            (stripe_customer_id,),
        )
        return cur.fetchone()


def _set_tenant_tier(tenant_id: int, tier: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE tenants SET tier = %s, updated_at = NOW() WHERE id = %s",
            (tier, tenant_id),
        )


def _handle_checkout_completed(event: dict) -> None:
    """checkout.session.completed — dispatch based on metadata source.

    One-time payments for invoices/orders go to _handle_invoice_or_order_payment.
    Subscription checkouts continue to the existing tier activation flow.
    """
    obj = event.get("data", {}).get("object", {})
    metadata = obj.get("metadata", {})
    source = metadata.get("source", "")

    if source in ("kbs_invoicing", "kbs_store"):
        _handle_invoice_or_order_payment(event)
        return

    # Original subscription/addon checkout handling follows...
    module_slug = metadata.get("module_slug")
    tenant_id = metadata.get("tenant_id")
    if not module_slug or not tenant_id:
        logger.warning("checkout.session.completed: missing module_slug or tenant_id in metadata")
        return
    activate_module(int(tenant_id), module_slug, source="addon_purchase")
    logger.info("Activated addon module %s for tenant %s", module_slug, tenant_id)


def _handle_subscription_updated(event: dict) -> None:
    """customer.subscription.updated — update tenant tier + sync modules."""
    subscription = event.get("data", {}).get("object", {})
    customer_id = subscription.get("customer")
    metadata = subscription.get("metadata", {})
    new_tier = metadata.get("tier", "free")

    tenant = _get_tenant_by_stripe_customer(customer_id) if customer_id else None
    if not tenant:
        logger.warning("subscription.updated: no tenant found for customer %s", customer_id)
        return

    _set_tenant_tier(tenant["id"], new_tier)
    sync_tier_modules(tenant["id"], new_tier)
    logger.info("Updated tenant %s tier to %s", tenant["id"], new_tier)


def _handle_subscription_deleted(event: dict) -> None:
    """customer.subscription.deleted — downgrade to free, deactivate non-free modules."""
    subscription = event.get("data", {}).get("object", {})
    customer_id = subscription.get("customer")

    tenant = _get_tenant_by_stripe_customer(customer_id) if customer_id else None
    if not tenant:
        logger.warning("subscription.deleted: no tenant found for customer %s", customer_id)
        return

    tenant_id = tenant["id"]
    free_modules = get_modules_for_tier("free")

    # Find currently-enabled tier_included modules that are NOT in the free set
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT module_slug FROM tenant_modules
            WHERE tenant_id = %s AND enabled = TRUE AND source = 'tier_included'
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()

    for row in rows:
        slug = row["module_slug"]
        if slug not in free_modules:
            deactivate_module(tenant_id, slug)

    _set_tenant_tier(tenant_id, "free")
    # Ensure free-tier modules are active
    sync_tier_modules(tenant_id, "free")
    logger.info("Downgraded tenant %s to free tier", tenant_id)


def _handle_invoice_or_order_payment(event: dict) -> None:
    """Handle checkout.session.completed for invoice or order payments.

    This is called by _handle_checkout_completed when the metadata indicates
    source=kbs_invoicing or source=kbs_store. Handles one-time payments.
    """
    obj = event.get("data", {}).get("object", {})
    metadata = obj.get("metadata", {})
    source = metadata.get("source", "")
    tenant_id_str = metadata.get("tenant_id")
    payment_intent = obj.get("payment_intent", "")
    amount_total = obj.get("amount_total", 0)  # in cents
    customer_email = obj.get("customer_email", "")

    if not tenant_id_str:
        logger.warning("checkout.session.completed with no tenant_id in metadata")
        return

    tenant_id = int(tenant_id_str)

    if source == "kbs_invoicing":
        invoice_id_str = metadata.get("invoice_id")
        if not invoice_id_str:
            logger.warning("Invoice checkout completed but no invoice_id in metadata")
            return

        invoice_id = int(invoice_id_str)
        _mark_invoice_paid_from_stripe(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            amount=amount_total / 100.0,
            payment_reference=payment_intent,
        )
        logger.info(
            "Stripe checkout completed: invoice %s paid (tenant %s, $%.2f)",
            invoice_id,
            tenant_id,
            amount_total / 100.0,
        )

    elif source == "kbs_store":
        order_id_str = metadata.get("order_id")
        if not order_id_str:
            logger.warning("Order checkout completed but no order_id in metadata")
            return

        order_id = int(order_id_str)
        _mark_order_paid_from_stripe(
            tenant_id=tenant_id,
            order_id=order_id,
            amount=amount_total / 100.0,
            payment_reference=payment_intent,
            customer_email=customer_email,
        )
        logger.info(
            "Stripe checkout completed: order %s paid (tenant %s, $%.2f)",
            order_id,
            tenant_id,
            amount_total / 100.0,
        )


def _mark_invoice_paid_from_stripe(
    tenant_id: int,
    invoice_id: int,
    amount: float,
    payment_reference: str,
) -> None:
    """Mark an invoice as paid and record the payment. Emit events."""
    from core.database import set_tenant_search_path
    from core.event_bus import event_bus

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)

        # Record payment
        cur.execute(
            """
            INSERT INTO invoice_payments (invoice_id, amount, payment_method, payment_reference)
            VALUES (%s, %s, %s, %s)
            """,
            (invoice_id, amount, "stripe", payment_reference),
        )

        # Update invoice status
        cur.execute(
            """
            UPDATE invoices
            SET amount_paid = total, balance_due = 0, status = 'paid', updated_at = NOW()
            WHERE id = %s
            RETURNING id, customer_id, total
            """,
            (invoice_id,),
        )
        invoice = cur.fetchone()

    if invoice:
        event_bus.emit(
            "payment.received",
            {
                "invoice_id": invoice_id,
                "amount": amount,
                "payment_method": "stripe",
                "payment_reference": payment_reference,
                "customer_id": invoice.get("customer_id"),
            },
            tenant_id=tenant_id,
        )
        event_bus.emit(
            "invoice.paid",
            {
                "invoice_id": invoice_id,
                "customer_id": invoice.get("customer_id"),
                "total": float(invoice.get("total", 0)),
            },
            tenant_id=tenant_id,
        )


def _mark_order_paid_from_stripe(
    tenant_id: int,
    order_id: int,
    amount: float,
    payment_reference: str,
    customer_email: str = "",
) -> None:
    """Mark a store order as paid and update status. Emit events."""
    from core.database import set_tenant_search_path
    from core.event_bus import event_bus

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)

        cur.execute(
            """
            UPDATE store_orders
            SET status = 'paid',
                payment_status = 'paid',
                payment_method = 'stripe',
                payment_reference = %s,
                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, customer_id
            """,
            (
                payment_reference,
                f'{{"stripe_amount_cents": {int(amount * 100)}, "customer_email": "{customer_email}"}}',
                order_id,
            ),
        )
        order = cur.fetchone()

    if order:
        event_bus.emit(
            "payment.received",
            {
                "order_id": order_id,
                "amount": amount,
                "payment_method": "stripe",
                "payment_reference": payment_reference,
                "customer_id": order.get("customer_id"),
            },
            tenant_id=tenant_id,
        )
        event_bus.emit(
            "order.paid",
            {
                "order_id": order_id,
                "customer_id": order.get("customer_id"),
                "amount": amount,
            },
            tenant_id=tenant_id,
        )


_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
}


def handle_stripe_webhook(payload: bytes, sig_header: str) -> Tuple[str, int]:
    """Validate signature, log event, dispatch to handler.

    Returns (response_body, status_code).
    """
    secret = _get_stripe_webhook_secret()

    if secret and not _verify_stripe_signature(payload, sig_header or "", secret):
        return "Invalid signature", 400

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Stripe webhook payload not valid JSON: %s", exc)
        return "Invalid payload", 400

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    # Best-effort tenant lookup from the event object
    obj = event.get("data", {}).get("object", {})
    customer_id = obj.get("customer")
    tenant_id = None
    if customer_id:
        tenant = _get_tenant_by_stripe_customer(customer_id)
        if tenant:
            tenant_id = tenant["id"]

    _log_stripe_event(event_id, event_type, tenant_id, event)

    handler = _HANDLERS.get(event_type)
    if handler:
        try:
            handler(event)
            _mark_event_processed(event_id)
        except Exception as exc:
            logger.exception("Error handling Stripe event %s (%s): %s", event_id, event_type, exc)
            return "Handler error", 500
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return "ok", 200
