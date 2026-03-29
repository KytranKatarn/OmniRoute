"""Public storefront routes — no login required for browsing.

These routes are mounted at /store/public/ and serve as the
public-facing storefront for each tenant. Guest checkout is supported
via email address (no account required).
"""

import json as _json
import logging
import os

import stripe
from flask import g, jsonify, render_template, request
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("KBS_STRIPE_SECRET_KEY", "")
_STRIPE_WEBHOOK_SECRET = os.getenv("KBS_STRIPE_WEBHOOK_SECRET", "")


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


def _create_tenant_checkout(tenant_keys, line_items, order_id, customer_email, tenant_id):
    """Create a Stripe Checkout Session using the tenant's own Stripe keys.

    This allows tenants to receive payments directly into their own Stripe account
    instead of going through the platform's account.
    """
    _BASE = os.getenv("KBS_BASE_URL", "https://app.kytranempowerment.com")

    stripe_items = []
    for item in line_items:
        unit_amount = int(round(float(item.get("price", 0)) * 100))
        stripe_items.append({
            "price_data": {
                "currency": "cad",
                "product_data": {"name": item.get("name", "Store item")},
                "unit_amount": unit_amount,
            },
            "quantity": int(item.get("quantity", 1)),
        })

    session = stripe.checkout.Session.create(
        mode="payment",
        customer_email=customer_email,
        line_items=stripe_items,
        metadata={
            "order_id": str(order_id),
            "tenant_id": str(tenant_id),
            "source": "kbs_store_tenant",
        },
        success_url=f"{_BASE}/store/order-success?order={order_id}",
        cancel_url=f"{_BASE}/store/order-cancelled?order={order_id}",
        api_key=tenant_keys["secret_key"],
    )

    # Save session ID on order
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE store_orders
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb, updated_at = NOW()
                WHERE id = %s
                """,
                (Json({"stripe_checkout_session_id": session.id, "stripe_account": "tenant"}), order_id),
            )
    except Exception:
        logger.warning("Failed to save tenant checkout session for order %s", order_id)

    return {"url": session.url, "session_id": session.id}


def _log_webhook(source: str, event_type: str, event_id, payload, processed: bool, error_message: str = None):
    """Log a webhook event to the store_webhook_logs table."""
    try:
        # Use tenant_1 schema for webhook logs
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, 1)
            cur.execute(
                """
                INSERT INTO store_webhook_logs (source, event_type, event_id, payload, processed, error_message)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    source,
                    event_type,
                    str(event_id) if event_id else None,
                    Json(payload if isinstance(payload, dict) else {"raw": str(payload)[:5000]}),
                    processed,
                    error_message,
                ),
            )
    except Exception:
        logger.warning("Failed to log webhook event: %s/%s", source, event_type)


