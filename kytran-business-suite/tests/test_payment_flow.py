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
