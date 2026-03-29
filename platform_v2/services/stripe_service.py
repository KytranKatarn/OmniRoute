"""
Stripe Service — thin wrapper around the Stripe Python SDK.

Reads API keys from Docker secrets (/run/secrets/) with env-var fallback.
Uses database.get_db_cursor for connection-pooled DB access.
Tables: billing_customers (user_id, stripe_customer_id, email, name)
        billing_products  (stripe_product_id, stripe_price_id, module, name, amount_cents, ...)
"""

import logging
import os

import stripe
import stripe.error

from database import get_db_cursor

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (set by init_stripe)
# ---------------------------------------------------------------------------
_initialized = False
_publishable_key: str | None = None
_webhook_secret: str | None = None


# ---------------------------------------------------------------------------
# 1. Secret loading
# ---------------------------------------------------------------------------


def _read_secret(name: str, env_fallback: str) -> str | None:
    """Read a Docker secret file, falling back to an environment variable.

    Docker mounts secrets at /run/secrets/<name>.  In dev the same value
    is typically set as an env var instead.

    Returns None if neither source provides a value.
    """
    secret_path = f"/run/secrets/{name}"
    try:
        with open(secret_path, "r") as f:
            value = f.read().strip()
            if value:
                log.debug("Loaded secret '%s' from Docker secrets", name)
                return value
    except (FileNotFoundError, PermissionError):
        pass

    value = os.environ.get(env_fallback)
    if value:
        log.debug("Loaded secret '%s' from env var %s", name, env_fallback)
    return value


# ---------------------------------------------------------------------------
# 2. Initialisation
# ---------------------------------------------------------------------------


def init_stripe() -> bool:
    """Initialise the Stripe SDK.  Call once at app startup.

    Sets ``stripe.api_key`` and caches the publishable key / webhook secret.
    Returns True if the secret key was found and applied.
    """
    global _initialized, _publishable_key, _webhook_secret

    secret_key = _read_secret("stripe_secret_key", "STRIPE_SECRET_KEY")
    if not secret_key:
        log.warning("Stripe secret key not found — billing features disabled")
        _initialized = False
        return False

    stripe.api_key = secret_key
    _publishable_key = _read_secret("stripe_publishable_key", "STRIPE_PUBLISHABLE_KEY")
    _webhook_secret = _read_secret("stripe_webhook_secret", "STRIPE_WEBHOOK_SECRET")

    _initialized = True
    # Log only last 4 chars for safety
    masked = "…" + secret_key[-4:]
    log.info("Stripe initialised (key ending %s)", masked)
    return True


# ---------------------------------------------------------------------------
# 3 / 4 / 5. Accessors
# ---------------------------------------------------------------------------


def is_stripe_configured() -> bool:
    """Return True if init_stripe() succeeded."""
    return _initialized


def get_publishable_key() -> str | None:
    """Return the publishable key for frontend checkout."""
    return _publishable_key


def get_webhook_secret() -> str | None:
    """Return the webhook signing secret for signature verification."""
    return _webhook_secret


# ---------------------------------------------------------------------------
# 6. Customer management
# ---------------------------------------------------------------------------


def get_or_create_customer(user_id: int, email: str, name: str) -> str:
    """Return an existing Stripe customer id, or create one lazily.

    Creates the customer in Stripe *and* upserts into ``billing_customers``.
    Returns the ``stripe_customer_id`` string (e.g. ``cus_xxx``).
    """
    # Check local DB first
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT stripe_customer_id FROM billing_customers WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return row["stripe_customer_id"]

    # Create in Stripe
    try:
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={"user_id": str(user_id)},
        )
    except stripe.error.StripeError as e:
        log.error("Stripe Customer.create failed for user %s: %s", user_id, e)
        raise

    # Persist locally
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO billing_customers (user_id, stripe_customer_id, email, name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
               SET stripe_customer_id = EXCLUDED.stripe_customer_id,
                   email = EXCLUDED.email,
                   name  = EXCLUDED.name
            """,
            (user_id, customer.id, email, name),
        )

    log.info("Created Stripe customer %s for user %s", customer.id, user_id)
    return customer.id


# ---------------------------------------------------------------------------
# 7. Customer lookup
# ---------------------------------------------------------------------------


def get_customer(user_id: int) -> dict | None:
    """Look up billing_customers row by user_id.  Returns dict or None."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT * FROM billing_customers WHERE user_id = %s",
            (user_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# 8. Checkout session
# ---------------------------------------------------------------------------


def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    metadata: dict | None = None,
) -> str:
    """Create a Stripe Checkout Session and return its URL.

    Parameters
    ----------
    customer_id : str
        Stripe customer id (``cus_xxx``).
    price_id : str
        Stripe price id (``price_xxx``).
    success_url / cancel_url : str
        Redirect URLs after checkout completes or is cancelled.
    metadata : dict, optional
        Extra key/value pairs attached to the session.

    Returns
    -------
    str
        The checkout session URL to redirect the user to.
    """
    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata or {},
        )
    except stripe.error.StripeError as e:
        log.error("Checkout session creation failed: %s", e)
        raise

    log.info("Checkout session %s created for customer %s", session.id, customer_id)
    return session.url


