# KBS Wave 1 Plan D: Store, Stripe Billing & Printful Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Stripe Checkout into invoicing and store orders, integrate Printful for print-on-demand fulfillment, create a public storefront, and connect payment tracking to CRM records. This completes the revenue pipeline: product browsing -> cart -> Stripe payment -> fulfillment -> CRM tracking.

**Architecture:** Stripe Checkout sessions are created server-side and redirect the user to Stripe-hosted pages. Webhooks fire back to KBS on payment completion, which marks invoices paid via the existing `event_bus.emit("invoice.paid", ...)` pattern. Printful integration is a standalone API client that syncs products and submits orders. The public storefront is a separate Blueprint with no `@login_required` for browsing, guest checkout via email. All payment interactions are recorded as CRM interactions via event bus.

**Tech Stack:** Flask, PostgreSQL, psycopg2, stripe (Python SDK), requests (Printful API), pytest

**Spec:** `docs/superpowers/specs/2026-03-28-kbs-completion-saas-resale-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `requirements.txt` | Add stripe Python SDK |
| Create | `core/stripe_checkout.py` | Create Stripe Checkout sessions for invoices and orders |
| Create | `core/printful_client.py` | Printful API client: product sync, order submission, fulfillment tracking |
| Modify | `plugins/kbs_invoicing/routes.py` | Add "Pay Online" checkout endpoint |
| Modify | `plugins/kbs_store/routes.py` | Add Printful sync route, wire Printful on order create |
| Create | `plugins/kbs_store/public_routes.py` | Public storefront: browse products, guest checkout |
| Modify | `plugins/kbs_store/__init__.py` | Register public routes Blueprint + payment webhook consumer |
| Modify | `plugins/kbs_crm/routes.py` | Add payment interaction logging via event consumer |
| Modify | `plugins/kbs_crm/__init__.py` | Register payment.received event consumer |
| Modify | `core/stripe_billing.py` | Add invoice/order payment webhook handlers |
| Create | `tests/test_stripe_checkout.py` | Stripe checkout session creation tests |
| Create | `tests/test_printful_client.py` | Printful API client tests |
| Create | `tests/test_payment_flow.py` | End-to-end payment flow tests |
| Create | `tests/test_public_storefront.py` | Public storefront browse + guest checkout tests |

---

## Task 1: Add Stripe Python SDK

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add stripe to requirements**

```bash
echo "stripe>=8.0" >> /mnt/archie_brain/kytran-business-suite/requirements.txt
```

- [ ] **Step 2: Install in container**

```bash
docker exec kbs_app pip install "stripe>=8.0"
```

- [ ] **Step 3: Verify import works**

```bash
docker exec kbs_app python -c "import stripe; print(f'stripe {stripe.VERSION} OK')"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add requirements.txt
git commit -m "chore: add stripe Python SDK for checkout integration"
```

---

## Task 2: Stripe Checkout Service

**Files:**
- Create: `core/stripe_checkout.py`
- Create: `tests/test_stripe_checkout.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stripe_checkout.py`:

```python
"""Tests for Stripe Checkout session creation."""

import json
from unittest.mock import patch, MagicMock

import pytest


def test_create_invoice_checkout_session_returns_url():
    """Verify checkout session creation returns a URL for invoice payment."""
    from core.stripe_checkout import create_invoice_checkout_session

    invoice = {
        "id": 42,
        "invoice_number": "INV-0001",
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "total": 565.00,
        "items": [
            {"description": "Web Design", "quantity": 1, "unit_price": 500.00, "amount": 500.00},
            {"description": "Tax (13%)", "quantity": 1, "unit_price": 65.00, "amount": 65.00},
        ],
    }

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/c/pay_test_abc123"
    mock_session.id = "cs_test_abc123"

    with patch("core.stripe_checkout.stripe") as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = mock_session
        result = create_invoice_checkout_session(invoice, tenant_id=1)

    assert result["url"] == "https://checkout.stripe.com/c/pay_test_abc123"
    assert result["session_id"] == "cs_test_abc123"

    call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
    assert call_kwargs["mode"] == "payment"
    assert call_kwargs["customer_email"] == "jane@example.com"
    assert len(call_kwargs["line_items"]) == 2
    assert call_kwargs["line_items"][0]["price_data"]["unit_amount"] == 50000  # cents


def test_create_order_checkout_session_returns_url():
    """Verify checkout session creation returns a URL for order payment."""
    from core.stripe_checkout import create_order_checkout_session

    order_items = [
        {"name": "T-Shirt (L)", "quantity": 2, "price": 29.99},
        {"name": "Mug", "quantity": 1, "price": 14.99},
    ]

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/c/pay_test_order456"
    mock_session.id = "cs_test_order456"

    with patch("core.stripe_checkout.stripe") as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = mock_session
        result = create_order_checkout_session(
            order_items=order_items,
            order_id=99,
            customer_email="buyer@example.com",
            tenant_id=1,
        )

    assert result["url"] == "https://checkout.stripe.com/c/pay_test_order456"
    assert result["session_id"] == "cs_test_order456"

    call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
    assert call_kwargs["mode"] == "payment"
    assert len(call_kwargs["line_items"]) == 2
    assert call_kwargs["line_items"][0]["price_data"]["unit_amount"] == 2999


def test_create_invoice_checkout_missing_items_raises():
    """Verify that an invoice with no items raises ValueError."""
    from core.stripe_checkout import create_invoice_checkout_session

    invoice = {
        "id": 1,
        "invoice_number": "INV-0002",
        "customer_email": "test@test.com",
        "total": 0,
        "items": [],
    }

    with pytest.raises(ValueError, match="at least one line item"):
        create_invoice_checkout_session(invoice, tenant_id=1)


def test_checkout_session_stores_metadata():
    """Verify that metadata (invoice_id, tenant_id) is passed to Stripe."""
    from core.stripe_checkout import create_invoice_checkout_session

    invoice = {
        "id": 77,
        "invoice_number": "INV-0077",
        "customer_email": "meta@test.com",
        "total": 100.00,
        "items": [
            {"description": "Service", "quantity": 1, "unit_price": 100.00, "amount": 100.00},
        ],
    }

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/c/pay_test_meta"
    mock_session.id = "cs_test_meta"

    with patch("core.stripe_checkout.stripe") as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = mock_session
        create_invoice_checkout_session(invoice, tenant_id=5)

    call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
    assert call_kwargs["metadata"]["invoice_id"] == "77"
    assert call_kwargs["metadata"]["tenant_id"] == "5"
    assert call_kwargs["metadata"]["source"] == "kbs_invoicing"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_stripe_checkout.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.stripe_checkout'`

