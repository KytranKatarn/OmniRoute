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
