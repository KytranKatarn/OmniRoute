"""Tests for the Salon/Hairdressing industry plugin — services, stylists, bookings, inventory, client history."""

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_TENANT_ID = 9916
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "salontest@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_CRM = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
MIGRATION_INVOICING = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_invoicing", "migrations", "001_invoicing_tables.sql"
)
MIGRATION_INDUSTRY = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_industry", "migrations", "001_industry_tables.sql"
)
MIGRATION_SALON = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_salon_tables.sql"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def salon_app():
    """Create Flask app with Salon + Industry + CRM plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def salon_setup(salon_app):
    """Create test tenant, user, schema, tables, and enable required modules."""
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up leftovers from a previous failed run
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'Salon Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Salon Test Tenant', 'salon-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Ensure module_catalog entries exist (FK requirement)
        for slug, name, tier, category in [
            ("industry", "Industry Framework", "business", "ecommerce"),
            ("industry-salon", "Salon & Hairdressing", "business", "ecommerce"),
        ]:
            cur.execute(
                """
                INSERT INTO module_catalog (slug, name, tier_required, category)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO NOTHING
                """,
                (slug, name, tier, category),
            )

        # Enable all required modules
        for slug in ("crm", "invoicing", "industry", "industry-salon"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create tenant schema and run migrations in dependency order
    create_tenant_schema(TEST_TENANT_ID)
    if os.path.exists(MIGRATION_CRM):
        run_migration_file(MIGRATION_CRM, schema=TEST_SCHEMA)
    if os.path.exists(MIGRATION_INVOICING):
        run_migration_file(MIGRATION_INVOICING, schema=TEST_SCHEMA)
    if os.path.exists(MIGRATION_INDUSTRY):
        run_migration_file(MIGRATION_INDUSTRY, schema=TEST_SCHEMA)
    run_migration_file(MIGRATION_SALON, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(salon_app, salon_setup):
    """Yield a logged-in test client."""
    with salon_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"
        yield client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = "/plugins/industry-salon"


def post_json(client, path, payload):
    return client.post(
        BASE + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        BASE + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Test 1 — Create service
# ---------------------------------------------------------------------------

class TestServices:
    """Test 1 — create and update a salon service."""

    def test_create_service(self, authed_client):
        resp = post_json(authed_client, "/api/services", {
            "name": "Balayage & Toner",
            "category": "color",
            "duration_minutes": 150,
            "price": 220.00,
            "description": "Hand-painted highlights with glossing toner finish",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Balayage & Toner"
        assert data["category"] == "color"
        assert data["duration_minutes"] == 150
        assert data["is_active"] is True
        TestServices._service_id = data["id"]

    def test_update_service(self, authed_client):
        resp = put_json(authed_client, f"/api/services/{TestServices._service_id}", {
            "price": 235.00,
            "description": "Hand-painted highlights with glossing toner — updated pricing",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert float(data["price"]) == 235.00

    def test_list_services(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/services")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "services" in data
        assert data["total"] >= 1


# ---------------------------------------------------------------------------
# Test 2 — Add stylist
# ---------------------------------------------------------------------------

class TestStylists:
    """Test 2 — create and update a stylist."""

    def test_add_stylist(self, authed_client):
        resp = post_json(authed_client, "/api/stylists", {
            "name": "Camille Dupont",
            "specialties": ["color", "balayage", "extensions"],
            "commission_rate": 45.00,
            "bio": "10 years experience in colour artistry and balayage techniques.",
            "schedule": {"mon": "09:00-17:00", "wed": "09:00-17:00", "fri": "09:00-18:00"},
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Camille Dupont"
        assert float(data["commission_rate"]) == 45.00
        assert data["is_active"] is True
        TestStylists._stylist_id = data["id"]

    def test_update_stylist(self, authed_client):
        resp = put_json(authed_client, f"/api/stylists/{TestStylists._stylist_id}", {
            "commission_rate": 48.00,
            "bio": "Senior colour specialist — 12 years experience.",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert float(data["commission_rate"]) == 48.00

    def test_list_stylists(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/stylists")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "stylists" in data
        assert data["total"] >= 1


# ---------------------------------------------------------------------------
# Test 3 — Book appointment
# ---------------------------------------------------------------------------

class TestBookings:
    """Test 3 & 4 — create booking and update status."""

    def test_book_appointment(self, authed_client):
        resp = post_json(authed_client, "/api/bookings", {
            "customer_id": 1001,
            "stylist_id": TestStylists._stylist_id,
            "service_id": TestServices._service_id,
            "booking_date": "2026-04-10",
            "start_time": "10:00",
            "end_time": "12:30",
            "notes": "Client wants natural-looking highlights — no heavy contrast",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["status"] == "scheduled"
        assert data["customer_id"] == 1001
        TestBookings._booking_id = data["id"]

    def test_get_booking(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/bookings/{TestBookings._booking_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["booking_date"] == "2026-04-10"

    def test_list_bookings(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/bookings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "bookings" in data
        assert data["total"] >= 1

    def test_list_bookings_stylist_filter(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/bookings?stylist_id={TestStylists._stylist_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(b["stylist_id"] == TestStylists._stylist_id for b in data["bookings"])

    # Test 4 — update booking status
    def test_update_booking_status(self, authed_client):
        resp = put_json(authed_client, f"/api/bookings/{TestBookings._booking_id}/status", {
            "status": "confirmed",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "confirmed"

    def test_cancel_booking(self, authed_client):
        # Create a second booking to cancel
        resp = post_json(authed_client, "/api/bookings", {
            "customer_id": 1002,
            "booking_date": "2026-04-11",
            "start_time": "14:00",
        })
        assert resp.status_code == 201
        cancel_id = resp.get_json()["id"]

        resp = authed_client.post(f"{BASE}/api/bookings/{cancel_id}/cancel")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "cancelled"


# ---------------------------------------------------------------------------
# Test 5 & 6 — Product inventory + low stock
# ---------------------------------------------------------------------------

class TestInventory:
    """Test 5 — add product; Test 6 — low stock check."""

    def test_add_product(self, authed_client):
        resp = post_json(authed_client, "/api/inventory", {
            "name": "Wella Koleston Perfect 7/0",
            "brand": "Wella",
            "category": "color",
            "sku": "WK-700",
            "quantity": 12,
            "min_quantity": 5,
            "retail_price": 18.50,
            "cost_price": 9.20,
            "supplier": "Salon Supplies Co.",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Wella Koleston Perfect 7/0"
        assert data["quantity"] == 12
        TestInventory._product_id = data["id"]

    def test_update_product_quantity(self, authed_client):
        resp = put_json(authed_client, f"/api/inventory/{TestInventory._product_id}", {
            "quantity": 3,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["quantity"] == 3

    def test_low_stock_check(self, authed_client):
        # quantity=3 <= min_quantity=5 so this product must appear
        resp = authed_client.get(f"{BASE}/api/inventory?low_stock=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "products" in data
        ids = [p["id"] for p in data["products"]]
        assert TestInventory._product_id in ids

    def test_list_inventory(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/inventory")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "products" in data
        assert data["total"] >= 1


# ---------------------------------------------------------------------------
# Test 7 — Client history
# ---------------------------------------------------------------------------

class TestClientHistory:
    """Test 7 — add and retrieve client history entry."""

    def test_add_client_history(self, authed_client):
        resp = post_json(authed_client, "/api/client-history", {
            "customer_id": 1001,
            "stylist_id": TestStylists._stylist_id,
            "service_id": TestServices._service_id,
            "visit_date": "2026-03-15",
            "formula": "10vol developer + 7/0 base, 9/3 highlights",
            "color_used": "Wella Koleston 7/0, 9/3",
            "notes": "Left natural at roots — client happy with result",
            "satisfaction": 5,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["customer_id"] == 1001
        assert data["satisfaction"] == 5
        assert data["formula"] == "10vol developer + 7/0 base, 9/3 highlights"
        TestClientHistory._history_id = data["id"]

    def test_list_client_history_by_customer(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/client-history?customer_id=1001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "history" in data
        assert data["total"] >= 1
        assert all(h["customer_id"] == 1001 for h in data["history"])


# ---------------------------------------------------------------------------
# Test 8 — Stats
# ---------------------------------------------------------------------------

class TestStats:
    """Test 8 — stats endpoint."""

    def test_stats(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "bookings_today" in data
        assert "completed_this_week" in data
        assert "low_stock_products" in data
        assert "revenue_this_month" in data
        # We set quantity below min — at least 1 low stock product
        assert data["low_stock_products"] >= 1
