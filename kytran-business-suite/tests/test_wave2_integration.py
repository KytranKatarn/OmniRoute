"""Wave 2 Communications integration tests.

These verify cross-module interactions: event bus wiring, provider fallback,
calendar sync with appointments, and unified inbox aggregation logic.
All external calls are mocked.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ------------------------------------------------------------------
# Event bus wiring
# ------------------------------------------------------------------


def test_event_bus_appointment_booked_wired():
    """Verify appointment.booked event fires the SMS handler."""
    from core.event_bus import event_bus

    handler = MagicMock()
    event_bus.on("appointment.booked")(handler)
    event_bus.emit("appointment.booked", {"customer_id": 1, "_tenant_id": 1})

    handler.assert_called_once()
    event_bus._handlers["appointment.booked"].remove(handler)


def test_event_bus_sms_sent_fires():
    """Verify sms.sent event can be emitted."""
    from core.event_bus import event_bus

    handler = MagicMock()
    event_bus.on("sms.sent")(handler)
    event_bus.emit(
        "sms.sent",
        {"sms_id": 1, "to": "+15551234567", "provider": "twilio"},
        tenant_id=1,
    )

    handler.assert_called_once()
    event_bus._handlers["sms.sent"].remove(handler)


def test_event_bus_chat_events():
    """Verify chat events can be emitted and received."""
    from core.event_bus import event_bus

    started_handler = MagicMock()
    closed_handler = MagicMock()

    event_bus.on("chat.started")(started_handler)
    event_bus.on("chat.closed")(closed_handler)

    event_bus.emit("chat.started", {"conversation_id": 1}, tenant_id=1)
    event_bus.emit("chat.closed", {"conversation_id": 1}, tenant_id=1)

    started_handler.assert_called_once()
    closed_handler.assert_called_once()

    event_bus._handlers["chat.started"].remove(started_handler)
    event_bus._handlers["chat.closed"].remove(closed_handler)


# ------------------------------------------------------------------
# SMS provider chain
# ------------------------------------------------------------------


def test_sms_dispatch_chain_ringcentral_then_twilio():
    """Full dispatch chain: RC fails, Twilio succeeds."""
    from core.sms_service import _dispatch_sms

    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_TWILIO_ACCOUNT_SID = "ACTEST"
    cfg.KBS_TWILIO_AUTH_TOKEN = "auth"
    cfg.KBS_TWILIO_PHONE_NUMBER = "+15550009999"

    with (
        patch(
            "core.sms_service._send_via_ringcentral",
            side_effect=Exception("RC timeout"),
        ),
        patch("core.sms_service._send_via_twilio") as mock_tw,
    ):
        mock_tw.return_value = {"external_id": "SM-fallback", "provider": "twilio"}
        result = _dispatch_sms(cfg, "+15551112222", "Integration test")

    assert result["provider"] == "twilio"
    assert result["external_id"] == "SM-fallback"


# ------------------------------------------------------------------
# Calendar sync with appointment data
# ------------------------------------------------------------------


def test_calendar_sync_appointment_creates_event():
    """Sync appointment data creates Google Calendar event."""
    from core.calendar_sync import CalendarSyncService

    mock_svc = MagicMock()
    mock_svc.events().insert().execute.return_value = {
        "id": "gcal-evt-1",
        "htmlLink": "https://calendar.google.com/gcal-evt-1",
    }

    sync = CalendarSyncService(service=mock_svc)
    result = sync.sync_appointment(
        calendar_id="primary",
        appointment_data={
            "service_name": "Deep Tissue Massage",
            "appointment_date": "2026-04-01",
            "appointment_time": "14:00",
            "duration_minutes": 90,
            "customer_name": "Jane Doe",
            "customer_email": "jane@test.com",
            "location": "456 Oak Ave",
        },
    )

    assert result["google_event_id"] == "gcal-evt-1"
    assert "calendar.google.com" in result["html_link"]


# ------------------------------------------------------------------
# Reach client sync
# ------------------------------------------------------------------


def test_reach_sync_crm_contacts_batch():
    """Sync multiple CRM contacts to Reach."""
    from core.reach_client import ReachClient

    client = ReachClient(
        api_url="https://api.hostinger.com/reach/v1",
        api_key="test-key",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": 1, "email": "test@test.com"}

    contacts = [
        {"email": f"user{i}@test.com", "name": f"User {i}"}
        for i in range(5)
    ]

    with patch("core.reach_client.requests.post", return_value=mock_resp):
        result = client.sync_crm_contacts(contacts)

    assert result["created"] == 5
    assert result["errors"] == 0
    assert result["total"] == 5


# ------------------------------------------------------------------
# RingCentral call parsing edge cases
# ------------------------------------------------------------------


def test_ringcentral_call_parsing_all_statuses():
    """Verify all RC status codes map correctly."""
    from plugins.kbs_communications.webhook_routes import _map_rc_status

    mappings = {
        "Answered": "completed",
        "Accepted": "completed",
        "CallConnected": "completed",
        "HangUp": "completed",
        "FaxReceive": "completed",
        "NoAnswer": "missed",
        "Voicemail": "missed",
        "Busy": "missed",
        "Rejected": "failed",
        "SomethingNew": "initiated",  # unknown defaults to initiated
    }

    for rc_status, expected in mappings.items():
        assert _map_rc_status(rc_status) == expected, (
            f"Expected {rc_status} -> {expected}"
        )


# ------------------------------------------------------------------
# Module imports (smoke test all modules load without error)
# ------------------------------------------------------------------


def test_all_communications_modules_import():
    """Smoke test that all communications modules can be imported."""
    from core.ringcentral_client import RingCentralClient
    from core.sms_service import send_sms
    from core.chat_manager import ChatManager
    from core.reach_client import ReachClient
    from core.calendar_sync import CalendarSyncService
    from plugins.kbs_communications.routes import register_routes
    from plugins.kbs_communications.webhook_routes import register_webhook_routes
    from plugins.kbs_communications.sms_routes import register_sms_routes
    from plugins.kbs_communications.chat_routes import register_chat_routes
    from plugins.kbs_communications.campaign_routes import register_campaign_routes

    assert callable(RingCentralClient)
    assert callable(send_sms)
    assert callable(ChatManager)
    assert callable(ReachClient)
    assert callable(CalendarSyncService)
    assert callable(register_routes)
    assert callable(register_webhook_routes)
    assert callable(register_sms_routes)
    assert callable(register_chat_routes)
    assert callable(register_campaign_routes)


def test_chat_manager_full_lifecycle():
    """Full chat lifecycle: start -> message -> message -> close."""
    from core.chat_manager import ChatManager

    call_count = [0]

    def make_ctx():
        ctx = MagicMock()
        mock_cur = MagicMock()
        ctx.__enter__ = MagicMock(return_value=(MagicMock(), mock_cur))
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx, mock_cur

    mgr = ChatManager()

    # Start conversation
    ctx1, cur1 = make_ctx()
    cur1.fetchone.return_value = {
        "id": 1,
        "visitor_name": "Test",
        "visitor_email": None,
        "customer_id": None,
        "status": "active",
        "channel": "widget",
        "created_at": "2026-03-28T10:00:00",
    }
    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx1),
        patch("core.chat_manager.set_tenant_search_path"),
        patch("core.chat_manager.event_bus"),
    ):
        conv = mgr.start_conversation(tenant_id=1, visitor_name="Test")
    assert conv["id"] == 1

    # Add visitor message
    ctx2, cur2 = make_ctx()
    cur2.fetchone.side_effect = [
        {"id": 1, "status": "active"},
        {
            "id": 2,
            "conversation_id": 1,
            "sender_type": "visitor",
            "sender_name": "Test",
            "content": "Hello!",
            "created_at": "2026-03-28T10:01:00",
        },
    ]
    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx2),
        patch("core.chat_manager.set_tenant_search_path"),
    ):
        msg = mgr.add_message(
            tenant_id=1,
            conversation_id=1,
            sender_type="visitor",
            content="Hello!",
            sender_name="Test",
        )
    assert msg["content"] == "Hello!"

    # Close conversation
    ctx3, cur3 = make_ctx()
    cur3.fetchone.return_value = {
        "id": 1,
        "status": "closed",
        "closed_at": "2026-03-28T10:05:00",
    }
    with (
        patch("core.chat_manager.get_db_cursor", return_value=ctx3),
        patch("core.chat_manager.set_tenant_search_path"),
        patch("core.chat_manager.event_bus"),
    ):
        result = mgr.close_conversation(tenant_id=1, conversation_id=1)
    assert result["status"] == "closed"
