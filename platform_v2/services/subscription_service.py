"""Subscription service — entitlements, trial grants, tier resolution.

Owner: billing/subscription routes and any module needing access gating.
Tables: billing_subscriptions

Import:
    from services.subscription_service import get_user_entitlements, get_user_membership_tier
"""

import logging
from datetime import datetime, timedelta, timezone

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Placeholder values for non-Stripe grants
_TRIAL_STRIPE_SUB_ID = "trial_grant"
_OVERRIDE_STRIPE_SUB_ID = "admin_override"
_NO_STRIPE_CUSTOMER_ID = 0


def _resolve_tier_from_price(stripe_price_id):
    """Map a Stripe price ID string to a tier name.

    Checks for known tier keywords in the price ID string.
    Falls back to 'viewer'.
    """
    if not stripe_price_id:
        return "viewer"
    pid = stripe_price_id.lower()
    if "enterprise" in pid:
        return "enterprise"
    if "pro" in pid:
        return "professional"
    if "starter" in pid:
        return "starter"
    if "vip" in pid:
        return "vip"
    if "viewer" in pid:
        return "viewer"
    return "viewer"


def resolve_tier_for_product(stripe_price_id, product_id=None):
    """DB-backed tier resolution via subscription_plans table (T3027).

    Looks up the tier_name for a given stripe_price_id (+ optional product_id
    for disambiguation).  Falls back to legacy keyword-matching only when the
    price ID is not yet seeded in subscription_plans.

    Args:
        stripe_price_id: Stripe price ID (e.g. 'price_1AbCdEfGhIjKlMnO')
        product_id:      Optional product scope (e.g. 'gov_watch', 'wtf').

    Returns:
        tier_name str — canonical tier vocabulary:
        free | starter | solo | team | agency | enterprise
    """
    if not stripe_price_id:
        return "free"

    try:
        with get_db_cursor() as (conn, cur):
            if product_id:
                cur.execute(
                    """
                    SELECT tier_name FROM billing_product_plans
                    WHERE stripe_price_id = %s AND product_id = %s AND is_active
                    LIMIT 1
                    """,
                    (stripe_price_id, product_id),
                )
            else:
                cur.execute(
                    """
                    SELECT tier_name FROM billing_product_plans
                    WHERE stripe_price_id = %s AND is_active
                    LIMIT 1
                    """,
                    (stripe_price_id,),
                )
            row = cur.fetchone()
            if row:
                return row["tier_name"]
    except Exception:
        logger.warning("resolve_tier_for_product: DB lookup failed, falling back to keyword match")

    # Fallback: legacy keyword heuristic (catches prices not yet in subscription_plans)
    return _resolve_tier_from_price(stripe_price_id) or "free"


