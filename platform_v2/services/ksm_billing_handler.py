"""
KSM Billing Handler — Stripe webhook handlers for Kytran SysOps Manager.

Listens for checkout.session.completed, customer.subscription.updated,
and customer.subscription.deleted events scoped to KSM products.
Pushes tier changes to the standalone KSM instance via OAuth bearer auth.
"""

import base64
import logging
import os

import requests
from database import get_db_cursor

from services.billing_webhook import register_billing_handler
from services.stripe_service import (
    update_subscription_from_stripe,
)

logger = logging.getLogger(__name__)

STANDALONE_SYSOPS_URL = os.getenv("STANDALONE_SYSOPS_URL", "https://server.kytranempowerment.com")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tier_for_price(price_id):
    """Look up billing_products where module='ksm' and map price to tier.

    Derives tier from the product name:
      - name contains 'pro'        -> 'pro'
      - name contains 'enterprise' -> 'enterprise'
      - name contains 'basic'      -> 'basic'
      - fallback                   -> 'free'
    """
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT name FROM billing_products
                   WHERE module = 'ksm' AND stripe_price_id = %s
                   LIMIT 1""",
                (price_id,),
            )
            row = cur.fetchone()
            if not row:
                logger.warning("No KSM product found for price_id=%s", price_id)
                return "free"

            name = row[0].lower()
            if "enterprise" in name:
                return "enterprise"
            elif "pro" in name:
                return "pro"
            elif "basic" in name:
                return "basic"
            else:
                return "free"
    except Exception as exc:
        logger.error("Failed to look up tier for price %s: %s", price_id, exc)
        return "free"


def _get_standalone_auth():
    """Read oauth_clients for 'kytran-sysops' and build a base64 bearer header.

    Returns:
        dict with Authorization header, or empty dict on failure.
    """
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT client_id, client_secret FROM oauth_clients
                   WHERE client_id = 'kytran-sysops'
                   LIMIT 1""",
                (),
            )
            row = cur.fetchone()
            if not row:
                logger.error("OAuth client 'kytran-sysops' not found")
                return {}

            client_id, client_secret = row[0], row[1]
            token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            return {"Authorization": f"Bearer {token}"}
    except Exception as exc:
        logger.error("Failed to read OAuth credentials: %s", exc)
        return {}


def _get_user_id_for_stripe_customer(stripe_customer_id):
    """Look up billing_customers to find the user_id for a Stripe customer.

    Returns:
        int user_id or None.
    """
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT user_id FROM billing_customers
                   WHERE stripe_customer_id = %s
                   LIMIT 1""",
                (stripe_customer_id,),
            )
            row = cur.fetchone()
            if not row:
                logger.warning("No user found for stripe_customer_id=%s", stripe_customer_id)
                return None
            return row[0]
    except Exception as exc:
        logger.error(
            "Failed to look up user for customer %s: %s",
            stripe_customer_id,
            exc,
        )
        return None


def _push_tier_to_standalone(user_id, tier):
    """POST tier update to the standalone KSM instance.

    Endpoint: {STANDALONE_SYSOPS_URL}/api/billing/tier-update
    Body: {"user_id": <int>, "tier": <str>}
    Auth: Bearer token from oauth_clients.

    Returns:
        True on success, False on failure.
    """
    headers = _get_standalone_auth()
    if not headers:
        logger.error("Cannot push tier — no auth credentials")
        return False

    headers["Content-Type"] = "application/json"
    url = f"{STANDALONE_SYSOPS_URL}/dashboard/api/billing/tier-update"

    try:
        resp = requests.post(
            url,
            json={"user_id": user_id, "tier": tier},
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Pushed tier '%s' to standalone for user %s", tier, user_id)
            return True
        else:
            logger.error("Standalone tier push failed: %s %s", resp.status_code, resp.text)
            return False
    except requests.RequestException as exc:
        logger.error("Standalone tier push request failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Event Handlers
# ---------------------------------------------------------------------------


def handle_ksm_checkout_completed(event):
    """Handle checkout.session.completed for KSM subscriptions.

    Retrieves the subscription from the session, extracts the price,
    maps to a tier, and pushes to the standalone instance.
    """
    session = event["data"]["object"]
    stripe_customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not subscription_id:
        return "No subscription in checkout session — skipping"

    user_id = _get_user_id_for_stripe_customer(stripe_customer_id)
    if not user_id:
        return f"No user for customer {stripe_customer_id}"

    # Retrieve subscription to get the price
    import stripe

    try:
        sub = stripe.Subscription.retrieve(subscription_id)
    except Exception as exc:
        return f"Failed to retrieve subscription {subscription_id}: {exc}"

    if not sub.get("items", {}).get("data"):
        return "Subscription has no items"

    price_id = sub["items"]["data"][0]["price"]["id"]
    tier = _get_tier_for_price(price_id)

    # Check this is actually a KSM product
    if tier == "free":
        # Verify it's truly a KSM product, not just unmapped
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """SELECT id FROM billing_products
                       WHERE module = 'ksm' AND stripe_price_id = %s""",
                    (price_id,),
                )
                if not cur.fetchone():
                    return f"Price {price_id} is not a KSM product — skipping"
        except Exception:
            pass

    success = _push_tier_to_standalone(user_id, tier)

    # Sync to billing_subscriptions
    _sync_subscription_to_billing(sub, user_id, price_id)

    return f"KSM checkout: user={user_id} tier={tier} pushed={success}"


def handle_ksm_subscription_updated(event):
    """Handle customer.subscription.updated — detect price change, push new tier."""
    subscription = event["data"]["object"]
    stripe_customer_id = subscription.get("customer")

    user_id = _get_user_id_for_stripe_customer(stripe_customer_id)
    if not user_id:
        return f"No user for customer {stripe_customer_id}"

    items = subscription.get("items", {}).get("data", [])
    if not items:
        return "Subscription has no items"

    price_id = items[0]["price"]["id"]
    tier = _get_tier_for_price(price_id)

    # Only push if this is a KSM product
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT id FROM billing_products
                   WHERE module = 'ksm' AND stripe_price_id = %s""",
                (price_id,),
            )
            if not cur.fetchone():
                return f"Price {price_id} is not a KSM product — skipping"
    except Exception:
        pass

    success = _push_tier_to_standalone(user_id, tier)

    # Sync to billing_subscriptions
    update_subscription_from_stripe(subscription["id"], subscription)

    return f"KSM sub updated: user={user_id} tier={tier} pushed={success}"


