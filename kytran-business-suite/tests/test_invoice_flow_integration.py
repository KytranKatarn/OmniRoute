"""Integration tests: full invoice PDF + email pipeline, and inbound email → ticket."""


def test_invoice_pdf_generation_with_real_data():
    """Test the full PDF pipeline with realistic data."""
    from core.pdf_generator import generate_invoice_pdf
    from core.email_templates import render_invoice_email

    invoice = {
        "invoice_number": "INV-0100",
        "created_at": "2026-03-28T14:30:00",
        "due_date": "2026-04-28",
        "status": "sent",
        "customer_name": "Acme Construction Ltd.",
        "customer_email": "billing@acme.ca",
        "notes": "Net 30 terms. Late fees of 1.5% per month apply.",
        "items": [
            {"description": "Foundation inspection — 123 Main St", "quantity": 1, "unit_price": 350.00, "amount": 350.00},
            {"description": "Electrical panel review", "quantity": 2, "unit_price": 175.00, "amount": 350.00},
            {"description": "HVAC commissioning report", "quantity": 1, "unit_price": 500.00, "amount": 500.00},
        ],
        "subtotal": 1200.00,
        "tax_rate": 13.0,
        "tax_amount": 156.00,
        "total": 1356.00,
    }
    business = {
        "name": "Kytran Empowerment Inc.",
        "email": "billing@kytranempowerment.com",
        "phone": "(613) 555-0199",
        "address": "Ottawa, ON, Canada",
    }

    pdf_bytes = generate_invoice_pdf(invoice, business)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 500

    html, text = render_invoice_email(
        invoice_number="INV-0100",
        customer_name="Acme Construction Ltd.",
        total=1356.00,
        due_date="April 28, 2026",
        business_name="Kytran Empowerment Inc.",
    )
    assert "INV-0100" in html
    assert "$1,356.00" in html or "$1356.00" in html
    assert "Acme Construction" in text


def test_inbound_email_to_ticket_pipeline():
    """Test email parsing → ticket data extraction."""
    from core.inbound_email import parse_inbound_email

    raw = {
        "from": "Sarah Chen <sarah@acme.ca>",
        "subject": "Urgent: Invoice discrepancy on INV-0100",
        "body_plain": "Hi, I noticed the HVAC commissioning was billed at $500 but our contract says $450.",
    }
    parsed = parse_inbound_email(raw)
    assert parsed["sender_email"] == "sarah@acme.ca"
    assert parsed["sender_name"] == "Sarah Chen"
    assert "Invoice discrepancy" in parsed["subject"]
    assert "HVAC commissioning" in parsed["body"]
    assert parsed["is_reply"] is False

    reply = {
        "from": "sarah@acme.ca",
        "subject": "Re: HD-0001: Urgent: Invoice discrepancy on INV-0100",
        "body_plain": "Thanks for looking into this!",
    }
    parsed_reply = parse_inbound_email(reply)
    assert parsed_reply["is_reply"] is True
    assert parsed_reply["ticket_number"] == "HD-0001"