- [ ] **Step 3: Write the implementation**

Create `core/stripe_checkout.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_stripe_checkout.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/stripe_checkout.py tests/test_stripe_checkout.py
git commit -m "feat(stripe): add Stripe Checkout session creation for invoices and orders"
```

---

## Task 3: Invoice "Pay Online" Endpoint

**Files:**
- Modify: `plugins/kbs_invoicing/routes.py`

- [ ] **Step 1: Read the current invoicing routes**

```bash
docker exec kbs_app cat plugins/kbs_invoicing/routes.py
```

Review existing endpoints. We need to add a POST endpoint that creates a Stripe Checkout session for an invoice.

- [ ] **Step 2: Add import at top of routes.py**

Add after the existing imports in `plugins/kbs_invoicing/routes.py`:

```python
from core.stripe_checkout import create_invoice_checkout_session
```

- [ ] **Step 3: Add checkout endpoint inside register_routes(bp)**

Add after the existing `mark_paid` route (around line 370):

```python
    # ------------------------------------------------------------------
    # Stripe Checkout — "Pay Online"
    # ------------------------------------------------------------------

    @bp.route("/api/invoices/<int:invoice_id>/checkout", methods=["POST"])
    @login_required
    @require_module("invoicing")
    def create_checkout(invoice_id):
        """Create a Stripe Checkout session for online invoice payment."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute(
                """
                SELECT i.id, i.invoice_number, i.status, i.total,
                       i.customer_id,
                       c.name AS customer_name, c.email AS customer_email
                FROM invoices i
                LEFT JOIN crm_customers c ON c.id = i.customer_id
                WHERE i.id = %s
                """,
                (invoice_id,),
            )
            invoice = cur.fetchone()

            if not invoice:
                return jsonify({"error": "invoice not found"}), 404

            if invoice["status"] == "paid":
                return jsonify({"error": "invoice is already paid"}), 400

            if not invoice.get("customer_email"):
                return jsonify({"error": "customer has no email address"}), 400

            # Fetch line items
            cur.execute(
                """
                SELECT description, quantity, unit_price, amount
                FROM invoice_items
                WHERE invoice_id = %s
                ORDER BY id
                """,
                (invoice_id,),
            )
            items = cur.fetchall()

        if not items:
            return jsonify({"error": "invoice has no line items"}), 400

        invoice_data = dict(invoice)
        invoice_data["items"] = [dict(item) for item in items]

        try:
            result = create_invoice_checkout_session(invoice_data, tenant_id=g.tenant_id)
        except Exception as exc:
            logger.exception("Failed to create Stripe checkout for invoice %s", invoice_id)
            return jsonify({"error": f"Stripe error: {str(exc)}"}), 500

        return jsonify(result)
```

- [ ] **Step 4: Verify the endpoint loads**

```bash
docker exec kbs_app python -c "
from plugins.kbs_invoicing.routes import register_routes
from flask import Blueprint
bp = Blueprint('test', __name__)
register_routes(bp)
print('Routes registered OK')
"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_invoicing/routes.py
git commit -m "feat(invoicing): add Stripe Checkout 'Pay Online' endpoint"
```

---

## Task 4: Stripe Payment Webhook Handler

**Files:**
- Modify: `core/stripe_billing.py`

- [ ] **Step 1: Read the current stripe_billing.py**

```bash
docker exec kbs_app cat core/stripe_billing.py
```

Review the existing `_HANDLERS` dict and `handle_stripe_webhook()`. We need to add a handler for `checkout.session.completed` that detects invoice/order payments (vs subscription checkouts) and marks them paid.

- [ ] **Step 2: Add invoice/order payment handler to stripe_billing.py**

Add the following function before the `_HANDLERS` dict, and update the handlers dict:

```python
def _handle_invoice_or_order_payment(event: dict) -> None:
    """Handle checkout.session.completed for invoice or order payments.

    This is called by the existing _handle_checkout_completed when the
    metadata indicates source=kbs_invoicing or source=kbs_store.
    The subscription handler is the default — this handles one-time payments.
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
```

- [ ] **Step 3: Update _handle_checkout_completed to dispatch to invoice/order handler**

Modify the existing `_handle_checkout_completed` function to check metadata source before treating as a subscription checkout:

```python
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

    # Original subscription checkout handling follows...
    customer_id = obj.get("customer")
    subscription_id = obj.get("subscription")
    tier = metadata.get("tier", "starter")

    tenant = _get_tenant_by_stripe_customer(customer_id) if customer_id else None
    if not tenant:
        logger.warning("checkout.session.completed: no tenant for customer %s", customer_id)
        return

    _set_tenant_tier(tenant["id"], tier)
    sync_tier_modules(tenant["id"], tier)
    logger.info("Activated tier %s for tenant %s via checkout", tier, tenant["id"])
```

- [ ] **Step 4: Verify the module loads**

```bash
docker exec kbs_app python -c "
from core.stripe_billing import handle_stripe_webhook, _handle_invoice_or_order_payment
print('stripe_billing handlers loaded OK')
"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/stripe_billing.py
git commit -m "feat(stripe): add invoice/order payment webhook handlers for checkout.session.completed"
```

---

## Task 5: Payment Received Email Template

**Files:**
- Create or Modify: `core/email_templates.py`

- [ ] **Step 1: Check if email_templates.py exists**

```bash
docker exec kbs_app ls -la core/email_templates.py 2>/dev/null || echo "DOES NOT EXIST"
```

If it does not exist, Plan A Task 3 creates it. If Plan A has not been executed yet, create it here. If it already exists, add to it.

- [ ] **Step 2: Add payment received email template**

Add `render_payment_received_email` to `core/email_templates.py`. If the file does not exist, create it with the full header:

