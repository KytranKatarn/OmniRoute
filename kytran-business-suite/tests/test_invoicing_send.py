"""Tests for invoice PDF generation and email template rendering."""


def test_generate_invoice_pdf_from_db_data():
    """Verify PDF generation works with DB-shaped data."""
    from core.pdf_generator import generate_invoice_pdf

    invoice = {
        "invoice_number": "INV-0001",
        "created_at": "2026-03-28T10:00:00",
        "due_date": "2026-04-28",
        "status": "sent",
        "customer_name": "Jane Smith",
        "customer_email": "jane@example.com",
        "notes": "Thanks",
        "subtotal": 500.00,
        "tax_rate": 13.0,
        "tax_amount": 65.00,
        "total": 565.00,
        "items": [
            {
                "description": "Consulting",
                "quantity": 5,
                "unit_price": 100.00,
                "amount": 500.00,
            }
        ],
    }
    business = {
        "name": "Test Biz",
        "email": "test@test.com",
        "phone": "",
        "address": "",
    }
    pdf = generate_invoice_pdf(invoice, business)
    assert pdf[:5] == b"%PDF-"


def test_render_invoice_email_template():
    from core.email_templates import render_invoice_email

    html, text = render_invoice_email(
        "INV-0001", "Jane Smith", 565.00, "April 28, 2026", "Kytran Empowerment Inc."
    )
    assert "INV-0001" in html
    assert "$565.00" in html
    assert "INV-0001" in text
