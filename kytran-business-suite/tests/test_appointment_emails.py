"""Tests for appointment email templates — confirmation and reminder."""

import pytest


def test_appointment_confirmation_email_contains_key_fields():
    from core.email_templates import render_appointment_confirmation_email

    html, text = render_appointment_confirmation_email(
        customer_name="Alice Johnson",
        service_name="Initial Consultation",
        appointment_date="April 1, 2026",
        appointment_time="10:00 AM",
        duration_minutes=45,
        business_name="Kytran Empowerment Inc.",
        booking_slug="kytran-emp",
    )

    assert "Alice Johnson" in html
    assert "Initial Consultation" in html
    assert "April 1, 2026" in html
    assert "10:00 AM" in html
    assert "45" in html
    assert "Kytran Empowerment" in html

    assert "Alice Johnson" in text
    assert "Initial Consultation" in text
    assert "April 1, 2026" in text
    assert "10:00 AM" in text


def test_appointment_confirmation_email_cancel_link():
    from core.email_templates import render_appointment_confirmation_email

    html, text = render_appointment_confirmation_email(
        customer_name="Bob",
        service_name="Checkup",
        appointment_date="April 2, 2026",
        appointment_time="2:00 PM",
        duration_minutes=30,
        business_name="Test Biz",
        booking_slug="test-biz",
        cancel_token="abc123",
    )

    assert "abc123" in html
    assert "cancel" in html.lower()


def test_appointment_reminder_email_contains_key_fields():
    from core.email_templates import render_appointment_reminder_email

    html, text = render_appointment_reminder_email(
        customer_name="Carol Davis",
        service_name="Follow-Up Session",
        appointment_date="April 5, 2026",
        appointment_time="3:30 PM",
        duration_minutes=60,
        business_name="Kytran Empowerment Inc.",
        hours_until=24,
    )

    assert "Carol Davis" in html
    assert "Follow-Up Session" in html
    assert "April 5, 2026" in html
    assert "3:30 PM" in html
    assert "24" in html
    assert "Kytran Empowerment" in html

    assert "Carol Davis" in text
    assert "Follow-Up Session" in text
    assert "24" in text


def test_appointment_reminder_email_pluralizes_hours():
    from core.email_templates import render_appointment_reminder_email

    html, text = render_appointment_reminder_email(
        customer_name="Dan",
        service_name="Massage",
        appointment_date="April 6, 2026",
        appointment_time="9:00 AM",
        duration_minutes=90,
        business_name="Test Spa",
        hours_until=1,
    )

    assert "1 hour" in text
    assert "1 hours" not in text
