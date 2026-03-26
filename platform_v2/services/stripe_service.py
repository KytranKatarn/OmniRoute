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
                   amount_cents, currency, interval, active, description,
                   created_at, updated_at
              FROM billing_products
             WHERE module = %s AND active = TRUE
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
                 amount_cents, currency, interval, description, active,
                 updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (stripe_product_id) DO UPDATE
               SET stripe_price_id = EXCLUDED.stripe_price_id,
                   module          = EXCLUDED.module,
                   name            = EXCLUDED.name,
                   amount_cents    = EXCLUDED.amount_cents,
                   currency        = EXCLUDED.currency,
                   interval        = EXCLUDED.interval,
                   description     = EXCLUDED.description,
                   active          = EXCLUDED.active,
                   updated_at      = NOW()
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