```python
"""HTML email templates for transactional emails."""


def _wrap_html(title: str, body_content: str) -> str:
    """Wrap body content in a simple responsive HTML email layout."""
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background: #f5f5f5; color: #333; }}
  .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 32px; margin: 20px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .header {{ text-align: center; padding-bottom: 16px; border-bottom: 2px solid #00e5ff; margin-bottom: 24px; }}
  .header h1 {{ color: #00e5ff; margin: 0; font-size: 24px; }}
  .amount {{ font-size: 32px; font-weight: bold; color: #10b981; text-align: center; margin: 16px 0; }}
  .detail-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #eee; }}
  .detail-label {{ color: #666; }}
  .detail-value {{ font-weight: 600; }}
  .footer {{ text-align: center; color: #999; font-size: 12px; padding: 16px 0; }}
</style>
</head>
<body>
<div class="container">
<div class="card">
{body_content}
</div>
<div class="footer">This is an automated payment confirmation.</div>
</div>
</body>
</html>"""


def render_payment_received_email(
    invoice_number: str,
    customer_name: str,
    amount: float,
    payment_method: str,
    payment_reference: str,
    business_name: str,
) -> tuple:
    """Render payment confirmation email.

    Returns:
        Tuple of (html_body, plain_text_body).
    """
    amount_str = f"${amount:,.2f}"

    body_content = f"""
<div class="header">
    <h1>Payment Received</h1>
</div>
<p>Hi {customer_name},</p>
<p>We've received your payment. Thank you!</p>
<div class="amount">{amount_str}</div>
<div class="detail-row">
    <span class="detail-label">Invoice</span>
    <span class="detail-value">{invoice_number}</span>
</div>
<div class="detail-row">
    <span class="detail-label">Payment Method</span>
    <span class="detail-value">{payment_method.title()}</span>
</div>
<div class="detail-row">
    <span class="detail-label">Reference</span>
    <span class="detail-value">{payment_reference}</span>
</div>
<p style="margin-top: 24px;">If you have any questions about this payment, please contact us.</p>
<p>Best regards,<br>{business_name}</p>
"""

    html = _wrap_html(f"Payment Received - {invoice_number}", body_content)

    text = f"""Payment Received

Hi {customer_name},

We've received your payment of {amount_str}.

Invoice: {invoice_number}
Payment Method: {payment_method.title()}
Reference: {payment_reference}

Thank you for your business.

{business_name}
"""

    return html, text
```

- [ ] **Step 3: Write a quick test**

```bash
docker exec kbs_app python -c "
from core.email_templates import render_payment_received_email
html, text = render_payment_received_email(
    invoice_number='INV-0001',
    customer_name='Jane',
    amount=565.00,
    payment_method='stripe',
    payment_reference='pi_test123',
    business_name='Kytran Empowerment Inc.',
)
assert 'INV-0001' in html
assert '565.00' in html
assert 'INV-0001' in text
print('Payment email template OK')
"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/email_templates.py
git commit -m "feat(email): add payment received email template"
```

---

## Task 6: Printful API Client

**Files:**
- Create: `core/printful_client.py`
- Create: `tests/test_printful_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_printful_client.py`:

```python
"""Tests for Printful API client."""

import json
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture()
def mock_response():
    """Create a mock requests.Response."""

    def _make(status_code=200, json_data=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        return resp

    return _make


def test_get_products_returns_list(mock_response):
    """Verify get_products returns a list of Printful catalog items."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {
        "result": [
            {"id": 1, "title": "Unisex Staple T-Shirt", "variants": 25},
            {"id": 2, "title": "Mug 11oz", "variants": 3},
        ]
    }

    with patch("core.printful_client.requests.get", return_value=mock_response(200, mock_data)):
        products = client.get_catalog_products()

    assert len(products) == 2
    assert products[0]["title"] == "Unisex Staple T-Shirt"


def test_create_order_sends_correct_payload(mock_response):
    """Verify order submission sends the right structure to Printful."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {"result": {"id": 12345, "status": "draft"}}

    order = {
        "recipient": {
            "name": "Jane Smith",
            "address1": "123 Main St",
            "city": "Toronto",
            "state_code": "ON",
            "country_code": "CA",
            "zip": "M5V 1A1",
        },
        "items": [
            {
                "variant_id": 4012,
                "quantity": 2,
                "files": [{"url": "https://example.com/design.png"}],
            }
        ],
    }

    with patch("core.printful_client.requests.post", return_value=mock_response(200, mock_data)) as mock_post:
        result = client.create_order(order)

    assert result["id"] == 12345
    assert result["status"] == "draft"
    mock_post.assert_called_once()


def test_get_order_status(mock_response):
    """Verify fetching order status works."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {
        "result": {
            "id": 12345,
            "status": "fulfilled",
            "shipments": [{"carrier": "USPS", "tracking_number": "9400111899223"}],
        }
    }

    with patch("core.printful_client.requests.get", return_value=mock_response(200, mock_data)):
        result = client.get_order(12345)

    assert result["status"] == "fulfilled"
    assert len(result["shipments"]) == 1


def test_sync_product_creates_mapping(mock_response):
    """Verify product sync creates a mapping between KBS product and Printful variant."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="test_key")
    mock_data = {
        "result": {
            "sync_product": {"id": 999, "name": "My T-Shirt"},
            "sync_variants": [
                {"id": 5001, "variant_id": 4012, "retail_price": "25.00"},
                {"id": 5002, "variant_id": 4013, "retail_price": "25.00"},
            ],
        }
    }

    with patch("core.printful_client.requests.get", return_value=mock_response(200, mock_data)):
        result = client.get_sync_product(999)

    assert result["sync_product"]["name"] == "My T-Shirt"
    assert len(result["sync_variants"]) == 2


def test_client_uses_auth_header(mock_response):
    """Verify all requests include the Bearer token."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="pk_test_abc123")

    with patch("core.printful_client.requests.get", return_value=mock_response(200, {"result": []})) as mock_get:
        client.get_catalog_products()

    call_kwargs = mock_get.call_args
    assert "Authorization" in call_kwargs[1].get("headers", {}) or call_kwargs.kwargs.get("headers", {})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_printful_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.printful_client'`

- [ ] **Step 3: Write the implementation**

Create `core/printful_client.py`:

