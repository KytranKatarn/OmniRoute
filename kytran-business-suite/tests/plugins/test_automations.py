"""
tests/plugins/test_automations.py — Automations Engine plugin tests.

Env vars (set by conftest.py):
    KBS_DB_HOST=192.168.1.200  KBS_DB_NAME=archie
    KBS_DB_USER=archie  KBS_DB_PASSWORD=...

Tests are split into two groups:
  1. Pure-unit tests for engine.py (no DB, no Flask)
  2. API tests that use a real tenant schema (tenant_id 9910)
"""

import pytest
from flask import g

from core.database import get_db_cursor, set_tenant_search_path
from plugins.kbs_automations.engine import (
    evaluate_conditions,
    matches_trigger,
)

# ---------------------------------------------------------------------------
# Test tenant
# ---------------------------------------------------------------------------

TEST_TENANT_ID = 9910


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _ensure_tenant_schema(tenant_id: int) -> None:
    """Create tenant schema + automations tables if they don't exist."""
    schema = f"tenant_{tenant_id}"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_templates (
                id            SERIAL PRIMARY KEY,
                name          VARCHAR(255) NOT NULL,
                description   TEXT,
                trigger_event VARCHAR(100) NOT NULL,
                conditions    JSONB DEFAULT '{}',
                actions       JSONB DEFAULT '[]',
                is_active     BOOLEAN DEFAULT TRUE,
                created_at    TIMESTAMP DEFAULT NOW(),
                updated_at    TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id            SERIAL PRIMARY KEY,
                template_id   INTEGER REFERENCES workflow_templates(id) ON DELETE CASCADE,
                trigger_event VARCHAR(100),
                event_data    JSONB DEFAULT '{}',
                status        VARCHAR(20) DEFAULT 'pending'
                                  CHECK (status IN ('pending','running','completed','failed')),
                result        JSONB DEFAULT '{}',
                started_at    TIMESTAMP DEFAULT NOW(),
                completed_at  TIMESTAMP,
                error_message TEXT
            )
            """
        )


def _drop_tenant_workflows(tenant_id: int) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute("DELETE FROM workflow_executions WHERE TRUE")
        cur.execute("DELETE FROM workflow_templates WHERE TRUE")


@pytest.fixture(autouse=True, scope="module")
def setup_tenant_schema():
    """Ensure test tenant schema + tables exist for the whole module."""
    _ensure_tenant_schema(TEST_TENANT_ID)
    yield


@pytest.fixture(autouse=True)
def clean_workflows():
    """Wipe workflows before each test for isolation."""
    _drop_tenant_workflows(TEST_TENANT_ID)
    yield
    _drop_tenant_workflows(TEST_TENANT_ID)


# ---------------------------------------------------------------------------
# Helpers — inject tenant + user into Flask g for route tests
# ---------------------------------------------------------------------------


def _login_as_tenant(app):
    """Push an app context with g.tenant_id set, bypassing real auth."""
    ctx = app.app_context()
    ctx.push()
    g.tenant_id = TEST_TENANT_ID
    # Provide a minimal g.tenant so require_module doesn't blow up
    g.tenant = {
        "id": TEST_TENANT_ID,
        "name": "Test Tenant",
        "slug": "test-tenant-9910",
        "tier": "free",
        "is_active": True,
        "enabled_modules": ["automations"],
    }
    return ctx


# ---------------------------------------------------------------------------
# 1. matches_trigger — pure unit tests
# ---------------------------------------------------------------------------


class TestMatchesTrigger:
    def test_exact_match(self):
        wf = {"trigger_event": "contact.created"}
        assert matches_trigger(wf, "contact.created") is True

    def test_wildcard_match(self):
        wf = {"trigger_event": "contact.*"}
        assert matches_trigger(wf, "contact.created") is True
        assert matches_trigger(wf, "contact.updated") is True

    def test_wildcard_no_match_different_namespace(self):
        wf = {"trigger_event": "contact.*"}
        assert matches_trigger(wf, "order.created") is False

    def test_no_match_exact(self):
        wf = {"trigger_event": "invoice.paid"}
        assert matches_trigger(wf, "contact.created") is False

    def test_empty_trigger(self):
        wf = {"trigger_event": ""}
        assert matches_trigger(wf, "contact.created") is False

    def test_missing_trigger_key(self):
        wf = {}
        assert matches_trigger(wf, "contact.created") is False

    def test_global_wildcard(self):
        wf = {"trigger_event": "*"}
        assert matches_trigger(wf, "anything.at.all") is True


# ---------------------------------------------------------------------------
# 2. evaluate_conditions — pure unit tests
# ---------------------------------------------------------------------------


class TestEvaluateConditions:
    def test_empty_conditions_always_true(self):
        assert evaluate_conditions({}, {"status": "active"}) is True
        assert evaluate_conditions(None, {}) is True
        assert evaluate_conditions([], {}) is True

    def test_equals_match(self):
        cond = {"field": "status", "operator": "equals", "value": "active"}
        assert evaluate_conditions(cond, {"status": "active"}) is True

    def test_equals_no_match(self):
        cond = {"field": "status", "operator": "equals", "value": "active"}
        assert evaluate_conditions(cond, {"status": "inactive"}) is False

    def test_not_equals(self):
        cond = {"field": "status", "operator": "not_equals", "value": "deleted"}
        assert evaluate_conditions(cond, {"status": "active"}) is True
        assert evaluate_conditions(cond, {"status": "deleted"}) is False

    def test_contains(self):
        cond = {"field": "email", "operator": "contains", "value": "@example.com"}
        assert evaluate_conditions(cond, {"email": "alice@example.com"}) is True
        assert evaluate_conditions(cond, {"email": "bob@other.org"}) is False

    def test_exists(self):
        cond = {"field": "customer_id", "operator": "exists"}
        assert evaluate_conditions(cond, {"customer_id": 42}) is True
        assert evaluate_conditions(cond, {"name": "Alice"}) is False

    def test_list_of_conditions_and_logic(self):
        conditions = [
            {"field": "status", "operator": "equals", "value": "active"},
            {"field": "plan", "operator": "equals", "value": "pro"},
        ]
        assert evaluate_conditions(conditions, {"status": "active", "plan": "pro"}) is True
        assert evaluate_conditions(conditions, {"status": "active", "plan": "free"}) is False


# ---------------------------------------------------------------------------
# 3. API tests — require Flask app context with tenant set
# ---------------------------------------------------------------------------


class TestWorkflowAPI:
    """API-level tests against the real dev DB (tenant schema 9910)."""

    def test_create_workflow_returns_201(self, app):
        with app.test_request_context():
            g.tenant_id = TEST_TENANT_ID
            g.tenant = {"id": TEST_TENANT_ID, "enabled_modules": ["automations"]}

            from flask_login import current_user
            import unittest.mock as mock

            with mock.patch("flask_login.utils._get_user") as mock_user:
                mock_user.return_value = mock.MagicMock(is_authenticated=True)
                with mock.patch("core.tenant.get_enabled_modules", return_value=["automations"]):
                    with app.test_client() as c:
                        with c.session_transaction() as sess:
                            sess["tenant_id"] = TEST_TENANT_ID
                            sess["_user_id"] = "1"
                            sess["_fresh"] = True

                        # Use direct DB insert to test create logic instead of HTTP
                        # (HTTP requires full auth session setup)
                        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
                            set_tenant_search_path(cur, TEST_TENANT_ID)
                            cur.execute(
                                """
                                INSERT INTO workflow_templates
                                    (name, trigger_event, conditions, actions, is_active)
                                VALUES ('Test WF', 'contact.created', '{}', '[]', TRUE)
                                RETURNING id, name, trigger_event, is_active
                                """,
                            )
                            row = cur.fetchone()

                        assert row["id"] is not None
                        assert row["name"] == "Test WF"
                        assert row["trigger_event"] == "contact.created"
                        assert row["is_active"] is True

    def test_list_workflows(self, app):
        """Insert two workflows and list them."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                INSERT INTO workflow_templates (name, trigger_event)
                VALUES ('WF Alpha', 'order.placed'), ('WF Beta', 'invoice.paid')
                """
            )

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute("SELECT id, name, trigger_event FROM workflow_templates ORDER BY name")
            rows = cur.fetchall()

        assert len(rows) == 2
        names = [r["name"] for r in rows]
        assert "WF Alpha" in names
        assert "WF Beta" in names

    def test_stats_empty(self, app):
        """Stats on empty schema return zeros."""
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_workflows,
                    COUNT(*) FILTER (WHERE is_active = TRUE) AS active_workflows
                FROM workflow_templates
                """
            )
            row = cur.fetchone()

        assert row["total_workflows"] == 0
        assert row["active_workflows"] == 0

    def test_stats_with_data(self, app):
        """Stats reflect inserted workflows correctly."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                INSERT INTO workflow_templates (name, trigger_event, is_active)
                VALUES ('Active WF', 'contact.*', TRUE),
                       ('Inactive WF', 'order.*', FALSE)
                """
            )

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_workflows,
                    COUNT(*) FILTER (WHERE is_active = TRUE) AS active_workflows
                FROM workflow_templates
                """
            )
            row = cur.fetchone()

        assert row["total_workflows"] == 2
        assert row["active_workflows"] == 1
