"""
Printful Integration Module for A.R.C.H.I.E. Platform
Handles product sync, order creation, and fulfillment
"""

import os
from database import _get_db_password
import requests
import json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

PRINTFUL_API_KEY = os.getenv("PRINTFUL_API_KEY")
PRINTFUL_API_URL = "https://api.printful.com"


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def printful_request(method, endpoint, data=None):
    """Make request to Printful API"""
    headers = {
        "Authorization": f"Bearer {PRINTFUL_API_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{PRINTFUL_API_URL}/{endpoint}"

    if method == "GET":
        response = requests.get(url, headers=headers)
    elif method == "POST":
        response = requests.post(url, headers=headers, json=data)
    elif method == "PUT":
        response = requests.put(url, headers=headers, json=data)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers)

    response.raise_for_status()
    return response.json()


# ============================================================================
# PRODUCT SYNC
# ============================================================================


def sync_products():
    """Sync products from Printful store"""
    try:
        # Get sync products from Printful
        result = printful_request("GET", "store/products")
        products = result.get("result", [])

        conn = get_db()
        cur = conn.cursor()

        synced_count = 0

        for product in products:
            # Get detailed product info
            detail_result = printful_request("GET", f'store/products/{product["id"]}')
            product_detail = detail_result.get("result", {})

            sync_product = product_detail.get("sync_product", {})
            sync_variants = product_detail.get("sync_variants", [])

            # Store product
            cur.execute(
                """
                INSERT INTO products
                (printful_product_id, name, description, sync_product_id,
                 images, variants, is_active, last_synced_at)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, NOW())
                ON CONFLICT (printful_product_id) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    images = EXCLUDED.images,
                    variants = EXCLUDED.variants,
                    last_synced_at = NOW()
            """,
                (
                    product["id"],
                    sync_product.get("name"),
                    sync_product.get("description"),
                    sync_product.get("id"),
                    json.dumps([v.get("files", []) for v in sync_variants]),
                    json.dumps(
                        [
                            {
                                "id": v["id"],
                                "name": v.get("name"),
                                "retail_price": v.get("retail_price"),
                                "currency": v.get("currency"),
                            }
                            for v in sync_variants
                        ]
                    ),
                ),
            )

            synced_count += 1

        # Log sync
        cur.execute(
            """
            INSERT INTO printful_sync (sync_type, last_sync_at, items_synced, status)
            VALUES ('products', NOW(), %s, 'success')
        """,
            (synced_count,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"success": True, "synced": synced_count}

    except Exception as e:
        print(f"Product sync error: {e}")

        # Log error
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO printful_sync (sync_type, last_sync_at, status, error_message)
                VALUES ('products', NOW(), 'failed', %s)
            """,
                (str(e),),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception:
            pass

        raise


def get_product_catalog():
    """Get all active products from database"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        """
        SELECT * FROM products
        WHERE is_active = TRUE
        ORDER BY name
    """
    )

    products = cur.fetchall()
    cur.close()
    conn.close()

    return products


# ============================================================================
# ORDER CREATION
# ============================================================================


def create_order(user_id, items, shipping_address):
    """Create order in Printful"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generate order number
        import uuid

        order_number = f"ARCH-{uuid.uuid4().hex[:8].upper()}"

        # Prepare Printful order
        printful_items = []
        for item in items:
            printful_items.append({"sync_variant_id": item["variant_id"], "quantity": item["quantity"]})

        printful_order = {
            "recipient": {
                "name": shipping_address["full_name"],
                "address1": shipping_address["address_line1"],
                "address2": shipping_address.get("address_line2", ""),
                "city": shipping_address["city"],
                "state_code": shipping_address["state_province"],
                "country_code": shipping_address["country"],
                "zip": shipping_address["postal_code"],
                "phone": shipping_address.get("phone", ""),
            },
            "items": printful_items,
            "retail_costs": {"currency": "USD"},
        }

        # Create order in Printful
        result = printful_request("POST", "orders", printful_order)
        printful_order_data = result.get("result", {})

        # Calculate totals
        subtotal = sum(item["quantity"] * item["price"] for item in items)
        shipping_cost = printful_order_data.get("costs", {}).get("shipping", 0)
        total = subtotal + shipping_cost

        # Store order in database
        cur.execute(
            """
            INSERT INTO orders
            (user_id, order_number, printful_order_id, status,
             subtotal, shipping_cost, total_amount, currency)
            VALUES (%s, %s, %s, 'pending', %s, %s, %s, 'USD')
            RETURNING id
        """,
            (
                user_id,
                order_number,
                printful_order_data.get("id"),
                subtotal,
                shipping_cost,
                total,
            ),
        )

        order_id = cur.fetchone()["id"]

        # Store order items
        for item in items:
            cur.execute(
                """
                INSERT INTO order_items
                (order_id, product_id, name, variant, quantity, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    order_id,
                    item.get("product_id"),
                    item["name"],
                    item.get("variant"),
                    item["quantity"],
                    item["price"],
                    item["quantity"] * item["price"],
                ),
            )

        # Store shipping address
        cur.execute(
            """
            INSERT INTO shipping_addresses
            (user_id, order_id, full_name, address_line1, address_line2,
             city, state_province, postal_code, country, phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
            (
                user_id,
                order_id,
                shipping_address["full_name"],
                shipping_address["address_line1"],
                shipping_address.get("address_line2"),
                shipping_address["city"],
                shipping_address["state_province"],
                shipping_address["postal_code"],
                shipping_address["country"],
                shipping_address.get("phone"),
            ),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {
            "success": True,
            "order_id": order_id,
            "order_number": order_number,
            "printful_order_id": printful_order_data.get("id"),
        }

    except Exception as e:
        print(f"Order creation error: {e}")
        raise


def confirm_order(order_id):
    """Confirm order with Printful for fulfillment"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get order
        cur.execute("SELECT printful_order_id FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()

        if not order or not order["printful_order_id"]:
            raise ValueError("Order not found or no Printful order ID")

        # Confirm with Printful
        result = printful_request("POST", f'orders/{order["printful_order_id"]}/confirm')

        # Update order status
        cur.execute(
            """
            UPDATE orders
            SET status = 'processing', updated_at = NOW()
            WHERE id = %s
        """,
            (order_id,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return {"success": True}

    except Exception as e:
        print(f"Order confirmation error: {e}")
        raise


# ============================================================================
# ORDER TRACKING
# ============================================================================


def update_order_status(printful_order_id, status, tracking_number=None, tracking_url=None):
    """Update order status from webhook"""
    conn = get_db()
    cur = conn.cursor()

    update_fields = ["status = %s", "updated_at = NOW()"]
    params = [status]

    if tracking_number:
        update_fields.append("tracking_number = %s")
        params.append(tracking_number)

    if tracking_url:
        update_fields.append("tracking_url = %s")
        params.append(tracking_url)

    if status == "shipped":
        update_fields.append("shipped_at = NOW()")
    elif status == "delivered":
        update_fields.append("delivered_at = NOW()")

    params.append(printful_order_id)

    query = f"""
        UPDATE orders
        SET {', '.join(update_fields)}
        WHERE printful_order_id = %s
    """

    cur.execute(query, params)
    conn.commit()
    cur.close()
    conn.close()


def get_order_status(order_id):
    """Get order status from Printful"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT printful_order_id FROM orders WHERE id = %s", (order_id,))
        order = cur.fetchone()

        if not order or not order["printful_order_id"]:
            return None

        # Get from Printful
        result = printful_request("GET", f'orders/{order["printful_order_id"]}')
        order_data = result.get("result", {})

        # Update local database
        if order_data.get("status"):
            update_order_status(
                order["printful_order_id"],
                order_data["status"],
                order_data.get("tracking_number"),
                order_data.get("tracking_url"),
            )

        cur.close()
        conn.close()

        return order_data

    except Exception as e:
        print(f"Get order status error: {e}")
        return None


# ============================================================================
# WEBHOOK HANDLER
# ============================================================================


def handle_printful_webhook(event_type, data):
    """Handle Printful webhook events"""
    try:
        conn = get_db()
        cur = conn.cursor()

        # Log webhook
        cur.execute(
            """
            INSERT INTO webhook_logs (source, event_type, payload)
            VALUES ('printful', %s, %s)
        """,
            (event_type, json.dumps(data)),
        )

        # Handle different events
        if event_type == "package_shipped":
            order = data.get("order", {})
            shipment = data.get("shipment", {})

            update_order_status(
                order.get("id"),
                "shipped",
                shipment.get("tracking_number"),
                shipment.get("tracking_url"),
            )

            # Create notification
            cur.execute(
                """
                INSERT INTO system_notifications (type, title, message, source, visibility)
                VALUES ('success', 'Order Shipped', %s, 'printful_webhook', 'all')
            """,
                (f"Order {order.get('external_id')} has been shipped. Tracking: {shipment.get('tracking_number')}",),
            )

        elif event_type == "package_returned":
            order = data.get("order", {})

            update_order_status(order.get("id"), "returned")

            # Create notification
            cur.execute(
                """
                INSERT INTO system_notifications (type, title, message, source, visibility)
                VALUES ('warning', 'Order Returned', %s, 'printful_webhook', 'all')
            """,
                (f"Order {order.get('external_id')} was returned",),
            )

        # Mark as processed
        cur.execute(
            """
            UPDATE webhook_logs
            SET processed = TRUE, processed_at = NOW()
            WHERE source = 'printful' AND event_type = %s
            ORDER BY created_at DESC LIMIT 1
        """,
            (event_type,),
        )

        conn.commit()
        cur.close()
        conn.close()

        return True

    except Exception as e:
        print(f"Printful webhook error: {e}")
        raise


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def get_store_analytics():
    """Get store performance metrics"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Total revenue
    cur.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) as total_revenue
        FROM orders
        WHERE status NOT IN ('canceled', 'refunded')
    """
    )
    revenue = cur.fetchone()["total_revenue"]

    # Orders this month
    cur.execute(
        """
        SELECT COUNT(*) as order_count
        FROM orders
        WHERE created_at >= DATE_TRUNC('month', CURRENT_DATE)
        AND status NOT IN ('canceled', 'refunded')
    """
    )
    orders_this_month = cur.fetchone()["order_count"]

    # Top products
    cur.execute(
        """
        SELECT p.name, COUNT(oi.id) as sales
        FROM products p
        JOIN order_items oi ON p.id = oi.product_id
        JOIN orders o ON oi.order_id = o.id
        WHERE o.status NOT IN ('canceled', 'refunded')
        GROUP BY p.name
        ORDER BY sales DESC
        LIMIT 5
    """
    )
    top_products = cur.fetchall()

    cur.close()
    conn.close()

    return {
        "total_revenue": float(revenue),
        "orders_this_month": orders_this_month,
        "top_products": top_products,
    }
