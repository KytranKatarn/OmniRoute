"""
Store Checkout Service — Stripe checkout using store owner's API keys.

Each store owner connects their own Stripe account via user_integrations.
Checkout sessions are created with the owner's key, so payments go directly
to their Stripe account (not the platform's).
"""

import json
import logging

import stripe
import stripe.error
from database import get_db_cursor

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Stripe key lookup
# ---------------------------------------------------------------------------


def get_store_stripe_keys(store_id):
    """Look up the store owner's Stripe credentials from user_integrations.

    Returns:
        dict with 'secret_key', 'publishable_key', 'webhook_secret' or None.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT ui.credentials
            FROM user_integrations ui
            JOIN user_stores us ON us.user_id = ui.user_id
            WHERE us.id = %s
              AND ui.service = 'stripe'
              AND ui.status = 'active'
            """,
            (store_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        creds = row["credentials"] if isinstance(row["credentials"], dict) else json.loads(row["credentials"])
        if not creds.get("secret_key"):
            return None
        return creds


# ---------------------------------------------------------------------------
# 2. Create checkout session
# ---------------------------------------------------------------------------


def create_store_checkout(store_id, items, customer_email, success_url, cancel_url):
    """Create a Stripe Checkout Session for a store purchase.

    Parameters
    ----------
    store_id : int
        The store ID.
    items : list[dict]
        Each dict has 'product_id' (int) and 'quantity' (int).
    customer_email : str
        Customer's email for the Stripe session.
    success_url : str
        Redirect URL after successful payment. Stripe appends ?session_id={CHECKOUT_SESSION_ID}.
    cancel_url : str
        Redirect URL if customer cancels.

    Returns
    -------
    dict with 'checkout_url' and 'session_id', or raises on error.
    """
    # Get store owner's Stripe key
    keys = get_store_stripe_keys(store_id)
    if not keys:
        raise ValueError("Store does not have Stripe configured")

    # Fetch product details and build line items
    product_ids = [item["product_id"] for item in items]
    qty_map = {item["product_id"]: item["quantity"] for item in items}

    with get_db_cursor(commit=False) as (conn, cur):
        # Verify all products belong to this store and are active
        placeholders = ",".join(["%s"] * len(product_ids))
        cur.execute(
            f"""
            SELECT id, name, price, currency, images
            FROM store_products
            WHERE id IN ({placeholders})
              AND store_id = %s
              AND status = 'active'
            """,
            (*product_ids, store_id),
        )
        products = cur.fetchall()

        if len(products) != len(product_ids):
            found_ids = {p["id"] for p in products}
            missing = [pid for pid in product_ids if pid not in found_ids]
            raise ValueError(f"Products not found or inactive: {missing}")

    # Build Stripe line_items
    line_items = []
    for product in products:
        qty = qty_map[product["id"]]
        price_cents = int(float(product["price"]) * 100)
        currency = product.get("currency", "cad") or "cad"

        images = product.get("images") or []
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except (json.JSONDecodeError, TypeError):
                images = []

        item = {
            "price_data": {
                "currency": currency,
                "unit_amount": price_cents,
                "product_data": {
                    "name": product["name"],
                },
            },
            "quantity": qty,
        }

        # Add first image if available
        if images and isinstance(images, list) and images[0]:
            item["price_data"]["product_data"]["images"] = [images[0]]

        line_items.append(item)

    # Create Stripe Checkout Session with store owner's key
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            customer_email=customer_email,
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            metadata={
                "store_id": str(store_id),
                "product_ids": json.dumps(product_ids),
            },
            api_key=keys["secret_key"],
        )
    except stripe.error.StripeError as e:
        log.error("Stripe checkout creation failed for store %s: %s", store_id, e)
        raise

    log.info("Checkout session %s created for store %s", session.id, store_id)
    return {"checkout_url": session.url, "session_id": session.id}


# ---------------------------------------------------------------------------
# 3. Handle successful payment
# ---------------------------------------------------------------------------


def handle_store_payment_success(store_id, session_id):
    """Process a completed Stripe Checkout Session — create order + items.

    Parameters
    ----------
    store_id : int
        The store this payment belongs to.
    session_id : str
        Stripe Checkout Session ID.

    Returns
    -------
    dict — the created order row.
    """
    keys = get_store_stripe_keys(store_id)
    if not keys:
        raise ValueError("Store does not have Stripe configured")

    # Retrieve the session from Stripe
    try:
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["line_items"],
            api_key=keys["secret_key"],
        )
    except stripe.error.StripeError as e:
        log.error("Failed to retrieve session %s: %s", session_id, e)
        raise

    if session.payment_status != "paid":
        raise ValueError(f"Session {session_id} not paid (status={session.payment_status})")

    # Parse product IDs from metadata
    product_ids = json.loads(session.metadata.get("product_ids", "[]"))

    # Get store info for the order
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()
        if not store:
            raise ValueError(f"Store {store_id} not found")
        store_owner_id = store["user_id"]

    # Fetch products for order items
    with get_db_cursor(commit=False) as (conn, cur):
        if product_ids:
            placeholders = ",".join(["%s"] * len(product_ids))
            cur.execute(
                f"SELECT id, name, sku, price FROM store_products WHERE id IN ({placeholders})",
                product_ids,
            )
            products = {p["id"]: p for p in cur.fetchall()}
        else:
            products = {}

    # Build quantity map from line items
    total_amount = session.amount_total / 100 if session.amount_total else 0
    currency = session.currency or "cad"

    # Create order
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO store_orders
                (store_id, user_id, customer_email, customer_name,
                 total, currency, status, payment_status, payment_method,
                 payment_id, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', 'paid', 'stripe', %s, %s)
            RETURNING *
            """,
            (
                store_id,
                store_owner_id,
                session.customer_details.email if session.customer_details else session.customer_email,
                session.customer_details.name if session.customer_details else None,
                total_amount,
                currency,
                session.payment_intent if hasattr(session, "payment_intent") else session.id,
                json.dumps({"stripe_session_id": session_id}),
            ),
        )
        order = cur.fetchone()
        order_id = order["id"]

        # Insert order items
        for line_item in session.line_items.data if session.line_items else []:
            # Try to match back to our product
            matched_product = None
            for pid in product_ids:
                if pid in products:
                    matched_product = products.pop(pid)
                    break

            cur.execute(
                """
                INSERT INTO store_order_items
                    (order_id, product_id, product_name, product_sku,
                     quantity, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    order_id,
                    matched_product["id"] if matched_product else None,
                    line_item.description or (matched_product["name"] if matched_product else "Item"),
                    matched_product["sku"] if matched_product else None,
                    line_item.quantity,
                    line_item.amount_total / 100 / line_item.quantity if line_item.quantity else 0,
                    line_item.amount_total / 100,
                ),
            )

    log.info("Order #%s created for store %s (session %s)", order_id, store_id, session_id)
    return order


# ---------------------------------------------------------------------------
# 4. Verify webhook signature (per-store)
# ---------------------------------------------------------------------------


def verify_store_webhook(store_id, payload, sig_header):
    """Verify a Stripe webhook signature using the store owner's webhook secret.

    Returns:
        (event, None) on success or (None, error_string) on failure.
    """
    keys = get_store_stripe_keys(store_id)
    if not keys or not keys.get("webhook_secret"):
        return None, "Store webhook secret not configured"

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, keys["webhook_secret"])
        return event, None
    except stripe.error.SignatureVerificationError as exc:
        return None, f"Signature verification failed: {exc}"
    except Exception as exc:
        return None, f"Event construction error: {exc}"