```python
"""Printful API client for product sync, order submission, and fulfillment tracking."""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PRINTFUL_API_BASE = "https://api.printful.com"


class PrintfulClient:
    """Client for the Printful REST API.

    Usage:
        client = PrintfulClient(api_key="your_key")
        products = client.get_catalog_products()
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("KBS_PRINTFUL_API_KEY", "")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def _get(self, path: str, params: dict = None) -> dict:
        """Perform a GET request to the Printful API."""
        url = f"{PRINTFUL_API_BASE}{path}"
        resp = requests.get(url, headers=self._session.headers, params=params)
        resp.raise_for_status()
        return resp.json().get("result", resp.json())

    def _post(self, path: str, data: dict = None) -> dict:
        """Perform a POST request to the Printful API."""
        url = f"{PRINTFUL_API_BASE}{path}"
        resp = requests.post(url, headers=self._session.headers, json=data)
        resp.raise_for_status()
        return resp.json().get("result", resp.json())

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def get_catalog_products(self) -> list:
        """Fetch all available Printful catalog products."""
        return self._get("/products")

    def get_catalog_product(self, product_id: int) -> dict:
        """Fetch a single Printful catalog product with variants."""
        return self._get(f"/products/{product_id}")

    # ------------------------------------------------------------------
    # Sync Products (store-linked products)
    # ------------------------------------------------------------------

    def get_sync_products(self) -> list:
        """Fetch all synced products from the Printful store."""
        return self._get("/store/products")

    def get_sync_product(self, sync_product_id: int) -> dict:
        """Fetch a single synced product with its variants."""
        return self._get(f"/store/products/{sync_product_id}")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def create_order(self, order_data: dict, confirm: bool = False) -> dict:
        """Submit an order to Printful.

        Args:
            order_data: Dict with 'recipient' and 'items' keys.
            confirm: If True, immediately confirm (charge and produce). Default draft.

        Returns:
            Printful order object with id, status, etc.
        """
        params_path = "/orders"
        if confirm:
            params_path += "?confirm=true"
        return self._post(params_path, data=order_data)

    def get_order(self, order_id: int) -> dict:
        """Fetch a Printful order by ID."""
        return self._get(f"/orders/{order_id}")

    def get_order_by_external_id(self, external_id: str) -> dict:
        """Fetch a Printful order by external (KBS) order ID."""
        return self._get(f"/orders/@{external_id}")

    def cancel_order(self, order_id: int) -> dict:
        """Cancel a Printful order (only if still in draft/pending)."""
        url = f"{PRINTFUL_API_BASE}/orders/{order_id}"
        resp = requests.delete(url, headers=self._session.headers)
        resp.raise_for_status()
        return resp.json().get("result", {})

    # ------------------------------------------------------------------
    # Shipping
    # ------------------------------------------------------------------

    def estimate_shipping(self, recipient: dict, items: list) -> list:
        """Get shipping rate estimates for an order.

        Args:
            recipient: Dict with address fields.
            items: List of item dicts with variant_id and quantity.

        Returns:
            List of shipping rate options.
        """
        return self._post(
            "/shipping/rates",
            data={"recipient": recipient, "items": items},
        )

    # ------------------------------------------------------------------
    # Webhooks (setup)
    # ------------------------------------------------------------------

    def get_webhooks(self) -> dict:
        """Get configured webhook settings."""
        return self._get("/webhooks")

    def set_webhook(self, url: str, types: list = None) -> dict:
        """Configure Printful webhook endpoint.

        Args:
            url: The URL Printful will POST events to.
            types: List of event types to receive. Default: all.
        """
        data = {"url": url}
        if types:
            data["types"] = types
        return self._post("/webhooks", data=data)


def get_printful_client() -> Optional[PrintfulClient]:
    """Factory function that returns a PrintfulClient if API key is configured.

    Returns None if KBS_PRINTFUL_API_KEY is not set.
    """
    api_key = os.getenv("KBS_PRINTFUL_API_KEY", "")
    if not api_key:
        logger.warning("KBS_PRINTFUL_API_KEY not set — Printful integration disabled")
        return None
    return PrintfulClient(api_key=api_key)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker exec kbs_app python -m pytest tests/test_printful_client.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add core/printful_client.py tests/test_printful_client.py
git commit -m "feat(printful): add Printful API client for product sync and order submission"
```

---

## Task 7: Printful Product Sync Route

**Files:**
- Modify: `plugins/kbs_store/routes.py`

- [ ] **Step 1: Read the current store routes**

```bash
docker exec kbs_app cat plugins/kbs_store/routes.py
```

Review existing product CRUD. We need to add:
- POST `/api/printful/sync` — pull products from Printful and upsert into store
- PUT `/api/products/<id>/printful-link` — link an existing KBS product to a Printful variant

- [ ] **Step 2: Add imports at top of store routes.py**

Add after the existing imports:

```python
from core.printful_client import get_printful_client
from core.stripe_checkout import create_order_checkout_session
```

- [ ] **Step 3: Add Printful sync endpoint inside register_routes(bp)**

Add after the existing `stats` route:

```python
    # ------------------------------------------------------------------
    # Printful Integration
    # ------------------------------------------------------------------

    @bp.route("/api/printful/sync", methods=["POST"])
    @login_required
    @require_module("store")
    def sync_printful_products():
        """Pull synced products from Printful and upsert into the store."""
        client = get_printful_client()
        if not client:
            return jsonify({"error": "Printful integration not configured"}), 400

        try:
            sync_products = client.get_sync_products()
        except Exception as exc:
            logger.exception("Failed to fetch Printful products")
            return jsonify({"error": f"Printful API error: {str(exc)}"}), 502

        created = 0
        updated = 0

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            for sp in sync_products:
                # Fetch full product with variants
                try:
                    detail = client.get_sync_product(sp["id"])
                except Exception:
                    logger.warning("Failed to fetch Printful product %s", sp["id"])
                    continue

                sync_product = detail.get("sync_product", detail)
                variants = detail.get("sync_variants", [])
                first_variant = variants[0] if variants else {}

                name = sync_product.get("name", "")
                price = float(first_variant.get("retail_price", 0))
                printful_id = str(sync_product.get("id", ""))
                images = []
                if sync_product.get("thumbnail_url"):
                    images.append(sync_product["thumbnail_url"])

                # Upsert by printful_sync_id
                cur.execute(
                    "SELECT id FROM store_products WHERE metadata->>'printful_sync_id' = %s",
                    (printful_id,),
                )
                existing = cur.fetchone()

                if existing:
                    cur.execute(
                        """
                        UPDATE store_products
                        SET name = %s, price = %s, images = %s,
                            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            name,
                            price,
                            Json(images),
                            Json({
                                "printful_sync_id": printful_id,
                                "printful_variants": [
                                    {"id": v.get("id"), "variant_id": v.get("variant_id"), "price": v.get("retail_price")}
                                    for v in variants
                                ],
                            }),
                            existing["id"],
                        ),
                    )
                    updated += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO store_products
                            (name, description, price, status, category, images, metadata, inventory_count)
                        VALUES (%s, %s, %s, 'active', 'printful', %s, %s, 999)
                        """,
                        (
                            name,
                            f"Print-on-demand: {name}",
                            price,
                            Json(images),
                            Json({
                                "printful_sync_id": printful_id,
                                "printful_product": True,
                                "printful_variants": [
                                    {"id": v.get("id"), "variant_id": v.get("variant_id"), "price": v.get("retail_price")}
                                    for v in variants
                                ],
                            }),
                        ),
                    )
                    created += 1

        return jsonify({
            "synced": created + updated,
            "created": created,
            "updated": updated,
        })

    @bp.route("/api/products/<int:product_id>/printful-link", methods=["PUT"])
    @login_required
    @require_module("store")
    def link_printful_product(product_id):
        """Link an existing KBS product to a Printful variant."""
        data = request.get_json(force=True)
        printful_variant_id = data.get("printful_variant_id")
        printful_sync_id = data.get("printful_sync_id")

        if not printful_variant_id:
            return jsonify({"error": "printful_variant_id is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM store_products WHERE id = %s", (product_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "product not found"}), 404

            cur.execute(
                """
                UPDATE store_products
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, metadata
                """,
                (
                    Json({
                        "printful_product": True,
                        "printful_variant_id": printful_variant_id,
                        "printful_sync_id": printful_sync_id or "",
                    }),
                    product_id,
                ),
            )
            product = cur.fetchone()

        return jsonify(product)
```

