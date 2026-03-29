"""
Printful Fulfillment Service — order submission and product sync.

Store owners connect their Printful accounts via user_integrations.
After a successful Stripe payment, eligible orders are auto-submitted
to Printful for print-on-demand fulfillment.
"""

import json
import logging
from datetime import datetime

import requests
from database import get_db_cursor

log = logging.getLogger(__name__)

PRINTFUL_API_BASE = "https://api.printful.com"
_REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# 1. Printful key lookup
# ---------------------------------------------------------------------------


def get_printful_api_key(user_id):
    """Look up the user's Printful API key from user_integrations.

    Returns:
        str API key or None.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT credentials
            FROM user_integrations
            WHERE user_id = %s AND service = 'printful' AND status = 'active'
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        creds = row["credentials"] if isinstance(row["credentials"], dict) else json.loads(row["credentials"])
        return creds.get("api_key")


def _printful_headers(api_key):
    """Build Printful API headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 2. Submit order to Printful
# ---------------------------------------------------------------------------


def submit_printful_order(order_id):
    """Submit a store order to Printful for fulfillment.

    Reads order + items from DB, maps products with Printful variant IDs
    (stored in store_products.metadata->'printful_variant_id'), and POSTs
    to Printful's /orders endpoint.

    Returns:
        dict with Printful order data on success, None on failure.
    """
    # Fetch order with items
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT * FROM store_orders WHERE id = %s", (order_id,))
        order = cur.fetchone()
        if not order:
            log.error("Order %s not found", order_id)
            return None

        cur.execute(
            """
            SELECT soi.*, sp.metadata as product_metadata
            FROM store_order_items soi
            LEFT JOIN store_products sp ON soi.product_id = sp.id
            WHERE soi.order_id = %s
            """,
            (order_id,),
        )
        items = cur.fetchall()

        # Get store owner for API key lookup
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (order["store_id"],))
        store = cur.fetchone()
        if not store:
            log.error("Store %s not found for order %s", order["store_id"], order_id)
            return None

    api_key = get_printful_api_key(store["user_id"])
    if not api_key:
        log.warning("No Printful API key for store owner %s — skipping fulfillment", store["user_id"])
        return None

    # Build Printful order payload
    printful_items = []
    for item in items:
        meta = item.get("product_metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}

        variant_id = meta.get("printful_variant_id")
        if not variant_id:
            log.info("Product %s has no printful_variant_id — skipping", item.get("product_id"))
            continue

        printful_items.append(
            {
                "variant_id": int(variant_id),
                "quantity": item["quantity"],
                "retail_price": str(item["unit_price"]),
                "name": item["product_name"],
            }
        )

    if not printful_items:
        log.info("No Printful-eligible items in order %s", order_id)
        return None

    # Parse shipping address
    shipping = order.get("shipping_address") or {}
    if isinstance(shipping, str):
        try:
            shipping = json.loads(shipping)
        except (json.JSONDecodeError, TypeError):
            shipping = {}

    payload = {
        "recipient": {
            "name": order.get("customer_name") or "Customer",
            "email": order.get("customer_email"),
            "address1": shipping.get("address1", ""),
            "city": shipping.get("city", ""),
            "state_code": shipping.get("state", ""),
            "country_code": shipping.get("country", "CA"),
            "zip": shipping.get("zip", ""),
        },
        "items": printful_items,
        "external_id": str(order_id),
    }

    # Submit to Printful
    try:
        resp = requests.post(
            f"{PRINTFUL_API_BASE}/orders",
            json=payload,
            headers=_printful_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )

        if resp.status_code in (200, 201):
            result = resp.json().get("result", {})
            printful_order_id = result.get("id")

            # Update order metadata with Printful order ID
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE store_orders
                    SET metadata = COALESCE(metadata, '{}'::jsonb)
                        || jsonb_build_object('printful_order_id', %s::text),
                        status = 'processing',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (str(printful_order_id), order_id),
                )

                # Log sync
                cur.execute(
                    """
                    INSERT INTO printful_sync (sync_type, last_sync_at, items_synced, status)
                    VALUES ('order_submit', NOW(), %s, 'success')
                    """,
                    (len(printful_items),),
                )

            log.info(
                "Printful order %s created for store order %s (%d items)",
                printful_order_id,
                order_id,
                len(printful_items),
            )
            return result
        else:
            log.error(
                "Printful order submission failed: %s %s",
                resp.status_code,
                resp.text[:300],
            )

            # Log failure
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO printful_sync (sync_type, last_sync_at, items_synced, status, error_message)
                    VALUES ('order_submit', NOW(), 0, 'error', %s)
                    """,
                    (resp.text[:500],),
                )

            return None

    except requests.RequestException as exc:
        log.error("Printful API request failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 3. Fetch Printful product catalog
# ---------------------------------------------------------------------------


def get_printful_products(user_id):
    """Fetch the user's Printful store products.

    Returns:
        list of product dicts or empty list.
    """
    api_key = get_printful_api_key(user_id)
    if not api_key:
        return []

    try:
        resp = requests.get(
            f"{PRINTFUL_API_BASE}/store/products",
            headers=_printful_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        if resp.ok:
            return resp.json().get("result", [])
        else:
            log.warning("Printful products fetch failed: %s", resp.status_code)
            return []
    except requests.RequestException as exc:
        log.error("Printful API error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# 4. Sync Printful product into store
# ---------------------------------------------------------------------------


def sync_printful_product(user_id, printful_product_id, store_id):
    """Import a Printful product into a store as a store_product.

    Fetches product details from Printful and creates a store_product
    with the printful_variant_id stored in metadata for fulfillment mapping.

    Returns:
        dict — created store_product row, or None on failure.
    """
    api_key = get_printful_api_key(user_id)
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{PRINTFUL_API_BASE}/store/products/{printful_product_id}",
            headers=_printful_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        if not resp.ok:
            log.warning("Printful product %s fetch failed: %s", printful_product_id, resp.status_code)
            return None

        data = resp.json().get("result", {})
        product_info = data.get("sync_product", {})
        variants = data.get("sync_variants", [])

        if not variants:
            log.warning("Printful product %s has no variants", printful_product_id)
            return None

        # Use first variant for default pricing
        first_variant = variants[0]
        retail_price = float(first_variant.get("retail_price", 0))

        # Get thumbnail
        thumbnail = product_info.get("thumbnail_url", "")

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO store_products
                    (store_id, user_id, name, description, price, currency,
                     images, status, metadata)
                VALUES (%s, %s, %s, %s, %s, 'cad', %s, 'active', %s)
                RETURNING *
                """,
                (
                    store_id,
                    user_id,
                    product_info.get("name", "Printful Product"),
                    f"Print-on-demand product synced from Printful",
                    retail_price,
                    json.dumps([thumbnail]) if thumbnail else "[]",
                    json.dumps(
                        {
                            "printful_product_id": printful_product_id,
                            "printful_variant_id": first_variant.get("id"),
                            "printful_variants": [
                                {"id": v.get("id"), "name": v.get("name"), "price": v.get("retail_price")}
                                for v in variants
                            ],
                        }
                    ),
                ),
            )
            product = cur.fetchone()

            # Log sync
            cur.execute(
                """
                INSERT INTO printful_sync (sync_type, last_sync_at, items_synced, status)
                VALUES ('product_import', NOW(), 1, 'success')
                """,
            )

        log.info("Synced Printful product %s into store %s", printful_product_id, store_id)
        return product

    except requests.RequestException as exc:
        log.error("Printful product sync failed: %s", exc)
        return None
