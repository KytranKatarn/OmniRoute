"""Tests for RingCentral webhook call logging and CRM matching."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_db():
    """Mock database cursor that returns a CRM customer match."""
    mock_cur = MagicMock()
    mock_conn = MagicMock()

    # Simulate CRM customer lookup by phone
    def execute_side_effect(query, params=None):
        if params and "phone" in str(query).lower():
            mock_cur.fetchone.return_value = {
                "id": 42,
                "first_name": "Jane",
                "last_name": "Doe",
            }
        elif "INSERT INTO call_records" in str(query):
            mock_cur.fetchone.return_value = {
                "id": 1,
                "phone_number_id": None,
                "customer_id": 42,
                "direction": "inbound",
                "status": "completed",
                "duration_seconds": 120,
                "notes": None,
                "started_at": "2026-03-28T10:00:00",
                "ended_at": None,
            }

    mock_cur.execute = MagicMock(side_effect=execute_side_effect)
    return mock_conn, mock_cur


def test_parse_ringcentral_call_event():
    """Verify we extract the right fields from a RingCentral call event."""
    from plugins.kbs_communications.webhook_routes import _parse_ringcentral_call

    event_body = {
        "body": {
            "sessionId": "sess-123",
            "parties": [
                {
                    "direction": "Inbound",
                    "from": {"phoneNumber": "+15551234567"},
                    "to": {"phoneNumber": "+15559876543"},
                    "status": {"code": "Answered"},
                    "duration": 120,
                    "recording": {
                        "id": "rec-1",
                        "contentUri": "https://example.com/rec.mp3",
                    },
                }
            ],
        }
    }

    parsed = _parse_ringcentral_call(event_body)

    assert parsed["direction"] == "inbound"
    assert parsed["caller_number"] == "+15551234567"
    assert parsed["callee_number"] == "+15559876543"
    assert parsed["status"] == "completed"
    assert parsed["duration_seconds"] == 120
    assert "rec.mp3" in parsed["recording_url"]


def test_parse_ringcentral_missed_call():
    from plugins.kbs_communications.webhook_routes import _parse_ringcentral_call

    event_body = {
        "body": {
            "sessionId": "sess-456",
            "parties": [
                {
                    "direction": "Inbound",
                    "from": {"phoneNumber": "+15550001111"},
                    "to": {"phoneNumber": "+15550002222"},
                    "status": {"code": "NoAnswer"},
                    "duration": 0,
                }
            ],
        }
    }

    parsed = _parse_ringcentral_call(event_body)

    assert parsed["status"] == "missed"
    assert parsed["duration_seconds"] == 0


def test_parse_ringcentral_no_parties():
    from plugins.kbs_communications.webhook_routes import _parse_ringcentral_call

    result = _parse_ringcentral_call({"body": {"parties": []}})
    assert result is None


def test_parse_ringcentral_outbound():
    from plugins.kbs_communications.webhook_routes import _parse_ringcentral_call

    event_body = {
        "body": {
            "sessionId": "sess-789",
            "parties": [
                {
                    "direction": "Outbound",
                    "from": {"phoneNumber": "+15559876543"},
                    "to": {"phoneNumber": "+15551234567"},
                    "status": {"code": "Accepted"},
                    "duration": 60,
                }
            ],
        }
    }

    parsed = _parse_ringcentral_call(event_body)
    assert parsed["direction"] == "outbound"
    assert parsed["status"] == "completed"


def test_match_customer_by_phone(mock_db):
    from plugins.kbs_communications.webhook_routes import _match_customer_by_phone

    _, cur = mock_db
    customer_id = _match_customer_by_phone(cur, "+15551234567")
    assert customer_id == 42


def test_match_customer_no_phone():
    from plugins.kbs_communications.webhook_routes import _match_customer_by_phone

    mock_cur = MagicMock()
    result = _match_customer_by_phone(mock_cur, "")
    assert result is None


def test_match_customer_not_found():
    from plugins.kbs_communications.webhook_routes import _match_customer_by_phone

    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    result = _match_customer_by_phone(mock_cur, "+15559999999")
    assert result is None


def test_ringcentral_status_mapping():
    from plugins.kbs_communications.webhook_routes import _map_rc_status

    assert _map_rc_status("Answered") == "completed"
    assert _map_rc_status("NoAnswer") == "missed"
    assert _map_rc_status("Voicemail") == "missed"
    assert _map_rc_status("Rejected") == "failed"
    assert _map_rc_status("Unknown") == "initiated"
    assert _map_rc_status("HangUp") == "completed"
    assert _map_rc_status("Busy") == "missed"
