"""Tests for PDF invoice generator."""

import pytest
from core.pdf_generator import generate_invoice_pdf


SAMPLE_BUSINESS = {
    "name": "Kytran Empowerment Inc.",
    "email": "billing@kytranempowerment.com",
    "phone": "+1 (555) 123-4567",
    "address": "123 Main Street, Toronto, ON M5V 1A1",
}

SAMPLE_INVOICE = {
    "invoice_number": "INV-2026-0042",
    "created_at": "2026-03-28T00:00:00",
    "due_date": "2026-04-28T00:00:00",
    "status": "unpaid",
    "customer_name": "Acme Corp",
    "customer_email": "accounts@acme.com",
    "notes": "Net 30 payment terms. Thank you for your business.",
    "items": [
        {
            "description": "Web Development Services",
            "quantity": 10,
            "unit_price": 150.00,
            "amount": 1500.00,
        },
        {
            "description": "Monthly Maintenance",
            "quantity": 1,
            "unit_price": 250.00,
            "amount": 250.00,
        },
    ],
    "subtotal": 1750.00,
    "tax_rate": 13.0,
    "tax_amount": 227.50,
    "total": 1977.50,
}


def test_generate_invoice_pdf_returns_bytes():
    """Full invoice with 2 items returns valid PDF bytes."""
    result = generate_invoice_pdf(SAMPLE_INVOICE, SAMPLE_BUSINESS)
    assert isinstance(result, bytes), "Result must be bytes"
    assert result[:4] == b"%PDF", "Result must start with %PDF"
    assert len(result) > 100, "PDF must be non-trivially sized"


def test_generate_invoice_pdf_with_no_items():
    """Invoice with empty items list still produces a valid PDF."""
    invoice = dict(SAMPLE_INVOICE)
    invoice["items"] = []
    invoice["subtotal"] = 0.0
    invoice["tax_amount"] = 0.0
    invoice["total"] = 0.0

    result = generate_invoice_pdf(invoice, SAMPLE_BUSINESS)
    assert isinstance(result, bytes), "Result must be bytes"
    assert result[:4] == b"%PDF", "Empty-items invoice must still produce valid PDF"
    assert len(result) > 100, "PDF must be non-trivially sized"
