"""
Database Connection Helper
Provides get_db() function and connection pooling for scripts and modules.
"""

from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import os
import threading
import atexit

# Thread-safe connection pool
_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    """Get or create the connection pool (thread-safe singleton)"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pool.ThreadedConnectionPool(
                    minconn=5,
                    maxconn=50,
                    host=os.environ.get("DB_HOST", "archie_database"),
                    port=os.environ.get("DB_PORT", "5432"),
                    database=os.environ.get("DB_NAME", "archie"),
                    user=os.environ.get("DB_USER", "archie"),
                    password=os.environ.get("DB_PASSWORD", ""),
                )
    return _pool


def _cleanup_pool():
    """Cleanup connection pool on exit"""
    global _pool
    if _pool is not None:
        _pool.closeall()


atexit.register(_cleanup_pool)


class _PooledConnection:
    """Wrapper that returns connection to pool on close() instead of destroying it."""

    __slots__ = ("_conn", "_pool", "_released")

    def __init__(self, conn, pool_ref):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool_ref)
        object.__setattr__(self, "_released", False)

    def close(self):
        if not self._released:
            object.__setattr__(self, "_released", True)
            try:
                self._pool.putconn(self._conn)
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def get_db():
    """
    Get a database connection from the pool.

    Returns a wrapper where .close() returns the connection to the pool
    instead of destroying it.  All other attributes delegate to the
    underlying psycopg2 connection.

    For safer usage, prefer get_db_connection() context manager.

    Returns:
        _PooledConnection wrapping a psycopg2 connection
    """
    p = _get_pool()
    return _PooledConnection(p.getconn(), p)


def release_db(conn):
    """
    Return a connection to the pool.

    Args:
        conn: The connection (or _PooledConnection wrapper) to release
    """
    if conn is not None:
        try:
            if isinstance(conn, _PooledConnection):
                conn.close()  # delegates to putconn
            else:
                _get_pool().putconn(conn)
        except Exception:
            pass  # Pool may be closed during shutdown


@contextmanager
def get_db_connection(cursor_factory=None):
    """
    Context manager for safe database connections with automatic cleanup.

    Usage:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT ...")
            # Connection automatically returned to pool

    Or with RealDictCursor:
        with get_db_connection(cursor_factory=RealDictCursor) as conn:
            cur = conn.cursor()
            # Returns dicts instead of tuples

    Args:
        cursor_factory: Optional cursor factory (e.g., RealDictCursor)

    Yields:
        _PooledConnection wrapper (close() returns to pool)
    """
    conn = None
    try:
        conn = get_db()
        if cursor_factory:
            conn.cursor_factory = cursor_factory
        yield conn
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            conn.close()  # _PooledConnection.close() → putconn


@contextmanager
def get_db_cursor(cursor_factory=RealDictCursor, commit=True):
    """
    Context manager for safe database cursor with automatic cleanup.

    Usage:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()
            # Automatically commits and returns connection to pool

    For read-only queries:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT ...")

    Args:
        cursor_factory: Cursor factory (default: RealDictCursor)
        commit: Whether to auto-commit on success (default: True)

    Yields:
        Tuple of (connection, cursor)
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=cursor_factory)
        yield conn, cur
        if commit:
            conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            conn.close()  # _PooledConnection.close() → putconn
