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
import logging

logger = logging.getLogger(__name__)

# Thread-safe connection pool
_pool = None
_pool_lock = threading.Lock()


def _get_db_password():
    """Read DB password from Docker secret file, fall back to env var."""
    secret_file = os.environ.get("DB_PASSWORD_FILE", "/run/secrets/db_password")
    try:
        with open(secret_file, "r") as f:
            pw = f.read().strip()
            if pw:
                return pw
    except (FileNotFoundError, PermissionError):
        pass
    return os.environ.get("DB_PASSWORD", "")


PROD_DB_NAME = "archie"


def _get_pool():
    """Get or create the connection pool (thread-safe singleton)"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                db_name = os.environ.get("DB_NAME", PROD_DB_NAME)
                # Safety backstop: a test run must NEVER open a pool against the
                # production database. A prior unscoped test wrote "mock" into
                # 1,166 live translation rows because tests silently connected to
                # prod. Under pytest we FORCE the isolated test DB regardless of
                # DB_NAME — some test modules set os.environ["DB_NAME"]="archie"
                # at import (e.g. test_personality.py), which must not be able to
                # point the pool at production. Forcing (not raising) is immune to
                # any such clobber and avoids cascading every test into an error.
                if os.environ.get("ARCHIE_PYTEST"):
                    db_name = os.environ.get("TEST_DB_NAME", "archie_test")
                    if db_name == PROD_DB_NAME:
                        raise RuntimeError(
                            "TEST_DB_NAME resolves to the production database "
                            f"'{PROD_DB_NAME}' under pytest — refusing to connect."
                        )
                _pool = pool.ThreadedConnectionPool(
                    minconn=5,
                    maxconn=50,
                    host=os.environ.get("DB_HOST", "archie_database"),
                    port=os.environ.get("DB_PORT", "5432"),
                    database=db_name,
                    user=os.environ.get("DB_USER", "archie"),
                    password=_get_db_password(),
                )
    return _pool


def reset_pool():
    """Close and discard the pool so the next access rebuilds it.

    Test-only helper: conftest redirects DB_NAME to an isolated test database
    and calls this so the new pool binds to the test DB rather than whatever
    the first import happened to create.
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception as exc:  # pool is being discarded — non-fatal
                logger.debug("reset_pool: closeall failed, discarding anyway: %s", exc)
            _pool = None


def _cleanup_pool():
    """Cleanup connection pool on exit"""
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
                # If the connection is in an aborted-transaction state, roll back
                # before returning to the pool so the next caller gets a clean conn.
                # If rollback fails the connection is broken — discard it (close=True)
                # instead of poisoning the pool.
                tx = self._conn.get_transaction_status()
                if tx == 3:  # INERROR
                    try:
                        self._conn.rollback()
                        self._pool.putconn(self._conn)
                    except Exception:
                        self._pool.putconn(self._conn, close=True)
                elif self._conn.closed or tx == 4:  # UNKNOWN / TCP gone
                    self._pool.putconn(self._conn, close=True)
                else:
                    self._pool.putconn(self._conn)
            except Exception:
                try:
                    self._pool.putconn(self._conn, close=True)
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
    conn = p.getconn()
    # Validate: discard connections that were closed by the server (e.g. after
    # a DB container restart) or left in an aborted-transaction state by a
    # previous caller whose rollback silently failed.
    # psycopg2 transaction status codes: IDLE=0 ACTIVE=1 INTRANS=2 INERROR=3 UNKNOWN=4
    try:
        tx = conn.get_transaction_status()
        if conn.closed or tx == 4:  # UNKNOWN → TCP gone
            p.putconn(conn, close=True)
            conn = p.getconn()
        elif tx == 3:  # INERROR → aborted txn, clear it
            try:
                conn.rollback()
            except Exception:
                p.putconn(conn, close=True)
                conn = p.getconn()
    except Exception:
        pass  # If we can't check, proceed and let normal error handling catch it
    return _PooledConnection(conn, p)


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


def check_fleet_model_unique(cur, model, exclude_agent_id=None, exclude_node_agent_id=None):
    """Check if a model is already in use by any agent across the fleet.

    Args:
        cur: Database cursor
        model: Model name to check
        exclude_agent_id: Hub agent ID to exclude (for updates)
        exclude_node_agent_id: Node agent ID to exclude (for updates)

    Returns:
        (is_unique: bool, conflict_msg: str or None)
    """
    if not model:
        return True, None

    # Check hub agents
    if exclude_agent_id:
        cur.execute(
            "SELECT id, name, display_name FROM agents WHERE model = %s AND id != %s AND status = 'active' LIMIT 1",
            (model, exclude_agent_id),
        )
    else:
        cur.execute(
            "SELECT id, name, display_name FROM agents WHERE model = %s AND status = 'active' LIMIT 1",
            (model,),
        )
    conflict = cur.fetchone()
    if conflict:
        who = conflict.get("display_name") or conflict.get("name")
        return False, f"Model '{model}' is already assigned to hub agent {who}"

    # Check node agents
    if exclude_node_agent_id:
        cur.execute(
            "SELECT id, name, display_name FROM node_agents WHERE model = %s AND id != %s AND status = 'active' LIMIT 1",
            (model, exclude_node_agent_id),
        )
    else:
        cur.execute(
            "SELECT id, name, display_name FROM node_agents WHERE model = %s AND status = 'active' LIMIT 1",
            (model,),
        )
    conflict = cur.fetchone()
    if conflict:
        who = conflict.get("display_name") or conflict.get("name")
        return False, f"Model '{model}' is already assigned to node agent {who}"

    return True, None


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
