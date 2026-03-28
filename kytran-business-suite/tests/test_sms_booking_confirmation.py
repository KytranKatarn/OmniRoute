"""Tests for SMS booking confirmation event handlers."""

from unittest.mock import MagicMock, patch

import pytest


def test_on_appointment_booked_sends_sms():
    """Verify SMS is sent when appointment.booked event fires."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(mock_conn, mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)

    mock_cur.fetchone.return_value = {
        "phone": "+15551234567",
        "first_name": "Jane",
        "last_name": "Doe",
    }

    with (
        patch("plugins.kbs_communications.routes.get_db_cursor", return_value=ctx),
        patch("plugins.kbs_communications.routes.set_tenant_search_path"),
        patch("plugins.kbs_communications.routes.send_sms") as mock_sms,
    ):
        on_appointment_booked(
            {
                "customer_id": 42,
                "_tenant_id": 1,
                "service_name": "Haircut",
                "appointment_date": "2026-03-28",
                "appointment_time": "10:00 AM",
            }
        )

    mock_sms.assert_called_once()
    call_kwargs = mock_sms.call_args[1]
    assert call_kwargs["to"] == "+15551234567"
    assert "Haircut" in call_kwargs["message"]
    assert "2026-03-28" in call_kwargs["message"]
    assert call_kwargs["tenant_id"] == 1
    assert call_kwargs["customer_id"] == 42


def test_on_appointment_booked_no_phone():
    """Should skip SMS if customer has no phone number."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {
        "phone": None,
        "first_name": "Bob",
        "last_name": "Smith",
    }

    with (
        patch("plugins.kbs_communications.routes.get_db_cursor", return_value=ctx),
        patch("plugins.kbs_communications.routes.set_tenant_search_path"),
        patch("plugins.kbs_communications.routes.send_sms") as mock_sms,
    ):
        on_appointment_booked(
            {"customer_id": 43, "_tenant_id": 1, "service_name": "Facial"}
        )

    mock_sms.assert_not_called()


def test_on_appointment_booked_no_customer():
    """Should skip if customer not found."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = None

    with (
        patch("plugins.kbs_communications.routes.get_db_cursor", return_value=ctx),
        patch("plugins.kbs_communications.routes.set_tenant_search_path"),
        patch("plugins.kbs_communications.routes.send_sms") as mock_sms,
    ):
        on_appointment_booked({"customer_id": 999, "_tenant_id": 1})

    mock_sms.assert_not_called()


def test_on_appointment_booked_missing_data():
    """Should return early if customer_id or tenant_id is missing."""
    from plugins.kbs_communications.routes import on_appointment_booked

    with patch("plugins.kbs_communications.routes.send_sms") as mock_sms:
        on_appointment_booked({"customer_id": None, "_tenant_id": 1})
        on_appointment_booked({"customer_id": 42, "_tenant_id": None})
        on_appointment_booked({})

    mock_sms.assert_not_called()


def test_on_appointment_cancelled_sends_sms():
    """Verify SMS is sent when appointment is cancelled."""
    from plugins.kbs_communications.routes import on_appointment_cancelled

    mock_cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {
        "phone": "+15559876543",
        "first_name": "Bob",
    }

    with (
        patch("plugins.kbs_communications.routes.get_db_cursor", return_value=ctx),
        patch("plugins.kbs_communications.routes.set_tenant_search_path"),
        patch("plugins.kbs_communications.routes.send_sms") as mock_sms,
    ):
        on_appointment_cancelled(
            {
                "customer_id": 43,
                "_tenant_id": 1,
                "service_name": "Massage",
            }
        )

    mock_sms.assert_called_once()
    call_kwargs = mock_sms.call_args[1]
    assert call_kwargs["to"] == "+15559876543"
    assert "cancelled" in call_kwargs["message"]
    assert "Massage" in call_kwargs["message"]


def test_on_appointment_cancelled_no_phone():
    """Should skip if customer has no phone."""
    from plugins.kbs_communications.routes import on_appointment_cancelled

    mock_cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {"phone": "", "first_name": "Alice"}

    with (
        patch("plugins.kbs_communications.routes.get_db_cursor", return_value=ctx),
        patch("plugins.kbs_communications.routes.set_tenant_search_path"),
        patch("plugins.kbs_communications.routes.send_sms") as mock_sms,
    ):
        on_appointment_cancelled({"customer_id": 44, "_tenant_id": 1})

    mock_sms.assert_not_called()


def test_on_appointment_booked_sms_failure_logged():
    """SMS failure should be caught and logged, not crash."""
    from plugins.kbs_communications.routes import on_appointment_booked

    mock_cur = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
    ctx.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {
        "phone": "+15551234567",
        "first_name": "Jane",
        "last_name": "Doe",
    }

    with (
        patch("plugins.kbs_communications.routes.get_db_cursor", return_value=ctx),
        patch("plugins.kbs_communications.routes.set_tenant_search_path"),
        patch(
            "plugins.kbs_communications.routes.send_sms",
            side_effect=Exception("SMS provider down"),
        ),
    ):
        # Should not raise
        on_appointment_booked(
            {
                "customer_id": 42,
                "_tenant_id": 1,
                "service_name": "Haircut",
                "appointment_date": "2026-03-28",
                "appointment_time": "10:00",
            }
        )
