"""
Watch Products Billing Handler — Stripe webhook handlers for all Watch standalones.

Handles checkout.session.completed, customer.subscription.updated, and
customer.subscription.deleted for:
  gov_watch, civic_watch, legal_watch, market_watch, wtf
  bundle_watch (4-product), bundle_intelligence (5-product)

Pushes tier changes to each standalone via X-Internal-Key + mesh IP.
Falls through to KSM handler when a price belongs to a non-Watch product.

Created: T3027 — Unified Pricing Infrastructure (2026-05-25)
"""

import logging
import os

import requests
from database import get_db_cursor

from services.billing_webhook import register_billing_handler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Product configuration
# ---------------------------------------------------------------------------

# Watch standalones — mesh IP (100.64.0.10 = Citadel/boston-2, where ALL watch
# products + WTF migrated 2026-06; outpost-us no longer runs any product
# containers, see #4032). NEVER use public CDN hostnames — Hostinger caps at
# 60s, bypasses queue.
PRODUCT_STANDALONE_URLS: dict[str, str] = {
    "gov_watch": os.getenv("GOV_WATCH_URL", "http://100.64.0.10:8102"),
    "civic_watch": os.getenv("CIVIC_WATCH_URL", "http://100.64.0.10:8099"),
    "legal_watch": os.getenv("LEGAL_WATCH_URL", "http://100.64.0.10:8100"),
    "market_watch": os.getenv("MARKET_WATCH_URL", "http://100.64.0.10:8101"),
    "wtf": os.getenv("WTF_CONSUMER_URL", "http://100.64.0.10:8103"),
}

# Bundle → list of constituent product_ids that receive the tier push
BUNDLE_PRODUCTS: dict[str, list[str]] = {
    "bundle_watch": ["gov_watch", "civic_watch", "legal_watch", "market_watch"],
    "bundle_intelligence": ["gov_watch", "civic_watch", "legal_watch", "market_watch", "wtf"],
}

# All product_ids this handler owns (including bundles)
WATCH_PRODUCT_IDS: set[str] = set(PRODUCT_STANDALONE_URLS) | set(BUNDLE_PRODUCTS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lookup_product_for_price(stripe_price_id: str) -> tuple[str | None, str]:
    """Query subscription_plans to find (product_id, tier_name) for a price.

    Returns:
        (product_id, tier_name) — product_id is None when price not found.
    """
    if not stripe_price_id:
        return None, "free"
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT product_id, tier_name
                FROM billing_product_plans
                WHERE stripe_price_id = %s AND is_active
                LIMIT 1
                """,
                (stripe_price_id,),
            )
            row = cur.fetchone()
            if row:
                return row["product_id"], row["tier_name"]
    except Exception as exc:
        logger.warning("_lookup_product_for_price failed for %s: %s", stripe_price_id, exc)
    return None, "free"


def _get_user_id_for_stripe_customer(stripe_customer_id: str) -> int | None:
    """Look up billing_customers to find user_id for a Stripe customer."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT user_id FROM billing_customers WHERE stripe_customer_id = %s LIMIT 1",
                (stripe_customer_id,),
            )
            row = cur.fetchone()
            return row["user_id"] if row else None
    except Exception as exc:
        logger.error("Customer lookup failed for %s: %s", stripe_customer_id, exc)
        return None


