"""Tests for the Contracts & Legal plugin — templates, contracts, versioning, signing, renewal."""

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

TEST_TENANT_ID = 9909
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "contractstest@example.com"
TEST_PASSWORD = "TestPass123!"
MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_contracts_tables.sql"
)
CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)


@pytest.fixture(scope="module")
def contracts_app():
    """Create the Flask app with contracts plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def contracts_setup(contracts_app):
    """Create test tenant, user, schema, tables, and enable contracts + crm modules."""
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up leftovers
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        # Create user
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'Contracts Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Contracts Test Tenant', 'contracts-test-tenant', 'enterprise', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable contracts and crm modules
        for slug in ("crm", "contracts"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create schema and run migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
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
def authed_client(contracts_app, contracts_setup):
    """Yield a logged-in test client with tenant session set."""
    with contracts_app.test_client() as client:
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


class TestContractTemplates:
    """Template CRUD tests."""

    def test_create_template(self, authed_client):
        resp = authed_client.post(
            "/plugins/contracts/api/templates",
            data=json.dumps({
                "name": "Standard NDA",
                "description": "Non-disclosure agreement",
                "doc_type": "nda",
                "content": "This NDA is between {{party_a}} and {{party_b}}.",
                "variables": [{"name": "party_a"}, {"name": "party_b"}],
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Standard NDA"
        assert data["doc_type"] == "nda"
        assert data["id"] is not None

    def test_list_templates(self, authed_client):
        # Create one first
        authed_client.post(
            "/plugins/contracts/api/templates",
            data=json.dumps({"name": "Service Agreement", "doc_type": "agreement"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/contracts/api/templates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "templates" in data
        assert data["templates"] is not None
        names = [t["name"] for t in data["templates"]]
        assert "Standard NDA" in names or "Service Agreement" in names


class TestContracts:
    """Contract CRUD and lifecycle tests."""

    def test_create_contract(self, authed_client):
        resp = authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({
                "title": "Acme SaaS Agreement",
                "customer_id": 1,
                "value": 5000.00,
                "content": "This agreement covers SaaS services.",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Acme SaaS Agreement"
        assert data["contract_number"] is not None
        # Auto-generated number matches CTR-NNNN format
        assert data["contract_number"].startswith("CTR-")
        assert data["status"] == "draft"
        assert data["id"] is not None

    def test_list_contracts(self, authed_client):
        authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({"title": "List Test Contract"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/contracts/api/contracts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "contracts" in data
        assert data["total"] >= 1
        titles = [c["title"] for c in data["contracts"]]
        assert "List Test Contract" in titles

    def test_get_contract_with_versions(self, authed_client):
        # Create a contract
        create_resp = authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({"title": "Version Test Contract", "content": "v1 content"}),
            content_type="application/json",
        )
        contract_id = create_resp.get_json()["id"]

        resp = authed_client.get(f"/plugins/contracts/api/contracts/{contract_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == contract_id
        assert "versions" in data
        assert len(data["versions"]) >= 1
        assert data["versions"][0]["version_number"] == 1
        assert "activities" in data
        assert len(data["activities"]) >= 1

    def test_update_contract_creates_new_version(self, authed_client):
        # Create
        create_resp = authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({"title": "Update Version Test", "content": "original content"}),
            content_type="application/json",
        )
        contract_id = create_resp.get_json()["id"]

        # Update content — should create version 2
        update_resp = authed_client.put(
            f"/plugins/contracts/api/contracts/{contract_id}",
            data=json.dumps({"content": "updated content v2", "change_notes": "Second revision"}),
            content_type="application/json",
        )
        assert update_resp.status_code == 200

        # Fetch and verify versions
        resp = authed_client.get(f"/plugins/contracts/api/contracts/{contract_id}")
        data = resp.get_json()
        version_numbers = [v["version_number"] for v in data["versions"]]
        assert 2 in version_numbers

    def test_send_contract(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({"title": "Send Test Contract"}),
            content_type="application/json",
        )
        contract_id = create_resp.get_json()["id"]

        resp = authed_client.post(f"/plugins/contracts/api/contracts/{contract_id}/send")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "sent"

    def test_sign_contract(self, authed_client):
        create_resp = authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({"title": "Sign Test Contract"}),
            content_type="application/json",
        )
        contract_id = create_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/contracts/api/contracts/{contract_id}/sign",
            data=json.dumps({"signed_by": "Jane CEO"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "signed"
        assert data["signed_by"] == "Jane CEO"
        assert data["signed_at"] is not None

    def test_get_expiring_contracts(self, authed_client):
        import datetime

        near_date = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        authed_client.post(
            "/plugins/contracts/api/contracts",
            data=json.dumps({
                "title": "Expiring Soon Contract",
                "end_date": near_date,
            }),
            content_type="application/json",
        )

        resp = authed_client.get("/plugins/contracts/api/expiring?days=30")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "contracts" in data
        titles = [c["title"] for c in data["contracts"]]
        assert "Expiring Soon Contract" in titles

    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/contracts/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_contracts" in data
        assert "active_count" in data
        assert "expiring_soon" in data
        assert "total_value" in data
        assert data["total_contracts"] >= 1
