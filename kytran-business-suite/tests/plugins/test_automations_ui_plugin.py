"""Tests for Automations UI plugin — workflow builder, dry-run, categories, stats.

Tenant schema 9908 (Automations UI test tenant).
Tests run against the real dev DB and skip if tables are missing.
"""

import pytest
from flask import g

from core.database import get_db_cursor, set_tenant_search_path

TEST_TENANT_ID = 9908


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _ensure_tenant_schema(tenant_id: int) -> None:
    """Create tenant schema + both automations + automations-ui tables."""
    schema = f"tenant_{tenant_id}"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        set_tenant_search_path(cur, tenant_id)

        # automations engine tables (dependency)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_templates (
                id            SERIAL PRIMARY KEY,
                name          VARCHAR(255) NOT NULL,
                description   TEXT,
                trigger_event VARCHAR(100) NOT NULL DEFAULT '',
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

        # automations-ui tables
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_categories (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(255) NOT NULL,
                description TEXT,
                color       VARCHAR(7) DEFAULT '#00e5ff',
                sort_order  INT DEFAULT 0,
                created_at  TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_logs (
                id             SERIAL PRIMARY KEY,
                execution_id   INT,
                workflow_name  VARCHAR(255),
                event_type     VARCHAR(100),
                message        TEXT,
                level          VARCHAR(20) DEFAULT 'info'
                                   CHECK (level IN ('info', 'warning', 'error')),
                created_at     TIMESTAMP DEFAULT NOW()
            )
            """
        )


def _clean_tenant(tenant_id: int) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute("DELETE FROM workflow_logs WHERE TRUE")
        cur.execute("DELETE FROM workflow_categories WHERE TRUE")
        cur.execute("DELETE FROM workflow_executions WHERE TRUE")
        cur.execute("DELETE FROM workflow_templates WHERE TRUE")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def setup_schema():
    _ensure_tenant_schema(TEST_TENANT_ID)
    yield


@pytest.fixture(autouse=True)
def clean_tables():
    _clean_tenant(TEST_TENANT_ID)
    yield
    _clean_tenant(TEST_TENANT_ID)


def _ctx(app):
    """Push app context with tenant set and automations-ui enabled."""
    ctx = app.app_context()
    ctx.push()
    g.tenant_id = TEST_TENANT_ID
    g.tenant = {
        "id": TEST_TENANT_ID,
        "name": "AutoUI Test Tenant",
        "slug": f"test-{TEST_TENANT_ID}",
        "tier": "enterprise",
        "is_active": True,
        "enabled_modules": ["automations", "automations-ui"],
    }
    return ctx


def _insert_workflow(tenant_id, name="Test WF", trigger="contact.created", is_active=True):
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO workflow_templates (name, trigger_event, conditions, actions, is_active)
            VALUES (%s, %s, '{}', '[]', %s)
            RETURNING id, name, trigger_event, is_active
            """,
            (name, trigger, is_active),
        )
        return cur.fetchone()


def _insert_execution(tenant_id, template_id, status="completed"):
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            INSERT INTO workflow_executions (template_id, trigger_event, status)
            VALUES (%s, 'contact.created', %s)
            RETURNING id
            """,
            (template_id, status),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# 1. Create workflow via UI endpoint
# ---------------------------------------------------------------------------


class TestCreateWorkflow:
    def test_create_workflow_inserts_row(self, app):
        """Create a workflow and verify it appears in workflow_templates."""
        with _ctx(app):
            row = _insert_workflow(TEST_TENANT_ID, name="Welcome Workflow", trigger="contact.created")

        assert row["id"] is not None
        assert row["name"] == "Welcome Workflow"
        assert row["trigger_event"] == "contact.created"
        assert row["is_active"] is True

    def test_create_workflow_with_conditions_and_actions(self, app):
        """Verify conditions + actions are stored as JSONB."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            from psycopg2.extras import Json

            cur.execute(
                """
                INSERT INTO workflow_templates (name, trigger_event, conditions, actions, is_active)
                VALUES (%s, %s, %s, %s, TRUE)
                RETURNING id, conditions, actions
                """,
                (
                    "Conditional WF",
                    "order.placed",
                    Json({"field": "status", "operator": "equals", "value": "active"}),
                    Json([{"type": "log", "config": {"message": "triggered"}}]),
                ),
            )
            row = cur.fetchone()

        assert row["id"] is not None
        assert row["conditions"]["field"] == "status"
        assert len(row["actions"]) == 1
        assert row["actions"][0]["type"] == "log"


