"""Tests for the Marketing Dashboard plugin — campaigns, leads, funnel, stats."""

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

TEST_TENANT_ID = 9905
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "marketingtest@example.com"
TEST_PASSWORD = "TestPass123!"

CRM_MIGRATION = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
MARKETING_MIGRATION = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_marketing_tables.sql"
)


@pytest.fixture(scope="module")
def marketing_app():
    """Create the Flask app with marketing + crm plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def marketing_setup(marketing_app):
    """Create test tenant, user, schema, migrations, and enable modules.

    Yields tenant metadata. Cleans up afterwards.
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
            VALUES (%s, 'Marketing Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Marketing Test Tenant', 'marketing-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable crm module (dependency)
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'crm', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

        # Enable marketing module
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'marketing', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    # Create tenant schema and run both migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION, schema=TEST_SCHEMA)
    run_migration_file(MARKETING_MIGRATION, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(marketing_app, marketing_setup):
    """Yield a test client that is logged in with tenant session set."""
    with marketing_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"
        yield client


# ======================================================================
# Tests
# ======================================================================


class TestCampaigns:
    """Campaign CRUD tests."""

    def test_create_campaign(self, authed_client):
        resp = authed_client.post(
            "/plugins/marketing/api/campaigns",
            data=json.dumps({"name": "Summer Launch", "status": "draft", "channel": "email"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Summer Launch"
        assert data["status"] == "draft"
        assert data["id"] is not None

    def test_list_campaigns(self, authed_client):
        authed_client.post(
            "/plugins/marketing/api/campaigns",
            data=json.dumps({"name": "List Campaign Test"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/marketing/api/campaigns")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "campaigns" in data
        assert len(data["campaigns"]) >= 1
        names = [c["name"] for c in data["campaigns"]]
        assert "List Campaign Test" in names


class TestLeads:
    """Lead CRUD and stage update tests."""

    def test_create_lead(self, authed_client):
        resp = authed_client.post(
            "/plugins/marketing/api/leads",
            data=json.dumps({"source": "website", "score": 42, "stage": "new"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["source"] == "website"
        assert data["score"] == 42
        assert data["stage"] == "new"
        assert data["id"] is not None

    def test_list_leads(self, authed_client):
        authed_client.post(
            "/plugins/marketing/api/leads",
            data=json.dumps({"source": "referral"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/marketing/api/leads")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "leads" in data
        assert len(data["leads"]) >= 1

    def test_update_lead_stage(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/marketing/api/leads",
            data=json.dumps({"source": "cold_outreach", "stage": "new"}),
            content_type="application/json",
        )
        lead_id = create_resp.get_json()["id"]

        resp = authed_client.put(
            f"/plugins/marketing/api/leads/{lead_id}",
            data=json.dumps({"stage": "qualified", "score": 75}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stage"] == "qualified"
        assert data["score"] == 75


class TestFunnelAndAnalytics:
    """Funnel, overview, and stats endpoint tests."""

    def test_get_funnel(self, authed_client):
        resp = authed_client.get("/plugins/marketing/api/funnel")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "funnel" in data
        stages = [f["stage"] for f in data["funnel"]]
        for expected in ["new", "contacted", "qualified", "proposal", "won", "lost"]:
            assert expected in stages

    def test_get_overview(self, authed_client):
        resp = authed_client.get("/plugins/marketing/api/overview")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_contacts" in data
        assert "total_posts" in data
        assert "total_documents" in data
        assert "leads_by_stage" in data
        assert "active_campaigns" in data
        # All values must be integers (cross-plugin tables may return 0 if not present)
        assert isinstance(data["total_contacts"], int)
        assert isinstance(data["total_posts"], int)
        assert isinstance(data["total_documents"], int)

    def test_get_stats(self, authed_client):
        resp = authed_client.get("/plugins/marketing/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_leads" in data
        assert "conversion_rate" in data
        assert "avg_lead_score" in data
        assert "active_campaigns" in data
        assert isinstance(data["total_leads"], int)
        assert isinstance(data["conversion_rate"], float)