# ---------------------------------------------------------------------------
# 9. Billing portal session
# ---------------------------------------------------------------------------


def create_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Billing Portal session and return its URL.

    The portal lets customers manage subscriptions, payment methods, and
    invoices without custom UI.
    """
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
    except stripe.error.StripeError as e:
        log.error("Portal session creation failed for %s: %s", customer_id, e)
        raise

    log.info("Portal session created for customer %s", customer_id)
    return session.url


# ---------------------------------------------------------------------------
# 10. Product listing
# ---------------------------------------------------------------------------


def list_module_products(module: str) -> list[dict]:
    """Return all billing_products rows for a given module slug."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT stripe_product_id, stripe_price_id, module, name,
                   amount_cents, currency, billing_interval, is_active,
                   description, created_at, updated_at
              FROM billing_products
             WHERE module = %s AND is_active = TRUE
             ORDER BY amount_cents
            """,
            (module,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# 11. Product registration (upsert)
# ---------------------------------------------------------------------------


def register_product(
    module: str,
    stripe_product_id: str,
    stripe_price_id: str,
    name: str,
    amount_cents: int,
    currency: str = "usd",
    interval: str = "month",
    description: str | None = None,
    active: bool = True,
) -> dict:
    """Upsert a product/price into billing_products.

    If a row with the same ``stripe_product_id`` already exists it is updated;
    otherwise a new row is inserted.

    Returns the upserted row as a dict.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO billing_products
                (stripe_product_id, stripe_price_id, module, name,
                 amount_cents, currency, billing_interval, description,
                 is_active, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (stripe_product_id) DO UPDATE
               SET stripe_price_id    = EXCLUDED.stripe_price_id,
                   module             = EXCLUDED.module,
                   name               = EXCLUDED.name,
                   amount_cents       = EXCLUDED.amount_cents,
                   currency           = EXCLUDED.currency,
                   billing_interval   = EXCLUDED.billing_interval,
                   description        = EXCLUDED.description,
                   is_active          = EXCLUDED.is_active,
                   updated_at         = NOW()
            RETURNING *
            """,
            (
                stripe_product_id,
                stripe_price_id,
                module,
                name,
                amount_cents,
                currency,
                interval,
                description,
                active,
            ),
        )
        row = cur.fetchone()

    log.info(
        "Registered product %s (%s) for module '%s' at %d %s/%s",
        stripe_product_id,
        name,
        module,
        amount_cents,
        currency,
        interval,
    )
    return row


# ---------------------------------------------------------------------------
# 12. Subscription — create
# ---------------------------------------------------------------------------


def create_subscription(
    customer_id: str,
    price_id: str,
    module: str,
    trial_days: int | None = None,
) -> dict:
    """Create a Stripe subscription and persist to billing_subscriptions.

    Parameters
    ----------
    customer_id : str
        Stripe customer id (``cus_xxx``).
    price_id : str
        Stripe price id (``price_xxx``).
    module : str
        Module slug this subscription belongs to (e.g. ``ksm``).
    trial_days : int, optional
        Number of trial days.

    Returns
    -------
    dict
        The inserted billing_subscriptions row.
    """
    params = {
        "customer": customer_id,
        "items": [{"price": price_id}],
        "metadata": {"module": module},
    }
    if trial_days:
        params["trial_period_days"] = trial_days

    try:
        sub = stripe.Subscription.create(**params)
    except stripe.error.StripeError as e:
        log.error("Subscription create failed for %s: %s", customer_id, e)
        raise

    from datetime import datetime, timezone

    def _ts(val):
        return datetime.fromtimestamp(val, tz=timezone.utc) if val else None

    # Look up billing_customer_id
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id FROM billing_customers WHERE stripe_customer_id = %s",
            (customer_id,),
        )
        row = cur.fetchone()
        billing_customer_id = row["id"] if row else None

    # Determine billing cycle from price interval
    cycle = "year" if sub.get("plan", {}).get("interval") == "year" else "month"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO billing_subscriptions
                (user_id, billing_customer_id, stripe_subscription_id,
                 stripe_price_id, module, status, billing_cycle,
                 current_period_start, current_period_end,
                 cancel_at_period_end, trial_start, trial_end,
                 created_at, updated_at)
            VALUES (
                (SELECT user_id FROM billing_customers
                 WHERE stripe_customer_id = %s),
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            )
            RETURNING *
            """,
            (
                customer_id,
                billing_customer_id,
                sub.id,
                price_id,
                module,
                sub.status,
                cycle,
                _ts(sub.current_period_start),
                _ts(sub.current_period_end),
                sub.get("cancel_at_period_end", False),
                _ts(sub.get("trial_start")),
                _ts(sub.get("trial_end")),
            ),
        )
        result = cur.fetchone()

    log.info(
        "Created subscription %s for customer %s (module=%s)",
        sub.id,
        customer_id,
        module,
    )
    return result


