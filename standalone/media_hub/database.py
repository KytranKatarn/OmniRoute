"""
Standalone DB shim for Media Hub.

Exposes the same `get_db_cursor` contract the platform provides, but
backed by DATABASE_URL so the standalone container points at its own
Postgres instance. Drop-in for `from database import get_db_cursor` in
tools/media_hub/ — lives at /app/database.py inside the container so
Python resolves it before anything else.
"""

import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor


def _connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. The standalone Media Hub needs its own "
            "Postgres — do NOT point it at the ARCHIE platform DB."
        )
    return psycopg2.connect(url)


@contextmanager
def get_db_cursor(cursor_factory=RealDictCursor, commit=False):
    conn = _connect()
    try:
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


def get_db():
    """Tuple-style accessor kept for parity with platform `db.get_db`."""
    return _connect()
