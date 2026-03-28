"""Stripe Checkout session creation for invoices and store orders."""

import logging
import os

import stripe

from core.database import get_db_cursor

logger = logging.getLogger(__name__)

# Configure Stripe API key from environment
stripe.api_key = os.getenv("KBS_STRIPE_SECRET_KEY", "")

# Base URL for success/cancel redirects
_BASE_URL = os.getenv("KBS_BASE_URL", "https://app.kytranempowerment.com")


def create_invoice_checkout_session(
    invoice: dict,
    tenant_id: int,
    success_url: str = None,
    cancel_url: str = None,
) -> dict:
    """Create a Stripe Checkout Session for paying an invoice.

    Args:
        invoice: Dict with id, invoice_number, customer_email, total, items[].
        tenant_id: Tenant ID for multi-tenant isolation.
        success_url: Override redirect on success.
        cancel_url: Override redirect on cancel.

    Returns:
        Dict with 'url' (redirect URL) and 'session_id'.

    Raises:
        ValueError: If invoice has no line items.
    """
    items = invoice.get("items", [])
    if not items:
        raise ValueError("Invoice must have at least one line item")

    line_items = []
    for item in items:
        unit_amount = int(round(float(item.get("unit_price", item.get("amount", 0))) * 100))
        line_items.append(
            {
                "price_data": {
                    "currency": "cad",
                    "product_data": {
                        "name": item.get("description", "Invoice item"),
                    },
                    "unit_amount": unit_amount,
                },
                "quantity": int(item.get("quantity", 1)),
            }
        )

    invoice_id = invoice.get("id", "")
    invoice_number = invoice.get("invoice_number", "")

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=invoice.get("customer_email"),
        line_items=line_items,
        metadata={
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "tenant_id": str(tenant_id),
            "source": "kbs_invoicing",
        },
        success_url=success_url or f"{_BASE_URL}/invoicing/payment-success?invoice={invoice_number}",
        cancel_url=cancel_url or f"{_BASE_URL}/invoicing/payment-cancelled?invoice={invoice_number}",
    )

    # Store session ID on the invoice for tracking
    _save_checkout_session(invoice_id, session.id, tenant_id)

    logger.info(
        "Created Stripe checkout session %s for invoice %s (tenant %s)",
        session.id,
        invoice_number,
        tenant_id,
    )

    return {"url": session.url, "session_id": session.id}


def create_order_checkout_session(
    order_items: list,
    order_id: int,
    customer_email: str,
    tenant_id: int,
    success_url: str = None,
    cancel_url: str = None,
) -> dict:
    """Create a Stripe Checkout Session for paying a store order.

    Args:
        order_items: List of dicts with name, quantity, price.
        order_id: Store order ID.
        customer_email: Buyer's email.
        tenant_id: Tenant ID.
        success_url: Override redirect on success.
        cancel_url: Override redirect on cancel.

    Returns:
        Dict with 'url' and 'session_id'.

    Raises:
        ValueError: If no items provided.
    """
    if not order_items:
        raise ValueError("Order must have at least one line item")

    line_items = []
    for item in order_items:
        unit_amount = int(round(float(item.get("price", 0)) * 100))
        line_items.append(
            {
                "price_data": {
                    "currency": "cad",
                    "product_data": {
                        "name": item.get("name", "Store item"),
                    },
                    "unit_amount": unit_amount,
                },
                "quantity": int(item.get("quantity", 1)),
            }
        )

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=customer_email,
        line_items=line_items,
        metadata={
            "order_id": str(order_id),
            "tenant_id": str(tenant_id),
            "source": "kbs_store",
        },
        success_url=success_url or f"{_BASE_URL}/store/order-success?order={order_id}",
        cancel_url=cancel_url or f"{_BASE_URL}/store/order-cancelled?order={order_id}",
    )

    _save_checkout_session_for_order(order_id, session.id, tenant_id)

    logger.info(
        "Created Stripe checkout session %s for order %s (tenant %s)",
        session.id,
        order_id,
        tenant_id,
    )

    return {"url": session.url, "session_id": session.id}


def _save_checkout_session(invoice_id: int, session_id: str, tenant_id: int) -> None:
    """Store the Stripe checkout session ID on the invoice record."""
    try:
        from core.database import set_tenant_search_path

        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE invoices
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    f'{{"stripe_checkout_session_id": "{session_id}"}}',
                    invoice_id,
                ),
            )
    except Exception:
        logger.exception("Failed to save checkout session for invoice %s", invoice_id)


def _save_checkout_session_for_order(order_id: int, session_id: str, tenant_id: int) -> None:
    """Store the Stripe checkout session ID on the order record."""
    try:
        from core.database import set_tenant_search_path

        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE store_orders
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    f'{{"stripe_checkout_session_id": "{session_id}"}}',
                    order_id,
                ),
            )
    except Exception:
        logger.exception("Failed to save checkout session for order %s", order_id)