def _resolve_tenant(tenant_slug: str):
    """Look up tenant_id from slug. Returns tenant dict or None.

    Falls back to the first active tenant when no slug is provided
    (single-tenant deployments).
    """
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        if tenant_slug:
            cur.execute(
                "SELECT id, name, slug, settings FROM tenants WHERE slug = %s AND is_active = TRUE",
                (tenant_slug,),
            )
        else:
            # Single-tenant fallback — return the first active tenant
            cur.execute(
                "SELECT id, name, slug, settings FROM tenants WHERE is_active = TRUE ORDER BY id LIMIT 1"
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
        # Try tenant-specific Stripe keys first, fall back to platform key
        try:
            from plugins.kbs_store.routes import get_tenant_stripe_keys

            tenant_keys = get_tenant_stripe_keys(tenant_id)
            if tenant_keys:
                # Use tenant's own Stripe account
                result = _create_tenant_checkout(
                    tenant_keys, stripe_line_items, order_id, data["email"], tenant_id,
                )
            else:
                # Fall back to platform Stripe key
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

    # ------------------------------------------------------------------
    # Stripe Webhook
    # ------------------------------------------------------------------

    @bp.route("/webhook/stripe", methods=["POST"])
    def stripe_webhook():
        """Handle Stripe webhook events for payment confirmation."""
        payload = request.get_data(as_text=True)
        sig_header = request.headers.get("Stripe-Signature", "")

        # Verify signature
        event = None
        if _STRIPE_WEBHOOK_SECRET:
            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, _STRIPE_WEBHOOK_SECRET
                )
            except stripe.error.SignatureVerificationError:
                logger.warning("Stripe webhook signature verification failed")
                _log_webhook("stripe", "signature_failed", None, payload, False, "Signature verification failed")
                return jsonify({"error": "invalid signature"}), 400
            except Exception as exc:
                logger.exception("Stripe webhook error")
                _log_webhook("stripe", "parse_error", None, payload, False, str(exc))
                return jsonify({"error": "webhook error"}), 400
        else:
            # No secret configured — parse raw payload (dev mode)
            try:
                event = _json.loads(payload)
            except Exception:
                return jsonify({"error": "invalid payload"}), 400

        event_type = event.get("type", "") if isinstance(event, dict) else event.type
        event_id = event.get("id", "") if isinstance(event, dict) else event.id

        _log_webhook("stripe", event_type, event_id, payload, True)

        if event_type == "checkout.session.completed":
            session_data = event.get("data", {}).get("object", {}) if isinstance(event, dict) else event.data.object
            metadata = session_data.get("metadata", {}) if isinstance(session_data, dict) else getattr(session_data, "metadata", {})
            order_id = metadata.get("order_id")
            tenant_id = metadata.get("tenant_id")

            if order_id and tenant_id:
                try:
                    tenant_id = int(tenant_id)
                    order_id = int(order_id)
                    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                        set_tenant_search_path(cur, tenant_id)
                        cur.execute(
                            """
                            UPDATE store_orders
                            SET payment_status = 'paid', status = 'processing',
                                metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                                updated_at = NOW()
                            WHERE id = %s
                            RETURNING id, order_number, total
                            """,
                            (
                                Json({"stripe_event_id": str(event_id)}),
                                order_id,
                            ),
                        )
                        order = cur.fetchone()

                    if order:
                        event_bus.emit(
                            "order.paid",
                            {
                                "order_id": order_id,
                                "order_number": order["order_number"],
                                "total": float(order["total"]),
                                "_tenant_id": tenant_id,
                            },
                            tenant_id=tenant_id,
                        )
                        logger.info("Order %s marked as paid via Stripe webhook", order_id)
                except Exception:
                    logger.exception("Failed to process Stripe checkout.session.completed for order %s", order_id)

        # Always return 200 to prevent Stripe retries
        return jsonify({"received": True}), 200

    # ------------------------------------------------------------------
    # Printful Webhook
    # ------------------------------------------------------------------

    @bp.route("/webhook/printful", methods=["POST"])
    def printful_webhook():
        """Handle Printful webhook events for shipping/fulfillment updates."""
        try:
            data = request.get_json(force=True)
        except Exception:
            return jsonify({"error": "invalid payload"}), 400

        event_type = data.get("type", "unknown")
        event_id = data.get("id", "")

        _log_webhook("printful", event_type, str(event_id), data, True)

        order_data = data.get("data", {}).get("order", {})
        external_id = order_data.get("external_id")

        if not external_id:
            return jsonify({"received": True}), 200

        try:
            order_id = int(external_id)
        except (TypeError, ValueError):
            return jsonify({"received": True}), 200

        # Resolve tenant from order metadata — we need to check all tenants
        # In practice, the webhook URL should include tenant context
        # For now, check tenant_1 (single-tenant deployment)
        tenant_id = 1

        try:
            with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, tenant_id)

                if event_type == "package_shipped":
                    shipment = data.get("data", {}).get("shipment", {})
                    tracking_number = shipment.get("tracking_number", "")
                    tracking_url = shipment.get("tracking_url", "")
                    carrier = shipment.get("carrier", "")

                    cur.execute(
                        """
                        UPDATE store_orders
                        SET status = 'shipped',
                            tracking_number = %s,
                            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            tracking_number,
                            Json({
                                "printful_tracking_url": tracking_url,
                                "printful_carrier": carrier,
                                "printful_shipped_at": data.get("created"),
                            }),
                            order_id,
                        ),
                    )

                    event_bus.emit(
                        "order.shipped",
                        {
                            "order_id": order_id,
                            "tracking_number": tracking_number,
                            "_tenant_id": tenant_id,
                        },
                        tenant_id=tenant_id,
                    )
                    logger.info("Order %s marked as shipped via Printful webhook", order_id)

                elif event_type == "package_returned":
                    cur.execute(
                        """
                        UPDATE store_orders
                        SET status = 'cancelled',
                            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            Json({"printful_returned_at": data.get("created")}),
                            order_id,
                        ),
                    )
                    logger.info("Order %s marked as returned via Printful webhook", order_id)

        except Exception:
            logger.exception("Failed to process Printful webhook for order %s", order_id)

        return jsonify({"received": True}), 200

    # ------------------------------------------------------------------
    # Order Success / Cancel Pages
    # ------------------------------------------------------------------

    @bp.route("/order-success", methods=["GET"])
    def order_success():
        """Order confirmation page after successful payment."""
        order_id = request.args.get("order")
        if not order_id:
            return jsonify({"status": "success", "message": "Payment received. Thank you!"}), 200

        tenant = _resolve_tenant(request.view_args.get("tenant_slug", tenant_slug or ""))
        if not tenant:
            return jsonify({"status": "success", "message": "Payment received. Thank you!"}), 200

        try:
            with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
                set_tenant_search_path(cur, tenant["id"])
                cur.execute(
                    """
                    SELECT id, order_number, total, status, payment_status, customer_email, created_at
                    FROM store_orders WHERE id = %s
                    """,
                    (int(order_id),),
                )
                order = cur.fetchone()

            if order:
                return jsonify({
                    "status": "success",
                    "message": "Payment received. Thank you for your order!",
                    "order": order,
                })
        except Exception:
            logger.exception("Error fetching order %s for success page", order_id)

        return jsonify({"status": "success", "message": "Payment received. Thank you!"}), 200

    @bp.route("/order-cancelled", methods=["GET"])
    def order_cancelled():
        """Order cancellation page."""
        return jsonify({
            "status": "cancelled",
            "message": "Your order was cancelled. No payment was charged.",
        }), 200
