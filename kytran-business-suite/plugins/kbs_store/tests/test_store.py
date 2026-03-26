"""Tests for the Store plugin — products, orders, categories, stats."""

import json
import os

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    run_migration_file,
    set_tenant_search_path,
)

# Use a test tenant ID in the 9xxx range to avoid collisions
TEST_TENANT_ID = 9902
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "storetest@example.com"
TEST_PASSWORD = "TestPass123!"
CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
STORE_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_store_tables.sql"
)


@pytest.fixture(scope="module")
def store_app():
    """Create the Flask app with Store + CRM plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def store_setup(store_app):
    """Create test tenant, user, schema, Store + CRM tables, enable both modules.

    Yields the tenant_id. Cleans up afterwards.
    """
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up any leftovers from a previous failed run
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        # Create user
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'Store Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Store Test Tenant', 'store-test-tenant', 'free', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable store + crm modules
        for slug in ("crm", "store"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create tenant schema and run both migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(STORE_MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(store_app, store_setup):
    """Return a logged-in test client."""
    with store_app.test_client() as c:
        # Log in via the login endpoint (form-encoded, same as CRM tests)
        resp = c.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert resp.status_code in (200, 302), f"Login failed: {resp.status_code} {resp.data}"
        yield c


# ----------------------------------------------------------------------
# Product tests
# ----------------------------------------------------------------------


class TestStoreProducts:
    """Product CRUD tests."""

    def test_create_product(self, authed_client):
        resp = authed_client.post(
            "/plugins/store/api/products",
            data=json.dumps(
                {
                    "name": "Test Widget",
                    "price": 19.99,
                    "sku": "WGT-001",
                    "inventory_count": 50,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.data
        data = resp.get_json()
        assert data["name"] == "Test Widget"
        assert float(data["price"]) == 19.99
        assert data["sku"] == "WGT-001"
        assert data["id"] is not None

    def test_list_products(self, authed_client):
        authed_client.post(
            "/plugins/store/api/products",
            data=json.dumps({"name": "List Test Product", "price": 5.00}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/store/api/products")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "products" in data
        assert data["total"] >= 1
        names = [p["name"] for p in data["products"]]
        assert "List Test Product" in names

    def test_get_single_product(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/store/api/products",
            data=json.dumps({"name": "Single Get Product", "price": 9.99}),
            content_type="application/json",
        )
        pid = create_resp.get_json()["id"]
        resp = authed_client.get(f"/plugins/store/api/products/{pid}")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Single Get Product"

    def test_update_product(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/store/api/products",
            data=json.dumps({"name": "Update Product", "price": 1.00}),
            content_type="application/json",
        )
        pid = create_resp.get_json()["id"]
        resp = authed_client.put(
            f"/plugins/store/api/products/{pid}",
            data=json.dumps({"name": "Updated Product Name", "price": 2.50}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Updated Product Name"
        assert float(data["price"]) == 2.50

    def test_delete_product_archives(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/store/api/products",
            data=json.dumps({"name": "Archive Me", "price": 1.00}),
            content_type="application/json",
        )
        pid = create_resp.get_json()["id"]
        resp = authed_client.delete(f"/plugins/store/api/products/{pid}")
        assert resp.status_code == 200
        assert resp.get_json()["archived"] is True

        # Should still be fetchable (archived, not deleted)
        resp2 = authed_client.get(f"/plugins/store/api/products/{pid}")
        assert resp2.status_code == 200
        assert resp2.get_json()["status"] == "archived"


# ----------------------------------------------------------------------
# Order tests
# ----------------------------------------------------------------------


class TestStoreOrders:
    """Order CRUD and status tests."""

    def _create_product(self, authed_client, name="Order Product", price=10.00):
        resp = authed_client.post(
            "/plugins/store/api/products",
            data=json.dumps({"name": name, "price": price}),
            content_type="application/json",
        )
        return resp.get_json()["id"]

    def test_create_order_with_items(self, authed_client):
        pid = self._create_product(authed_client)
        resp = authed_client.post(
            "/plugins/store/api/orders",
            data=json.dumps(
                {
                    "items": [
                        {
                            "product_id": pid,
                            "product_name": "Order Product",
                            "quantity": 2,
                            "unit_price": 10.00,
                        }
                    ],
                    "shipping": 5.00,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201, resp.data
        data = resp.get_json()
        assert data["order_number"].startswith("ORD-")
        assert float(data["subtotal"]) == 20.00
        assert float(data["total"]) == 25.00
        assert data["id"] is not None

    def test_list_orders(self, authed_client):
        pid = self._create_product(authed_client, "List Order Product")
        authed_client.post(
            "/plugins/store/api/orders",
            data=json.dumps(
                {
                    "items": [
                        {"product_name": "List Order Product", "quantity": 1, "unit_price": 5.00}
                    ]
                }
            ),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/store/api/orders")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "orders" in data
        assert data["total"] >= 1

    def test_get_order_with_items(self, authed_client):
        pid = self._create_product(authed_client, "Get Order Product")
        create_resp = authed_client.post(
            "/plugins/store/api/orders",
            data=json.dumps(
                {
                    "items": [
                        {"product_name": "Get Order Product", "quantity": 3, "unit_price": 7.00}
                    ]
                }
            ),
            content_type="application/json",
        )
        oid = create_resp.get_json()["id"]
        resp = authed_client.get(f"/plugins/store/api/orders/{oid}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["product_name"] == "Get Order Product"
        assert data["items"][0]["quantity"] == 3

    def test_update_order_status(self, authed_client):
        pid = self._create_product(authed_client, "Status Order Product")
        create_resp = authed_client.post(
            "/plugins/store/api/orders",
            data=json.dumps(
                {
                    "items": [
                        {"product_name": "Status Order Product", "quantity": 1, "unit_price": 1.00}
                    ]
                }
            ),
            content_type="application/json",
        )
        oid = create_resp.get_json()["id"]
        resp = authed_client.put(
            f"/plugins/store/api/orders/{oid}/status",
            data=json.dumps({"status": "shipped", "tracking_number": "TRACK123"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "shipped"
        assert data["tracking_number"] == "TRACK123"


# ----------------------------------------------------------------------
# Stats test
# ----------------------------------------------------------------------


class TestStoreStats:
    def test_get_stats(self, authed_client):
        resp = authed_client.get("/plugins/store/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_products" in data
        assert "active_products" in data
        assert "total_orders" in data
        assert "revenue" in data
