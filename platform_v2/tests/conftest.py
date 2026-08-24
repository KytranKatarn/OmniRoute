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

# ── ai_bridge on sys.path (#5192) ─────────────────────────────────────────────
# tools/department_hq/services/department_dispatcher.py does `from db import
# _get_db_password` at module scope, and ``db`` lives in ai_bridge/ — so ANY test that
# imports the dispatcher (directly or transitively, e.g. tools.therapy.routes) died at
# COLLECTION with "No module named 'db'". That took out test_therapy_crisis,
# test_dispatch_cloud_attribution and test_route_legacy_loops_ai_owner, and because a
# collection error aborts the whole run, `pytest tests/` never completed at all.
# Several tests worked around it by stubbing the dispatcher in sys.modules; this fixes
# the cause once instead. Purely additive — a sys.modules stub still takes precedence
# over path resolution, so tests that deliberately stub are unaffected.
# Same import-path issue the runtime solves via signal_calendar_service
# ._ensure_import_paths() (KB #272154).
_PLATFORM_V2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _ai_bridge in (
    os.path.join(os.path.dirname(_PLATFORM_V2), "ai_bridge"),  # repo-relative (host + worktrees)
    "/mnt/archie_brain/ai_bridge",  # container mount (docker-compose mounts this path verbatim)
):
    if os.path.isdir(_ai_bridge) and _ai_bridge not in sys.path:
        sys.path.append(_ai_bridge)
        break

# ── Real root packages, imported EAGERLY (#5665) ──────────────────────────────
# Several test modules stub a leaf like
#     sys.modules["tools.department_hq.services.department_dispatcher"] = _stub
# and first do `sys.modules.setdefault("tools", types.ModuleType("tools"))` to give it a
# parent. That synthetic parent has NO __path__, so if such a module is collected BEFORE
# anything imported the real `tools`, the empty shell wins for the whole session and every
# later `tools.*` import dies with "'tools' is not a package". A collection error aborts the
# ENTIRE run, so one test file silently disables all 3,332 tests.
# Those tests use setdefault — i.e. they INTEND to reuse the real package if present.
# Importing the real roots here (conftest loads before any test module) makes that true, so
# each setdefault becomes a harmless no-op and NO test file needs changing. Leaf stubs still
# win over path resolution, so deliberate stubbing is unaffected (as in the ai_bridge block).
# Include any package a test synthesises as a stub PARENT — not just top-level roots.
# test_delegation_service fakes `tools.consciousness.translation_scanners` to hang an
# `orchestrator` stub off, which then makes the real semantic_scanner / untagged_scanner /
# generator submodules unimportable for the rest of the session.
for _root in (
    "tools",
    "ai_bridge",
    "tools.department_hq.services",
    "tools.consciousness.translation_scanners",
):
    try:
        __import__(_root)
    except Exception:  # pragma: no cover - must never abort collection
        pass

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


_SCHEMA_FINGERPRINT_SQL = """
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
    ORDER BY table_name, column_name
"""


