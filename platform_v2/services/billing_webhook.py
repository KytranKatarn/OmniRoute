"""
Billing Webhook Handler — Stripe webhook verification + fan-out event dispatcher.

Verifies Stripe signatures, enforces idempotency via billing_events table,
and dispatches events to registered handlers by longest-prefix match.
"""

import json
import logging

import stripe
from database import get_db_cursor
from psycopg2.extras import Json

from services.stripe_service import get_webhook_secret

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handler registry — modules register at startup via register_billing_handler
# ---------------------------------------------------------------------------
_handlers = {}


def register_billing_handler(event_prefix, handler_fn):
    """Register a handler for a Stripe event prefix.

    Args:
        event_prefix: e.g. "invoice.payment_succeeded" or "customer.subscription"
        handler_fn:   callable(event) -> str  (returns a short result description)
    """
    _handlers[event_prefix] = handler_fn
    logger.info("Registered billing handler for prefix '%s'", event_prefix)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def verify_and_construct_event(payload, sig_header):
    """Verify Stripe webhook signature and construct the event object.

    Returns:
        (event, None) on success or (None, error_string) on failure.
    """
    secret = get_webhook_secret()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        return event, None
    except stripe.error.SignatureVerificationError as exc:
        logger.warning("Stripe signature verification failed: %s", exc)
        return None, f"Signature verification failed: {exc}"
    except Exception as exc:
        logger.error("Unexpected error constructing Stripe event: %s", exc)
        return None, f"Event construction error: {exc}"


# ---------------------------------------------------------------------------
# Fan-out dispatcher — longest prefix match
# ---------------------------------------------------------------------------


def dispatch_event(event):
    """Dispatch a verified Stripe event to the best-matching handler.

    Matching uses longest-prefix on ``event["type"]``.

    Returns:
        Result string from the handler, or a fallback message if no handler matched.
    """
    event_type = event.get("type", "")

    # Sort candidate prefixes by length descending so we match most specific first
    matched_prefix = None
    for prefix in sorted(_handlers.keys(), key=len, reverse=True):
        if event_type.startswith(prefix):
            matched_prefix = prefix
            break

    if matched_prefix is None:
        msg = f"No handler registered for event type '{event_type}'"
        logger.info(msg)
        return msg

    handler_fn = _handlers[matched_prefix]
    try:
        result = handler_fn(event)
        logger.info("Handler '%s' processed '%s': %s", matched_prefix, event_type, result)
        return result
    except Exception as exc:
        logger.error(
            "Handler '%s' raised an exception for '%s': %s",
            matched_prefix,
            event_type,
            exc,
        )
        return f"Handler error: {exc}"


# ---------------------------------------------------------------------------
# Full webhook pipeline
# ---------------------------------------------------------------------------


def process_webhook(payload, sig_header):
    """End-to-end webhook processing pipeline.

    1. Verify Stripe signature
    2. Idempotency check (skip duplicate stripe_event_id)
    3. Log event to billing_events (processed=False)
    4. Dispatch to registered handler
    5. Update billing_events with result
    6. Always return 200 to Stripe (prevent retry floods)

    Returns:
        (status_code, response_dict)
    """
    # --- 1. Verify signature ---
    event, error = verify_and_construct_event(payload, sig_header)
    if error:
        # Still return 200 so Stripe doesn't retry bad signatures endlessly
        logger.warning("Webhook signature error — returning 200 anyway: %s", error)
        return 200, {"status": "error", "message": error}

    stripe_event_id = event.get("id", "")
    event_type = event.get("type", "")
    event_data = json.loads(json.dumps(event.get("data", {})))

    # --- 2. Idempotency check ---
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM billing_events WHERE stripe_event_id = %s",
                (stripe_event_id,),
            )
            if cur.fetchone():
                logger.info("Duplicate webhook event %s — skipping", stripe_event_id)
                return 200, {"status": "duplicate", "event_id": stripe_event_id}
    except Exception as exc:
        logger.error("Idempotency check failed: %s", exc)
        return 200, {"status": "error", "message": f"DB check failed: {exc}"}

    # --- 3. Log event (processed=False) ---
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO billing_events
                       (stripe_event_id, event_type, data, processed, handler_result)
                   VALUES (%s, %s, %s, FALSE, NULL)""",
                (stripe_event_id, event_type, Json(event_data)),
            )
    except Exception as exc:
        logger.error("Failed to log billing event %s: %s", stripe_event_id, exc)
        return 200, {"status": "error", "message": f"Event logging failed: {exc}"}

    # --- 4. Dispatch to handler ---
    result = dispatch_event(event)

    # --- 5. Mark processed ---
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE billing_events
                      SET processed = TRUE, handler_result = %s
                    WHERE stripe_event_id = %s""",
                (result, stripe_event_id),
            )
    except Exception as exc:
        logger.error("Failed to update billing event %s result: %s", stripe_event_id, exc)

    # --- 6. Always 200 ---
    return 200, {"status": "ok", "event_id": stripe_event_id, "result": result}
