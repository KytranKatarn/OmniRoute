"""Tests for the Plumbing industry plugin — service calls, fixtures, inventory, backflow tests."""

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
TEST_TENANT_ID = 9914
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "plumbingtest@example.com"
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
MIGRATION_PLUMBING = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_plumbing_tables.sql"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def plumbing_app():
    """Create Flask app with Plumbing + Industry + CRM plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def plumbing_setup(plumbing_app):
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
            VALUES (%s, 'Plumbing Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Plumbing Test Tenant', 'plumbing-test-tenant', 'business', TRUE)
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
            ("industry-plumbing", "Plumbing", "business", "ecommerce"),
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
        for slug in ("crm", "invoicing", "industry", "industry-plumbing"):
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
    run_migration_file(MIGRATION_PLUMBING, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(plumbing_app, plumbing_setup):
    """Yield a logged-in test client."""
    with plumbing_app.test_client() as client:
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

BASE = "/plugins/industry-plumbing"


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
# Tests
# ---------------------------------------------------------------------------

class TestServiceCalls:
    """Test 1 & 2 — create and update service calls."""

    def test_create_service_call(self, authed_client):
        resp = post_json(authed_client, "/api/service-calls", {
            "call_type": "emergency",
            "priority": "emergency",
            "description": "Burst pipe in basement — water everywhere",
            "technician": "Joe Plumber"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["call_type"] == "emergency"
        assert data["priority"] == "emergency"
        assert data["status"] == "new"
        TestServiceCalls._call_id = data["id"]

    def test_update_service_call(self, authed_client):
        resp = put_json(authed_client, f"/api/service-calls/{TestServiceCalls._call_id}", {
            "status": "dispatched",
            "diagnosis": "Copper pipe joint failed near water meter"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "dispatched"
        assert data["diagnosis"] == "Copper pipe joint failed near water meter"

    def test_get_service_call(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/service-calls/{TestServiceCalls._call_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["call_type"] == "emergency"

    def test_list_service_calls(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/service-calls")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "service_calls" in data
        assert data["total"] >= 1

    def test_list_service_calls_status_filter(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/service-calls?status=dispatched")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(c["status"] == "dispatched" for c in data["service_calls"])


class TestFixtures:
    """Test 3 — add fixture."""

    def test_add_fixture(self, authed_client):
        resp = post_json(authed_client, "/api/fixtures", {
            "fixture_type": "water_heater",
            "brand": "Rheem",
            "model": "XE50T10HD45U1",
            "location": "Utility room",
            "install_date": "2026-01-15",
            "warranty_expiry": "2032-01-15",
            "serial_number": "RH2026-00442"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["fixture_type"] == "water_heater"
        assert data["brand"] == "Rheem"
        assert data["status"] == "active"
        TestFixtures._fixture_id = data["id"]

    def test_update_fixture(self, authed_client):
        resp = put_json(authed_client, f"/api/fixtures/{TestFixtures._fixture_id}", {
            "status": "needs_repair",
            "notes": "Thermostat shows fault code E4"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "needs_repair"
        assert data["notes"] == "Thermostat shows fault code E4"

    def test_list_fixtures(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/fixtures")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "fixtures" in data
        assert data["total"] >= 1


class TestInventory:
    """Tests 4 & 5 — add and update inventory parts."""

    def test_add_inventory_part(self, authed_client):
        resp = post_json(authed_client, "/api/inventory", {
            "name": "1/2 inch copper elbow",
            "category": "fitting",
            "sku": "CU-ELB-05",
            "quantity": 50,
            "min_quantity": 10,
            "unit_cost": 1.25,
            "supplier": "Ferguson Plumbing",
            "location": "Bin A3"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "1/2 inch copper elbow"
        assert data["quantity"] == 50
        TestInventory._part_id = data["id"]

    def test_update_inventory_quantity(self, authed_client):
        resp = put_json(authed_client, f"/api/inventory/{TestInventory._part_id}", {
            "quantity": 8,
            "unit_cost": 1.35
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["quantity"] == 8
        assert float(data["unit_cost"]) == 1.35

    def test_low_stock_filter(self, authed_client):
        # quantity=8 < min_quantity=10 so this part should appear
        resp = authed_client.get(f"{BASE}/api/inventory?low_stock=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "parts" in data
        ids = [p["id"] for p in data["parts"]]
        assert TestInventory._part_id in ids


class TestBackflowTests:
    """Test 6 — record backflow test."""

    def test_record_backflow_test(self, authed_client):
        resp = post_json(authed_client, "/api/backflow-tests", {
            "device_location": "120 Main St — Irrigation backflow preventer",
            "device_type": "Reduced Pressure Zone (RPZ)",
            "serial_number": "RPZ-2024-0881",
            "test_date": "2026-03-26",
            "tester_name": "Maria Santos",
            "test_result": "pass",
            "pressure_readings": {"inlet": 85, "outlet": 82, "check1": 10.5},
            "next_test_date": "2027-03-26",
            "certification_number": "CERT-2026-0093"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["test_result"] == "pass"
        assert data["tester_name"] == "Maria Santos"
        assert data["certification_number"] == "CERT-2026-0093"
        TestBackflowTests._test_id = data["id"]

    def test_update_backflow_test(self, authed_client):
        resp = put_json(authed_client, f"/api/backflow-tests/{TestBackflowTests._test_id}", {
            "notes": "Device in good condition. No repairs required.",
            "certification_number": "CERT-2026-0093-FINAL"
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["certification_number"] == "CERT-2026-0093-FINAL"

    def test_list_backflow_tests(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/backflow-tests")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "backflow_tests" in data
        assert data["total"] >= 1


class TestStats:
    """Test 8 — stats endpoint."""

    def test_stats(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_calls" in data
        assert "completed_today" in data
        assert "low_stock_items" in data
        assert "upcoming_backflow_tests" in data
        # We created a dispatched call — it should count as active
        assert data["active_calls"] >= 1
        # We set quantity below min — at least 1 low stock item
        assert data["low_stock_items"] >= 1