def handle_ksm_subscription_deleted(event):
    """Handle customer.subscription.deleted — push tier='free'."""
    subscription = event["data"]["object"]
    stripe_customer_id = subscription.get("customer")

    user_id = _get_user_id_for_stripe_customer(stripe_customer_id)
    if not user_id:
        return f"No user for customer {stripe_customer_id}"

    # Verify this was a KSM subscription by checking the price
    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0]["price"]["id"]
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """SELECT id FROM billing_products
                       WHERE module = 'ksm' AND stripe_price_id = %s""",
                    (price_id,),
                )
                if not cur.fetchone():
                    return f"Price {price_id} is not a KSM product — skipping"
        except Exception:
            pass

    success = _push_tier_to_standalone(user_id, "free")

    # Sync cancellation to billing_subscriptions
    sub_id = subscription.get("id")
    if sub_id:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE billing_subscriptions
                       SET status = 'canceled', canceled_at = NOW(), updated_at = NOW()
                     WHERE stripe_subscription_id = %s""",
                    (sub_id,),
                )
        except Exception as exc:
            logger.error("Failed to mark billing_subscription canceled: %s", exc)

    return f"KSM sub deleted: user={user_id} tier=free pushed={success}"


# ---------------------------------------------------------------------------
# Billing sync helper
# ---------------------------------------------------------------------------


def _sync_subscription_to_billing(stripe_sub, user_id, price_id):
    """Create or update billing_subscriptions from a Stripe subscription object."""
    from datetime import datetime, timezone

    def _ts(val):
        return datetime.fromtimestamp(val, tz=timezone.utc) if val else None

    sub_id = stripe_sub.get("id") or stripe_sub.id
    status = stripe_sub.get("status", "active")
    cycle = "year" if stripe_sub.get("plan", {}).get("interval") == "year" else "month"

    try:
        # Look up billing_customer_id
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM billing_customers WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            billing_customer_id = row[0] if row else None

        if not billing_customer_id:
            logger.warning("No billing_customer for user %s — skipping sync", user_id)
            return

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO billing_subscriptions
                       (user_id, billing_customer_id, stripe_subscription_id,
                        stripe_price_id, module, status, billing_cycle,
                        current_period_start, current_period_end,
                        cancel_at_period_end, trial_start, trial_end,
                        created_at, updated_at)
                   VALUES (%s, %s, %s, %s, 'ksm', %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                   ON CONFLICT (stripe_subscription_id) DO UPDATE
                   SET status = EXCLUDED.status,
                       current_period_start = EXCLUDED.current_period_start,
                       current_period_end = EXCLUDED.current_period_end,
                       cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                       updated_at = NOW()
                """,
                (
                    user_id,
                    billing_customer_id,
                    sub_id,
                    price_id,
                    status,
                    cycle,
                    _ts(stripe_sub.get("current_period_start")),
                    _ts(stripe_sub.get("current_period_end")),
                    stripe_sub.get("cancel_at_period_end", False),
                    _ts(stripe_sub.get("trial_start")),
                    _ts(stripe_sub.get("trial_end")),
                ),
            )
        logger.info("Synced billing_subscription for stripe_sub=%s user=%s", sub_id, user_id)
    except Exception as exc:
        logger.error("Failed to sync billing_subscription: %s", exc)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_ksm_billing_handlers():
    """Register KSM webhook handlers with the billing dispatcher.

    Uses longest-prefix matching:
      - checkout.session.completed -> handle_ksm_checkout_completed
      - customer.subscription.updated -> handle_ksm_subscription_updated
      - customer.subscription.deleted -> handle_ksm_subscription_deleted
    """
    register_billing_handler("checkout.session.completed", handle_ksm_checkout_completed)
    register_billing_handler("customer.subscription.updated", handle_ksm_subscription_updated)
    register_billing_handler("customer.subscription.deleted", handle_ksm_subscription_deleted)
    logger.info("KSM billing handlers registered")