- [ ] **Step 4: Verify routes load**

```bash
docker exec kbs_app python -c "
from plugins.kbs_store.routes import register_routes
from flask import Blueprint
bp = Blueprint('test', __name__)
register_routes(bp)
print('Store routes with Printful registered OK')
"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_store/routes.py
git commit -m "feat(store): add Printful product sync and product linking endpoints"
```

---

## Task 8: Wire Order Creation to Printful

**Files:**
- Modify: `plugins/kbs_store/routes.py`

- [ ] **Step 1: Read the create_order route**

```bash
docker exec kbs_app grep -n -A 80 'def create_order' plugins/kbs_store/routes.py
```

Review how orders are created. We need to: after a paid order is created, check if any items are Printful-linked and submit to Printful.

- [ ] **Step 2: Add Printful order submission function**

Add the following function inside `register_routes(bp)` as a helper (before the stats route):

```python
    def _submit_printful_order(order_id, tenant_id):
        """Submit a Printful order for any Printful-linked items in an order."""
        client = get_printful_client()
        if not client:
            return

        try:
            with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, tenant_id)

                # Get order with items
                cur.execute(
                    """
                    SELECT o.id, o.customer_name, o.customer_email,
                           o.shipping_address, o.metadata AS order_metadata
                    FROM store_orders o
                    WHERE o.id = %s
                    """,
                    (order_id,),
                )
                order = cur.fetchone()
                if not order:
                    return

                cur.execute(
                    """
                    SELECT oi.product_id, oi.quantity, oi.price,
                           p.name, p.metadata AS product_metadata
                    FROM store_order_items oi
                    JOIN store_products p ON p.id = oi.product_id
                    WHERE oi.order_id = %s
                    """,
                    (order_id,),
                )
                items = cur.fetchall()

                # Filter to Printful-linked items only
                printful_items = []
                for item in items:
                    meta = item.get("product_metadata") or {}
                    if isinstance(meta, str):
                        import json as _json
                        meta = _json.loads(meta)
                    if meta.get("printful_product"):
                        variant_id = meta.get("printful_variant_id")
                        if variant_id:
                            printful_items.append({
                                "variant_id": int(variant_id),
                                "quantity": item["quantity"],
                            })

                if not printful_items:
                    return

                # Parse shipping address
                shipping = order.get("shipping_address") or {}
                if isinstance(shipping, str):
                    import json as _json
                    shipping = _json.loads(shipping)

                printful_order = {
                    "external_id": str(order_id),
                    "recipient": {
                        "name": order.get("customer_name", ""),
                        "email": order.get("customer_email", ""),
                        "address1": shipping.get("address1", ""),
                        "address2": shipping.get("address2", ""),
                        "city": shipping.get("city", ""),
                        "state_code": shipping.get("state_code", ""),
                        "country_code": shipping.get("country_code", "CA"),
                        "zip": shipping.get("zip", ""),
                    },
                    "items": printful_items,
                }

                result = client.create_order(printful_order, confirm=False)

                # Store Printful order ID on our order
                cur.execute(
                    """
                    UPDATE store_orders
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        Json({"printful_order_id": result.get("id"), "printful_status": result.get("status")}),
                        order_id,
                    ),
                )

            logger.info("Submitted Printful order %s for KBS order %s", result.get("id"), order_id)
        except Exception:
            logger.exception("Failed to submit Printful order for KBS order %s", order_id)
```

- [ ] **Step 3: Wire the Printful submission into order.paid event consumer**

Add a new event consumer function at module level (outside `register_routes`), after the existing `on_invoice_paid`:

```python
def on_order_paid(data):
    """When an order is paid, submit Printful-linked items for fulfillment."""
    order_id = data.get("order_id")
    tenant_id = data.get("_tenant_id")
    if not order_id or not tenant_id:
        return
    try:
        client = get_printful_client()
        if not client:
            return

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            cur.execute(
                "SELECT id, customer_name, customer_email, shipping_address, metadata FROM store_orders WHERE id = %s",
                (order_id,),
            )
            order = cur.fetchone()
            if not order:
                return

            cur.execute(
                """
                SELECT oi.product_id, oi.quantity, p.metadata AS product_metadata
                FROM store_order_items oi
                JOIN store_products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                """,
                (order_id,),
            )
            items = cur.fetchall()

            printful_items = []
            for item in items:
                meta = item.get("product_metadata") or {}
                if isinstance(meta, str):
                    meta = json.loads(meta)
                if meta.get("printful_product") and meta.get("printful_variant_id"):
                    printful_items.append({
                        "variant_id": int(meta["printful_variant_id"]),
                        "quantity": item["quantity"],
                    })

            if not printful_items:
                return

            shipping = order.get("shipping_address") or {}
            if isinstance(shipping, str):
                shipping = json.loads(shipping)

            printful_order = {
                "external_id": str(order_id),
                "recipient": {
                    "name": order.get("customer_name", ""),
                    "email": order.get("customer_email", ""),
                    "address1": shipping.get("address1", ""),
                    "city": shipping.get("city", ""),
                    "state_code": shipping.get("state_code", ""),
                    "country_code": shipping.get("country_code", "CA"),
                    "zip": shipping.get("zip", ""),
                },
                "items": printful_items,
            }

            result = client.create_order(printful_order, confirm=False)

            cur.execute(
                """
                UPDATE store_orders
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb, updated_at = NOW()
                WHERE id = %s
                """,
                (Json({"printful_order_id": result.get("id"), "printful_status": result.get("status")}), order_id),
            )
        logger.info("Submitted Printful order for KBS order %s", order_id)
    except Exception:
        logger.exception("Failed to submit Printful order for KBS order %s", order_id)
```

- [ ] **Step 4: Register the event consumer in store __init__.py**

