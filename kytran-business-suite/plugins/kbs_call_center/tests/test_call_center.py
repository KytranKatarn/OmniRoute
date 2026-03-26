"""Tests for the Call Center plugin — numbers, calls, escalations, CRM lookup, stats."""

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

# Use a test tenant ID in the 9xxx range to avoid collisions
TEST_TENANT_ID = 9906
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "callcentertest@example.com"
TEST_PASSWORD = "TestPass123!"
CC_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_call_center_tables.sql"
)
CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "kbs_crm",
    "migrations",
    "001_crm_tables.sql",
)


@pytest.fixture(scope="module")
def cc_app():
    """Create the Flask app for Call Center tests."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def cc_setup(cc_app):
    """Create test tenant, user, schema, tables, and enable call-center + crm modules."""
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
            VALUES (%s, 'CC Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'CC Test Tenant', 'cc-test-tenant', 'enterprise', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable call-center and crm modules
        for slug in ("call-center", "crm"):
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
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(CC_MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(cc_app, cc_setup):
    """Yield a test client that is logged in."""
    with cc_app.test_client() as client:
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


class TestPhoneNumbers:
    """Phone number management tests."""

    def test_add_phone_number(self, authed_client):
        resp = authed_client.post(
            "/plugins/call-center/api/numbers",
            data=json.dumps({"number": "+15550001234", "provider": "twilio", "label": "Main Line"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["number"] == "+15550001234"
        assert data["provider"] == "twilio"
        assert data["id"] is not None

    def test_list_numbers(self, authed_client):
        authed_client.post(
            "/plugins/call-center/api/numbers",
            data=json.dumps({"number": "+15550005678", "provider": "telnyx"}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/call-center/api/numbers")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "numbers" in data
        assert len(data["numbers"]) >= 1


class TestCallRecords:
    """Call record lifecycle tests."""

    def _add_number(self, client):
        resp = client.post(
            "/plugins/call-center/api/numbers",
            data=json.dumps({"number": "+15559990001", "provider": "twilio"}),
            content_type="application/json",
        )
        return resp.get_json()["id"]

    def test_log_call(self, authed_client):
        num_id = self._add_number(authed_client)
        resp = authed_client.post(
            "/plugins/call-center/api/calls",
            data=json.dumps({"phone_number_id": num_id, "direction": "inbound"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["direction"] == "inbound"
        assert data["status"] == "initiated"
        assert data["id"] is not None

    def test_end_call(self, authed_client):
        num_id = self._add_number(authed_client)
        create_resp = authed_client.post(
            "/plugins/call-center/api/calls",
            data=json.dumps({"phone_number_id": num_id, "direction": "outbound"}),
            content_type="application/json",
        )
        call_id = create_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/call-center/api/calls/{call_id}/end",
            data=json.dumps({"duration_seconds": 120}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "completed"
        assert data["duration_seconds"] == 120
        assert data["ended_at"] is not None


class TestEscalations:
    """Escalation lifecycle tests."""

    def _create_call(self, client):
        num_resp = client.post(
            "/plugins/call-center/api/numbers",
            data=json.dumps({"number": "+15558880001", "provider": "other"}),
            content_type="application/json",
        )
        num_id = num_resp.get_json()["id"]
        call_resp = client.post(
            "/plugins/call-center/api/calls",
            data=json.dumps({"phone_number_id": num_id, "direction": "inbound"}),
            content_type="application/json",
        )
        return call_resp.get_json()["id"]

    def test_escalate_call(self, authed_client):
        call_id = self._create_call(authed_client)
        resp = authed_client.post(
            f"/plugins/call-center/api/calls/{call_id}/escalate",
            data=json.dumps({"reason": "Angry customer", "priority": "high"}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["reason"] == "Angry customer"
        assert data["priority"] == "high"
        assert data["status"] == "pending"
        assert data["id"] is not None

    def test_resolve_escalation(self, authed_client):
        call_id = self._create_call(authed_client)
        esc_resp = authed_client.post(
            f"/plugins/call-center/api/calls/{call_id}/escalate",
            data=json.dumps({"reason": "Billing issue", "priority": "normal"}),
            content_type="application/json",
        )
        esc_id = esc_resp.get_json()["id"]

        resp = authed_client.post(
            f"/plugins/call-center/api/escalations/{esc_id}/resolve",
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None


class TestCRMLookup:
    """CRM phone lookup test."""

    def test_crm_lookup(self, authed_client):
        # Seed a CRM customer with a known phone number
        with get_db_cursor(commit=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                INSERT INTO crm_customers (name, email, phone, company)
                VALUES ('Lookup Customer', 'lookup@example.com', '+15551112222', 'Acme Corp')
                ON CONFLICT DO NOTHING
                """
            )

        resp = authed_client.get("/plugins/call-center/api/crm/lookup?phone=5551112222")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "customers" in data
        names = [c["name"] for c in data["customers"]]
        assert "Lookup Customer" in names


class TestStats:
    """Stats endpoint test."""

    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/call-center/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_calls" in data
        assert "active_calls" in data
        assert "avg_duration_seconds" in data
        assert "pending_escalations" in data
