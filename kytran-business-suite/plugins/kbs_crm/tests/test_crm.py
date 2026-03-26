"""Tests for the CRM plugin — contacts CRUD, search, stats."""

import os
import json

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
TEST_TENANT_ID = 9901
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "crmtest@example.com"
TEST_PASSWORD = "TestPass123!"
MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_crm_tables.sql"
)


@pytest.fixture(scope="module")
def crm_app():
    """Create the Flask app with CRM plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def crm_setup(crm_app):
    """Create test tenant, user, schema, CRM tables, and enable CRM module.

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

        # Create user (ARCHIE's users table uses 'username' not 'name')
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'CRM Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'CRM Test Tenant', 'crm-test-tenant', 'free', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable CRM module
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'crm', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    # Create tenant schema and run CRM migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(crm_app, crm_setup):
    """Yield a test client that is logged in and has the tenant session set."""
    with crm_app.test_client() as client:
        # Log in via the login endpoint
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        # Should redirect on success (302)
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"

        yield client


# ======================================================================
# Tests
# ======================================================================


class TestCRMCustomers:
    """Customer CRUD tests."""

    def test_create_customer(self, authed_client):
        resp = authed_client.post(
            "/plugins/crm/api/customers",
            data=json.dumps({"name": "Jane Doe", "email": "jane@example.com", "company": "Acme"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Jane Doe"
        assert data["email"] == "jane@example.com"
        assert data["id"] is not None

    def test_list_customers(self, authed_client):
        # Create a customer first
        authed_client.post(
            "/plugins/crm/api/customers",
            data=json.dumps({"name": "List Test User"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/crm/api/customers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "customers" in data
        assert data["total"] >= 1
        names = [c["name"] for c in data["customers"]]
        assert "List Test User" in names

    def test_get_single_customer(self, authed_client):
        # Create
        create_resp = authed_client.post(
            "/plugins/crm/api/customers",
            data=json.dumps({"name": "Single Get Test"}),
            content_type="application/json",
        )
        cid = create_resp.get_json()["id"]

        resp = authed_client.get(f"/plugins/crm/api/customers/{cid}")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == "Single Get Test"

    def test_update_customer(self, authed_client):
        # Create
        create_resp = authed_client.post(
            "/plugins/crm/api/customers",
            data=json.dumps({"name": "Update Me"}),
            content_type="application/json",
        )
        cid = create_resp.get_json()["id"]

        resp = authed_client.put(
            f"/plugins/crm/api/customers/{cid}",
            data=json.dumps({"name": "Updated Name", "status": "lead"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Updated Name"
        assert data["status"] == "lead"

    def test_delete_customer(self, authed_client):
        # Create
        create_resp = authed_client.post(
            "/plugins/crm/api/customers",
            data=json.dumps({"name": "Delete Me"}),
            content_type="application/json",
        )
        cid = create_resp.get_json()["id"]

        resp = authed_client.delete(f"/plugins/crm/api/customers/{cid}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True

        # Verify gone
        resp2 = authed_client.get(f"/plugins/crm/api/customers/{cid}")
        assert resp2.status_code == 404

    def test_search_customers(self, authed_client):
        authed_client.post(
            "/plugins/crm/api/customers",
            data=json.dumps({"name": "Searchable Person", "email": "search@test.com"}),
            content_type="application/json",
        )

        resp = authed_client.get("/plugins/crm/api/search?q=Searchable")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["customers"]) >= 1
        assert any(c["name"] == "Searchable Person" for c in data["customers"])

    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/crm/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_customers" in data
        assert "active_customers" in data
        assert "leads" in data
        assert "new_this_month" in data
