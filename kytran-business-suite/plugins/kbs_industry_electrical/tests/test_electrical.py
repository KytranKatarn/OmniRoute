"""Tests for the Electrical industry plugin — panels, circuits, load calculations, materials."""

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
TEST_TENANT_ID = 9913
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "electricaltest@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_ELECTRICAL = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_electrical_tables.sql"
)
MIGRATION_INDUSTRY = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_industry", "migrations", "001_industry_tables.sql"
)
MIGRATION_CRM = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def electrical_app():
    """Create the Flask app with Electrical + Industry + CRM plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def electrical_setup(electrical_app):
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
            VALUES (%s, 'Electrical Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Electrical Test Tenant', 'electrical-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Ensure module_catalog entries exist (FK requirement)
        for slug, name, tier, cat in [
            ("crm", "CRM & Contacts", "free", "crm"),
            ("industry", "Industry Framework", "business", "ecommerce"),
            ("industry-electrical", "Electrical", "business", "ecommerce"),
        ]:
            cur.execute(
                """
                INSERT INTO module_catalog (slug, name, tier_required, category)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO NOTHING
                """,
                (slug, name, tier, cat),
            )

        # Enable all required modules
        for slug in ("crm", "industry", "industry-electrical"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create tenant schema and run migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(MIGRATION_CRM, schema=TEST_SCHEMA)
    run_migration_file(MIGRATION_INDUSTRY, schema=TEST_SCHEMA)
    run_migration_file(MIGRATION_ELECTRICAL, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(electrical_app, electrical_setup):
    """Yield a logged-in test client with the tenant session set."""
    with electrical_app.test_client() as client:
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
        f"/plugins/industry-electrical{path}",
        json=payload,
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        f"/plugins/industry-electrical{path}",
        json=payload,
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPanels:
    def test_create_panel(self, authed_client):
        resp = post_json(
            authed_client,
            "/api/panels",
            {
                "name": "Main Distribution Panel",
                "panel_type": "main",
                "amperage": 200,
                "voltage": 240,
                "phases": 1,
                "spaces": 40,
                "location": "Basement utility room",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "Main Distribution Panel"
        assert data["amperage"] == 200
        assert data["panel_type"] == "main"
        assert data["spaces_used"] == 0
        TestPanels._panel_id = data["id"]

    def test_add_circuit(self, authed_client):
        resp = post_json(
            authed_client,
            f"/api/panels/{TestPanels._panel_id}/circuits",
            {
                "circuit_number": 1,
                "description": "Kitchen refrigerator",
                "amperage": 20,
                "wire_size": "12 AWG",
                "breaker_type": "gfci",
                "load_watts": 150,
                "is_dedicated": True,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["circuit_number"] == 1
        assert data["description"] == "Kitchen refrigerator"
        assert data["amperage"] == 20
        assert data["breaker_type"] == "gfci"
        assert data["is_dedicated"] is True
        TestPanels._circuit_id = data["id"]

    def test_list_panel_with_circuits(self, authed_client):
        resp = authed_client.get(f"/plugins/industry-electrical/api/panels/{TestPanels._panel_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == TestPanels._panel_id
        assert data["name"] == "Main Distribution Panel"
        assert "circuits" in data
        assert len(data["circuits"]) >= 1
        circuit = data["circuits"][0]
        assert circuit["circuit_number"] == 1
        assert circuit["description"] == "Kitchen refrigerator"


class TestLoadCalculations:
    def test_create_load_calc(self, authed_client):
        resp = post_json(
            authed_client,
            "/api/load-calculations",
            {
                "building_type": "residential",
                "total_sqft": 1800,
                "hvac_load": 5000,
                "fixed_appliance_load": 2400,
                "notes": "Single-family dwelling NEC 220.82 calculation",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["building_type"] == "residential"
        assert data["total_sqft"] == 1800
        # Auto-calc: general_lighting = 1800 * 3 = 5400, small_appliance = 3000
        assert float(data["general_lighting_load"]) == pytest.approx(5400.0)
        assert float(data["small_appliance_load"]) == pytest.approx(3000.0)
        # required_service_amps should be a standard size >= raw calculation
        assert data["required_service_amps"] in [100, 150, 200, 400, 600, 800, 1000, 1200]
        assert data["required_service_amps"] >= 100
        TestLoadCalculations._calc_id = data["id"]


class TestMaterials:
    def test_add_material(self, authed_client):
        resp = post_json(
            authed_client,
            "/api/materials",
            {
                "name": "12 AWG THHN Wire (Black)",
                "category": "wire",
                "quantity": 500,
                "unit": "ft",
                "unit_cost": 0.45,
                "supplier": "Rexel Canada",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["name"] == "12 AWG THHN Wire (Black)"
        assert data["category"] == "wire"
        assert float(data["quantity"]) == 500.0
        assert float(data["unit_cost"]) == pytest.approx(0.45)
        assert float(data["total_cost"]) == pytest.approx(225.0)  # 500 * 0.45
        assert data["status"] == "needed"
        TestMaterials._material_id = data["id"]

    def test_update_material_status(self, authed_client):
        resp = put_json(
            authed_client,
            f"/api/materials/{TestMaterials._material_id}",
            {"status": "ordered"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ordered"
        assert float(data["total_cost"]) == pytest.approx(225.0)  # unchanged

    def test_list_materials(self, authed_client):
        resp = authed_client.get("/plugins/industry-electrical/api/materials")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "materials" in data
        assert len(data["materials"]) >= 1
        assert data["materials"][0]["name"] == "12 AWG THHN Wire (Black)"


class TestStats:
    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/industry-electrical/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_panels" in data
        assert "total_circuits" in data
        assert "materials_needed" in data
        assert "load_calcs_done" in data
        assert data["total_panels"] >= 1
        assert data["total_circuits"] >= 1
        assert data["load_calcs_done"] >= 1
        # material was updated to 'ordered' so materials_needed should be 0
        assert data["materials_needed"] == 0
