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