def get_user_subscriptions(user_id):
    """Return all active subscriptions for a user.

    Excludes rows that are revoked, expired trials, or canceled.

    Returns:
        List of dicts with keys: id, module, status, stripe_price_id,
        expires_at, granted_by, created_at, source.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, module, status, stripe_price_id, expires_at,
                       granted_by, created_at, stripe_subscription_id
                FROM billing_subscriptions
                WHERE user_id = %s
                  AND revoked_at IS NULL
                  AND status NOT IN ('canceled', 'revoked')
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        result = []
        for row in rows:
            sub_id = row["stripe_subscription_id"] or ""
            if sub_id == _TRIAL_STRIPE_SUB_ID:
                source = "trial"
            elif sub_id == _OVERRIDE_STRIPE_SUB_ID:
                source = "admin_override"
            else:
                source = "stripe"

            result.append(
                {
                    "id": row["id"],
                    "module": row["module"],
                    "status": row["status"],
                    "stripe_price_id": row["stripe_price_id"],
                    "expires_at": row["expires_at"],
                    "granted_by": row["granted_by"],
                    "created_at": row["created_at"],
                    "source": source,
                }
            )
        return result
    except Exception:
        logger.exception("get_user_subscriptions failed for user_id=%s", user_id)
        return []


def get_user_entitlements(user_id, user_role=None):
    """Compute effective entitlements for a user.

    Admin bypass: returns {"_admin": True, "_tier": "staff"}.
    Otherwise returns dict of {module: {tier, source, expires_at, status}}.
    """
    if user_role in ("admin", "staff"):
        return {"_admin": True, "_tier": "staff"}

    subs = get_user_subscriptions(user_id)
    entitlements = {}
    for sub in subs:
        module = sub["module"]
        tier = _resolve_tier_from_price(sub["stripe_price_id"])
        entitlements[module] = {
            "tier": tier,
            "source": sub["source"],
            "expires_at": sub["expires_at"],
            "status": sub["status"],
        }
    return entitlements


def get_user_membership_tier(user_id, user_role=None):
    """Return the overall membership tier string for a user.

    Tiers (highest to lowest): staff > vip > enterprise > professional > starter > explorer

    Admin bypass returns "staff". No active subscription returns "explorer".
    Checks for membership_* module subscriptions to determine tier.
    """
    if user_role in ("admin", "staff"):
        return "staff"

    subs = get_user_subscriptions(user_id)

    tier_rank = {
        "staff": 6,
        "vip": 5,
        "enterprise": 4,
        "professional": 3,
        "starter": 2,
        "explorer": 1,
        "viewer": 1,
    }

    best_tier = "explorer"
    best_rank = 1

    for sub in subs:
        module = sub["module"] or ""
        # Membership modules are prefixed with "membership_"
        if module.startswith("membership_"):
            # DB-backed resolution (billing_product_plans) with legacy keyword
            # fallback built in. The old keyword-only matcher scanned the opaque
            # Stripe price ID and always fell through to "viewer", so no real
            # membership price ever resolved to its tier.
            tier = resolve_tier_for_product(sub["stripe_price_id"])
            rank = tier_rank.get(tier, 1)
            if rank > best_rank:
                best_rank = rank
                best_tier = tier

    return best_tier


def grant_trial(user_id, module, tier_price_id, duration_days, granted_by_user_id):
    """Create or update a trial subscription row for a user+module.

    Uses ON CONFLICT DO UPDATE for idempotent upsert (keyed on user_id + module
    + stripe_subscription_id = 'trial_grant').

    Returns:
        Dict with keys: id, expires_at — or None on failure.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO billing_subscriptions
                    (user_id, billing_customer_id, stripe_subscription_id,
                     stripe_price_id, module, status, expires_at, granted_by,
                     trial_start, trial_end, created_at, updated_at)
                VALUES
                    (%s, %s, %s, %s, %s, 'trialing', %s, %s,
                     NOW(), %s, NOW(), NOW())
                ON CONFLICT (user_id, module, stripe_subscription_id)
                DO UPDATE SET
                    stripe_price_id = EXCLUDED.stripe_price_id,
                    expires_at      = EXCLUDED.expires_at,
                    trial_end       = EXCLUDED.trial_end,
                    status          = 'trialing',
                    revoked_at      = NULL,
                    updated_at      = NOW()
                RETURNING id, expires_at
                """,
                (
                    user_id,
                    _NO_STRIPE_CUSTOMER_ID,
                    _TRIAL_STRIPE_SUB_ID,
                    tier_price_id,
                    module,
                    expires_at,
                    granted_by_user_id,
                    expires_at,
                ),
            )
            row = cur.fetchone()

        if row:
            logger.info(
                "Trial granted: user_id=%s module=%s expires=%s granted_by=%s",
                user_id,
                module,
                row["expires_at"],
                granted_by_user_id,
            )
            return {"id": row["id"], "expires_at": row["expires_at"]}
        return None
    except Exception:
        logger.exception("grant_trial failed: user_id=%s module=%s", user_id, module)
        return None


def revoke_subscription(subscription_id, revoked_by_user_id):
    """Revoke a trial or admin_override subscription.

    Only rows with stripe_subscription_id in ('trial_grant', 'admin_override')
    can be revoked through this function. Stripe-managed subs must be canceled
    via the Stripe API.

    Returns:
        True if a row was updated, False otherwise.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE billing_subscriptions
                SET revoked_at = NOW(),
                    status     = 'revoked',
                    updated_at = NOW()
                WHERE id = %s
                  AND stripe_subscription_id IN (%s, %s)
                  AND revoked_at IS NULL
                """,
                (subscription_id, _TRIAL_STRIPE_SUB_ID, _OVERRIDE_STRIPE_SUB_ID),
            )
            updated = cur.rowcount

        if updated:
            logger.info(
                "Subscription revoked: id=%s by user_id=%s",
                subscription_id,
                revoked_by_user_id,
            )
            return True

        logger.warning(
            "revoke_subscription: no eligible row for id=%s (Stripe sub or already revoked)",
            subscription_id,
        )
        return False
    except Exception:
        logger.exception("revoke_subscription failed: id=%s", subscription_id)
        return False