# ---------------------------------------------------------------------------
# Subscription checkout
# ---------------------------------------------------------------------------

# Tier -> Stripe Price ID mapping (loaded from env)
_TIER_PRICE_MAP = {
    "business": os.getenv("KBS_STRIPE_PRICE_BUSINESS", ""),
    "enterprise": os.getenv("KBS_STRIPE_PRICE_ENTERPRISE", ""),
}


def create_subscription_checkout(
    tenant_id: int,
    tier: str,
    customer_email: str,
    success_url: str = None,
    cancel_url: str = None,
    trial_days: int = None,
) -> dict:
    """Create a Stripe Checkout Session for a subscription.

    Args:
        tenant_id: Tenant purchasing the subscription.
        tier: 'business' or 'enterprise'.
        customer_email: Email for the Stripe customer.
        success_url: Redirect on success.
        cancel_url: Redirect on cancel.
        trial_days: If set, adds a trial period (default 14 for business).

    Returns:
        Dict with 'url' (redirect URL) and 'session_id'.

    Raises:
        ValueError: If tier is invalid or has no price ID configured.
    """
    price_id = _TIER_PRICE_MAP.get(tier)
    if not price_id:
        raise ValueError(
            f"No Stripe price ID configured for tier '{tier}'. "
            f"Set KBS_STRIPE_PRICE_{tier.upper()} env var."
        )

    # Default trial: 14 days for business tier
    if trial_days is None and tier == "business":
        trial_days = 14

    checkout_params = {
        "mode": "subscription",
        "customer_email": customer_email,
        "line_items": [{"price": price_id, "quantity": 1}],
        "metadata": {
            "tenant_id": str(tenant_id),
            "tier": tier,
            "source": "kbs_subscription",
        },
        "subscription_data": {
            "metadata": {"tenant_id": str(tenant_id), "tier": tier},
        },
        "success_url": success_url or f"{_BASE_URL}/dashboard?subscription=success",
        "cancel_url": cancel_url or f"{_BASE_URL}/marketplace?subscription=cancelled",
    }

    if trial_days and trial_days > 0:
        checkout_params["subscription_data"]["trial_period_days"] = trial_days

    session = stripe.checkout.Session.create(**checkout_params)

    # Record the checkout attempt
    _save_subscription_checkout(tenant_id, session.id, tier)

    logger.info(
        "Created Stripe subscription checkout %s for tenant %s (tier=%s, trial=%s)",
        session.id,
        tenant_id,
        tier,
        trial_days,
    )

    return {"url": session.url, "session_id": session.id}


def create_addon_checkout(
    tenant_id: int,
    plugin_slug: str,
    customer_email: str,
    success_url: str = None,
    cancel_url: str = None,
) -> dict:
    """Create a Stripe Checkout Session for an add-on plugin subscription.

    Args:
        tenant_id: Tenant purchasing the add-on.
        plugin_slug: Plugin slug (e.g. 'salon', 'electrical').
        customer_email: Email for the Stripe customer.
        success_url: Redirect on success.
        cancel_url: Redirect on cancel.

    Returns:
        Dict with 'url' and 'session_id'.

    Raises:
        ValueError: If no price ID is configured for this plugin.
    """
    import json as _json

    addon_prices = _json.loads(os.getenv("KBS_STRIPE_ADDON_PRICES", "{}"))
    price_id = addon_prices.get(plugin_slug)

    if not price_id:
        raise ValueError(
            f"No Stripe price ID configured for add-on plugin '{plugin_slug}'. "
            f"Add it to KBS_STRIPE_ADDON_PRICES JSON env var."
        )

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=customer_email,
        line_items=[{"price": price_id, "quantity": 1}],
        metadata={
            "tenant_id": str(tenant_id),
            "module_slug": plugin_slug,
            "source": "kbs_addon",
        },
        subscription_data={
            "metadata": {
                "tenant_id": str(tenant_id),
                "module_slug": plugin_slug,
            },
        },
        success_url=success_url
        or f"{_BASE_URL}/marketplace?addon={plugin_slug}&status=success",
        cancel_url=cancel_url
        or f"{_BASE_URL}/marketplace?addon={plugin_slug}&status=cancelled",
    )

    logger.info(
        "Created Stripe addon checkout %s for tenant %s plugin %s",
        session.id,
        tenant_id,
        plugin_slug,
    )

    return {"url": session.url, "session_id": session.id}


def _save_subscription_checkout(
    tenant_id: int, session_id: str, tier: str
) -> None:
    """Record subscription checkout attempt in tenants metadata."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE tenants
                SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    f'{{"last_checkout_session": "{session_id}", "pending_tier": "{tier}"}}',
                    tenant_id,
                ),
            )
    except Exception:
        logger.exception(
            "Failed to save subscription checkout for tenant %s", tenant_id
        )
