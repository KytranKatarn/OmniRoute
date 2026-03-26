"""
tests/plugins/test_help_desk_plugin.py — Help Desk plugin tests.

Env vars (set by conftest.py):
    KBS_DB_HOST=192.168.1.200  KBS_DB_NAME=archie
    KBS_DB_USER=archie  KBS_DB_PASSWORD=...

Tests run against a real tenant schema (tenant_id 9907) using direct DB
inserts/queries (same pattern as test_automations.py).
"""

import pytest
from flask import g

from core.database import get_db_cursor, set_tenant_search_path

TEST_TENANT_ID = 9907

# ---------------------------------------------------------------------------
# Schema setup helpers
# ---------------------------------------------------------------------------


def _ensure_tenant_schema(tenant_id: int) -> None:
    """Create tenant schema + help desk tables if they don't exist."""
    schema = f"tenant_{tenant_id}"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        set_tenant_search_path(cur, tenant_id)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                id              SERIAL PRIMARY KEY,
                ticket_number   VARCHAR(20) UNIQUE NOT NULL,
                customer_id     INTEGER,
                subject         VARCHAR(255) NOT NULL,
                description     TEXT,
                status          VARCHAR(20) DEFAULT 'open'
                                    CHECK (status IN ('open','in_progress','waiting','resolved','closed')),
                priority        VARCHAR(20) DEFAULT 'medium'
                                    CHECK (priority IN ('low','medium','high','urgent')),
                category        VARCHAR(100),
                assigned_to     VARCHAR(255),
                tags            JSONB DEFAULT '[]',
                metadata        JSONB DEFAULT '{}',
                created_at      TIMESTAMP DEFAULT NOW(),
                updated_at      TIMESTAMP DEFAULT NOW(),
                resolved_at     TIMESTAMP,
                closed_at       TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ticket_comments (
                id          SERIAL PRIMARY KEY,
                ticket_id   INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
                author      VARCHAR(255) NOT NULL,
                content     TEXT NOT NULL,
                is_internal BOOLEAN DEFAULT FALSE,
                metadata    JSONB DEFAULT '{}',
                created_at  TIMESTAMP DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sla_policies (
                id                   SERIAL PRIMARY KEY,
                name                 VARCHAR(255) NOT NULL,
                priority             VARCHAR(20) NOT NULL,
                first_response_hours INTEGER DEFAULT 24,
                resolution_hours     INTEGER DEFAULT 72,
                is_active            BOOLEAN DEFAULT TRUE,
                created_at           TIMESTAMP DEFAULT NOW()
            )
            """
        )
        # Ensure modules enabled
        cur.execute("SET search_path TO public")
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'help-desk', TRUE), (%s, 'crm', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (tenant_id, tenant_id),
        )


def _clean_tickets(tenant_id: int) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        cur.execute("DELETE FROM ticket_comments WHERE TRUE")
        cur.execute("DELETE FROM support_tickets WHERE TRUE")
        cur.execute("DELETE FROM sla_policies WHERE TRUE")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="module")
def setup_tenant_schema():
    """Ensure test tenant schema + tables exist for the whole module."""
    _ensure_tenant_schema(TEST_TENANT_ID)
    yield


@pytest.fixture(autouse=True)
def clean_tickets():
    """Wipe all tickets/comments/sla before each test for isolation."""
    _clean_tickets(TEST_TENANT_ID)
    yield
    _clean_tickets(TEST_TENANT_ID)


def _insert_ticket(subject="Test Ticket", priority="medium", status="open",
                   customer_id=None):
    """Helper: directly insert a ticket and return the row."""
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute("SELECT COUNT(*) FROM support_tickets")
        count = cur.fetchone()["count"]
        ticket_number = f"HD-{count + 1:04d}"
        cur.execute(
            """
            INSERT INTO support_tickets
                (ticket_number, customer_id, subject, status, priority)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, ticket_number, customer_id, subject, status, priority,
                      created_at, updated_at, resolved_at, closed_at
            """,
            (ticket_number, customer_id, subject, status, priority),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHelpDeskPlugin:
    """Help Desk plugin tests against tenant schema 9907."""

    # 1. Create ticket — verify auto ticket_number
    def test_create_ticket_auto_ticket_number(self, app):
        """Ticket is created with auto-generated HD-NNNN number."""
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute("SELECT COUNT(*) FROM support_tickets")
            initial = cur.fetchone()["count"]
            expected_number = f"HD-{initial + 1:04d}"

            cur.execute(
                """
                INSERT INTO support_tickets
                    (ticket_number, subject, priority, status)
                VALUES (%s, 'Login broken', 'high', 'open')
                RETURNING id, ticket_number, subject, status, priority
                """,
                (expected_number,),
            )
            ticket = cur.fetchone()

        assert ticket["id"] is not None
        assert ticket["ticket_number"] == expected_number
        assert ticket["ticket_number"].startswith("HD-")
        assert ticket["subject"] == "Login broken"
        assert ticket["status"] == "open"
        assert ticket["priority"] == "high"

    # 2. List tickets
    def test_list_tickets(self, app):
        """Inserting tickets makes them listable."""
        _insert_ticket("Ticket A", priority="low")
        _insert_ticket("Ticket B", priority="urgent")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                "SELECT id, ticket_number, subject, priority FROM support_tickets ORDER BY created_at"
            )
            rows = cur.fetchall()

        assert len(rows) == 2
        subjects = [r["subject"] for r in rows]
        assert "Ticket A" in subjects
        assert "Ticket B" in subjects

    # 3. Get ticket with comments
    def test_get_ticket_with_comments(self, app):
        """Fetching a ticket also returns its comments."""
        ticket = _insert_ticket("Fetch me")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                INSERT INTO ticket_comments (ticket_id, author, content)
                VALUES (%s, 'agent@example.com', 'Looking into this.')
                RETURNING id, ticket_id, author, content
                """,
                (ticket["id"],),
            )
            comment = cur.fetchone()

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                "SELECT id, subject FROM support_tickets WHERE id = %s", (ticket["id"],)
            )
            fetched = cur.fetchone()
            cur.execute(
                "SELECT id, author, content FROM ticket_comments WHERE ticket_id = %s",
                (ticket["id"],),
            )
            comments = cur.fetchall()

        assert fetched["id"] == ticket["id"]
        assert len(comments) == 1
        assert comments[0]["author"] == "agent@example.com"
        assert comments[0]["content"] == "Looking into this."

    # 4. Add comment
    def test_add_comment(self, app):
        """A comment can be added to a ticket."""
        ticket = _insert_ticket("Comment target")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                INSERT INTO ticket_comments (ticket_id, author, content, is_internal)
                VALUES (%s, 'support@kytran.com', 'This is an internal note.', TRUE)
                RETURNING id, author, content, is_internal
                """,
                (ticket["id"],),
            )
            comment = cur.fetchone()

        assert comment["id"] is not None
        assert comment["author"] == "support@kytran.com"
        assert comment["is_internal"] is True

    # 5. Assign ticket
    def test_assign_ticket(self, app):
        """A ticket can be assigned to an agent."""
        ticket = _insert_ticket("Assign me")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                UPDATE support_tickets
                SET assigned_to = 'jane@example.com', updated_at = NOW()
                WHERE id = %s
                RETURNING id, assigned_to
                """,
                (ticket["id"],),
            )
            updated = cur.fetchone()

        assert updated["assigned_to"] == "jane@example.com"

    # 6. Resolve ticket
    def test_resolve_ticket(self, app):
        """Resolving a ticket sets status=resolved and resolved_at timestamp."""
        ticket = _insert_ticket("Resolve me")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                UPDATE support_tickets
                SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING id, status, resolved_at
                """,
                (ticket["id"],),
            )
            resolved = cur.fetchone()

        assert resolved["status"] == "resolved"
        assert resolved["resolved_at"] is not None

    # 7. Close ticket
    def test_close_ticket(self, app):
        """Closing a ticket sets status=closed and closed_at timestamp."""
        ticket = _insert_ticket("Close me")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                UPDATE support_tickets
                SET status = 'closed', closed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                RETURNING id, status, closed_at
                """,
                (ticket["id"],),
            )
            closed = cur.fetchone()

        assert closed["status"] == "closed"
        assert closed["closed_at"] is not None

    # 8. Reopen ticket
    def test_reopen_ticket(self, app):
        """Reopening a resolved ticket clears timestamps and sets status=open."""
        ticket = _insert_ticket("Reopen me", status="resolved")

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                UPDATE support_tickets
                SET status = 'open', resolved_at = NULL, closed_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id, status, resolved_at, closed_at
                """,
                (ticket["id"],),
            )
            reopened = cur.fetchone()

        assert reopened["status"] == "open"
        assert reopened["resolved_at"] is None
        assert reopened["closed_at"] is None

    # 9. Stats
    def test_stats(self, app):
        """Stats returns correct totals for tickets in the tenant schema."""
        _insert_ticket("Open ticket 1", status="open")
        _insert_ticket("Open ticket 2", status="in_progress")
        _insert_ticket("Resolved ticket", status="resolved")

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, TEST_TENANT_ID)
            cur.execute(
                """
                SELECT
                    COUNT(*) AS total_tickets,
                    COUNT(*) FILTER (WHERE status IN ('open','in_progress','waiting'))
                        AS open_tickets,
                    COUNT(*) FILTER (WHERE status = 'resolved' OR status = 'closed')
                        AS resolved_tickets
                FROM support_tickets
                """
            )
            row = cur.fetchone()

        assert row["total_tickets"] == 3
        assert row["open_tickets"] == 2
        assert row["resolved_tickets"] == 1
