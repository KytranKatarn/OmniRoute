"""Tests for LCARS-styled email templates."""
import pytest
from core.email_templates import (
    render_invoice_email,
    render_ticket_created_email,
    render_ticket_updated_email,
)


def test_invoice_email_template_contains_key_fields():
    html, text = render_invoice_email(
        invoice_number="INV-001",
        customer_name="Jane Smith",
        total="$250.00",
        due_date="2026-04-15",
        business_name="Acme Corp",
    )
    for content in (html, text):
        assert "INV-001" in content
        assert "Jane Smith" in content
        assert "$250.00" in content
        assert "2026-04-15" in content
        assert "Acme Corp" in content


def test_ticket_created_email_template():
    html, text = render_ticket_created_email(
        ticket_number="TKT-042",
        subject="Login issue",
        customer_name="Bob Jones",
        business_name="Beta LLC",
    )
    for content in (html, text):
        assert "TKT-042" in content
        assert "Login issue" in content


def test_ticket_updated_email_template():
    html, text = render_ticket_updated_email(
        ticket_number="TKT-099",
        subject="Billing error",
        status="in_progress",
        comment="We are looking into this now.",
        business_name="Gamma Inc",
    )
    assert "TKT-099" in html
    # status may appear as-is or title-cased
    assert ("in_progress" in html or "In_Progress" in html or "In Progress" in html)
    assert "We are looking into this now." in html