# ---------------------------------------------------------------------------
# 13. Subscription — cancel
# ---------------------------------------------------------------------------


def cancel_subscription(stripe_subscription_id: str, immediate: bool = False) -> dict:
    """Cancel a subscription in Stripe and update billing_subscriptions.

    If ``immediate`` is True the subscription is deleted now; otherwise it
    is set to cancel at the end of the current billing period.

    Returns the updated billing_subscriptions row.
    """
    try:
        if immediate:
            stripe.Subscription.delete(stripe_subscription_id)
        else:
            stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=True)
    except stripe.error.StripeError as e:
        log.error("Subscription cancel failed for %s: %s", stripe_subscription_id, e)
        raise

    with get_db_cursor(commit=True) as (conn, cur):
        if immediate:
            cur.execute(
                """
                UPDATE billing_subscriptions
                   SET status = 'canceled', canceled_at = NOW(), updated_at = NOW()
                 WHERE stripe_subscription_id = %s
                RETURNING *
                """,
                (stripe_subscription_id,),
            )
        else:
            cur.execute(
                """
                UPDATE billing_subscriptions
                   SET cancel_at_period_end = TRUE, updated_at = NOW()
                 WHERE stripe_subscription_id = %s
                RETURNING *
                """,
                (stripe_subscription_id,),
            )
        result = cur.fetchone()

    log.info("Canceled subscription %s (immediate=%s)", stripe_subscription_id, immediate)
    return result


# ---------------------------------------------------------------------------
# 14. Subscription — reactivate
# ---------------------------------------------------------------------------


def reactivate_subscription(stripe_subscription_id: str) -> dict:
    """Reactivate a subscription that was set to cancel at period end.

    Returns the updated billing_subscriptions row.
    """
    try:
        stripe.Subscription.modify(stripe_subscription_id, cancel_at_period_end=False)
    except stripe.error.StripeError as e:
        log.error("Subscription reactivate failed for %s: %s", stripe_subscription_id, e)
        raise

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE billing_subscriptions
               SET cancel_at_period_end = FALSE, canceled_at = NULL, updated_at = NOW()
             WHERE stripe_subscription_id = %s
            RETURNING *
            """,
            (stripe_subscription_id,),
        )
        result = cur.fetchone()

    log.info("Reactivated subscription %s", stripe_subscription_id)
    return result


# ---------------------------------------------------------------------------
# 15. Subscription — lookup by user
# ---------------------------------------------------------------------------


def get_active_subscription(user_id: int, module: str | None = None) -> dict | None:
    """Return the active (or trialing) subscription for a user.

    Optionally filter by module.  Returns the most recent match or None.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        if module:
            cur.execute(
                """
                SELECT * FROM billing_subscriptions
                 WHERE user_id = %s AND module = %s
                   AND status IN ('active', 'trialing')
                 ORDER BY created_at DESC LIMIT 1
                """,
                (user_id, module),
            )
        else:
            cur.execute(
                """
                SELECT * FROM billing_subscriptions
                 WHERE user_id = %s
                   AND status IN ('active', 'trialing')
                 ORDER BY created_at DESC LIMIT 1
                """,
                (user_id,),
            )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# 16. Subscription — lookup by Stripe ID
# ---------------------------------------------------------------------------


def get_subscription_by_stripe_id(stripe_subscription_id: str) -> dict | None:
    """Look up a billing_subscriptions row by Stripe subscription id."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT * FROM billing_subscriptions WHERE stripe_subscription_id = %s",
            (stripe_subscription_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# 17. Subscription — sync from webhook
# ---------------------------------------------------------------------------


def update_subscription_from_stripe(stripe_subscription_id: str, data: dict) -> dict | None:
    """Update a billing_subscriptions row from Stripe webhook event data.

    ``data`` should be the subscription object from the event payload.
    Returns the updated row or None if not found.
    """
    from datetime import datetime, timezone

    def _ts(val):
        return datetime.fromtimestamp(val, tz=timezone.utc) if val else None

    status = data.get("status", "active")
    cancel_at_period_end = data.get("cancel_at_period_end", False)
    period_start = _ts(data.get("current_period_start"))
    period_end = _ts(data.get("current_period_end"))

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE billing_subscriptions
               SET status = %s,
                   current_period_start = %s,
                   current_period_end = %s,
                   cancel_at_period_end = %s,
                   updated_at = NOW()
             WHERE stripe_subscription_id = %s
            RETURNING *
            """,
            (status, period_start, period_end, cancel_at_period_end, stripe_subscription_id),
        )
        return cur.fetchone()
