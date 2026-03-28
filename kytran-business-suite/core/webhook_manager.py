"""Webhook manager — register tenant webhooks, dispatch events with HMAC signing.

Webhooks are dispatched asynchronously in a background thread to avoid blocking
the event bus. Each delivery is logged to webhook_deliveries for debugging.
"""

import hashlib
import hmac
import json
import logging
import secrets
import threading

import requests

from core.database import get_db_cursor

logger = logging.getLogger(__name__)


def _compute_signature(payload_str: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    return hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()


def register_webhook(
    tenant_id: int,
    url: str,
    events: list,
) -> dict:
    """Register a new webhook for a tenant.

    Returns:
        Dict with webhook metadata including the generated secret.
    """
    from psycopg2.extras import Json

    secret = secrets.token_urlsafe(32)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO tenant_webhooks (tenant_id, url, events, secret)
            VALUES (%s, %s, %s, %s)
            RETURNING id, tenant_id, url, events, secret, is_active, created_at
            """,
            (tenant_id, url, Json(events), secret),
        )
        row = cur.fetchone()

    return row


def list_webhooks(tenant_id: int) -> list:
    """List all webhooks for a tenant."""
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, url, events, is_active, created_at
            FROM tenant_webhooks
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def delete_webhook(webhook_id: int, tenant_id: int) -> bool:
    """Delete a webhook (hard delete)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM tenant_webhooks WHERE id = %s AND tenant_id = %s RETURNING id",
            (webhook_id, tenant_id),
        )
        return cur.fetchone() is not None


def dispatch_webhooks(tenant_id: int, event_type: str, payload: dict) -> None:
    """Find matching webhooks for a tenant + event and dispatch in background.

    Matches on exact event_type or wildcard ("*").
    """
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT id, url, events, secret
            FROM tenant_webhooks
            WHERE tenant_id = %s AND is_active = TRUE
            """,
            (tenant_id,),
        )
        webhooks = cur.fetchall()

    for webhook in webhooks:
        events = webhook["events"]
        if "*" in events or event_type in events:
            # Dispatch in background thread to avoid blocking
            thread = threading.Thread(
                target=_deliver_webhook,
                args=(webhook, event_type, payload),
                daemon=True,
            )
            thread.start()


def _deliver_webhook(webhook: dict, event_type: str, payload: dict) -> None:
    """Deliver a single webhook with HMAC signature and log the result."""
    from psycopg2.extras import Json

    delivery_payload = {
        "event": event_type,
        "data": payload,
    }
    payload_str = json.dumps(delivery_payload, default=str)
    signature = _compute_signature(payload_str, webhook["secret"])

    response_code = None
    response_body = None

    try:
        resp = requests.post(
            webhook["url"],
            data=payload_str,
            headers={
                "Content-Type": "application/json",
                "X-KBS-Signature": signature,
                "X-KBS-Event": event_type,
            },
            timeout=10,
        )
        response_code = resp.status_code
        response_body = resp.text[:500]
    except Exception as exc:
        response_code = 0
        response_body = str(exc)[:500]
        logger.warning("Webhook delivery failed to %s: %s", webhook["url"], exc)

    # Log delivery
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO webhook_deliveries
                    (webhook_id, event_type, payload, response_code, response_body)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (webhook["id"], event_type, Json(delivery_payload), response_code, response_body),
            )
    except Exception:
        logger.exception("Failed to log webhook delivery")