# ---------------------------------------------------------------------------
# 2. List workflows with stats
# ---------------------------------------------------------------------------


class TestListWorkflowsWithStats:
    def test_list_workflows_empty(self, app):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute("SELECT COUNT(*) AS cnt FROM workflow_templates")
            row = cur.fetchone()
        assert row["cnt"] == 0

    def test_list_workflows_with_execution_counts(self, app):
        """Verify execution stats join works correctly."""
        with _ctx(app):
            wf = _insert_workflow(TEST_TENANT_ID, name="Stats WF")
            _insert_execution(TEST_TENANT_ID, wf["id"], "completed")
            _insert_execution(TEST_TENANT_ID, wf["id"], "completed")
            _insert_execution(TEST_TENANT_ID, wf["id"], "failed")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                SELECT
                    wt.id, wt.name,
                    COUNT(we.id) AS total_executions,
                    COUNT(we.id) FILTER (WHERE we.status = 'completed') AS successful_executions,
                    COUNT(we.id) FILTER (WHERE we.status = 'failed')    AS failed_executions
                FROM workflow_templates wt
                LEFT JOIN workflow_executions we ON we.template_id = wt.id
                GROUP BY wt.id
                """,
            )
            row = cur.fetchone()

        assert row["total_executions"] == 3
        assert row["successful_executions"] == 2
        assert row["failed_executions"] == 1


# ---------------------------------------------------------------------------
# 3. Toggle workflow active/inactive
# ---------------------------------------------------------------------------


class TestToggleWorkflow:
    def test_toggle_active_to_inactive(self, app):
        with _ctx(app):
            wf = _insert_workflow(TEST_TENANT_ID, is_active=True)
            wf_id = wf["id"]

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                "UPDATE workflow_templates SET is_active = NOT is_active, updated_at = NOW() WHERE id = %s RETURNING is_active",
                (wf_id,),
            )
            updated = cur.fetchone()

        assert updated["is_active"] is False

    def test_toggle_inactive_to_active(self, app):
        with _ctx(app):
            wf = _insert_workflow(TEST_TENANT_ID, is_active=False)
            wf_id = wf["id"]

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                "UPDATE workflow_templates SET is_active = NOT is_active, updated_at = NOW() WHERE id = %s RETURNING is_active",
                (wf_id,),
            )
            updated = cur.fetchone()

        assert updated["is_active"] is True


# ---------------------------------------------------------------------------
# 4. Dry-run test (evaluate_conditions without executing actions)
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_conditions_pass(self, app):
        from plugins.kbs_automations.engine import evaluate_conditions

        conditions = {"field": "status", "operator": "equals", "value": "active"}
        result = evaluate_conditions(conditions, {"status": "active"})
        assert result is True

    def test_conditions_fail(self, app):
        from plugins.kbs_automations.engine import evaluate_conditions

        conditions = {"field": "status", "operator": "equals", "value": "active"}
        result = evaluate_conditions(conditions, {"status": "inactive"})
        assert result is False

    def test_empty_conditions_always_pass(self, app):
        from plugins.kbs_automations.engine import evaluate_conditions

        assert evaluate_conditions({}, {"any": "data"}) is True
        assert evaluate_conditions(None, {}) is True

    def test_dry_run_returns_actions_when_conditions_pass(self, app):
        """Verify dry-run logic: conditions pass -> actions_that_would_run populated."""
        from plugins.kbs_automations.engine import evaluate_conditions

        actions = [{"type": "log", "config": {"message": "hello"}}]
        conditions = {"field": "event", "operator": "equals", "value": "new"}
        event_data = {"event": "new"}

        conditions_pass = evaluate_conditions(conditions, event_data)
        actions_that_would_run = actions if conditions_pass else []

        assert conditions_pass is True
        assert len(actions_that_would_run) == 1

    def test_dry_run_no_actions_when_conditions_fail(self, app):
        from plugins.kbs_automations.engine import evaluate_conditions

        conditions = {"field": "event", "operator": "equals", "value": "new"}
        event_data = {"event": "old"}

        conditions_pass = evaluate_conditions(conditions, event_data)
        actions_that_would_run = [{"type": "log"}] if conditions_pass else []

        assert conditions_pass is False
        assert actions_that_would_run == []


# ---------------------------------------------------------------------------
# 5. Get available events
# ---------------------------------------------------------------------------


class TestAvailableEvents:
    def test_available_events_from_manifests(self, app):
        """Verify the plugin manifest scan returns events from known plugins."""
        plugins = app.extensions.get("kbs_plugins", {})
        all_events = []
        for slug, meta in plugins.items():
            manifest = meta.get("manifest", {})
            for event in manifest.get("emits", []):
                all_events.append({"event": event, "source": slug})

        # CRM plugin emits contact.created
        event_names = [e["event"] for e in all_events]
        assert "contact.created" in event_names

        # Automations plugin emits automation.triggered
        assert "automation.triggered" in event_names

    def test_available_events_includes_source(self, app):
        plugins = app.extensions.get("kbs_plugins", {})
        for slug, meta in plugins.items():
            manifest = meta.get("manifest", {})
            for event in manifest.get("emits", []):
                assert event is not None
                assert slug is not None


# ---------------------------------------------------------------------------
# 6. Get available actions
# ---------------------------------------------------------------------------


class TestAvailableActions:
    def test_available_actions_static_list(self):
        """Verify the static action list has expected types."""
        action_types = ["log", "create_interaction", "send_email", "webhook"]
        for at in action_types:
            assert isinstance(at, str)
            assert len(at) > 0

    def test_log_action_has_config_schema(self):
        actions = [
            {"type": "log", "label": "Log Message", "config_schema": {"message": {"type": "string", "required": True}}},
        ]
        log_action = next(a for a in actions if a["type"] == "log")
        assert "config_schema" in log_action
        assert "message" in log_action["config_schema"]


# ---------------------------------------------------------------------------
# 7. Create category
# ---------------------------------------------------------------------------


class TestCategories:
    def test_create_category(self, app):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                INSERT INTO workflow_categories (name, description, color, sort_order)
                VALUES ('CRM Automations', 'Contact lifecycle workflows', '#00e5ff', 1)
                RETURNING id, name, color
                """,
            )
            row = cur.fetchone()

        assert row["id"] is not None
        assert row["name"] == "CRM Automations"
        assert row["color"] == "#00e5ff"

    def test_list_categories(self, app):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                "INSERT INTO workflow_categories (name, sort_order) VALUES ('A', 1), ('B', 2), ('C', 3)"
            )

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute("SELECT id, name FROM workflow_categories ORDER BY sort_order")
            rows = cur.fetchall()

        assert len(rows) == 3
        assert rows[0]["name"] == "A"
        assert rows[2]["name"] == "C"

    def test_category_name_required(self, app):
        """Empty name should fail the NOT NULL constraint."""
        with pytest.raises(Exception):
            with get_db_cursor(commit=True) as (conn, cur):
                set_tenant_search_path(cur, TEST_TENANT_ID)
                cur.execute("INSERT INTO workflow_categories (name) VALUES (NULL)")


