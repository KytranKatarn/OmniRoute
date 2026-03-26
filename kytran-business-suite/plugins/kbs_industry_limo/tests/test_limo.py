"""Tests for the Limo Service plugin — vehicles, drivers, bookings, dispatch, maintenance, stats."""

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
TEST_TENANT_ID = 9918
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "limotest@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_CRM = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
MIGRATION_INDUSTRY = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_industry", "migrations", "001_industry_tables.sql"
)
MIGRATION_LIMO = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_limo_tables.sql"
)


@pytest.fixture(scope="module")
def limo_app():
    """Create the Flask app with Limo plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def limo_setup(limo_app):
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
            VALUES (%s, 'Limo Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Limo Test Tenant', 'limo-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Ensure required slugs exist in module_catalog
        for slug, name, category in [
            ("crm", "CRM", "ecommerce"),
            ("industry", "Industry Framework", "ecommerce"),
            ("industry-limo", "Limo Service", "ecommerce"),
        ]:
            cur.execute(
                """
                INSERT INTO module_catalog (slug, name, tier_required, category)
                VALUES (%s, %s, 'business', %s)
                ON CONFLICT (slug) DO NOTHING
                """,
                (slug, name, category),
            )

        for slug in ("crm", "industry", "industry-limo"):
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
    if os.path.exists(MIGRATION_INDUSTRY):
        run_migration_file(MIGRATION_INDUSTRY, schema=TEST_SCHEMA)
    run_migration_file(MIGRATION_LIMO, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(limo_app, limo_setup):
    """Yield a logged-in test client with the tenant session set."""
    with limo_app.test_client() as client:
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

def post_json(client, path, payload):
    return client.post(
        "/plugins/industry-limo" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        "/plugins/industry-limo" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVehicles:
    def test_add_vehicle(self, authed_client):
        resp = post_json(authed_client, "/api/vehicles", {
            "name": "Black Lincoln Navigator",
            "vehicle_type": "suv",
            "make": "Lincoln",
            "model": "Navigator",
            "year": 2024,
            "license_plate": "KYT-001",
            "capacity": 6,
            "features": ["leather seats", "wifi", "bar"],
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Black Lincoln Navigator"
        assert data["status"] == "available"
        TestVehicles._vehicle_id = data["id"]

    def test_vehicle_status_update(self, authed_client):
        resp = post_json(authed_client, f"/api/vehicles/{TestVehicles._vehicle_id}/status", {
            "status": "maintenance",
        })
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "maintenance"
        # Restore to available for subsequent tests
        post_json(authed_client, f"/api/vehicles/{TestVehicles._vehicle_id}/status", {
            "status": "available",
        })


class TestDrivers:
    def test_add_driver(self, authed_client):
        resp = post_json(authed_client, "/api/drivers", {
            "name": "Marcus Williams",
            "license_number": "DL-MW-9918",
            "license_expiry": "2028-03-01",
            "phone": "416-555-0192",
            "email": "marcus@limotest.com",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Marcus Williams"
        assert data["status"] == "available"
        TestDrivers._driver_id = data["id"]


class TestBookings:
    def test_create_booking(self, authed_client):
        resp = post_json(authed_client, "/api/bookings", {
            "booking_type": "airport",
            "pickup_address": "123 Main St, Toronto, ON",
            "dropoff_address": "Toronto Pearson International Airport",
            "pickup_time": "2026-04-10T08:00:00",
            "estimated_duration_hours": 1.5,
            "passengers": 2,
            "base_fare": 120.00,
            "extras": 20.00,
            "total_fare": 140.00,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["booking_type"] == "airport"
        assert data["status"] == "pending"
        TestBookings._booking_id = data["id"]

    def test_dispatch_booking(self, authed_client):
        resp = post_json(
            authed_client,
            f"/api/bookings/{TestBookings._booking_id}/dispatch",
            {
                "driver_id": TestDrivers._driver_id,
                "vehicle_id": TestVehicles._vehicle_id,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "dispatched"
        assert data["driver_id"] == TestDrivers._driver_id
        assert data["vehicle_id"] == TestVehicles._vehicle_id

    def test_complete_trip(self, authed_client):
        resp = post_json(
            authed_client,
            f"/api/bookings/{TestBookings._booking_id}/complete",
            {"actual_duration_hours": 1.4},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "completed"
        assert float(data["actual_duration_hours"]) == 1.4

    def test_add_maintenance_record(self, authed_client):
        resp = post_json(
            authed_client,
            f"/api/vehicles/{TestVehicles._vehicle_id}/maintenance",
            {
                "maintenance_type": "oil_change",
                "description": "Full synthetic oil change",
                "cost": 89.99,
                "performed_date": "2026-03-26",
                "next_due_date": "2026-06-26",
                "mileage_at_service": 45200,
                "performed_by": "Kytran Auto Services",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["maintenance_type"] == "oil_change"
        TestBookings._maintenance_id = data["id"]


class TestStats:
    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/industry-limo/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "available_vehicles" in data
        assert "active_bookings" in data
        assert "revenue_today" in data
        assert "trips_this_week" in data
        # Vehicle is available again after trip completed
        assert data["available_vehicles"] >= 1