def _get_user_email(user_id: int) -> str | None:
    """Look up the email address for a platform user_id.

    Used to pass email alongside user_id in tier-push payloads so that
    standalone products keyed by email (e.g. gov-watch user_profiles) can
    update their tier without needing access to the platform users table.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT email FROM users WHERE id = %s LIMIT 1", (user_id,))
            row = cur.fetchone()
            return row["email"] if row else None
    except Exception as exc:
        logger.error("User email lookup failed for user_id=%s: %s", user_id, exc)
        return None


def _push_tier_to_standalone(product_id: str, user_id: int, tier: str, email: str | None = None) -> bool:
    """POST tier update to the standalone via internal API key (mesh IP).

    Endpoint: {url}/api/internal/set-tier
    Auth: X-Internal-Key header from INTERNAL_API_KEY env var.

    Payload includes email when available — standalones keyed by email
    (e.g. gov-watch user_profiles) use it directly instead of platform user_id.
    No-downgrade invariant is enforced on the standalone side.
    """
    url = PRODUCT_STANDALONE_URLS.get(product_id)
    if not url:
        logger.warning("No standalone URL configured for product_id=%s", product_id)
        return False

    payload: dict = {"user_id": user_id, "tier": tier}
    if email:
        payload["email"] = email.strip().lower()

    try:
        resp = requests.post(
            f"{url}/api/internal/set-tier",
            json=payload,
            headers={
                "X-Internal-Key": os.getenv("INTERNAL_API_KEY", ""),
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.ok:
            logger.info("Pushed tier='%s' to %s (user=%s): %s", tier, product_id, user_id, resp.status_code)
            return True
        logger.error(
            "Tier push failed for %s (user=%s): %s %s",
            product_id,
            user_id,
            resp.status_code,
            resp.text[:200],
        )
        return False
    except requests.RequestException as exc:
        logger.error("Tier push request failed for %s: %s", product_id, exc)
        return False


def _push_tier_for_product_id(product_id: str, user_id: int, tier: str, email: str | None = None) -> dict:
    """Push tier to all standalones for a product (handles bundles)."""
    results = {}
    targets = BUNDLE_PRODUCTS.get(product_id, [product_id] if product_id in PRODUCT_STANDALONE_URLS else [])
    for pid in targets:
        results[pid] = _push_tier_to_standalone(pid, user_id, tier, email=email)
    return results


def _update_billing_subscription(stripe_sub: dict, user_id: int, price_id: str, product_id: str, tier: str):
    """Upsert billing_subscriptions row from a Stripe subscription object."""
    from datetime import datetime, timezone

    def _ts(val):
        return datetime.fromtimestamp(val, tz=timezone.utc) if val else None

    sub_id = stripe_sub.get("id") or getattr(stripe_sub, "id", None)
    if not sub_id:
        return
    status = stripe_sub.get("status", "active")
    interval = (stripe_sub.get("plan") or {}).get("interval", "month")
    cycle = "year" if interval == "year" else "month"

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM billing_customers WHERE user_id = %s LIMIT 1", (user_id,))
            row = cur.fetchone()
            billing_customer_id = row["id"] if row else None

        if not billing_customer_id:
            logger.warning("No billing_customer for user=%s — skipping subscription sync", user_id)
            return

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO billing_subscriptions
                    (user_id, billing_customer_id, stripe_subscription_id,
                     stripe_price_id, module, status, billing_cycle,
                     tier_name, product_id,
                     current_period_start, current_period_end,
                     cancel_at_period_end, trial_start, trial_end,
                     created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())
                ON CONFLICT (stripe_subscription_id) DO UPDATE
                SET status               = EXCLUDED.status,
                    tier_name            = EXCLUDED.tier_name,
                    current_period_start = EXCLUDED.current_period_start,
                    current_period_end   = EXCLUDED.current_period_end,
                    cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                    updated_at           = NOW()
                """,
                (
                    user_id,
                    billing_customer_id,
                    sub_id,
                    price_id,
                    product_id,
                    status,
                    cycle,
                    tier,
                    product_id,
                    _ts(stripe_sub.get("current_period_start")),
                    _ts(stripe_sub.get("current_period_end")),
                    stripe_sub.get("cancel_at_period_end", False),
                    _ts(stripe_sub.get("trial_start")),
                    _ts(stripe_sub.get("trial_end")),
                ),
            )
        logger.info("Synced billing_subscription sub=%s user=%s product=%s", sub_id, user_id, product_id)
    except Exception as exc:
        logger.error("Failed to sync billing_subscription: %s", exc)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def handle_checkout_completed(event: dict) -> str:
    """Handle checkout.session.completed for Watch products.

    Looks up the price_id → product_id via subscription_plans.
    If the product is a Watch/bundle product, pushes the tier.
    Falls through to KSM handler if the price belongs to a KSM product.
    Returns a short status string for the webhook dispatcher log.
    """
    session = event["data"]["object"]
    stripe_customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not subscription_id:
        return "No subscription in session — skipping"

    user_id = _get_user_id_for_stripe_customer(stripe_customer_id)
    if not user_id:
        return f"No user for customer {stripe_customer_id}"

    email = _get_user_email(user_id)

    import stripe as _stripe  # noqa: PLC0415

    try:
        sub = _stripe.Subscription.retrieve(subscription_id)
    except Exception as exc:
        return f"Failed to retrieve subscription {subscription_id}: {exc}"

    items = (sub.get("items") or {}).get("data", [])
    if not items:
        return "Subscription has no items"

    price_id = items[0]["price"]["id"]
    product_id, tier = _lookup_product_for_price(price_id)

    if product_id not in WATCH_PRODUCT_IDS:
        # Not a Watch product — try KSM fallthrough
        try:
            from services.ksm_billing_handler import handle_ksm_checkout_completed  # noqa: PLC0415

            return handle_ksm_checkout_completed(event)
        except Exception as exc:
            logger.debug("KSM fallthrough skipped: %s", exc)
        return f"Price {price_id} not a Watch product — skipped"

    pushed = _push_tier_for_product_id(product_id, user_id, tier, email=email)
    _update_billing_subscription(sub, user_id, price_id, product_id, tier)

    return f"Watch checkout: user={user_id} product={product_id} tier={tier} " f"pushed={pushed}"


