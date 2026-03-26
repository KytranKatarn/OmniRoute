import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import sql


def get_connection():
    """Return a new psycopg2 connection using KBS_* env vars."""
    return psycopg2.connect(
        host=os.getenv("KBS_DB_HOST", "kbs-postgres"),
        port=int(os.getenv("KBS_DB_PORT", "5432")),
        dbname=os.getenv("KBS_DB_NAME", "kbs"),
        user=os.getenv("KBS_DB_USER", "kbs"),
        password=os.getenv("KBS_DB_PASSWORD", ""),
    )


@contextmanager
def get_db_cursor(commit=True, dict_cursor=False):
    """
    Context manager that yields (conn, cur).

    Usage:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(...)
    """
    conn = get_connection()
    try:
        cursor_factory = psycopg2.extras.RealDictCursor if dict_cursor else None
        cur = conn.cursor(cursor_factory=cursor_factory) if cursor_factory else conn.cursor()
        try:
            yield conn, cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


def create_tenant_schema(tenant_id: int) -> None:
    """Create the schema for a tenant (tenant_{id})."""
    schema_name = f"tenant_{tenant_id}"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(schema_name)
            )
        )


def drop_tenant_schema(tenant_id: int) -> None:
    """Drop a tenant's schema — DESTRUCTIVE, no recovery."""
    schema_name = f"tenant_{tenant_id}"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema_name)
            )
        )


def set_tenant_search_path(cur, tenant_id: int) -> None:
    """Set the search_path to tenant_{id}, public for the current cursor's session."""
    schema_name = f"tenant_{tenant_id}"
    cur.execute(
        sql.SQL("SET search_path TO {}, public").format(
            sql.Identifier(schema_name)
        )
    )


def run_migration_file(filepath: str, schema: str = None) -> None:
    """
    Execute a SQL migration file.

    If schema is provided, sets search_path to that schema before executing.
    """
    with open(filepath, "r") as f:
        migration_sql = f.read()

    with get_db_cursor(commit=True) as (conn, cur):
        if schema:
            cur.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(schema)
                )
            )
        cur.execute(migration_sql)
