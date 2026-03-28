"""Tests for SMS dispatch service -- RingCentral primary, Twilio fallback."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_config_ringcentral():
    """Config with RingCentral as primary SMS provider."""
    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_RINGCENTRAL_SERVER_URL = "https://platform.ringcentral.com"
    cfg.KBS_RINGCENTRAL_CLIENT_ID = "rc-cid"
    cfg.KBS_RINGCENTRAL_CLIENT_SECRET = "rc-secret"
    cfg.KBS_RINGCENTRAL_JWT_TOKEN = "rc-jwt"
    cfg.KBS_RINGCENTRAL_ACCOUNT_ID = "~"
    cfg.KBS_TWILIO_ACCOUNT_SID = ""
    cfg.KBS_TWILIO_AUTH_TOKEN = ""
    cfg.KBS_TWILIO_PHONE_NUMBER = ""
    return cfg


@pytest.fixture
def mock_config_twilio():
    """Config with Twilio as primary SMS provider."""
    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "twilio"
    cfg.KBS_RINGCENTRAL_SERVER_URL = ""
    cfg.KBS_RINGCENTRAL_CLIENT_ID = ""
    cfg.KBS_RINGCENTRAL_CLIENT_SECRET = ""
    cfg.KBS_RINGCENTRAL_JWT_TOKEN = ""
    cfg.KBS_RINGCENTRAL_ACCOUNT_ID = ""
    cfg.KBS_TWILIO_ACCOUNT_SID = "ACTEST123"
    cfg.KBS_TWILIO_AUTH_TOKEN = "tw-auth"
    cfg.KBS_TWILIO_PHONE_NUMBER = "+15550009999"
    return cfg


def test_send_sms_via_ringcentral(mock_config_ringcentral):
    from core.sms_service import _send_via_ringcentral

    mock_rc_client = MagicMock()
    mock_rc_client.send_sms.return_value = {"id": "sms-rc-1", "status": "Queued"}

    with patch("core.sms_service.RingCentralClient", return_value=mock_rc_client):
        result = _send_via_ringcentral(
            mock_config_ringcentral, "+15551112222", "Hello from RC"
        )

    assert result["external_id"] == "sms-rc-1"
    assert result["provider"] == "ringcentral"


def test_send_sms_via_twilio(mock_config_twilio):
    import core.sms_service as sms_mod
    from core.sms_service import _send_via_twilio

    mock_twilio_msg = MagicMock()
    mock_twilio_msg.sid = "SM-tw-1"
    mock_twilio_msg.status = "queued"

    mock_client_cls = MagicMock()
    mock_client_cls.return_value.messages.create.return_value = mock_twilio_msg

    # Patch the module-level global directly
    original = sms_mod.TwilioClient
    sms_mod.TwilioClient = mock_client_cls
    try:
        result = _send_via_twilio(
            mock_config_twilio, "+15551112222", "Hello from Twilio"
        )
    finally:
        sms_mod.TwilioClient = original

    assert result["external_id"] == "SM-tw-1"
    assert result["provider"] == "twilio"


def test_send_sms_records_to_database():
    """Verify send_sms creates an sms_messages record."""
    from core.sms_service import send_sms

    mock_cur = MagicMock()
    mock_conn = MagicMock()
    mock_cur.fetchone.return_value = {"id": 1}

    with (
        patch("core.sms_service.Config") as MockConfig,
        patch("core.sms_service.get_db_cursor") as mock_db,
        patch("core.sms_service._dispatch_sms") as mock_dispatch,
        patch("core.sms_service.event_bus") as mock_event_bus,
    ):
        mock_db.return_value.__enter__ = MagicMock(
            return_value=(mock_conn, mock_cur)
        )
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        cfg = MagicMock()
        cfg.KBS_SMS_PROVIDER = "ringcentral"
        MockConfig.return_value = cfg

        mock_dispatch.return_value = {
            "external_id": "ext-1",
            "provider": "ringcentral",
        }

        result = send_sms(
            to="+15551112222",
            message="Test message",
            tenant_id=1,
            customer_id=42,
        )

    # Verify INSERT was called
    insert_call = [
        c
        for c in mock_cur.execute.call_args_list
        if "INSERT INTO sms_messages" in str(c)
    ]
    assert len(insert_call) == 1


def test_send_sms_fallback_on_failure():
    """If primary provider fails, fallback to secondary."""
    from core.sms_service import _dispatch_sms

    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_TWILIO_ACCOUNT_SID = "ACTEST"
    cfg.KBS_TWILIO_AUTH_TOKEN = "tw-auth"
    cfg.KBS_TWILIO_PHONE_NUMBER = "+15550009999"

    with (
        patch(
            "core.sms_service._send_via_ringcentral",
            side_effect=Exception("RC down"),
        ),
        patch("core.sms_service._send_via_twilio") as mock_twilio,
    ):
        mock_twilio.return_value = {"external_id": "SM-fb-1", "provider": "twilio"}
        result = _dispatch_sms(cfg, "+15551112222", "Fallback test")

    assert result["provider"] == "twilio"


def test_dispatch_no_fallback_raises():
    """If primary fails and no fallback configured, raise."""
    from core.sms_service import _dispatch_sms

    cfg = MagicMock()
    cfg.KBS_SMS_PROVIDER = "ringcentral"
    cfg.KBS_TWILIO_ACCOUNT_SID = ""  # No fallback
    cfg.KBS_TWILIO_AUTH_TOKEN = ""

    with patch(
        "core.sms_service._send_via_ringcentral",
        side_effect=Exception("RC down"),
    ):
        with pytest.raises(Exception, match="RC down"):
            _dispatch_sms(cfg, "+15551112222", "No fallback")


def test_send_sms_twilio_primary(mock_config_twilio):
    """Twilio as primary provider dispatches correctly."""
    from core.sms_service import _dispatch_sms

    with patch("core.sms_service._send_via_twilio") as mock_tw:
        mock_tw.return_value = {"external_id": "SM-1", "provider": "twilio"}
        result = _dispatch_sms(mock_config_twilio, "+15551112222", "Hello")

    assert result["provider"] == "twilio"
