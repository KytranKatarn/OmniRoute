"""Tests for RingCentral API client — all HTTP calls mocked."""

import time
from unittest.mock import MagicMock, patch

import pytest


def test_get_access_token():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="test-client-id",
        client_secret="test-client-secret",
        jwt_token="test-jwt-token",
        account_id="~",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "tok-abc-123",
        "expires_in": 3600,
    }

    with patch("core.ringcentral_client.requests.post", return_value=mock_response) as mock_post:
        token = client._get_access_token()

    assert token == "tok-abc-123"
    call_data = mock_post.call_args[1].get("data", {})
    assert "jwt" in call_data.get("grant_type", "")


def test_get_access_token_cached():
    """Second call should use cached token."""
    import time

    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"
    client._token_expires_at = time.time() + 3600

    token = client._get_access_token()
    assert token == "cached-token"


def test_get_call_log():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"
    client._token_expires_at = time.time() + 3600

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "records": [
            {
                "id": "call-1",
                "direction": "Inbound",
                "from": {"phoneNumber": "+15551234567"},
                "to": {"phoneNumber": "+15559876543"},
                "duration": 120,
                "result": "Accepted",
                "startTime": "2026-03-28T10:00:00.000Z",
            }
        ],
        "paging": {"totalRecords": 1},
    }

    with patch("core.ringcentral_client.requests.get", return_value=mock_response):
        records = client.get_call_log(date_from="2026-03-27", date_to="2026-03-28")

    assert len(records) == 1
    assert records[0]["id"] == "call-1"
    assert records[0]["direction"] == "Inbound"


def test_send_sms():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"
    client._token_expires_at = time.time() + 3600

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "sms-1",
        "status": "Queued",
        "to": [{"phoneNumber": "+15551234567"}],
    }

    with patch("core.ringcentral_client.requests.post", return_value=mock_response):
        result = client.send_sms(
            from_number="+15559876543",
            to_number="+15551234567",
            message="Test SMS",
        )

    assert result["id"] == "sms-1"
    assert result["status"] == "Queued"


def test_get_sms_log():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="jwt",
        account_id="~",
    )
    client._access_token = "cached-token"
    client._token_expires_at = time.time() + 3600

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "records": [
            {
                "id": "msg-1",
                "direction": "Outbound",
                "subject": "Hello",
                "type": "SMS",
            }
        ],
    }

    with patch("core.ringcentral_client.requests.get", return_value=mock_response):
        records = client.get_sms_log(date_from="2026-03-27", date_to="2026-03-28")

    assert len(records) == 1
    assert records[0]["type"] == "SMS"


def test_auth_failure_raises():
    from core.ringcentral_client import RingCentralClient

    client = RingCentralClient(
        server_url="https://platform.ringcentral.com",
        client_id="cid",
        client_secret="csec",
        jwt_token="bad-jwt",
        account_id="~",
    )

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("core.ringcentral_client.requests.post", return_value=mock_response):
        with pytest.raises(Exception, match="401"):
            client._get_access_token()