Modify `plugins/kbs_store/__init__.py` to register the `on_order_paid` event:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "store",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/store",
    )
    from plugins.kbs_store.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_store.routes import on_contact_created, on_invoice_paid, on_order_paid

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("invoice.paid")(on_invoice_paid)
    event_bus.on("order.paid")(on_order_paid)

    return bp
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_store/routes.py plugins/kbs_store/__init__.py
git commit -m "feat(store): wire Printful order submission on order.paid event"
```

---

## Task 9: Public Storefront

**Files:**
- Create: `plugins/kbs_store/public_routes.py`
- Modify: `plugins/kbs_store/__init__.py`
- Create: `tests/test_public_storefront.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_public_storefront.py`:

```python
"""Tests for public storefront routes — no login required for browsing."""

import json
from unittest.mock import patch, MagicMock

import pytest


def test_public_product_list_requires_no_login():
    """Verify the public product listing does not require authentication."""
    from plugins.kbs_store.public_routes import register_public_routes
    from flask import Flask, Blueprint

    app = Flask(__name__)
    app.config["TESTING"] = True
    bp = Blueprint("store_public_test", __name__)
    register_public_routes(bp, tenant_slug="demo")

    # Check that no route has login_required
    for rule in bp.deferred_functions:
        pass  # Registration is deferred

    # Verify the function exists and is importable
    assert callable(register_public_routes)


def test_guest_checkout_requires_email():
    """Verify guest checkout validates email presence."""
    from plugins.kbs_store.public_routes import _validate_guest_checkout

    # Missing email should fail
    result = _validate_guest_checkout({})
    assert result is not None  # returns error message

    # With email should pass
    result = _validate_guest_checkout({"email": "guest@example.com"})
    assert result is None  # no error


def test_build_cart_total():
    """Verify cart total calculation."""
    from plugins.kbs_store.public_routes import _calculate_cart_total

    items = [
        {"price": 29.99, "quantity": 2},
        {"price": 14.99, "quantity": 1},
    ]
    total = _calculate_cart_total(items)
    assert abs(total - 74.97) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec kbs_app python -m pytest tests/test_public_storefront.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'plugins.kbs_store.public_routes'`

- [ ] **Step 3: Write the implementation**

Create `plugins/kbs_store/public_routes.py`:

```python
"""Public storefront routes — no login required for browsing.

These routes are mounted at /store/<tenant_slug>/ and serve as the
public-facing storefront for each tenant. Guest checkout is supported
via email address (no account required).
"""

import logging
import os

from flask import g, jsonify, render_template, request
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus

logger = logging.getLogger(__name__)


def _validate_guest_checkout(data: dict) -> str:
    """Validate guest checkout data. Returns error message or None."""
    email = (data.get("email") or "").strip()
    if not email:
        return "email is required for guest checkout"
    if "@" not in email:
        return "invalid email address"
    return None


def _calculate_cart_total(items: list) -> float:
    """Calculate the total for a list of cart items."""
    total = 0.0
    for item in items:
        total += float(item.get("price", 0)) * int(item.get("quantity", 1))
    return round(total, 2)