def _schema_fingerprint(cur):
    """Stable hash of the public schema's (table, column, type) triples.

    Deliberately ignores row DATA, indexes, constraints and defaults: the thing
    that breaks a test when archie_test goes stale is a column the code writes
    that the clone does not have. Hashing more would make the fingerprint
    churn on harmless prod activity and train everyone to ignore a reclone.
    """
    import hashlib

    cur.execute(_SCHEMA_FINGERPRINT_SQL)
    return hashlib.sha256(repr(cur.fetchall()).encode()).hexdigest()


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

    # 2. ensure schema present AND CURRENT (idempotent clone)
    #
    # The old check was `to_regclass('public.translations') IS NOT NULL` — i.e.
    # schema currency inferred from ONE table existing. That table exists forever
    # after the first clone, so the check could never fire again and archie_test
    # drifted from archie indefinitely. On 2026-07-26 it was a clone predating
    # migration 463: seeding `node_role` raised UndefinedColumn, a fixture
    # downgraded that to a skip, and three fleet tests reported "3 skipped" —
    # which reads as passing (task #5231).
    #
    # A fingerprint over (table, column, type) is the property we actually care
    # about and costs ~0.6s for 823 tables / 9,645 columns — cheap enough to pay
    # every session. Presence of a sentinel is a proxy; this is the real thing.
    test = _connect(TEST_DB_NAME)
    test.autocommit = True
    try:
        with test.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("SELECT to_regclass('public.translations')")
            has_schema = cur.fetchone()[0] is not None
            test_fp = _schema_fingerprint(cur) if has_schema else None
    finally:
        test.close()

    prod_fp = None
    if has_schema:
        prod = _connect(PROD_DB_NAME)
        try:
            with prod.cursor() as cur:
                prod_fp = _schema_fingerprint(cur)
        finally:
            prod.close()

    if has_schema and prod_fp == test_fp and not os.environ.get("TEST_DB_REBUILD"):
        return

    if has_schema and prod_fp != test_fp:
        # DROP, don't overlay. Re-applying a schema dump on top of an existing
        # schema is a no-op for drift: every CREATE TABLE fails "already exists"
        # (ON_ERROR_STOP=0 swallows it) so a newly-added COLUMN is never created.
        # Overlaying would leave the drift in place while looking like a repair.
        sys.stderr.write(
            f"\n[conftest] SCHEMA DRIFT: {TEST_DB_NAME} ({test_fp[:12]}) != "
            f"{PROD_DB_NAME} ({prod_fp[:12]}) — recloning.\n"
        )
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
                cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        finally:
            admin.close()
        fresh = _connect(TEST_DB_NAME)
        fresh.autocommit = True
        try:
            with fresh.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        finally:
            fresh.close()

    # Timeouts are ASYMMETRIC because the two halves are wildly different, and
    # measuring only the cheap half is how the wrong conclusion got drawn.
    # Measured 2026-07-26 against 823 tables / 109k lines of DDL:
    #     pg_dump --schema-only :   2s
    #     psql restore          : 344s     <- 170x the dump
    # The old flat 300s therefore aborted mid-restore EVERY time, leaving a
    # half-built archie_test. Default 1200s gives ~3.5x headroom for a busy
    # server; tune with TEST_DB_RESTORE_TIMEOUT if the schema keeps growing.
    dump_timeout = int(os.environ.get("TEST_DB_DUMP_TIMEOUT", "300"))
    restore_timeout = int(os.environ.get("TEST_DB_RESTORE_TIMEOUT", "1200"))

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
        timeout=dump_timeout,
    )
    if dump.returncode != 0:
        raise RuntimeError(f"test-db schema dump failed: {dump.stderr[:400]}")
    subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", TEST_DB_NAME, "-v", "ON_ERROR_STOP=0", "-q"],
        input=dump.stdout,
        env=env,
        capture_output=True,
        text=True,
        timeout=restore_timeout,
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


# One built Flask app per app.py path, for the life of the pytest process (#5998).
#
# `spec.loader.exec_module()` below executes the WHOLE of app.py: every blueprint across
# all 36 modules, the Jinja environment, the extensions. That is ~1 GB of objects, and
# nothing releases them — the registrations, logging handlers and module-level globals in
# the imported route modules keep each app reachable forever.
#
# The `app` fixture is function-scoped, so before this cache that ~1 GB was paid ONCE PER
# TEST and never given back. Measured 2026-08-24: individual tests in test_coo_actions.py,
# test_coo_consult.py and test_dhq_chat_routing.py each added 0.5-1.2 GB, and a full run
# was OOM-killed at a 16 GiB ceiling around 57% (tests/test_dispatch_history_routes.py).
# Doubling the ceiling from 8 GiB changed nothing except where it died — the growth is
# unbounded, so no ceiling fixes it.
#
# Keyed by path so ARCHIE_APP_PY still gives a worktree/bundle run its OWN app.
_FLASK_APP_CACHE: dict = {}


def _load_flask_app():
    """Load app.py directly to avoid __init__.py package shadowing.

    Registers the module as sys.modules["app"] before exec so that any
    internal import (e.g. `from app import User`) resolves to this module
    rather than the /app/__init__.py package stub.

    Built at most once per app.py path per process — see _FLASK_APP_CACHE above.
    """
    # Default to the live checkout; ARCHIE_APP_PY lets a bundle/worktree run
    # (feature branch synced to /tmp/wt) test its OWN app.py instead of /app.
    app_py = os.environ.get("ARCHIE_APP_PY", "/app/app.py")

    cached = _FLASK_APP_CACHE.get(app_py)
    if cached is not None:
        # Re-assert the shadow: another test may have replaced sys.modules["app"], and
        # `from app import User` must still resolve to the module this app was built from.
        sys.modules["app"] = cached[0]
        return cached[1]

    spec = importlib.util.spec_from_file_location("flask_app_module", app_py)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = mod  # shadow the package stub before exec
    spec.loader.exec_module(mod)
    _FLASK_APP_CACHE[app_py] = (mod, mod.app)
    return mod.app


@pytest.fixture
def app():
    """Create Flask application for testing.

    Deliberately still FUNCTION-scoped: the test config is re-applied on every use, so a
    test that changes TESTING/WTF_CSRF_ENABLED cannot leak into the next one. Only the
    ~1 GB rebuild is cached (see _FLASK_APP_CACHE) — the fixture's contract is unchanged.
    """
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
