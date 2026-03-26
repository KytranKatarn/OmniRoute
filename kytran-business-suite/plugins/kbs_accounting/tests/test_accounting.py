"""Tests for the Accounting plugin — chart of accounts, transactions, expenses, reports, stats."""

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

TEST_TENANT_ID = 9910
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "accountingtest@example.com"
TEST_PASSWORD = "TestPass123!"

CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "../../kbs_crm/migrations/001_crm_tables.sql"
)
INV_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "../../kbs_invoicing/migrations/001_invoicing_tables.sql"
)
ACCT_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_accounting_tables.sql"
)


@pytest.fixture(scope="module")
def acct_app():
    """Create the Flask app with accounting plugin loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def acct_setup(acct_app):
    """Create test tenant, user, schema, and run CRM + Invoicing + Accounting migrations.

    Accounting depends on invoicing (manifest dependency), invoicing depends on CRM.
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
            VALUES (%s, 'Accounting Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Accounting Test Tenant', 'accounting-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable crm, invoicing, and accounting modules
        for slug in ("crm", "invoicing", "accounting"):
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
                """,
                (TEST_TENANT_ID, slug),
            )

    # Create tenant schema, run migrations in dependency order
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(INV_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(ACCT_MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(acct_app, acct_setup):
    """Yield a test client that is logged in and has the tenant session set."""
    with acct_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302), f"Login failed: {resp.status_code}"
        yield client


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _post_json(client, path, payload):
    return client.post(
        "/plugins/accounting" + path,
        data=json.dumps(payload),
        content_type="application/json",
    )


def _make_transaction(client, **kwargs):
    defaults = {
        "description": "Test income entry",
        "amount": 500.00,
        "transaction_type": "income",
        "category": "Sales Revenue",
    }
    defaults.update(kwargs)
    return _post_json(client, "/api/transactions", defaults)


def _make_expense(client, **kwargs):
    defaults = {
        "vendor": "Office Depot",
        "amount": 75.50,
        "category": "Office Supplies",
    }
    defaults.update(kwargs)
    return _post_json(client, "/api/expenses", defaults)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestAccounting:
    def test_list_chart_of_accounts_seeded_defaults(self, authed_client):
        """Chart of accounts should have 20 seeded default accounts."""
        resp = authed_client.get("/plugins/accounting/api/accounts")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "accounts" in data
        assert "grouped" in data
        # At least the 20 seeded accounts
        assert len(data["accounts"]) >= 20
        codes = [a["code"] for a in data["accounts"]]
        assert "1000" in codes  # Cash
        assert "4000" in codes  # Sales Revenue
        assert "7000" in codes  # Tax Expense
        grouped = data["grouped"]
        assert "asset" in grouped
        assert "revenue" in grouped
        assert "expense" in grouped

    def test_create_account(self, authed_client):
        """Should create a new account and return it."""
        resp = _post_json(
            authed_client,
            "/api/accounts",
            {"code": "9001", "name": "Test Reserve Account", "account_type": "asset", "sub_type": "other"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["code"] == "9001"
        assert data["name"] == "Test Reserve Account"
        assert data["account_type"] == "asset"

    def test_record_transaction(self, authed_client):
        """Should record a new income transaction and return 201."""
        resp = _make_transaction(authed_client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["description"] == "Test income entry"
        assert float(data["amount"]) == 500.00
        assert data["transaction_type"] == "income"
        assert data["status"] == "recorded"

    def test_list_transactions(self, authed_client):
        """Should list transactions with pagination metadata."""
        _make_transaction(authed_client)
        resp = authed_client.get("/plugins/accounting/api/transactions")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "transactions" in data
        assert "total" in data
        assert data["total"] >= 1

    def test_record_expense(self, authed_client):
        """Should record a new expense and emit expense.recorded event."""
        resp = _make_expense(authed_client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["vendor"] == "Office Depot"
        assert float(data["amount"]) == 75.50
        assert data["status"] == "pending"
        assert data["category"] == "Office Supplies"

    def test_list_expenses(self, authed_client):
        """Should list expenses with pagination and total."""
        _make_expense(authed_client, vendor="Staples", amount=30.00)
        resp = authed_client.get("/plugins/accounting/api/expenses")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "expenses" in data
        assert data["total"] >= 1

    def test_approve_expense(self, authed_client):
        """Approving a pending expense should set status to approved."""
        create_resp = _make_expense(authed_client, vendor="Amazon", amount=120.00)
        exp_id = create_resp.get_json()["id"]

        resp = _post_json(authed_client, f"/api/expenses/{exp_id}/approve", {})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "approved"
        assert data["id"] == exp_id

    def test_profit_loss_report(self, authed_client):
        """P&L report should return revenue, expenses, and net_income."""
        # Ensure at least one income transaction exists
        _make_transaction(authed_client, amount=1000.00, transaction_type="income")
        _make_transaction(authed_client, amount=200.00, transaction_type="expense", description="Expense txn")

        resp = authed_client.get("/plugins/accounting/api/reports/profit-loss")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "revenue" in data
        assert "expenses" in data
        assert "net_income" in data
        assert "period" in data
        assert float(data["revenue"]) >= 1000.00

    def test_balance_sheet(self, authed_client):
        """Balance sheet should return assets, liabilities, equity totals."""
        resp = authed_client.get("/plugins/accounting/api/reports/balance-sheet")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "assets" in data
        assert "liabilities" in data
        assert "equity" in data
        assert "total_assets" in data
        assert "total_liabilities" in data
        assert "total_equity" in data
        assert "balance_check" in data

    def test_stats(self, authed_client):
        """Stats endpoint should return revenue, expenses, net income, account count."""
        resp = authed_client.get("/plugins/accounting/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "revenue_this_month" in data
        assert "expenses_this_month" in data
        assert "net_income" in data
        assert "account_count" in data
        assert data["account_count"] >= 20
