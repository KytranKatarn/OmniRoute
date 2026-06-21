"""
ARCHIE Platform Test Fixtures
"""

import importlib.util
import os
import sys
import pytest

# /app contains __init__.py making it a package, so `from app import app`
# resolves to the package init rather than app.py.  Load app.py directly
# via importlib so the Flask application object is always found correctly.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

# ── Test DB isolation (CRITICAL — see KB #274942) ─────────────────────────────
# Tests hit the SAME postgres server as production but a SEPARATE database.
# DB_NAME is a HARD override, NOT setdefault: inside the archie_platform
# container DB_NAME=archie is already set, so the old setdefault was a no-op and
# the whole suite silently ran against PRODUCTION — a mock-dispatch test once
# wrote "mock" into 1,166 live translation rows. ARCHIE_PYTEST additionally makes
# database._get_pool() refuse the prod DB outright as a backstop.
PROD_DB_NAME = "archie"
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "archie_test")

os.environ["ARCHIE_PYTEST"] = "1"
os.environ["DB_NAME"] = TEST_DB_NAME  # hard override
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_USER", "archie")
os.environ.setdefault("DB_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")


def _ensure_test_db():
    """Create the isolated test database + clone the prod schema if missing.

    Idempotent: once archie_test has the schema this is a fast no-op. A prod
    schema change requires a rebuild (drop archie_test, or set TEST_DB_REBUILD=1).
    Uses raw psycopg2 — NOT the platform pool — so it bypasses the prod guard;
    it only ever issues CREATE DATABASE + a read-only schema dump against prod.
    """
    import subprocess

    import psycopg2

    import database

    host = os.environ.get("DB_HOST", "archie_database")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "archie")
    pw = database._get_db_password()

    def _connect(dbname):
        return psycopg2.connect(host=host, port=port, user=user, password=pw, dbname=dbname)

    # 0. TEST_DB_REBUILD: drop the test DB for a guaranteed-clean recreate.
    # archie_test is PERSISTENT by design (re-cloning 704 tables every run is
    # slow); individual tests must clean up their own writes. Set
    # TEST_DB_REBUILD=1 to wipe accumulated state and rebuild the schema fresh.
    if os.environ.get("TEST_DB_REBUILD"):
        admin = _connect(PROD_DB_NAME)
        admin.autocommit = True
        try:
            with admin.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=%s AND pid<>pg_backend_pid()",
                    (TEST_DB_NAME,),
                )
                cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        finally:
            admin.close()

    # 1. create the test DB if missing (connect to prod only to issue CREATE DATABASE)
    admin = _connect(PROD_DB_NAME)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DB_NAME,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        admin.close()

    # 2. ensure schema present (idempotent clone)
    test = _connect(TEST_DB_NAME)
    test.autocommit = True
    try:
        with test.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("SELECT to_regclass('public.translations')")
            has_schema = cur.fetchone()[0] is not None
    finally:
        test.close()

    if has_schema and not os.environ.get("TEST_DB_REBUILD"):
        return

    env = {**os.environ, "PGPASSWORD": pw}
    dump = subprocess.run(
        [
            "pg_dump",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            PROD_DB_NAME,
            "--schema-only",
            "--no-owner",
            "--no-privileges",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if dump.returncode != 0:
        raise RuntimeError(f"test-db schema dump failed: {dump.stderr[:400]}")
    subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", TEST_DB_NAME, "-v", "ON_ERROR_STOP=0", "-q"],
        input=dump.stdout,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="session", autouse=True)
def _isolated_test_db():
    """Guarantee the whole session runs against the isolated test DB, never prod."""
    import database

    _ensure_test_db()
    database.reset_pool()  # rebind the pool to TEST_DB_NAME

    with database.get_db_cursor() as (_conn, cur):
        cur.execute("SELECT current_database() AS db")
        row = cur.fetchone()
    live = row["db"] if isinstance(row, dict) else row[0]
    assert live == TEST_DB_NAME and live != PROD_DB_NAME, (
        f"TEST DB GUARD TRIPPED: connected to {live!r}; refusing to run the suite "
        f"against production. Expected {TEST_DB_NAME!r}."
    )
    yield


def _load_flask_app():
    """Load app.py directly to avoid __init__.py package shadowing.

    Registers the module as sys.modules["app"] before exec so that any
    internal import (e.g. `from app import User`) resolves to this module
    rather than the /app/__init__.py package stub.
    """
    spec = importlib.util.spec_from_file_location("flask_app_module", "/app/app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = mod  # shadow the package stub before exec
    spec.loader.exec_module(mod)
    return mod.app


@pytest.fixture
def app():
    """Create Flask application for testing."""
    flask_app = _load_flask_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    yield flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def db_conn(app):
    """Raw psycopg2 connection via the platform DB module for direct SQL in tests."""
    with app.app_context():
        from database import get_db

        conn = get_db()
        yield conn
        conn.rollback()
        conn.close()
