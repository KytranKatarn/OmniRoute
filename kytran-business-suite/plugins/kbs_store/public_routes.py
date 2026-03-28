"""Public storefront routes — no login required for browsing.

These routes are mounted at /store/public/ and serve as the
public-facing storefront for each tenant. Guest checkout is supported
via email address (no account required).
"""

import logging
import os

from flask import g, jsonify, render_template, request
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus

logger = logging.getLogger(__name__)


def _validate_guest_checkout(data: dict) -> str:
    """Validate guest checkout data. Returns error message or None."""
    email = (data.get("email") or "").strip()
    if not email:
        return "email is required for guest checkout"
    if "@" not in email:
        return "invalid email address"
    return None


def _calculate_cart_total(items: list) -> float:
    """Calculate the total for a list of cart items."""
    total = 0.0
    for item in items:
        total += float(item.get("price", 0)) * int(item.get("quantity", 1))
    return round(total, 2)


def _resolve_tenant(tenant_slug: str):
    """Look up tenant_id from slug. Returns tenant dict or None."""
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            "SELECT id, name, slug, settings FROM tenants WHERE slug = %s AND active = TRUE",
            (tenant_slug,),
        )
        return cur.fetchone()


def register_public_routes(bp, tenant_slug: str = None):
    """Attach public storefront routes to the given blueprint.

    These routes do NOT require login — they are the public storefront.
    Tenant context is resolved from the URL slug.
    """

    # ------------------------------------------------------------------
    # Public Product Browsing
    # ------------------------------------------------------------------

    @bp.route("/products", methods=["GET"])
    def public_list_products():
        """List active products for public browsing."""
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 24, type=int)
        category = request.args.get("category")
        offset = (page - 1) * per_page

        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            where_parts = ["status = 'active'"]
            params = []
            if category:
                where_parts.append("category = %s")
                params.append(category)

            where = "WHERE " + " AND ".join(where_parts)

            cur.execute(f"SELECT COUNT(*) AS cnt FROM store_products {where}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, name, description, price, compare_at_price,
                       category, images, inventory_count
                FROM store_products {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            products = cur.fetchall()

        return jsonify({
            "products": products,
            "total": total,
            "page": page,
            "per_page": per_page,
            "store_name": tenant.get("name", ""),
        })

    @bp.route("/products/<int:product_id>", methods=["GET"])
    def public_get_product(product_id):
        """Get a single product for public viewing."""
        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            cur.execute(
                """
                SELECT id, name, description, price, compare_at_price,
                       category, images, inventory_count, metadata
                FROM store_products
                WHERE id = %s AND status = 'active'
                """,
                (product_id,),
            )
            product = cur.fetchone()

        if not product:
            return jsonify({"error": "product not found"}), 404

        return jsonify(product)

    @bp.route("/categories", methods=["GET"])
    def public_list_categories():
        """List product categories for public browsing."""
        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant["id"])

            cur.execute(
                "SELECT id, name, description FROM store_categories ORDER BY name"
            )
            categories = cur.fetchall()

        return jsonify({"categories": categories})

    # ------------------------------------------------------------------
    # Guest Checkout
    # ------------------------------------------------------------------

    @bp.route("/checkout", methods=["POST"])
    def guest_checkout():
        """Create an order from a guest cart and redirect to Stripe Checkout.

        Expects JSON:
        {
            "email": "guest@example.com",
            "name": "Jane Smith",
            "items": [{"product_id": 1, "quantity": 2}, ...],
            "shipping_address": {...}
        }
        """
        data = request.get_json(force=True)

        # Validate guest email
        error = _validate_guest_checkout(data)
        if error:
            return jsonify({"error": error}), 400

        cart_items = data.get("items", [])
        if not cart_items:
            return jsonify({"error": "cart is empty"}), 400

        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"error": "store not found"}), 404

        tenant_id = tenant["id"]

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Validate products and build order items
            order_items = []
            stripe_line_items = []
            total = 0.0

            for cart_item in cart_items:
                product_id = cart_item.get("product_id")
                quantity = int(cart_item.get("quantity", 1))

                cur.execute(
                    """
                    SELECT id, name, price, inventory_count, status
                    FROM store_products
                    WHERE id = %s AND status = 'active'
                    """,
                    (product_id,),
                )
                product = cur.fetchone()

                if not product:
                    return jsonify({"error": f"product {product_id} not found or unavailable"}), 400

                if product["inventory_count"] < quantity:
                    return jsonify({"error": f"insufficient stock for {product['name']}"}), 400

                item_total = float(product["price"]) * quantity
                total += item_total

                order_items.append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "quantity": quantity,
                    "price": float(product["price"]),
                    "total": item_total,
                })

                stripe_line_items.append({
                    "name": product["name"],
                    "quantity": quantity,
                    "price": float(product["price"]),
                })

            # Create the order
            import uuid

            order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"

            cur.execute(
                """
                INSERT INTO store_orders
                    (order_number, customer_name, customer_email, status,
                     payment_status, total, shipping_address, metadata)
                VALUES (%s, %s, %s, 'pending', 'unpaid', %s, %s, %s)
                RETURNING id
                """,
                (
                    order_number,
                    data.get("name", ""),
                    data["email"],
                    round(total, 2),
                    Json(data.get("shipping_address", {})),
                    Json({"source": "public_storefront", "guest_checkout": True}),
                ),
            )
            order = cur.fetchone()
            order_id = order["id"]

            # Insert order items
            for item in order_items:
                cur.execute(
                    """
                    INSERT INTO store_order_items (order_id, product_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (order_id, item["product_id"], item["quantity"], item["price"]),
                )

                # Decrement inventory
                cur.execute(
                    """
                    UPDATE store_products
                    SET inventory_count = inventory_count - %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (item["quantity"], item["product_id"]),
                )

        # Create Stripe Checkout session
        try:
            from core.stripe_checkout import create_order_checkout_session

            result = create_order_checkout_session(
                order_items=stripe_line_items,
                order_id=order_id,
                customer_email=data["email"],
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.exception("Failed to create Stripe checkout for order %s", order_id)
            return jsonify({"error": f"Payment setup failed: {str(exc)}"}), 500

        event_bus.emit(
            "order.created",
            {
                "order_id": order_id,
                "order_number": order_number,
                "customer_email": data["email"],
                "total": round(total, 2),
            },
            tenant_id=tenant_id,
        )

        return jsonify({
            "order_id": order_id,
            "order_number": order_number,
            "checkout_url": result["url"],
            "session_id": result["session_id"],
        }), 201
