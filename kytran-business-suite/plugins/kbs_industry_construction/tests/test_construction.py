"""Tests for the Construction industry plugin — projects, subcontractors, RFIs, change orders, inspections."""

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
TEST_TENANT_ID = 9912
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "constructiontest@example.com"
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
MIGRATION_CONSTRUCTION = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_construction_tables.sql"
)


@pytest.fixture(scope="module")
def construction_app():
    """Create the Flask app with Construction + Industry + CRM + Invoicing plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def construction_setup(construction_app):
    """Create test tenant, user, schema, tables, and enable required modules.

    Yields context dict. Cleans up afterwards.
    """
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
            VALUES (%s, 'Construction Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Construction Test Tenant', 'construction-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Ensure all required slugs exist in module_catalog
        for slug, name, category in [
            ("industry", "Industry Framework", "ecommerce"),
            ("industry-construction", "Construction", "ecommerce"),
        ]:
            cur.execute(
                """
                INSERT INTO module_catalog (slug, name, tier_required, category)
                VALUES (%s, %s, 'business', %s)
                ON CONFLICT (slug) DO NOTHING
                """,
                (slug, name, category),
            )

        # Enable all required modules
        for slug in ("crm", "invoicing", "industry", "industry-construction"):
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
    run_migration_file(MIGRATION_INDUSTRY, schema=TEST_SCHEMA)
    run_migration_file(MIGRATION_CONSTRUCTION, schema=TEST_SCHEMA)

    # Seed a base job in the industry jobs table for FK use
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute(
            """
            INSERT INTO jobs (job_number, title, status)
            VALUES ('JOB-0001', 'Test Construction Job', 'approved')
            RETURNING id
            """
        )
        job_id = cur.fetchone()["id"]

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id, "job_id": job_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(construction_app, construction_setup):
    """Yield a logged-in test client with the tenant session set."""
    with construction_app.test_client() as client:
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
        "/plugins/industry-construction" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        "/plugins/industry-construction" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProjects:
    def test_create_project(self, authed_client, construction_setup):
        """Test 1: Create a construction project linked to a job."""
        resp = post_json(authed_client, "/api/projects", {
            "job_id": construction_setup["job_id"],
            "project_type": "commercial",
            "general_contractor": "Apex Builders Inc.",
            "site_supervisor": "Jane Doe",
            "project_value": 1500000.00,
            "safety_plan": "Full OHSA safety plan on file",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["project_type"] == "commercial"
        assert data["general_contractor"] == "Apex Builders Inc."
        assert data["completion_percentage"] == 0
        TestProjects._project_id = data["id"]

    def test_list_projects(self, authed_client):
        resp = authed_client.get("/plugins/industry-construction/api/projects")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "projects" in data
        assert len(data["projects"]) >= 1

    def test_get_project_with_relations(self, authed_client):
        resp = authed_client.get(f"/plugins/industry-construction/api/projects/{TestProjects._project_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == TestProjects._project_id
        assert "rfis" in data
        assert "change_orders" in data
        assert "inspections" in data

    def test_update_project(self, authed_client):
        resp = put_json(authed_client, f"/api/projects/{TestProjects._project_id}", {
            "completion_percentage": 25,
            "weather_delays": 2,
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["completion_percentage"] == 25
        assert data["weather_delays"] == 2


class TestSubcontractors:
    def test_add_subcontractor(self, authed_client):
        """Test 2: Add a subcontractor."""
        resp = post_json(authed_client, "/api/subcontractors", {
            "company_name": "Elite Electrical Services",
            "contact_name": "Bob Smith",
            "phone": "416-555-0100",
            "email": "bob@eliteelec.ca",
            "trade": "Electrical",
            "license_number": "ELEC-2024-001",
            "hourly_rate": 125.00,
            "rating": 5,
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["company_name"] == "Elite Electrical Services"
        assert data["trade"] == "Electrical"
        assert data["is_active"] is True
        TestSubcontractors._sub_id = data["id"]

    def test_list_subcontractors(self, authed_client):
        resp = authed_client.get("/plugins/industry-construction/api/subcontractors")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "subcontractors" in data
        assert len(data["subcontractors"]) >= 1

    def test_update_subcontractor(self, authed_client):
        resp = put_json(authed_client, f"/api/subcontractors/{TestSubcontractors._sub_id}", {
            "rating": 4,
            "notes": "Excellent work on previous projects",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["rating"] == 4


class TestRFIs:
    def test_submit_rfi(self, authed_client):
        """Test 3: Submit an RFI."""
        resp = post_json(
            authed_client,
            f"/api/projects/{TestProjects._project_id}/rfis",
            {
                "subject": "Clarification on Foundation Depth Spec",
                "description": "Section 3.2 specifies 1.8m depth but drawings show 2.1m. Please clarify.",
                "submitted_by": "Site Supervisor Jane Doe",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["rfi_number"].startswith("RFI-")
        assert data["subject"] == "Clarification on Foundation Depth Spec"
        assert data["status"] == "open"
        TestRFIs._rfi_id = data["id"]
        TestRFIs._rfi_number = data["rfi_number"]

    def test_rfi_auto_number(self, authed_client):
        """RFI number should be RFI-001 for the first RFI."""
        assert TestRFIs._rfi_number == "RFI-001"

    def test_respond_to_rfi(self, authed_client):
        """Test 4: Respond to an RFI."""
        resp = put_json(authed_client, f"/api/rfis/{TestRFIs._rfi_id}", {
            "status": "responded",
            "response": "Use 2.1m depth as shown in the drawings. Spec document will be updated.",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "responded"
        assert data["response"] is not None
        assert data["responded_at"] is not None


class TestChangeOrders:
    def test_create_change_order(self, authed_client):
        """Test 5: Create a change order."""
        resp = post_json(
            authed_client,
            f"/api/projects/{TestProjects._project_id}/change-orders",
            {
                "description": "Additional excavation required due to rock obstruction",
                "reason": "Unforeseen site conditions",
                "amount": 18500.00,
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["co_number"].startswith("CO-")
        assert data["status"] == "pending"
        assert float(data["amount"]) == 18500.00
        TestChangeOrders._co_id = data["id"]
        TestChangeOrders._co_number = data["co_number"]

    def test_co_auto_number(self, authed_client):
        """CO number should be CO-001 for the first change order."""
        assert TestChangeOrders._co_number == "CO-001"

    def test_approve_change_order(self, authed_client):
        """Test 6: Approve a change order."""
        resp = put_json(authed_client, f"/api/change-orders/{TestChangeOrders._co_id}/approve", {
            "approved_by": "Project Owner Alice Johnson",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "approved"
        assert data["approved_by"] == "Project Owner Alice Johnson"
        assert data["approved_at"] is not None


class TestInspections:
    def test_schedule_inspection(self, authed_client):
        """Test 7: Schedule an inspection."""
        resp = post_json(
            authed_client,
            f"/api/projects/{TestProjects._project_id}/inspections",
            {
                "inspection_type": "Foundation Inspection",
                "inspector": "City Inspector Mike Brown",
                "scheduled_date": "2026-04-15",
                "notes": "Pre-pour foundation inspection required before concrete pour",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["inspection_type"] == "Foundation Inspection"
        assert data["status"] == "scheduled"
        TestInspections._inspection_id = data["id"]

    def test_update_inspection_status(self, authed_client):
        resp = put_json(authed_client, f"/api/inspections/{TestInspections._inspection_id}", {
            "status": "passed",
            "notes": "Foundation depth and rebar placement approved. Clear to pour.",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "passed"


class TestStats:
    def test_stats(self, authed_client):
        """Test 8: Verify stats endpoint returns expected keys and values."""
        resp = authed_client.get("/plugins/industry-construction/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_projects" in data
        assert "total_project_value" in data
        assert "pending_rfis" in data
        assert "pending_change_orders" in data
        # We have 1 active project (< 100% complete)
        assert data["active_projects"] >= 1
        # project_value is 1,500,000
        assert data["total_project_value"] >= 1500000.0
        # RFI was responded, so 0 pending
        assert data["pending_rfis"] == 0
        # Change order was approved, so 0 pending
        assert data["pending_change_orders"] == 0