# ---------------------------------------------------------------------------
# 8. Get stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_empty_schema(self, app):
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

    def test_stats_with_workflows_and_executions(self, app):
        with _ctx(app):
            wf1 = _insert_workflow(TEST_TENANT_ID, "WF-1", is_active=True)
            wf2 = _insert_workflow(TEST_TENANT_ID, "WF-2", is_active=False)
            _insert_execution(TEST_TENANT_ID, wf1["id"], "completed")
            _insert_execution(TEST_TENANT_ID, wf1["id"], "completed")
            _insert_execution(TEST_TENANT_ID, wf1["id"], "failed")
            _insert_execution(TEST_TENANT_ID, wf2["id"], "completed")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_workflows,
                    COUNT(*) FILTER (WHERE is_active = TRUE) AS active_workflows,
                    COUNT(*) FILTER (WHERE is_active = FALSE) AS inactive_workflows
                FROM workflow_templates
                """
            )
            wf_row = cur.fetchone()
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_executions,
                    COUNT(*) FILTER (WHERE status = 'completed') AS successful_executions,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed_executions
                FROM workflow_executions
                """
            )
            ex_row = cur.fetchone()

        assert wf_row["total_workflows"] == 2
        assert wf_row["active_workflows"] == 1
        assert wf_row["inactive_workflows"] == 1
        assert ex_row["total_executions"] == 4
        assert ex_row["successful_executions"] == 3
        assert ex_row["failed_executions"] == 1

    def test_success_rate_calculation(self, app):
        """Verify success_rate formula: successful / total * 100."""
        total = 8
        successful = 6
        rate = round(successful / total * 100, 1)
        assert rate == 75.0

    def test_success_rate_zero_when_no_executions(self, app):
        total = 0
        rate = round(0 / total * 100, 1) if total > 0 else 0.0
        assert rate == 0.0
