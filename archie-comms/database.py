"""Database connection for archie_comms — standalone, no Flask."""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager


def _get_db_password():
    """Read password from Docker secret or env var."""
    secret_path = "/run/secrets/db_password"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    return os.getenv("DB_PASSWORD", "")


def get_db():
    """Get a raw psycopg2 connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


@contextmanager
def get_db_cursor(commit=False):
    """Context manager yielding (conn, cursor) with RealDictCursor."""
    conn = get_db()
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    cur = conn.cursor()
    try:
        yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
