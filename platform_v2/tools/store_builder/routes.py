"""
Store Builder Routes
====================
E-commerce store building with product management and payments.

Dual-purpose module:
- Admin: Manages ARCHIE company store (courses, APIs, services)
- Users: Build their own e-commerce stores with their own payment providers

Author: A.R.C.H.I.E. Platform
Date: 2026-01-12
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import os
import json

# Import user context helpers
try:
    from services.user_context import (
        get_user_filter,
        can_access_resource,
        require_ownership,
        add_user_id_to_data,
        is_admin_user,
        log_user_activity,
    )
except ImportError:

    def get_user_filter(*args, **kwargs):
        return f"user_id = {current_user.id}" if current_user.is_authenticated else "1=0"

    def can_access_resource(user_id):
        return current_user.is_authenticated and (
            current_user.id == user_id or getattr(current_user, "is_admin", False)
        )

    def is_admin_user():
        return getattr(current_user, "is_admin", False)


# Create blueprint
store_builder_bp = Blueprint(
    "store_builder",
    __name__,
    url_prefix="/tools/store-builder",
    template_folder="../../templates/tools",
)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ============================================================================
# MAIN PAGE
# ============================================================================


@store_builder_bp.route("/")
@login_required
def index():
    """Main Store Builder interface"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get user's stores with stats
        if is_admin_user():
            cur.execute(
                """
                SELECT s.*, u.username as owner_name,
                       COUNT(DISTINCT p.id) as product_count,
                       COUNT(DISTINCT o.id) as order_count,
                       COALESCE(SUM(o.total) FILTER (WHERE o.payment_status = 'paid'), 0) as revenue
                FROM user_stores s
                LEFT JOIN users u ON s.user_id = u.id
                LEFT JOIN store_products p ON s.id = p.store_id
                LEFT JOIN store_orders o ON s.id = o.store_id
                GROUP BY s.id, u.username
                ORDER BY s.updated_at DESC
            """
            )
        else:
            cur.execute(
                """
                SELECT s.*,
                       COUNT(DISTINCT p.id) as product_count,
                       COUNT(DISTINCT o.id) as order_count,
                       COALESCE(SUM(o.total) FILTER (WHERE o.payment_status = 'paid'), 0) as revenue
                FROM user_stores s
                LEFT JOIN store_products p ON s.id = p.store_id
                LEFT JOIN store_orders o ON s.id = o.store_id
                WHERE s.user_id = %s
                GROUP BY s.id
                ORDER BY s.updated_at DESC
            """,
                (current_user.id,),
            )

        stores = cur.fetchall()

        # Get user's payment integrations
        cur.execute(
            """
            SELECT * FROM user_integrations
            WHERE user_id = %s AND service IN ('stripe', 'paypal', 'printful')
        """,
            (current_user.id,),
        )
        integrations = {row["service"]: row for row in cur.fetchall()}

        # Get recent orders summary
        cur.execute(
            """
            SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE status = 'pending') as pending,
                   COALESCE(SUM(total) FILTER (WHERE payment_status = 'paid'), 0) as revenue
            FROM store_orders
            WHERE user_id = %s AND created_at > NOW() - INTERVAL '30 days'
        """,
            (current_user.id,),
        )
        order_stats = cur.fetchone()

        return render_template(
            "store_builder.html",
            stores=stores,
            integrations=integrations,
            order_stats=order_stats,
            is_admin=is_admin_user(),
        )
    except Exception as e:
        current_app.logger.error(f"[StoreBuilder] Error loading: {e}")
        return render_template(
            "store_builder.html",
            stores=[],
            integrations={},
            order_stats={"total": 0, "pending": 0, "revenue": 0},
            error=str(e),
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STORE CRUD
# ============================================================================


@store_builder_bp.route("/api/stores", methods=["GET"])
@login_required
def get_stores():
    """Get all stores for current user"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if is_admin_user() and request.args.get("all") == "true":
            cur.execute(
                """
                SELECT s.*, u.username as owner_name
                FROM user_stores s
                LEFT JOIN users u ON s.user_id = u.id
                ORDER BY s.updated_at DESC
            """
            )
        else:
            cur.execute(
                """
                SELECT * FROM user_stores
                WHERE user_id = %s
                ORDER BY updated_at DESC
            """,
                (current_user.id,),
            )

        stores = cur.fetchall()

        return jsonify({"success": True, "stores": [dict(s) for s in stores]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores", methods=["POST"])
@login_required
def create_store():
    """Create a new store"""
    try:
        data = request.get_json()

        if not data.get("name"):
            return jsonify({"success": False, "error": "Store name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generate slug from name
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")

        # Check for duplicate slug
        cur.execute("SELECT id FROM user_stores WHERE slug = %s", (slug,))
        if cur.fetchone():
            slug = f"{slug}-{current_user.id}"

        # Create store
        cur.execute(
            """
            INSERT INTO user_stores
            (user_id, name, slug, description, settings, contact_email)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                current_user.id,
                data["name"],
                slug,
                data.get("description", ""),
                json.dumps(data.get("settings", {"currency": "USD", "theme": "default"})),
                data.get(
                    "contact_email",
                    current_user.email if hasattr(current_user, "email") else "",
                ),
            ),
        )

        store = cur.fetchone()
        conn.commit()

        try:
            log_user_activity(
                "create",
                "store_builder",
                {"store_name": data["name"]},
                "store",
                store["id"],
            )
        except:
            pass

        return jsonify(
            {
                "success": True,
                "message": "Store created successfully",
                "store": dict(store),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>", methods=["GET"])
@login_required
def get_store(store_id):
    """Get a specific store with products and stats"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get store
        cur.execute("SELECT * FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store:
            return jsonify({"success": False, "error": "Store not found"}), 404

        if not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get products
        cur.execute(
            """
            SELECT * FROM store_products
            WHERE store_id = %s
            ORDER BY sort_order, created_at DESC
        """,
            (store_id,),
        )
        products = cur.fetchall()

        # Get categories
        cur.execute(
            """
            SELECT * FROM store_categories
            WHERE store_id = %s
            ORDER BY sort_order, name
        """,
            (store_id,),
        )
        categories = cur.fetchall()

        # Get recent orders
        cur.execute(
            """
            SELECT * FROM store_orders
            WHERE store_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """,
            (store_id,),
        )
        orders = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "store": dict(store),
                "products": [dict(p) for p in products],
                "categories": [dict(c) for c in categories],
                "orders": [dict(o) for o in orders],
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>", methods=["PUT"])
@login_required
def update_store(store_id):
    """Update a store"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store:
            return jsonify({"success": False, "error": "Store not found"}), 404

        if not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Build update
        updates = []
        values = []
        allowed = [
            "name",
            "description",
            "settings",
            "status",
            "contact_email",
            "contact_phone",
            "address",
            "social_links",
            "logo_url",
            "banner_url",
        ]

        for field in allowed:
            if field in data:
                updates.append(f"{field} = %s")
                val = json.dumps(data[field]) if field in ["settings", "address", "social_links"] else data[field]
                values.append(val)

        if not updates:
            return jsonify({"success": False, "error": "No valid fields"}), 400

        updates.append("updated_at = NOW()")
        values.append(store_id)

        cur.execute(
            f"""
            UPDATE user_stores
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Store updated", "store": dict(updated)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>", methods=["DELETE"])
@login_required
def delete_store(store_id):
    """Delete a store"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify ownership
        cur.execute("SELECT user_id, name FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store:
            return jsonify({"success": False, "error": "Store not found"}), 404

        if not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Delete (CASCADE handles products, orders)
        cur.execute("DELETE FROM user_stores WHERE id = %s", (store_id,))
        conn.commit()

        try:
            log_user_activity(
                "delete",
                "store_builder",
                {"store_name": store["name"]},
                "store",
                store_id,
            )
        except:
            pass

        return jsonify({"success": True, "message": f'Store "{store["name"]}" deleted'})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# PRODUCTS
# ============================================================================


@store_builder_bp.route("/api/stores/<int:store_id>/products", methods=["GET"])
@login_required
def get_products(store_id):
    """Get all products for a store"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            SELECT p.*, c.name as category_name
            FROM store_products p
            LEFT JOIN store_categories c ON p.category_id = c.id
            WHERE p.store_id = %s
            ORDER BY p.sort_order, p.created_at DESC
        """,
            (store_id,),
        )

        products = cur.fetchall()

        return jsonify({"success": True, "products": [dict(p) for p in products]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>/products", methods=["POST"])
@login_required
def create_product(store_id):
    """Create a new product"""
    try:
        data = request.get_json()

        if not data.get("name") or data.get("price") is None:
            return (
                jsonify({"success": False, "error": "Name and price are required"}),
                400,
            )

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Generate slug
        import re

        slug = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")

        cur.execute(
            """
            INSERT INTO store_products
            (store_id, user_id, name, slug, description, short_description,
             sku, price, compare_at_price, images, inventory, category_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                store_id,
                current_user.id,
                data["name"],
                slug,
                data.get("description", ""),
                data.get("short_description", ""),
                data.get("sku"),
                data["price"],
                data.get("compare_at_price"),
                json.dumps(data.get("images", [])),
                data.get("inventory", 0),
                data.get("category_id"),
                data.get("status", "draft"),
            ),
        )

        product = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Product created", "product": dict(product)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/products/<int:product_id>", methods=["PUT"])
@login_required
def update_product(product_id):
    """Update a product"""
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM store_products WHERE id = %s", (product_id,))
        product = cur.fetchone()

        if not product or not can_access_resource(product["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        updates = []
        values = []
        allowed = [
            "name",
            "description",
            "short_description",
            "sku",
            "price",
            "compare_at_price",
            "cost_price",
            "images",
            "inventory",
            "category_id",
            "status",
            "featured",
            "variants",
            "attributes",
            "seo_title",
            "seo_description",
            "tags",
            "sort_order",
        ]

        for field in allowed:
            if field in data:
                updates.append(f"{field} = %s")
                if field in ["images", "variants", "attributes"]:
                    val = json.dumps(data[field])
                elif field == "tags":
                    val = data[field]  # PostgreSQL array
                else:
                    val = data[field]
                values.append(val)

        if not updates:
            return jsonify({"success": False, "error": "No valid fields"}), 400

        updates.append("updated_at = NOW()")
        values.append(product_id)

        cur.execute(
            f"""
            UPDATE store_products
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Product updated", "product": dict(updated)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/products/<int:product_id>", methods=["DELETE"])
@login_required
def delete_product(product_id):
    """Delete a product"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id, name FROM store_products WHERE id = %s", (product_id,))
        product = cur.fetchone()

        if not product or not can_access_resource(product["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute("DELETE FROM store_products WHERE id = %s", (product_id,))
        conn.commit()

        return jsonify({"success": True, "message": f'Product "{product["name"]}" deleted'})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# ORDERS
# ============================================================================


@store_builder_bp.route("/api/stores/<int:store_id>/orders", methods=["GET"])
@login_required
def get_orders(store_id):
    """Get all orders for a store"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        status_filter = request.args.get("status")

        if status_filter:
            cur.execute(
                """
                SELECT * FROM store_orders
                WHERE store_id = %s AND status = %s
                ORDER BY created_at DESC
            """,
                (store_id, status_filter),
            )
        else:
            cur.execute(
                """
                SELECT * FROM store_orders
                WHERE store_id = %s
                ORDER BY created_at DESC
            """,
                (store_id,),
            )

        orders = cur.fetchall()

        return jsonify({"success": True, "orders": [dict(o) for o in orders]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/orders/<int:order_id>", methods=["GET"])
@login_required
def get_order(order_id):
    """Get a specific order with items"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM store_orders WHERE id = %s", (order_id,))
        order = cur.fetchone()

        if not order:
            return jsonify({"success": False, "error": "Order not found"}), 404

        if not can_access_resource(order["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        # Get order items
        cur.execute(
            """
            SELECT * FROM store_order_items
            WHERE order_id = %s
        """,
            (order_id,),
        )
        items = cur.fetchall()

        return jsonify({"success": True, "order": dict(order), "items": [dict(i) for i in items]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/orders/<int:order_id>/status", methods=["PUT"])
@login_required
def update_order_status(order_id):
    """Update order status"""
    try:
        data = request.get_json()

        if not data.get("status"):
            return jsonify({"success": False, "error": "Status is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify access
        cur.execute("SELECT user_id FROM store_orders WHERE id = %s", (order_id,))
        order = cur.fetchone()

        if not order or not can_access_resource(order["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        updates = ["status = %s", "updated_at = NOW()"]
        values = [data["status"]]

        if data.get("tracking_number"):
            updates.append("tracking_number = %s")
            values.append(data["tracking_number"])

        if data.get("tracking_url"):
            updates.append("tracking_url = %s")
            values.append(data["tracking_url"])

        if data["status"] == "shipped":
            updates.append("shipped_at = NOW()")
        elif data["status"] == "delivered":
            updates.append("delivered_at = NOW()")

        values.append(order_id)

        cur.execute(
            f"""
            UPDATE store_orders
            SET {', '.join(updates)}
            WHERE id = %s
            RETURNING *
        """,
            values,
        )

        updated = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Order status updated", "order": dict(updated)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# PAYMENT INTEGRATIONS
# ============================================================================


@store_builder_bp.route("/api/integrations", methods=["GET"])
@login_required
def get_integrations():
    """Get user's payment integrations"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, service, status, settings, last_verified_at, created_at
            FROM user_integrations
            WHERE user_id = %s AND service IN ('stripe', 'paypal', 'printful')
        """,
            (current_user.id,),
        )

        integrations = cur.fetchall()

        return jsonify({"success": True, "integrations": [dict(i) for i in integrations]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/integrations/<service>", methods=["POST"])
@login_required
def connect_integration(service):
    """Connect a payment integration"""
    try:
        allowed_services = ["stripe", "paypal", "printful"]
        if service not in allowed_services:
            return jsonify({"success": False, "error": "Invalid service"}), 400

        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            INSERT INTO user_integrations (user_id, service, credentials, settings, status)
            VALUES (%s, %s, %s, %s, 'active')
            ON CONFLICT (user_id, service)
            DO UPDATE SET
                credentials = EXCLUDED.credentials,
                settings = EXCLUDED.settings,
                status = 'active',
                updated_at = NOW()
            RETURNING id, service, status, settings
        """,
            (
                current_user.id,
                service,
                json.dumps(data.get("credentials", {})),
                json.dumps(data.get("settings", {})),
            ),
        )

        integration = cur.fetchone()
        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": f"{service.title()} connected",
                "integration": dict(integration),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# CATEGORIES
# ============================================================================


@store_builder_bp.route("/api/stores/<int:store_id>/categories", methods=["GET"])
@login_required
def get_categories(store_id):
    """Get categories for a store"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        cur.execute(
            """
            SELECT c.*, COUNT(p.id) as product_count
            FROM store_categories c
            LEFT JOIN store_products p ON c.id = p.category_id
            WHERE c.store_id = %s
            GROUP BY c.id
            ORDER BY c.sort_order, c.name
        """,
            (store_id,),
        )

        categories = cur.fetchall()

        return jsonify({"success": True, "categories": [dict(c) for c in categories]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>/categories", methods=["POST"])
@login_required
def create_category(store_id):
    """Create a category"""
    try:
        data = request.get_json()

        if not data.get("name"):
            return jsonify({"success": False, "error": "Name is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return jsonify({"success": False, "error": "Access denied"}), 403

        import re

        slug = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")

        cur.execute(
            """
            INSERT INTO store_categories
            (store_id, user_id, name, slug, description, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """,
            (
                store_id,
                current_user.id,
                data["name"],
                slug,
                data.get("description", ""),
                data.get("sort_order", 0),
            ),
        )

        category = cur.fetchone()
        conn.commit()

        return jsonify({"success": True, "message": "Category created", "category": dict(category)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# STORE SYNC - Migrated from admin/routes.py
# ============================================================================

# Import Printful integration if available
try:
    from tools.store_builder.printful_integration import sync_products, get_product_catalog

    PRINTFUL_AVAILABLE = True
except ImportError:
    PRINTFUL_AVAILABLE = False


@store_builder_bp.route("/api/sync-products", methods=["POST"])
@login_required
def store_sync_products():
    """Sync products from Printful"""
    # Admin check for syncing
    if not is_admin_user():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    if not PRINTFUL_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Printful integration not available"}),
            503,
        )

    try:
        result = sync_products()
        return jsonify({"success": True, "synced": result["synced"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@store_builder_bp.route("/api/products", methods=["GET"])
@login_required
def store_products_list():
    """Get all products (Printful catalog)"""
    if not PRINTFUL_AVAILABLE:
        return (
            jsonify({"success": False, "error": "Printful integration not available"}),
            503,
        )

    try:
        products = get_product_catalog()
        return jsonify({"success": True, "products": [dict(p) for p in products]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ANALYTICS - Migrated from admin/routes.py
# ============================================================================


@store_builder_bp.route("/api/analytics/user-growth", methods=["GET"])
@login_required
def analytics_user_growth():
    """Get user growth data"""
    # Admin check for analytics
    if not is_admin_user():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM users
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """
        )
        data = cur.fetchall()

        return jsonify({"success": True, "data": [dict(row) for row in data]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/analytics/revenue", methods=["GET"])
@login_required
def analytics_revenue():
    """Get revenue data"""
    # Admin check for analytics
    if not is_admin_user():
        return jsonify({"success": False, "error": "Admin access required"}), 403

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT DATE(created_at) as date, SUM(amount) as revenue
            FROM payments
            WHERE status = 'succeeded'
            AND created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """
        )
        data = cur.fetchall()

        return jsonify({"success": True, "data": [dict(row) for row in data]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# HEALTH CHECK
# ============================================================================


@store_builder_bp.route("/health")
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM user_stores")
        count = cur.fetchone()[0]

        return jsonify({"healthy": True, "module": "store_builder", "total_stores": count})
    except Exception as e:
        return (
            jsonify({"healthy": False, "module": "store_builder", "error": str(e)}),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


# ============================================================================
# WEBSITE INTEGRATION
# ============================================================================


@store_builder_bp.route("/api/stores/<int:store_id>/embed-code", methods=["GET"])
@login_required
def get_embed_code(store_id):
    """Get embeddable widget code for a store"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get store details
        cur.execute(
            """
            SELECT * FROM user_stores WHERE id = %s
        """,
            (store_id,),
        )
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return (
                jsonify({"success": False, "error": "Store not found or access denied"}),
                404,
            )

        # Get products for embed
        cur.execute(
            """
            SELECT id, name, price, images, description
            FROM store_products
            WHERE store_id = %s AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 10
        """,
            (store_id,),
        )
        products = cur.fetchall()

        cur.close()
        conn.close()

        # Generate embed code
        base_url = request.host_url.rstrip("/")
        store_slug = store["slug"] or store_id

        # Product grid widget
        product_grid_embed = f"""<!-- ARCHIE Store Product Grid -->
<div id="archie-store-{store_id}" class="archie-store-widget"></div>
<script>
(function() {{
    var script = document.createElement('script');
    script.src = '{base_url}/api/stores/{store_id}/widget.js';
    script.async = true;
    document.head.appendChild(script);
}})();
</script>"""

        # Buy button widget
        buy_button_embed = f"""<!-- ARCHIE Buy Button -->
<div class="archie-buy-button" data-store="{store_id}" data-product="PRODUCT_ID"></div>
<script src="{base_url}/api/stores/buy-button.js" async></script>"""

        # Cart widget
        cart_embed = f"""<!-- ARCHIE Shopping Cart -->
<div id="archie-cart-{store_id}" class="archie-cart-widget"></div>
<script>
window.ARCHIE_STORE = {{
    storeId: {store_id},
    apiUrl: '{base_url}/tools/store-builder/api'
}};
</script>
<script src="{base_url}/api/stores/cart.js" async></script>"""

        # Full storefront iframe
        iframe_embed = f"""<!-- ARCHIE Full Storefront -->
<iframe
    src="{base_url}/store/{store_slug}"
    width="100%"
    height="800"
    frameborder="0"
    style="border: none; max-width: 100%;">
</iframe>"""

        return jsonify(
            {
                "success": True,
                "store_id": store_id,
                "store_name": store["name"],
                "embeds": {
                    "product_grid": product_grid_embed,
                    "buy_button": buy_button_embed,
                    "cart": cart_embed,
                    "iframe": iframe_embed,
                },
                "products": [dict(p) for p in products],
                "api_endpoints": {
                    "products": f"{base_url}/tools/store-builder/api/stores/{store_id}/products",
                    "cart": f"{base_url}/tools/store-builder/api/stores/{store_id}/cart",
                    "checkout": f"{base_url}/tools/store-builder/api/stores/{store_id}/checkout",
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@store_builder_bp.route("/api/stores/<int:store_id>/storefront-config", methods=["GET"])
@login_required
def get_storefront_config(store_id):
    """Get storefront theme/settings for website integration"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get store details
        cur.execute(
            """
            SELECT * FROM user_stores WHERE id = %s
        """,
            (store_id,),
        )
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return (
                jsonify({"success": False, "error": "Store not found or access denied"}),
                404,
            )

        # Get product count
        cur.execute(
            "SELECT COUNT(*) as count FROM store_products WHERE store_id = %s AND status = 'active'",
            (store_id,),
        )
        product_count = cur.fetchone()["count"]

        # Get categories
        cur.execute(
            """
            SELECT id, name, slug, description, parent_id
            FROM store_categories
            WHERE store_id = %s
            ORDER BY name
        """,
            (store_id,),
        )
        categories = cur.fetchall()

        # Default theme settings
        default_theme = {
            "primary_color": "#6366f1",
            "secondary_color": "#8b5cf6",
            "background_color": "#0f0f1a",
            "text_color": "#ffffff",
            "accent_color": "#10b981",
            "font_family": "Inter, system-ui, sans-serif",
            "border_radius": "12px",
            "button_style": "rounded",
        }

        settings = store.get("settings", {}) or {}
        theme = settings.get("theme", default_theme)

        return jsonify(
            {
                "success": True,
                "store": {
                    "id": store["id"],
                    "name": store["name"],
                    "slug": store["slug"],
                    "description": store["description"],
                    "logo_url": store["logo_url"],
                    "banner_url": store["banner_url"],
                    "contact_email": store["contact_email"],
                    "contact_phone": store["contact_phone"],
                    "social_links": store.get("social_links", {}),
                    "website_id": store.get("website_id"),
                },
                "theme": theme,
                "product_count": product_count,
                "categories": [dict(c) for c in categories],
                "payment_methods": list(store.get("payment_config", {}).keys()),
                "features": {
                    "cart_enabled": True,
                    "checkout_enabled": True,
                    "reviews_enabled": settings.get("reviews_enabled", False),
                    "wishlist_enabled": settings.get("wishlist_enabled", False),
                    "subscriptions_enabled": settings.get("subscriptions_enabled", True),
                },
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>/website-link", methods=["POST"])
@login_required
def link_store_to_website(store_id):
    """Link a store to a website"""
    try:
        data = request.get_json()
        website_id = data.get("website_id")

        if not website_id:
            return jsonify({"success": False, "error": "website_id is required"}), 400

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify store ownership
        cur.execute("SELECT user_id FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or not can_access_resource(store["user_id"]):
            return (
                jsonify({"success": False, "error": "Store not found or access denied"}),
                404,
            )

        # Verify website ownership
        cur.execute("SELECT user_id FROM websites WHERE id = %s", (website_id,))
        website = cur.fetchone()

        if not website or not can_access_resource(website["user_id"]):
            return (
                jsonify({"success": False, "error": "Website not found or access denied"}),
                404,
            )

        # Link store to website
        cur.execute(
            """
            UPDATE user_stores
            SET website_id = %s, updated_at = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (website_id, store_id),
        )

        updated_store = cur.fetchone()

        # Also update website settings to include store reference
        cur.execute(
            """
            UPDATE websites
            SET settings = jsonb_set(
                COALESCE(settings, '{}'::jsonb),
                '{store_id}',
                to_jsonb(%s)
            ),
            updated_at = NOW()
            WHERE id = %s
        """,
            (store_id, website_id),
        )

        conn.commit()

        return jsonify(
            {
                "success": True,
                "message": "Store linked to website successfully",
                "store_id": store_id,
                "website_id": website_id,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/stores/<int:store_id>/public-products", methods=["GET"])
def get_public_products(store_id):
    """Get public products for a store (no auth required for storefront)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Verify store is active
        cur.execute("SELECT status FROM user_stores WHERE id = %s", (store_id,))
        store = cur.fetchone()

        if not store or store["status"] != "active":
            return jsonify({"success": False, "error": "Store not available"}), 404

        # Get products
        category = request.args.get("category")
        search = request.args.get("search")
        sort = request.args.get("sort", "newest")
        limit = min(int(request.args.get("limit", 20)), 100)
        offset = int(request.args.get("offset", 0))

        query = """
            SELECT p.id, p.name, p.slug, p.description, p.price, p.compare_price,
                   p.images, p.category_id, c.name as category_name,
                   p.stock_quantity, p.sku, p.tags
            FROM store_products p
            LEFT JOIN store_categories c ON p.category_id = c.id
            WHERE p.store_id = %s AND p.status = 'active'
        """
        params = [store_id]

        if category:
            query += " AND (c.slug = %s OR c.id = %s)"
            params.extend([category, category if category.isdigit() else -1])

        if search:
            query += " AND (p.name ILIKE %s OR p.description ILIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        # Sorting
        if sort == "price_low":
            query += " ORDER BY p.price ASC"
        elif sort == "price_high":
            query += " ORDER BY p.price DESC"
        elif sort == "name":
            query += " ORDER BY p.name ASC"
        else:  # newest
            query += " ORDER BY p.created_at DESC"

        query += " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        products = cur.fetchall()

        # Get total count
        cur.execute(
            """
            SELECT COUNT(*) FROM store_products
            WHERE store_id = %s AND status = 'active'
        """,
            (store_id,),
        )
        total = cur.fetchone()["count"]

        return jsonify(
            {
                "success": True,
                "products": [dict(p) for p in products],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@store_builder_bp.route("/api/status")
def api_status():
    """Get module status"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT COUNT(*) as count FROM user_stores WHERE status = 'active'")
        active_stores = cur.fetchone()["count"]

        cur.execute("SELECT COUNT(*) as count FROM store_products WHERE status = 'active'")
        active_products = cur.fetchone()["count"]

        cur.execute(
            """
            SELECT COUNT(*) as count FROM store_orders
            WHERE created_at >= CURRENT_DATE
        """
        )
        today_orders = cur.fetchone()["count"]

        return jsonify(
            {
                "module": "store_builder",
                "status": "operational",
                "healthy": True,
                "active_stores": active_stores,
                "active_products": active_products,
                "today_orders": today_orders,
            }
        )

    except Exception as e:
        return (
            jsonify(
                {
                    "module": "store_builder",
                    "status": "error",
                    "healthy": False,
                    "error": str(e),
                }
            ),
            500,
        )
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
