"""
Bundle Checkout Service
=======================
Watch Series cross-product bundle pricing: watch_bundle ($12.99 CAD/mo)
and intelligence_bundle ($19.99 CAD/mo).

Bundles live in the archie PostgreSQL DB (billing_bundle_products).
Tier sync for WTF and Watch products happens via OAuth /oauth/userinfo
entitlements on next login — no direct write to WTF SQLite from here.
"""

import logging
import os

import stripe

from database import get_db_cursor

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

BUNDLE_CATALOG = {
    "watch_bundle": {
        "name": "Watch Bundle",
        "description": "Civic Watch + Legal Watch + Gov Watch + Market Watch",
        "price_cad": 12.99,
        "stripe_price_env": "WTF_STRIPE_PRICE_WATCH_BUNDLE",
    },
    "intelligence_bundle": {
        "name": "Intelligence Bundle",
        "description": "All Watch products + What The Fact Starter",
        "price_cad": 19.99,
        "stripe_price_env": "WTF_STRIPE_PRICE_INTELLIGENCE_BUNDLE",
    },
}


def get_bundle_products(bundle_id: str) -> list[str]:
    """Return list of product_id strings for a given bundle_id."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT product_id FROM billing_bundle_products WHERE bundle_id = %s ORDER BY product_id",
                (bundle_id,),
            )
            rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception:
        logger.exception("bundle_checkout_service: get_bundle_products failed for %s", bundle_id)
        return []


def create_bundle_checkout_session(
    bundle_id: str,
    email: str,
    success_url: str,
    cancel_url: str,
) -> str | None:
    """Create a Stripe Checkout Session for a bundle subscription.

    Returns the session URL on success, None on failure.
    """
    bundle = BUNDLE_CATALOG.get(bundle_id)
    if not bundle:
        logger.warning("bundle_checkout_service: unknown bundle_id=%s", bundle_id)
        return None

    stripe_price_id = os.getenv(bundle["stripe_price_env"], "")
    if not stripe_price_id:
        logger.warning(
            "bundle_checkout_service: env %s not set for bundle %s",
            bundle["stripe_price_env"],
            bundle_id,
        )
        return None

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        logger.warning("bundle_checkout_service: STRIPE_SECRET_KEY not set")
        return None

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": stripe_price_id, "quantity": 1}],
            customer_email=email,
            metadata={
                "subscription_type": "bundle",
                "bundle_id": bundle_id,
                "email": email,
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return session.url
    except stripe.error.StripeError:
        logger.exception("bundle_checkout_service: Stripe error creating session for %s", bundle_id)
        return None


def activate_bundle(
    email: str,
    bundle_id: str,
    stripe_sub_id: str | None = None,
    stripe_customer_id: str | None = None,
) -> bool:
    """Record bundle activation in billing_subscriptions.

    Sets bundle_id on the user's active subscription row (upsert by email).
    Returns True on success.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO billing_subscriptions
                    (user_id, billing_customer_id, stripe_subscription_id, stripe_price_id,
                     module, status, billing_cycle, bundle_id)
                SELECT
                    COALESCE(
                        (SELECT id FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1), 0
                    ),
                    0,
                    COALESCE(%s, ''),
                    '',
                    'bundle',
                    'active',
                    'month',
                    %s
                ON CONFLICT (stripe_subscription_id) DO UPDATE SET
                    bundle_id  = EXCLUDED.bundle_id,
                    status     = 'active'
                """,
                (email, stripe_sub_id or f"bundle_{bundle_id}_{email}", bundle_id),
            )
        logger.info("bundle_checkout_service: activated bundle %s for %s", bundle_id, email)
        return True
    except Exception:
        logger.exception("bundle_checkout_service: activate_bundle failed for %s / %s", email, bundle_id)
        return False


def get_user_bundles(email: str) -> list[str]:
    """Return list of active bundle_ids for a given email."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT bundle_id
                FROM billing_subscriptions
                WHERE LOWER(email) = LOWER(%s)
                  AND bundle_id IS NOT NULL
                  AND status = 'active'
                """,
                (email,),
            )
            rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception:
        # billing_subscriptions may not have an email column on all installs —
        # fall back gracefully rather than crashing the request.
        logger.debug("bundle_checkout_service: get_user_bundles failed for %s", email)
        return []
