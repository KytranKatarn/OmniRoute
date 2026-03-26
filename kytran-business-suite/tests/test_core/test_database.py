"""
Tests for core/database.py.

These tests connect to the ARCHIE dev database (192.168.1.200).
Tenant schemas starting with 'tenant_9' are used and cleaned up after each test.
"""

import pytest

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    set_tenant_search_path,
)

# Use high IDs unlikely to conflict with real tenants
TEST_TENANT_ID = 99999


@pytest.fixture(autouse=True)
def cleanup_test_schemas():
    """Drop any tenant_9* schemas before and after each test."""
    _drop_test_schemas()
    yield
    _drop_test_schemas()


def _drop_test_schemas():
    """Drop all schemas starting with tenant_9 used in tests."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name LIKE 'tenant_9%'
            """
        )
        schemas = [row[0] for row in cur.fetchall()]

    for schema in schemas:
        tenant_id = int(schema.split("_", 1)[1])
        drop_tenant_schema(tenant_id)


def test_get_db_cursor_basic():
    """get_db_cursor returns a working connection and cursor."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT 1 AS val")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 1


def test_get_db_cursor_dict():
    """get_db_cursor with dict_cursor=True returns dict-like rows."""
    with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
        cur.execute("SELECT 42 AS answer")
        row = cur.fetchone()
    assert row is not None
    assert row["answer"] == 42


def test_create_tenant_schema_creates_pg_schema():
    """create_tenant_schema creates a PostgreSQL schema named tenant_{id}."""
    create_tenant_schema(TEST_TENANT_ID)

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name = %s
            """,
            (f"tenant_{TEST_TENANT_ID}",),
        )
        row = cur.fetchone()

    assert row is not None, f"Schema tenant_{TEST_TENANT_ID} was not created"
    assert row[0] == f"tenant_{TEST_TENANT_ID}"


def test_create_tenant_schema_idempotent():
    """create_tenant_schema can be called twice without error."""
    create_tenant_schema(TEST_TENANT_ID)
    create_tenant_schema(TEST_TENANT_ID)  # second call must not raise

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s",
            (f"tenant_{TEST_TENANT_ID}",),
        )
        count = cur.fetchone()[0]

    assert count == 1


def test_drop_tenant_schema_removes_schema():
    """drop_tenant_schema removes a previously created schema."""
    create_tenant_schema(TEST_TENANT_ID)
    drop_tenant_schema(TEST_TENANT_ID)

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
            (f"tenant_{TEST_TENANT_ID}",),
        )
        row = cur.fetchone()

    assert row is None, f"Schema tenant_{TEST_TENANT_ID} should have been dropped"


def test_set_tenant_search_path():
    """set_tenant_search_path sets the search_path to tenant schema + public."""
    create_tenant_schema(TEST_TENANT_ID)

    with get_db_cursor(commit=False) as (conn, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute("SHOW search_path")
        row = cur.fetchone()

    assert row is not None
    search_path = row[0]
    assert f"tenant_{TEST_TENANT_ID}" in search_path
