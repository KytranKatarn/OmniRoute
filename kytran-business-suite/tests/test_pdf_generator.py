"""Tests for Invoice PDF Generator."""
import pytest
from core.pdf_generator import generate_invoice_pdf


SAMPLE_BUSINESS = {
    "name": "Kytran Empowerment Inc.",
    "email": "billing@kytranempowerment.com",
    "phone": "+1 (555) 123-4567",
    "address": "123 Business Ave, Toronto, ON M5V 1A1",
}

SAMPLE_INVOICE = {
    "invoice_number": "INV-2026-001",
    "created_at": "2026-03-28",
    "due_date": "2026-04-28",
    "status": "pending",
    "customer_name": "Acme Corp",
    "customer_email": "accounts@acme.com",
    "notes": "Thank you for your business!",
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
            "unit_price": 200.00,
            "amount": 200.00,
        },
    ],
    "subtotal": 1700.00,
    "tax_rate": 13.0,
    "tax_amount": 221.00,
    "total": 1921.00,
}


def test_generate_invoice_pdf_returns_bytes():
    """Test that generate_invoice_pdf returns valid PDF bytes."""
    result = generate_invoice_pdf(SAMPLE_INVOICE, SAMPLE_BUSINESS)

    assert isinstance(result, bytes), "Result should be bytes"
    assert result[:4] == b"%PDF", "Result should start with %PDF-"
    assert len(result) > 100, "PDF should be larger than 100 bytes"


def test_generate_invoice_pdf_with_no_items():
    """Test that generate_invoice_pdf works with empty items list."""
    invoice = SAMPLE_INVOICE.copy()
    invoice["items"] = []
    invoice["subtotal"] = 0.00
    invoice["tax_amount"] = 0.00
    invoice["total"] = 0.00

    result = generate_invoice_pdf(invoice, SAMPLE_BUSINESS)

    assert isinstance(result, bytes), "Result should be bytes"
    assert result[:4] == b"%PDF", "Result should start with %PDF-"
    assert len(result) > 100, "PDF should be larger than 100 bytes"