def handle_subscription_updated(event: dict) -> str:
    """Handle customer.subscription.updated — detect tier change, push."""
    subscription = event["data"]["object"]
    stripe_customer_id = subscription.get("customer")

    user_id = _get_user_id_for_stripe_customer(stripe_customer_id)
    if not user_id:
        return f"No user for customer {stripe_customer_id}"

    email = _get_user_email(user_id)

    items = subscription.get("items", {}).get("data", [])
    if not items:
        return "Subscription has no items"

    price_id = items[0]["price"]["id"]
    product_id, tier = _lookup_product_for_price(price_id)

    if product_id not in WATCH_PRODUCT_IDS:
        try:
            from services.ksm_billing_handler import handle_ksm_subscription_updated  # noqa: PLC0415

            return handle_ksm_subscription_updated(event)
        except Exception as exc:
            logger.debug("KSM fallthrough skipped: %s", exc)
        return f"Price {price_id} not a Watch product — skipped"

    pushed = _push_tier_for_product_id(product_id, user_id, tier, email=email)
    _update_billing_subscription(subscription, user_id, price_id, product_id, tier)

    return f"Watch sub updated: user={user_id} product={product_id} tier={tier} pushed={pushed}"


def handle_subscription_deleted(event: dict) -> str:
    """Handle customer.subscription.deleted — push tier='free' to standalones."""
    subscription = event["data"]["object"]
    stripe_customer_id = subscription.get("customer")

    user_id = _get_user_id_for_stripe_customer(stripe_customer_id)
    if not user_id:
        return f"No user for customer {stripe_customer_id}"

    email = _get_user_email(user_id)

    items = subscription.get("items", {}).get("data", [])
    if not items:
        return f"No items on deleted subscription — skipping for user={user_id}"

    price_id = items[0]["price"]["id"]
    product_id, _old_tier = _lookup_product_for_price(price_id)

    if product_id not in WATCH_PRODUCT_IDS:
        try:
            from services.ksm_billing_handler import handle_ksm_subscription_deleted  # noqa: PLC0415

            return handle_ksm_subscription_deleted(event)
        except Exception as exc:
            logger.debug("KSM fallthrough skipped: %s", exc)
        return f"Price {price_id} not a Watch product — skipped"

    pushed = _push_tier_for_product_id(product_id, user_id, "free", email=email)

    sub_id = subscription.get("id")
    if sub_id:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE billing_subscriptions
                          SET status = 'canceled', updated_at = NOW()
                        WHERE stripe_subscription_id = %s""",
                    (sub_id,),
                )
        except Exception as exc:
            logger.error("Failed to mark sub canceled: %s", exc)

    return f"Watch sub deleted: user={user_id} product={product_id} tier=free pushed={pushed}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_watch_billing_handlers() -> None:
    """Register Watch webhook handlers with the billing dispatcher.

    Replaces KSM's checkout.session.completed handler — KSM checkout
    falls through inside handle_checkout_completed().

    Call this AFTER register_ksm_billing_handlers() in app.py.
    """
    register_billing_handler("checkout.session.completed", handle_checkout_completed)
    register_billing_handler("customer.subscription.updated", handle_subscription_updated)
    register_billing_handler("customer.subscription.deleted", handle_subscription_deleted)
    logger.info("Watch billing handlers registered (gov_watch, civic_watch, legal_watch, market_watch, wtf + bundles)")
