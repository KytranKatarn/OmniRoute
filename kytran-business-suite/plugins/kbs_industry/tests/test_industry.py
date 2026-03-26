"""Tests for the Industry Framework plugin — config, jobs, items, notes, permits, opportunities, stats."""

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
TEST_TENANT_ID = 9911
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "industrytest@example.com"
TEST_PASSWORD = "TestPass123!"

MIGRATION_INDUSTRY = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_industry_tables.sql"
)
MIGRATION_CRM = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
MIGRATION_INVOICING = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_invoicing", "migrations", "001_invoicing_tables.sql"
)


@pytest.fixture(scope="module")
def industry_app():
    """Create the Flask app with Industry + CRM + Invoicing plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def industry_setup(industry_app):
    """Create test tenant, user, schema, tables, and enable required modules.

    Yields the tenant_id. Cleans up afterwards.
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
            VALUES (%s, 'Industry Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Industry Test Tenant', 'industry-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Ensure 'industry' exists in module_catalog (FK requirement)
        cur.execute(
            """
            INSERT INTO module_catalog (slug, name, tier_required, category)
            VALUES ('industry', 'Industry Framework', 'business', 'ecommerce')
            ON CONFLICT (slug) DO NOTHING
            """,
        )

        # Enable all three required modules
        for slug in ("crm", "invoicing", "industry"):
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

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(industry_app, industry_setup):
    """Yield a logged-in test client with the tenant session set."""
    with industry_app.test_client() as client:
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
        "/plugins/industry" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def put_json(client, path, payload):
    return client.put(
        "/plugins/industry" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIndustryConfig:
    def test_set_industry_config(self, authed_client):
        resp = post_json(authed_client, "/api/config", {
            "industry_type": "construction",
            "company_license": "LIC-12345",
            "service_area": "Greater Toronto Area",
            "certifications": ["Gold Seal", "OHSA"]
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["industry_type"] == "construction"
        assert data["company_license"] == "LIC-12345"

    def test_get_industry_config(self, authed_client):
        resp = authed_client.get("/plugins/industry/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["industry_type"] == "construction"


class TestJobs:
    def test_create_job_auto_number(self, authed_client):
        resp = post_json(authed_client, "/api/jobs", {
            "title": "Roof Repair at 123 Main St",
            "job_type": "service",
            "priority": "high",
            "estimated_cost": 4500.00
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["job_number"].startswith("JOB-")
        assert data["title"] == "Roof Repair at 123 Main St"
        assert data["status"] == "quoted"
        # Store for later tests
        TestJobs._job_id = data["id"]

    def test_list_jobs(self, authed_client):
        resp = authed_client.get("/plugins/industry/api/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "jobs" in data
        assert data["total"] >= 1

    def test_add_job_item(self, authed_client):
        resp = post_json(authed_client, f"/api/jobs/{TestJobs._job_id}/items", {
            "item_type": "labor",
            "description": "Senior roofer 8 hours",
            "quantity": 8,
            "unit_price": 95.00
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert float(data["total"]) == 760.0
        TestJobs._item_id = data["id"]

    def test_add_job_note(self, authed_client):
        resp = post_json(authed_client, f"/api/jobs/{TestJobs._job_id}/notes", {
            "author": "John Smith",
            "content": "Site inspection complete — no structural damage found.",
            "note_type": "inspection"
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["author"] == "John Smith"
        assert data["note_type"] == "inspection"

    def test_approve_job(self, authed_client):
        resp = authed_client.post(f"/plugins/industry/api/jobs/{TestJobs._job_id}/approve")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "approved"

    def test_start_job(self, authed_client):
        resp = authed_client.post(f"/plugins/industry/api/jobs/{TestJobs._job_id}/start")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "in_progress"
        assert data["start_date"] is not None

    def test_complete_job(self, authed_client):
        resp = authed_client.post(f"/plugins/industry/api/jobs/{TestJobs._job_id}/complete")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "completed"
        assert data["completion_date"] is not None


class TestPermits:
    def test_create_permit(self, authed_client):
        resp = post_json(authed_client, "/api/permits", {
            "permit_type": "Building Permit",
            "job_id": TestJobs._job_id,
            "issuing_authority": "City of Toronto",
            "cost": 350.00
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["permit_type"] == "Building Permit"
        assert data["status"] == "pending"
        TestPermits._permit_id = data["id"]

    def test_list_permits(self, authed_client):
        resp = authed_client.get("/plugins/industry/api/permits")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "permits" in data
        assert len(data["permits"]) >= 1


class TestOpportunities:
    def test_add_opportunity(self, authed_client):
        resp = post_json(authed_client, "/api/opportunities", {
            "title": "City of Toronto — Roof Restoration Program 2026",
            "source": "MERX",
            "reference_number": "TOR-2026-0045",
            "industry_types": ["construction", "general"],
            "region": "Ontario",
            "value_min": 50000,
            "value_max": 250000,
            "deadline": "2026-04-30",
            "match_score": 85
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["id"] is not None
        assert data["status"] == "new"
        TestOpportunities._opp_id = data["id"]

    def test_apply_to_opportunity(self, authed_client):
        resp = authed_client.post(f"/plugins/industry/api/opportunities/{TestOpportunities._opp_id}/apply")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "applied"


class TestStats:
    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/industry/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "active_jobs" in data
        assert "completed_this_month" in data
        assert "total_revenue" in data
        assert "pending_permits" in data
        assert "new_opportunities" in data
        # We completed one job this month
        assert data["completed_this_month"] >= 1