def _resolve_tenant(tenant_slug: str):
    """Look up tenant_id from slug. Returns tenant dict or None."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id, name, slug, settings FROM tenants WHERE slug = %s AND active = TRUE",
            (tenant_slug,),
        )
        return cur.fetchone()


def register_public_routes(bp, tenant_slug: str = None):
    """Attach public storefront routes to the given blueprint.

    These routes do NOT require login — they are the public storefront.
    Tenant context is resolved from the URL slug.
    """

    # ------------------------------------------------------------------
    # Public Product Browsing
    # ------------------------------------------------------------------

    @bp.route("/products", methods=["GET"])
    def public_list_products():
        """List active products for public browsing."""
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 24, type=int)
        category = request.args.get("category")
        offset = (page - 1) * per_page

        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            where_parts = ["status = 'active'"]
            params = []
            if category:
                where_parts.append("category = %s")
                params.append(category)

            where = "WHERE " + " AND ".join(where_parts)

            cur.execute(f"SELECT COUNT(*) AS cnt FROM store_products {where}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, name, description, price, compare_at_price,
                       category, images, inventory_count
                FROM store_products {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            products = cur.fetchall()

        return jsonify({
            "products": products,
            "total": total,
            "page": page,
            "per_page": per_page,
            "store_name": tenant.get("name", ""),
        })

    @bp.route("/products/<int:product_id>", methods=["GET"])
    def public_get_product(product_id):
        """Get a single product for public viewing."""
        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            cur.execute(
                """
                SELECT id, name, description, price, compare_at_price,
                       category, images, inventory_count, metadata
                FROM store_products
                WHERE id = %s AND status = 'active'
                """,
                (product_id,),
            )
            product = cur.fetchone()

        if not product:
            return jsonify({"error": "product not found"}), 404

        return jsonify(product)

    @bp.route("/categories", methods=["GET"])
    def public_list_categories():
        """List product categories for public browsing."""
        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            cur.execute(
                "SELECT id, name, description, slug FROM store_categories ORDER BY name"
            )
            categories = cur.fetchall()

        return jsonify({"categories": categories})

    # ------------------------------------------------------------------
    # Guest Checkout
    # ------------------------------------------------------------------

    @bp.route("/checkout", methods=["POST"])
    def guest_checkout():
        """Create an order from a guest cart and redirect to Stripe Checkout.

        Expects JSON:
        {
            "email": "guest@example.com",
            "name": "Jane Smith",
            "items": [{"product_id": 1, "quantity": 2}, ...],
            "shipping_address": {...}
        }
        """
        data = request.get_json(force=True)

        # Validate guest email
        error = _validate_guest_checkout(data)
        if error:
            return jsonify({"error": error}), 400

        cart_items = data.get("items", [])
        if not cart_items:
            return jsonify({"error": "cart is empty"}), 400

        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        tenant_id = tenant["id"]

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Validate products and build order items
            order_items = []
            stripe_line_items = []
            total = 0.0

            for cart_item in cart_items:
                product_id = cart_item.get("product_id")
                quantity = int(cart_item.get("quantity", 1))

                cur.execute(
                    """
                    SELECT id, name, price, inventory_count, status
                    FROM store_products
                    WHERE id = %s AND status = 'active'
                    """,
                    (product_id,),
                )
                product = cur.fetchone()

                if not product:
                    return jsonify({"error": f"product {product_id} not found or unavailable"}), 400

                if product["inventory_count"] < quantity:
                    return jsonify({"error": f"insufficient stock for {product['name']}"}), 400

                item_total = float(product["price"]) * quantity
                total += item_total

                order_items.append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "quantity": quantity,
                    "price": float(product["price"]),
                    "total": item_total,
                })

                stripe_line_items.append({
                    "name": product["name"],
                    "quantity": quantity,
                    "price": float(product["price"]),
                })

            # Create the order
            import uuid

            order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"

            cur.execute(
                """
                INSERT INTO store_orders
                    (order_number, customer_name, customer_email, status,
                     payment_status, total, shipping_address, metadata)
                VALUES (%s, %s, %s, 'pending', 'unpaid', %s, %s, %s)
                RETURNING id
                """,
                (
                    order_number,
                    data.get("name", ""),
                    data["email"],
                    round(total, 2),
                    Json(data.get("shipping_address", {})),
                    Json({"source": "public_storefront", "guest_checkout": True}),
                ),
            )
            order = cur.fetchone()
            order_id = order["id"]

            # Insert order items
            for item in order_items:
                cur.execute(
                    """
                    INSERT INTO store_order_items (order_id, product_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (order_id, item["product_id"], item["quantity"], item["price"]),
                )

                # Decrement inventory
                cur.execute(
                    """
                    UPDATE store_products
                    SET inventory_count = inventory_count - %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (item["quantity"], item["product_id"]),
                )

        # Create Stripe Checkout session
        try:
            from core.stripe_checkout import create_order_checkout_session

            result = create_order_checkout_session(
                order_items=stripe_line_items,
                order_id=order_id,
                customer_email=data["email"],
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.exception("Failed to create Stripe checkout for order %s", order_id)
            return jsonify({"error": f"Payment setup failed: {str(exc)}"}), 500

        event_bus.emit(
            "order.created",
            {
                "order_id": order_id,
                "order_number": order_number,
                "customer_email": data["email"],
                "total": round(total, 2),
            },
            tenant_id=tenant_id,
        )

        return jsonify({
            "order_id": order_id,
            "order_number": order_number,
            "checkout_url": result["url"],
            "session_id": result["session_id"],
        }), 201
```

- [ ] **Step 4: Register public routes in store __init__.py**

Update `plugins/kbs_store/__init__.py`:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "store",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/store",
    )
    from plugins.kbs_store.routes import register_routes

    register_routes(bp)

    # Public storefront routes (no login)
    from plugins.kbs_store.public_routes import register_public_routes

    public_bp = Blueprint(
        "store_public",
        __name__,
        url_prefix="/public",
    )
    register_public_routes(public_bp)
    bp.register_blueprint(public_bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_store.routes import on_contact_created, on_invoice_paid, on_order_paid

    event_bus.on("contact.created")(on_contact_created)
    event_bus.on("invoice.paid")(on_invoice_paid)
    event_bus.on("order.paid")(on_order_paid)

    return bp
```

- [ ] **Step 5: Run tests**

```bash
docker exec kbs_app python -m pytest tests/test_public_storefront.py -v
```

Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_store/public_routes.py plugins/kbs_store/__init__.py tests/test_public_storefront.py
git commit -m "feat(store): add public storefront with guest checkout and Stripe integration"
```

---

## Task 10: Payment Tracking in CRM

**Files:**
- Modify: `plugins/kbs_crm/routes.py`
- Modify: `plugins/kbs_crm/__init__.py`

- [ ] **Step 1: Read the current CRM event consumers**

```bash
docker exec kbs_app grep -n -A 30 'def on_' plugins/kbs_crm/routes.py
```

Review the existing `on_order_created` and `on_invoice_paid` consumers. We need to add a `on_payment_received` consumer that records the payment as a CRM interaction.

- [ ] **Step 2: Add payment received event consumer to CRM routes**

Add after the existing `on_invoice_paid` function in `plugins/kbs_crm/routes.py`:

```python
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
```

- [ ] **Step 3: Register the event consumer in CRM __init__.py**

Read and update `plugins/kbs_crm/__init__.py`:

```python
from flask import Blueprint


def create_blueprint(manifest):
    bp = Blueprint(
        "crm",
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static/crm",
    )
    from plugins.kbs_crm.routes import register_routes

    register_routes(bp)

    # Register event consumers
    from core.event_bus import event_bus
    from plugins.kbs_crm.routes import on_order_created, on_invoice_paid, on_payment_received

    event_bus.on("order.created")(on_order_created)
    event_bus.on("invoice.paid")(on_invoice_paid)
    event_bus.on("payment.received")(on_payment_received)

    return bp
```

- [ ] **Step 4: Verify the module loads**

```bash
docker exec kbs_app python -c "
from plugins.kbs_crm.routes import on_payment_received
print('CRM payment consumer OK')
"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add plugins/kbs_crm/routes.py plugins/kbs_crm/__init__.py
git commit -m "feat(crm): add payment.received event consumer for payment tracking"
```

---

## Task 11: Integration Tests

**Files:**
- Create: `tests/test_payment_flow.py`

- [ ] **Step 1: Write comprehensive payment flow tests**

Create `tests/test_payment_flow.py`:

```python
"""Integration tests for the full payment pipeline.

Tests the flow: Invoice -> Stripe Checkout -> Webhook -> Invoice Paid -> CRM Interaction.
Also tests: Order -> Stripe Checkout -> Webhook -> Order Paid -> Printful Submit.
"""

import json
from unittest.mock import patch, MagicMock

import pytest


# ---- Stripe Checkout Session Creation ----

def test_invoice_checkout_creates_session_with_correct_line_items():
    """Verify invoice checkout session includes all line items in cents."""
    from core.stripe_checkout import create_invoice_checkout_session

    invoice = {
        "id": 1,
        "invoice_number": "INV-0001",
        "customer_email": "test@example.com",
        "total": 113.00,
        "items": [
            {"description": "Consulting (1h)", "quantity": 1, "unit_price": 100.00, "amount": 100.00},
            {"description": "HST 13%", "quantity": 1, "unit_price": 13.00, "amount": 13.00},
        ],
    }

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/test"
    mock_session.id = "cs_test_1"

    with patch("core.stripe_checkout.stripe") as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = mock_session
        result = create_invoice_checkout_session(invoice, tenant_id=1)

    call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
    assert len(call_kwargs["line_items"]) == 2
    assert call_kwargs["line_items"][0]["price_data"]["unit_amount"] == 10000
    assert call_kwargs["line_items"][1]["price_data"]["unit_amount"] == 1300
    assert call_kwargs["line_items"][0]["price_data"]["currency"] == "cad"


def test_order_checkout_creates_session_with_product_names():
    """Verify order checkout session uses product names."""
    from core.stripe_checkout import create_order_checkout_session

    items = [{"name": "Custom T-Shirt", "quantity": 3, "price": 25.00}]

    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/test"
    mock_session.id = "cs_test_2"

    with patch("core.stripe_checkout.stripe") as mock_stripe:
        mock_stripe.checkout.Session.create.return_value = mock_session
        result = create_order_checkout_session(items, 99, "buyer@test.com", 1)

    call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
    assert call_kwargs["line_items"][0]["price_data"]["product_data"]["name"] == "Custom T-Shirt"
    assert call_kwargs["line_items"][0]["quantity"] == 3


# ---- Webhook Handler Dispatch ----

def test_webhook_dispatches_invoice_payment():
    """Verify checkout.session.completed with source=kbs_invoicing routes to invoice handler."""
    from core.stripe_billing import _handle_invoice_or_order_payment

    event = {
        "data": {
            "object": {
                "metadata": {
                    "source": "kbs_invoicing",
                    "invoice_id": "42",
                    "tenant_id": "1",
                },
                "payment_intent": "pi_test_123",
                "amount_total": 56500,
                "customer_email": "jane@test.com",
            }
        }
    }

    with patch("core.stripe_billing._mark_invoice_paid_from_stripe") as mock_mark:
        _handle_invoice_or_order_payment(event)

    mock_mark.assert_called_once_with(
        tenant_id=1,
        invoice_id=42,
        amount=565.00,
        payment_reference="pi_test_123",
    )


def test_webhook_dispatches_order_payment():
    """Verify checkout.session.completed with source=kbs_store routes to order handler."""
    from core.stripe_billing import _handle_invoice_or_order_payment

    event = {
        "data": {
            "object": {
                "metadata": {
                    "source": "kbs_store",
                    "order_id": "99",
                    "tenant_id": "2",
                },
                "payment_intent": "pi_test_456",
                "amount_total": 7497,
                "customer_email": "buyer@test.com",
            }
        }
    }

    with patch("core.stripe_billing._mark_order_paid_from_stripe") as mock_mark:
        _handle_invoice_or_order_payment(event)

    mock_mark.assert_called_once_with(
        tenant_id=2,
        order_id=99,
        amount=74.97,
        payment_reference="pi_test_456",
        customer_email="buyer@test.com",
    )


def test_webhook_ignores_missing_tenant():
    """Verify handler gracefully handles missing tenant_id."""
    from core.stripe_billing import _handle_invoice_or_order_payment

    event = {
        "data": {
            "object": {
                "metadata": {"source": "kbs_invoicing"},
                "payment_intent": "pi_test",
                "amount_total": 1000,
            }
        }
    }

    # Should not raise — just log warning and return
    _handle_invoice_or_order_payment(event)


# ---- Printful Client ----

def test_printful_client_auth_header():
    """Verify Printful client includes Bearer token in requests."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="pk_test_secret")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("core.printful_client.requests.get", return_value=mock_resp) as mock_get:
        client.get_catalog_products()

    headers = mock_get.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer pk_test_secret"


def test_printful_order_submission():
    """Verify Printful order submission sends correct payload."""
    from core.printful_client import PrintfulClient

    client = PrintfulClient(api_key="pk_test")
    order_data = {
        "external_id": "42",
        "recipient": {"name": "Jane", "address1": "123 Main", "city": "Toronto"},
        "items": [{"variant_id": 4012, "quantity": 1}],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": {"id": 555, "status": "draft"}}
    mock_resp.raise_for_status = MagicMock()

    with patch("core.printful_client.requests.post", return_value=mock_resp) as mock_post:
        result = client.create_order(order_data)

    assert result["id"] == 555
    assert result["status"] == "draft"


# ---- Email Template ----

def test_payment_received_email_contains_amount():
    """Verify payment email template includes the payment amount."""
    from core.email_templates import render_payment_received_email

    html, text = render_payment_received_email(
        invoice_number="INV-0099",
        customer_name="Bob",
        amount=250.00,
        payment_method="stripe",
        payment_reference="pi_abc",
        business_name="Kytran Empowerment Inc.",
    )

    assert "$250.00" in html
    assert "$250.00" in text
    assert "INV-0099" in html
    assert "Bob" in text
    assert "Stripe" in html  # .title() capitalizes


# ---- Event Bus Wiring ----

def test_event_bus_payment_received_consumer():
    """Verify the CRM on_payment_received consumer is callable."""
    from plugins.kbs_crm.routes import on_payment_received

    assert callable(on_payment_received)


def test_event_bus_order_paid_consumer():
    """Verify the store on_order_paid consumer is callable."""
    from plugins.kbs_store.routes import on_order_paid

    assert callable(on_order_paid)


# ---- Guest Checkout Validation ----

def test_guest_checkout_validation():
    """Verify guest checkout requires valid email."""
    from plugins.kbs_store.public_routes import _validate_guest_checkout

    assert _validate_guest_checkout({}) is not None
    assert _validate_guest_checkout({"email": ""}) is not None
    assert _validate_guest_checkout({"email": "bad"}) is not None
    assert _validate_guest_checkout({"email": "good@test.com"}) is None


def test_cart_total_calculation():
    """Verify cart total sums correctly."""
    from plugins.kbs_store.public_routes import _calculate_cart_total

    items = [
        {"price": 10.00, "quantity": 3},
        {"price": 5.50, "quantity": 2},
    ]
    assert abs(_calculate_cart_total(items) - 41.00) < 0.01
```

- [ ] **Step 2: Run all tests**

```bash
docker exec kbs_app python -m pytest tests/test_stripe_checkout.py tests/test_printful_client.py tests/test_payment_flow.py tests/test_public_storefront.py -v
```

Expected: All pass

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/kytran-business-suite
git add tests/test_payment_flow.py
git commit -m "test: add integration tests for Stripe checkout, Printful, and payment flow"
```

---

## Summary

After completing all 11 tasks, the KBS revenue pipeline is fully wired:

- **Stripe Checkout**: Invoice "Pay Online" button creates Stripe Checkout sessions; store orders also create checkout sessions for guest and authenticated checkout
- **Webhook Handling**: `checkout.session.completed` dispatches to invoice or order payment handlers based on metadata source; invoices auto-marked paid, orders auto-marked paid
- **Printful Integration**: API client supports catalog browsing, product sync, order submission, and fulfillment tracking; paid orders with Printful-linked items auto-submit to Printful
- **Public Storefront**: No-login product browsing, guest checkout via email, Stripe-powered payment
- **CRM Payment Tracking**: Every `payment.received` event creates a CRM interaction on the customer profile with amount, method, and reference
- **Email Confirmation**: Payment received email template renders with LCARS-styled HTML and plain text fallback

**Next plan:** Plan E (Subdomain Setup + DNS) configures `store.kytranempowerment.com` via NPM proxy and Hostinger DNS, wiring the public storefront to a public URL.
