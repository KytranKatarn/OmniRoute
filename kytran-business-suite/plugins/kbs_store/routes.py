"""Store plugin routes — products, orders, categories, stats."""

import json as _json
import logging
import uuid

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.printful_client import get_printful_client
from core.stripe_checkout import create_order_checkout_session
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Store routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("store")
    def index():
        return render_template("store.html")

    # ------------------------------------------------------------------
    # Products CRUD
    # ------------------------------------------------------------------

    @bp.route("/api/products", methods=["GET"])
    @login_required
    @require_module("store")
    def list_products():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        category = request.args.get("category")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where_parts = []
            params: list = []
            if status:
                where_parts.append("status = %s")
                params.append(status)
            if category:
                where_parts.append("category = %s")
                params.append(category)

            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM store_products {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, name, description, sku, price, compare_at_price,
                       inventory_count, status, category, images, metadata,
                       created_at, updated_at
                FROM store_products {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            products = cur.fetchall()

        return jsonify(
            {
                "products": products,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/products", methods=["POST"])
    @login_required
    @require_module("store")
    def create_product():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        try:
            price = float(data.get("price", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "price must be a number"}), 400
        if price < 0:
            return jsonify({"error": "price is required and must be >= 0"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO store_products
                    (name, description, sku, price, compare_at_price,
                     inventory_count, status, category, images, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, description, sku, price, compare_at_price,
                          inventory_count, status, category, images, metadata,
                          created_at, updated_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("sku"),
                    price,
                    data.get("compare_at_price"),
                    data.get("inventory_count", 0),
                    data.get("status", "active"),
                    data.get("category"),
                    Json(data.get("images", [])),
                    Json(data.get("metadata", {})),
                ),
            )
            product = cur.fetchone()

        event_bus.emit(
            "product.created",
            {"product_id": product["id"], "name": product["name"]},
            tenant_id=g.tenant_id,
        )
        return jsonify(product), 201

    @bp.route("/api/products/<int:product_id>", methods=["GET"])
    @login_required
    @require_module("store")
    def get_product(product_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, sku, price, compare_at_price,
                       inventory_count, status, category, images, metadata,
                       created_at, updated_at
                FROM store_products
                WHERE id = %s
                """,
                (product_id,),
            )
            product = cur.fetchone()

        if product is None:
            return jsonify({"error": "product not found"}), 404
        return jsonify(product)

    @bp.route("/api/products/<int:product_id>", methods=["PUT"])
    @login_required
    @require_module("store")
    def update_product(product_id):
        data = request.get_json(force=True)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM store_products WHERE id = %s", (product_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "product not found"}), 404

            fields = []
            params: list = []
            allowed = [
                "name", "description", "sku", "price", "compare_at_price",
                "inventory_count", "status", "category",
            ]
            for field in allowed:
                if field in data:
                    fields.append(f"{field} = %s")
                    params.append(data[field])
            if "images" in data:
                fields.append("images = %s")
                params.append(Json(data["images"]))
            if "metadata" in data:
                fields.append("metadata = %s")
                params.append(Json(data["metadata"]))

            if not fields:
                return jsonify({"error": "no fields to update"}), 400

            fields.append("updated_at = NOW()")
            params.append(product_id)

            cur.execute(
                f"""
                UPDATE store_products SET {', '.join(fields)}
                WHERE id = %s
                RETURNING id, name, description, sku, price, compare_at_price,
                          inventory_count, status, category, images, metadata,
                          created_at, updated_at
                """,
                params,
            )
            product = cur.fetchone()

        return jsonify(product)

    @bp.route("/api/products/<int:product_id>", methods=["DELETE"])
    @login_required
    @require_module("store")
    def delete_product(product_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM store_products WHERE id = %s", (product_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "product not found"}), 404

            cur.execute(
                "UPDATE store_products SET status = 'archived', updated_at = NOW() WHERE id = %s",
                (product_id,),
            )

        return jsonify({"archived": True, "id": product_id})

    @bp.route("/api/products/<int:product_id>/inventory", methods=["PUT"])
    @login_required
    @require_module("store")
    def update_inventory(product_id):
        data = request.get_json(force=True)
        quantity = data.get("quantity")
        if quantity is None:
            return jsonify({"error": "quantity is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE store_products SET inventory_count = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, inventory_count
                """,
                (int(quantity), product_id),
            )
            product = cur.fetchone()

        if not product:
            return jsonify({"error": "product not found"}), 404

        if product["inventory_count"] <= 5:
            event_bus.emit(
                "product.low_stock",
                {"product_id": product["id"], "name": product["name"], "stock_quantity": product["inventory_count"]},
                tenant_id=g.tenant_id,
            )

        return jsonify(product)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    @bp.route("/api/orders", methods=["GET"])
    @login_required
    @require_module("store")
    def list_orders():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        status = request.args.get("status")
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            where = ""
            params: list = []
            if status:
                where = "WHERE status = %s"
                params.append(status)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM store_orders {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, order_number, customer_id, status, subtotal, tax,
                       shipping, total, shipping_address, tracking_number,
                       notes, metadata, created_at, updated_at
                FROM store_orders {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            orders = cur.fetchall()

        return jsonify(
            {
                "orders": orders,
                "total": total,
                "page": page,
                "per_page": per_page,
            }
        )

    @bp.route("/api/orders", methods=["POST"])
    @login_required
    @require_module("store")
    def create_order():
        data = request.get_json(force=True)
        items_data = data.get("items", [])
        if not items_data:
            return jsonify({"error": "items are required"}), 400

        order_number = "ORD-" + uuid.uuid4().hex[:8].upper()

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Calculate totals from items
            subtotal = 0.0
            resolved_items = []
            for item in items_data:
                product_name = item.get("product_name", "")
                unit_price = float(item.get("unit_price", 0))
                quantity = int(item.get("quantity", 1))
                product_id = item.get("product_id")

                # If product_id provided, look up name/price as fallback
                if product_id and not product_name:
                    cur.execute(
                        "SELECT name, price FROM store_products WHERE id = %s",
                        (product_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        product_name = product_name or row["name"]
                        unit_price = unit_price or float(row["price"])

                if not product_name:
                    return jsonify({"error": "product_name is required for each item"}), 400

                item_total = unit_price * quantity
                subtotal += item_total
                resolved_items.append(
                    {
                        "product_id": product_id,
                        "product_name": product_name,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "total": item_total,
                    }
                )

            tax = float(data.get("tax", 0))
            shipping = float(data.get("shipping", 0))
            total = subtotal + tax + shipping

            cur.execute(
                """
                INSERT INTO store_orders
                    (order_number, customer_id, status, subtotal, tax, shipping, total,
                     shipping_address, tracking_number, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, order_number, customer_id, status, subtotal, tax,
                          shipping, total, shipping_address, tracking_number,
                          notes, metadata, created_at, updated_at
                """,
                (
                    order_number,
                    data.get("customer_id"),
                    data.get("status", "pending"),
                    subtotal,
                    tax,
                    shipping,
                    total,
                    Json(data.get("shipping_address", {})),
                    data.get("tracking_number"),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            order = cur.fetchone()
            order_id = order["id"]

            # Insert order items
            for item in resolved_items:
                cur.execute(
                    """
                    INSERT INTO store_order_items
                        (order_id, product_id, product_name, quantity, unit_price, total)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        item["product_id"],
                        item["product_name"],
                        item["quantity"],
                        item["unit_price"],
                        item["total"],
                    ),
                )

        event_bus.emit(
            "order.created",
            {
                "order_id": order_id,
                "order_number": order_number,
                "customer_id": data.get("customer_id"),
                "total": total,
                "_tenant_id": g.tenant_id,
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(order), 201

    @bp.route("/api/orders/<int:order_id>", methods=["GET"])
    @login_required
    @require_module("store")
    def get_order(order_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, order_number, customer_id, status, subtotal, tax,
                       shipping, total, shipping_address, tracking_number,
                       notes, metadata, created_at, updated_at
                FROM store_orders
                WHERE id = %s
                """,
                (order_id,),
            )
            order = cur.fetchone()

            if order is None:
                return jsonify({"error": "order not found"}), 404

            cur.execute(
                """
                SELECT id, product_id, product_name, quantity, unit_price, total, created_at
                FROM store_order_items
                WHERE order_id = %s
                ORDER BY id
                """,
                (order_id,),
            )
            order["items"] = cur.fetchall()

        return jsonify(order)

    @bp.route("/api/orders/<int:order_id>/status", methods=["PUT"])
    @login_required
    @require_module("store")
    def update_order_status(order_id):
        data = request.get_json(force=True)
        new_status = (data.get("status") or "").strip()
        valid_statuses = ("pending", "processing", "shipped", "delivered", "cancelled", "refunded")
        if new_status not in valid_statuses:
            return jsonify({"error": f"status must be one of {valid_statuses}"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM store_orders WHERE id = %s", (order_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "order not found"}), 404

            extra_fields = ""
            extra_params: list = []
            if new_status == "shipped" and data.get("tracking_number"):
                extra_fields = ", tracking_number = %s"
                extra_params.append(data["tracking_number"])

            cur.execute(
                f"""
                UPDATE store_orders
                SET status = %s{extra_fields}, updated_at = NOW()
                WHERE id = %s
                RETURNING id, order_number, customer_id, status, subtotal, tax,
                          shipping, total, shipping_address, tracking_number,
                          notes, metadata, created_at, updated_at
                """,
                [new_status] + extra_params + [order_id],
            )
            order = cur.fetchone()

        if new_status == "shipped":
            event_bus.emit(
                "order.shipped",
                {"order_id": order_id, "tracking_number": order.get("tracking_number"), "_tenant_id": g.tenant_id},
                tenant_id=g.tenant_id,
            )
        elif new_status == "delivered":
            event_bus.emit(
                "order.completed",
                {"order_id": order_id, "_tenant_id": g.tenant_id},
                tenant_id=g.tenant_id,
            )

        return jsonify(order)

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    @bp.route("/api/categories", methods=["GET"])
    @login_required
    @require_module("store")
    def list_categories():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, name, description, parent_id, sort_order, created_at
                FROM store_categories
                ORDER BY sort_order, name
                """
            )
            categories = cur.fetchall()
        return jsonify({"categories": categories})

    @bp.route("/api/categories", methods=["POST"])
    @login_required
    @require_module("store")
    def create_category():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO store_categories (name, description, parent_id, sort_order)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, description, parent_id, sort_order, created_at
                """,
                (
                    name,
                    data.get("description"),
                    data.get("parent_id"),
                    data.get("sort_order", 0),
                ),
            )
            category = cur.fetchone()

        return jsonify(category), 201

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("store")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_products,
                    COUNT(*) FILTER (WHERE status = 'active') AS active_products
                FROM store_products
                """
            )
            product_stats = cur.fetchone()

            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_orders,
                    COALESCE(SUM(total), 0) AS revenue
                FROM store_orders
                WHERE status NOT IN ('cancelled', 'refunded')
                """
            )
            order_stats = cur.fetchone()

        return jsonify(
            {
                "total_products": product_stats["total_products"],
                "active_products": product_stats["active_products"],
                "total_orders": order_stats["total_orders"],
                "revenue": float(order_stats["revenue"]),
            }
        )

    # ------------------------------------------------------------------
    # Printful Integration
    # ------------------------------------------------------------------

    @bp.route("/api/printful/sync", methods=["POST"])
    @login_required
    @require_module("store")
    def sync_printful_products():
        """Pull synced products from Printful and upsert into the store."""
        client = get_printful_client()
        if not client:
            return jsonify({"error": "Printful integration not configured"}), 400

        try:
            sync_products = client.get_sync_products()
        except Exception as exc:
            logger.exception("Failed to fetch Printful products")
            return jsonify({"error": f"Printful API error: {str(exc)}"}), 502

        created = 0
        updated = 0

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            for sp in sync_products:
                # Fetch full product with variants
                try:
                    detail = client.get_sync_product(sp["id"])
                except Exception:
                    logger.warning("Failed to fetch Printful product %s", sp["id"])
                    continue

                sync_product = detail.get("sync_product", detail)
                variants = detail.get("sync_variants", [])
                first_variant = variants[0] if variants else {}

                name = sync_product.get("name", "")
                price = float(first_variant.get("retail_price", 0))
                printful_id = str(sync_product.get("id", ""))
                images = []
                if sync_product.get("thumbnail_url"):
                    images.append(sync_product["thumbnail_url"])

                # Upsert by printful_sync_id
                cur.execute(
                    "SELECT id FROM store_products WHERE metadata->>'printful_sync_id' = %s",
                    (printful_id,),
                )
                existing = cur.fetchone()

                if existing:
                    cur.execute(
                        """
                        UPDATE store_products
                        SET name = %s, price = %s, images = %s,
                            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            name,
                            price,
                            Json(images),
                            Json({
                                "printful_sync_id": printful_id,
                                "printful_variants": [
                                    {"id": v.get("id"), "variant_id": v.get("variant_id"), "price": v.get("retail_price")}
                                    for v in variants
                                ],
                            }),
                            existing["id"],
                        ),
                    )
                    updated += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO store_products
                            (name, description, price, status, category, images, metadata, inventory_count)
                        VALUES (%s, %s, %s, 'active', 'printful', %s, %s, 999)
                        """,
                        (
                            name,
                            f"Print-on-demand: {name}",
                            price,
                            Json(images),
                            Json({
                                "printful_sync_id": printful_id,
                                "printful_product": True,
                                "printful_variants": [
                                    {"id": v.get("id"), "variant_id": v.get("variant_id"), "price": v.get("retail_price")}
                                    for v in variants
                                ],
                            }),
                        ),
                    )
                    created += 1

        return jsonify({
            "synced": created + updated,
            "created": created,
            "updated": updated,
        })

    @bp.route("/api/products/<int:product_id>/printful-link", methods=["PUT"])
    @login_required
    @require_module("store")
    def link_printful_product(product_id):
        """Link an existing KBS product to a Printful variant."""
        data = request.get_json(force=True)
        printful_variant_id = data.get("printful_variant_id")
        printful_sync_id = data.get("printful_sync_id")

        if not printful_variant_id:
            return jsonify({"error": "printful_variant_id is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT id FROM store_products WHERE id = %s", (product_id,))
            if cur.fetchone() is None:
                return jsonify({"error": "product not found"}), 404

            cur.execute(
                """
                UPDATE store_products
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, name, metadata
                """,
                (
                    Json({
                        "printful_product": True,
                        "printful_variant_id": printful_variant_id,
                        "printful_sync_id": printful_sync_id or "",
                    }),
                    product_id,
                ),
            )
            product = cur.fetchone()

        return jsonify(product)


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------


def on_contact_created(data):
    """Placeholder — no action needed when a contact is created."""
    pass


def on_invoice_paid(data):
    """Update linked order to 'processing' when an invoice is paid."""
    order_id = data.get("order_id")
    tenant_id = data.get("_tenant_id")
    if not order_id or not tenant_id:
        return
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE store_orders
                SET status = 'processing', updated_at = NOW()
                WHERE id = %s AND status = 'pending'
                """,
                (order_id,),
            )
    except Exception:
        logger.exception("Failed to update order %s on invoice.paid", order_id)


def on_order_paid(data):
    """When an order is paid, submit Printful-linked items for fulfillment."""
    order_id = data.get("order_id")
    tenant_id = data.get("_tenant_id")
    if not order_id or not tenant_id:
        return
    try:
        client = get_printful_client()
        if not client:
            return

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            cur.execute(
                "SELECT id, customer_name, customer_email, shipping_address, metadata FROM store_orders WHERE id = %s",
                (order_id,),
            )
            order = cur.fetchone()
            if not order:
                return

            cur.execute(
                """
                SELECT oi.product_id, oi.quantity, p.metadata AS product_metadata
                FROM store_order_items oi
                JOIN store_products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                """,
                (order_id,),
            )
            items = cur.fetchall()

            printful_items = []
            for item in items:
                meta = item.get("product_metadata") or {}
                if isinstance(meta, str):
                    meta = _json.loads(meta)
                if meta.get("printful_product") and meta.get("printful_variant_id"):
                    printful_items.append({
                        "variant_id": int(meta["printful_variant_id"]),
                        "quantity": item["quantity"],
                    })

            if not printful_items:
                return

            shipping = order.get("shipping_address") or {}
            if isinstance(shipping, str):
                shipping = _json.loads(shipping)

            printful_order = {
                "external_id": str(order_id),
                "recipient": {
                    "name": order.get("customer_name", ""),
                    "email": order.get("customer_email", ""),
                    "address1": shipping.get("address1", ""),
                    "city": shipping.get("city", ""),
                    "state_code": shipping.get("state_code", ""),
                    "country_code": shipping.get("country_code", "CA"),
                    "zip": shipping.get("zip", ""),
                },
                "items": printful_items,
            }

            result = client.create_order(printful_order, confirm=False)

            cur.execute(
                """
                UPDATE store_orders
                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb, updated_at = NOW()
                WHERE id = %s
                """,
                (Json({"printful_order_id": result.get("id"), "printful_status": result.get("status")}), order_id),
            )
        logger.info("Submitted Printful order for KBS order %s", order_id)
    except Exception:
        logger.exception("Failed to submit Printful order for KBS order %s", order_id)
