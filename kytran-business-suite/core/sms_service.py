"""SMS dispatch service -- RingCentral primary with Twilio fallback.

Usage:
    from core.sms_service import send_sms
    send_sms(to="+15551234567", message="Hello", tenant_id=1, customer_id=42)
"""

import logging

from core.config import Config
from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.ringcentral_client import RingCentralClient

logger = logging.getLogger(__name__)

# Lazy import Twilio to avoid hard dependency if not installed
TwilioClient = None


def _ensure_twilio():
    global TwilioClient
    if TwilioClient is None:
        try:
            from twilio.rest import Client as _TwilioClient

            TwilioClient = _TwilioClient
        except ImportError:
            raise ImportError(
                "twilio package is required for Twilio SMS. "
                "Install it with: pip install twilio"
            )
    return TwilioClient


def _send_via_ringcentral(cfg, to_number, message):
    """Send SMS via RingCentral API.

    Args:
        cfg: Config instance with RingCentral credentials.
        to_number: Recipient phone number.
        message: SMS text.

    Returns:
        Dict with external_id and provider.
    """
    client = RingCentralClient(
        server_url=cfg.KBS_RINGCENTRAL_SERVER_URL,
        client_id=cfg.KBS_RINGCENTRAL_CLIENT_ID,
        client_secret=cfg.KBS_RINGCENTRAL_CLIENT_SECRET,
        jwt_token=cfg.KBS_RINGCENTRAL_JWT_TOKEN,
        account_id=cfg.KBS_RINGCENTRAL_ACCOUNT_ID,
    )
    result = client.send_sms(
        from_number=cfg.KBS_RINGCENTRAL_ACCOUNT_ID,
        to_number=to_number,
        message=message,
    )
    return {
        "external_id": result.get("id", ""),
        "provider": "ringcentral",
    }


def _send_via_twilio(cfg, to_number, message):
    """Send SMS via Twilio API.

    Args:
        cfg: Config instance with Twilio credentials.
        to_number: Recipient phone number.
        message: SMS text.

    Returns:
        Dict with external_id and provider.
    """
    _ensure_twilio()
    client = TwilioClient(cfg.KBS_TWILIO_ACCOUNT_SID, cfg.KBS_TWILIO_AUTH_TOKEN)
    msg = client.messages.create(
        body=message,
        from_=cfg.KBS_TWILIO_PHONE_NUMBER,
        to=to_number,
    )
    return {
        "external_id": msg.sid,
        "provider": "twilio",
    }


def _dispatch_sms(cfg, to_number, message):
    """Dispatch SMS via configured provider with automatic fallback.

    Args:
        cfg: Config instance.
        to_number: Recipient phone number.
        message: SMS text.

    Returns:
        Dict with external_id and provider.

    Raises:
        Exception: If both providers fail.
    """
    primary = cfg.KBS_SMS_PROVIDER
    fallback = "twilio" if primary == "ringcentral" else "ringcentral"

    try:
        if primary == "ringcentral":
            return _send_via_ringcentral(cfg, to_number, message)
        else:
            return _send_via_twilio(cfg, to_number, message)
    except Exception as primary_err:
        logger.warning(
            "SMS primary (%s) failed: %s -- trying fallback", primary, primary_err
        )

        # Only fallback if fallback provider is configured
        has_fallback = (
            fallback == "twilio" and cfg.KBS_TWILIO_ACCOUNT_SID
        ) or (fallback == "ringcentral" and cfg.KBS_RINGCENTRAL_CLIENT_ID)

        if not has_fallback:
            raise

        try:
            if fallback == "twilio":
                return _send_via_twilio(cfg, to_number, message)
            else:
                return _send_via_ringcentral(cfg, to_number, message)
        except Exception as fallback_err:
            logger.error(
                "SMS fallback (%s) also failed: %s", fallback, fallback_err
            )
            raise


def send_sms(to, message, tenant_id, customer_id=None):
    """Send an SMS and record it in the database.

    Args:
        to: Recipient phone number (E.164 format).
        message: Text message content.
        tenant_id: Tenant ID for schema isolation.
        customer_id: Optional CRM customer ID to associate.

    Returns:
        Dict with sms_id and delivery result.

    Raises:
        Exception: If SMS delivery fails after fallback.
    """
    cfg = Config()

    # Dispatch through provider
    result = _dispatch_sms(cfg, to, message)

    # Record in database
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO sms_messages
                (direction, phone_number, customer_id, message, status,
                 provider, external_id)
            VALUES ('outbound', %s, %s, %s, 'sent', %s, %s)
            RETURNING id
            """,
            (to, customer_id, message, result["provider"], result["external_id"]),
        )
        row = cur.fetchone()

    event_bus.emit(
        "sms.sent",
        {
            "sms_id": row["id"],
            "to": to,
            "customer_id": customer_id,
            "provider": result["provider"],
        },
        tenant_id=tenant_id,
    )

    return {"sms_id": row["id"], **result}
