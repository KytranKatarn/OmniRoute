"""Tests for the Mechanical / HVAC industry plugin — systems, maintenance, energy audits, commissioning, stats."""

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
TEST_TENANT_ID = 9915
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "mechanicaltest@example.com"
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
MIGRATION_MECHANICAL = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_mechanical_tables.sql"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mechanical_app():
    """Create Flask app with Mechanical + Industry + CRM plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def mechanical_setup(mechanical_app):
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
            VALUES (%s, 'Mechanical Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Mechanical Test Tenant', 'mechanical-test-tenant', 'business', TRUE)
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
            ("industry-mechanical", "Mechanical / HVAC", "business", "ecommerce"),
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
        for slug in ("crm", "invoicing", "industry", "industry-mechanical"):
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
    run_migration_file(MIGRATION_MECHANICAL, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(mechanical_app, mechanical_setup):
    """Yield a logged-in test client."""
    with mechanical_app.test_client() as client:
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

BASE = "/plugins/industry-mechanical"


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
# Test 1 — Create HVAC system
# ---------------------------------------------------------------------------


class TestHvacSystems:
    """Test 1 — create system; Test 7 — update system status."""

    def test_create_system(self, authed_client):
        resp = post_json(authed_client, "/api/systems", {
            "system_type": "heat_pump",
            "manufacturer": "Carrier",
            "model": "Infinity 20 25VNA048A003",
            "serial_number": "CP2026-0012345",
            "install_date": "2026-01-10",
            "warranty_expiry": "2031-01-10",
            "capacity_btu": 48000,
            "efficiency_rating": 20.0,
            "location": "Rooftop Unit #1",
            "status": "active",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["system_type"] == "heat_pump"
        assert data["capacity_btu"] == 48000
        assert data["status"] == "active"
        TestHvacSystems._system_id = data["id"]

    def test_list_systems(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/systems")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "systems" in data
        assert data["total"] >= 1

    def test_get_system(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/systems/{TestHvacSystems._system_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["manufacturer"] == "Carrier"
        assert data["serial_number"] == "CP2026-0012345"

    def test_update_system_status(self, authed_client):
        """Test 7 — update system status to needs_service."""
        resp = put_json(authed_client, f"/api/systems/{TestHvacSystems._system_id}", {
            "status": "needs_service",
            "notes": "Annual filter replacement due",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "needs_service"
        assert data["notes"] == "Annual filter replacement due"

        # Restore to active for remaining tests
        put_json(authed_client, f"/api/systems/{TestHvacSystems._system_id}", {"status": "active"})


# ---------------------------------------------------------------------------
# Test 2 — Add maintenance schedule
# Test 3 — List upcoming maintenance
# Test 4 — Mark maintenance performed
# ---------------------------------------------------------------------------


class TestMaintenanceSchedules:
    """Tests 2, 3, 4 — maintenance scheduling workflow."""

    def test_add_maintenance_schedule(self, authed_client):
        """Test 2 — add schedule."""
        system_id = TestHvacSystems._system_id
        resp = post_json(authed_client, f"/api/systems/{system_id}/maintenance", {
            "task_name": "Filter replacement",
            "frequency": "quarterly",
            "last_performed": "2025-12-15",
            "next_due": "2026-03-15",
            "technician": "Alex Torres",
            "notes": "Replace MERV-13 filter on RTU-1",
            "is_active": True,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["system_id"] == system_id
        assert data["frequency"] == "quarterly"
        assert data["is_active"] is True
        TestMaintenanceSchedules._schedule_id = data["id"]

    def test_list_upcoming_maintenance(self, authed_client):
        """Test 3 — list upcoming maintenance (next 30 days). Uses a far-future date to ensure it shows."""
        # Add a second schedule with next_due well within the window
        system_id = TestHvacSystems._system_id
        post_json(authed_client, f"/api/systems/{system_id}/maintenance", {
            "task_name": "Coil cleaning",
            "frequency": "semi_annual",
            "next_due": "2026-04-01",
            "technician": "Maria Santos",
        })

        resp = authed_client.get(f"{BASE}/api/maintenance?days=365")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "maintenance" in data
        assert data["total"] >= 1
        # All returned records should have next_due populated
        for m in data["maintenance"]:
            assert m["next_due"] is not None

    def test_mark_maintenance_performed(self, authed_client):
        """Test 4 — mark performed by updating last_performed and next_due."""
        schedule_id = TestMaintenanceSchedules._schedule_id
        resp = put_json(authed_client, f"/api/maintenance/{schedule_id}", {
            "last_performed": "2026-03-26",
            "next_due": "2026-06-26",
            "technician": "Alex Torres",
            "notes": "Filter replaced. Unit running normally.",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["last_performed"] is not None
        assert data["next_due"] is not None
        assert data["notes"] == "Filter replaced. Unit running normally."


# ---------------------------------------------------------------------------
# Test 5 — Create energy audit
# ---------------------------------------------------------------------------


class TestEnergyAudits:
    """Test 5 — energy audit CRUD."""

    def test_create_energy_audit(self, authed_client):
        resp = post_json(authed_client, "/api/audits", {
            "building_sqft": 12000,
            "current_system": "Aging rooftop unit, SEER 10, installed 2005",
            "recommended_system": "Variable refrigerant flow (VRF) system, SEER 22",
            "estimated_savings": 8400.00,
            "payback_years": 6.5,
            "audit_date": "2026-03-20",
            "auditor": "Green Energy Consultants Ltd.",
            "status": "draft",
            "notes": "Building envelope needs improvement before upgrade.",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["building_sqft"] == 12000
        assert float(data["estimated_savings"]) == 8400.00
        assert data["status"] == "draft"
        TestEnergyAudits._audit_id = data["id"]

    def test_get_energy_audit(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/audits/{TestEnergyAudits._audit_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["auditor"] == "Green Energy Consultants Ltd."

    def test_update_audit_status(self, authed_client):
        resp = put_json(authed_client, f"/api/audits/{TestEnergyAudits._audit_id}", {
            "status": "submitted",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "submitted"

    def test_list_energy_audits(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/audits")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "audits" in data
        assert data["total"] >= 1


# ---------------------------------------------------------------------------
# Test 6 — Add commissioning report
# ---------------------------------------------------------------------------


class TestCommissioningReports:
    """Test 6 — commissioning report creation and retrieval."""

    def test_add_commissioning_report(self, authed_client):
        system_id = TestHvacSystems._system_id
        resp = post_json(authed_client, f"/api/systems/{system_id}/commissioning", {
            "report_type": "startup",
            "test_results": {
                "supply_air_temp": 55.2,
                "return_air_temp": 72.1,
                "static_pressure": 0.45,
                "airflow_cfm": 1600,
            },
            "passed": True,
            "technician": "Alex Torres",
            "report_date": "2026-01-12",
            "notes": "All checks passed. Unit operating within spec.",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["report_type"] == "startup"
        assert data["passed"] is True
        assert data["test_results"]["supply_air_temp"] == 55.2
        TestCommissioningReports._report_id = data["id"]

    def test_list_commissioning_reports(self, authed_client):
        system_id = TestHvacSystems._system_id
        resp = authed_client.get(f"{BASE}/api/systems/{system_id}/commissioning")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "reports" in data
        assert data["total"] >= 1
        report_ids = [r["id"] for r in data["reports"]]
        assert TestCommissioningReports._report_id in report_ids


# ---------------------------------------------------------------------------
# Test 8 — Stats
# ---------------------------------------------------------------------------


class TestStats:
    """Test 8 — stats endpoint."""

    def test_stats(self, authed_client):
        resp = authed_client.get(f"{BASE}/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_systems" in data
        assert "needs_service" in data
        assert "maintenance_due" in data
        assert "audits_pending" in data
        assert "avg_efficiency" in data
        # We have at least 1 system
        assert data["total_systems"] >= 1
        # At least 1 audit in draft/submitted
        assert data["audits_pending"] >= 1
        # avg_efficiency should be a float (we set efficiency_rating=20.0)
        assert data["avg_efficiency"] is not None
        assert float(data["avg_efficiency"]) > 0
