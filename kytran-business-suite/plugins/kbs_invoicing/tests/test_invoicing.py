"""Tests for the Invoicing plugin — invoice CRUD, payments, line items, stats."""

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
TEST_TENANT_ID = 9902
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "invoicingtest@example.com"
TEST_PASSWORD = "TestPass123!"

CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "../../kbs_crm/migrations/001_crm_tables.sql"
)
INV_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_invoicing_tables.sql"
)


@pytest.fixture(scope="module")
def inv_app():
    """Create the Flask app with invoicing plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def inv_setup(inv_app):
    """Create test tenant, user, schema, CRM+Invoicing tables, and enable both modules.

    Invoicing depends on CRM — invoices reference crm_customers via FK.
    Yields dict with tenant_id, user_id. Cleans up afterwards.
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
            VALUES (%s, 'Invoicing Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Invoicing Test Tenant', 'invoicing-test-tenant', 'free', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable both crm and invoicing modules (invoicing depends on crm)
        for slug in ("crm", "invoicing"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create tenant schema, run CRM migration first (FK dependency), then invoicing
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(INV_MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(inv_app, inv_setup):
    """Yield a test client that is logged in and has the tenant session set."""
    with inv_app.test_client() as client:
        # Log in via form POST (auth route uses request.form, not JSON)
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302), f"Login failed: {resp.status_code} {resp.data}"

        yield client


# ======================================================================
# Helpers
# ======================================================================

def _make_invoice(client, **kwargs):
    """POST a new invoice with optional line items and return parsed JSON."""
    payload = {
        "customer_id": None,
        "due_date": "2026-12-31",
        "items": [
            {"description": "Consulting", "quantity": 2, "unit_price": 100.00},
            {"description": "Hosting", "quantity": 1, "unit_price": 50.00},
        ],
    }
    payload.update(kwargs)
    resp = client.post(
        "/plugins/invoicing/api/invoices",
        data=json.dumps(payload),
        content_type="application/json",
    )
    return resp


# ======================================================================
# Tests
# ======================================================================


class TestInvoicingCRUD:
    """Invoice CRUD tests."""

    def test_create_invoice_with_items(self, authed_client):
        resp = _make_invoice(authed_client)
        assert resp.status_code == 201, resp.data
        data = resp.get_json()
        assert data["id"] is not None
        assert data["invoice_number"].startswith("INV-")
        assert data["status"] == "draft"
        # subtotal = 2*100 + 1*50 = 250; tax = 250 * 13% = 32.50; total = 282.50
        assert float(data["subtotal"]) == 250.00
        assert float(data["tax"]) == 32.50
        assert float(data["total"]) == 282.50
        assert float(data["balance_due"]) == 282.50

    def test_list_invoices(self, authed_client):
        _make_invoice(authed_client)
        resp = authed_client.get("/plugins/invoicing/api/invoices")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "invoices" in data
        assert data["total"] >= 1

    def test_get_invoice_with_items(self, authed_client):
        create_resp = _make_invoice(authed_client)
        inv_id = create_resp.get_json()["id"]

        resp = authed_client.get(f"/plugins/invoicing/api/invoices/{inv_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["id"] == inv_id
        assert "items" in data
        assert len(data["items"]) == 2
        descs = [i["description"] for i in data["items"]]
        assert "Consulting" in descs
        assert "Hosting" in descs

    def test_update_invoice(self, authed_client):
        create_resp = _make_invoice(authed_client)
        inv_id = create_resp.get_json()["id"]

        resp = authed_client.put(
            f"/plugins/invoicing/api/invoices/{inv_id}",
            data=json.dumps({"notes": "Updated notes", "payment_method": "bank_transfer"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["notes"] == "Updated notes"
        assert data["payment_method"] == "bank_transfer"

    def test_mark_invoice_paid(self, authed_client):
        create_resp = _make_invoice(authed_client)
        inv_id = create_resp.get_json()["id"]
        total = float(create_resp.get_json()["total"])

        # Send first
        authed_client.post(f"/plugins/invoicing/api/invoices/{inv_id}/send")

        resp = authed_client.post(
            f"/plugins/invoicing/api/invoices/{inv_id}/mark-paid",
            data=json.dumps({"amount": total, "payment_method": "credit_card"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "paid"
        assert float(data["amount_paid"]) == total
        assert float(data["balance_due"]) == 0.00

    def test_get_stats(self, authed_client):
        resp = authed_client.get("/plugins/invoicing/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_invoices" in data
        assert "paid_count" in data
        assert "outstanding_total" in data
        assert "overdue_count" in data
        assert data["total_invoices"] >= 1

    def test_delete_draft_invoice(self, authed_client):
        create_resp = _make_invoice(authed_client)
        inv_id = create_resp.get_json()["id"]

        resp = authed_client.delete(f"/plugins/invoicing/api/invoices/{inv_id}")
        assert resp.status_code == 200
        assert resp.get_json()["deleted"] is True

        # Verify gone
        resp2 = authed_client.get(f"/plugins/invoicing/api/invoices/{inv_id}")
        assert resp2.status_code == 404

    def test_cannot_delete_sent_invoice(self, authed_client):
        create_resp = _make_invoice(authed_client)
        inv_id = create_resp.get_json()["id"]

        authed_client.post(f"/plugins/invoicing/api/invoices/{inv_id}/send")

        resp = authed_client.delete(f"/plugins/invoicing/api/invoices/{inv_id}")
        assert resp.status_code == 409

    def test_list_invoices_status_filter(self, authed_client):
        resp = authed_client.get("/plugins/invoicing/api/invoices?status=draft")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(i["status"] == "draft" for i in data["invoices"])
