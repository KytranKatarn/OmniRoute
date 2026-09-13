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
# GPU per-card telemetry (#5273): the REAL exporter file is bind-mounted at
# /app/.runtime/gpu_state.json, so without this pin every budget/placement test
# would compute against whatever the box's GPUs held at that moment. An env
# path, when set, is the SOLE path model_service reads — pinning it to a
# nonexistent file makes get_gpu_fit_budget deterministically use its
# worst-case fallback; tests that WANT telemetry monkeypatch _GPU_STATE_PATHS.
os.environ.setdefault("ARCHIE_GPU_STATE_PATH", "/nonexistent/gpu_state_test_pin.json")


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
    restore = subprocess.run(
        ["psql", "-h", host, "-p", port, "-U", user, "-d", TEST_DB_NAME, "-v", "ON_ERROR_STOP=0", "-q"],
        input=dump.stdout,
        env=env,
        capture_output=True,
        text=True,
        timeout=restore_timeout,
    )

    # VERIFY THE ARTIFACT, NOT THE EXIT CODE (#6239).
    #
    # The dump's returncode is checked above; the restore's was not checked AT ALL,
    # and its stderr was captured and thrown away. With ON_ERROR_STOP=0 psql exits 0
    # having skipped whatever failed, so a HALF-BUILT archie_test looked like a
    # successful clone and _ensure_test_db() returned normally.
    #
    # The damage surfaced ~480 lines later as an unreadable symptom: _seed_admin_user
    # died on `ON CONFLICT (id)` with "there is no unique or exclusion constraint
    # matching the ON CONFLICT specification" — because the tables had restored but
    # their PRIMARY KEYs had not. That error names neither the restore nor the clone,
    # so every db-backed test in the suite errored with no path back to the cause.
    #
    # ON_ERROR_STOP=0 stays: a fresh clone legitimately emits benign noise (extensions
    # that already exist, role grants). What changes is that we now confirm the
    # RESULT — re-fingerprint and require it to match prod, the same property the
    # reclone was triggered on. Same discipline as backup_triage judging the archive
    # with `gzip -t` rather than trusting tar's exit status.
    verify = _connect(TEST_DB_NAME)
    try:
        with verify.cursor() as cur:
            rebuilt_fp = _schema_fingerprint(cur)
    finally:
        verify.close()

    prod = _connect(PROD_DB_NAME)
    try:
        with prod.cursor() as cur:
            expected_fp = _schema_fingerprint(cur)
    finally:
        prod.close()

    if rebuilt_fp != expected_fp:
        tail = (restore.stderr or "").strip().splitlines()
        raise RuntimeError(
            f"test-db schema restore INCOMPLETE: {TEST_DB_NAME} fingerprint "
            f"{rebuilt_fp[:12]} != {PROD_DB_NAME} {expected_fp[:12]}.\n"
            f"psql rc={restore.returncode}; last errors:\n  "
            + "\n  ".join(tail[-8:] or ["(psql reported nothing on stderr)"])
            + f"\nRe-run with TEST_DB_REBUILD=1, or raise TEST_DB_RESTORE_TIMEOUT "
            f"(currently {restore_timeout}s) if the restore is being cut short."
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


# ── Detect module stubs that OUTLIVE their own test module (#6021) ────────────────────
# THREE separate incidents, each fixed one file at a time before the class was addressed:
#   #5665           a synthetic PARENT package aborted the ENTIRE run
#   #6017 / #6018   sys.modules["...department_dispatcher"] -> 8 failures in
#                   test_fleet_candidate_welfare_gate, which passes 8/8 alone
#   #6016 / #2810   sys.modules["ai_bridge.agent_loop"]     -> 10 failures across
#                   test_pr_merge_approval_dedup + test_tab_merge_freshness, both of
#                   which pass in isolation
#
# pytest imports every test module during COLLECTION, so a module-level
# `sys.modules[x] = stub` is SESSION-GLOBAL from that moment. Whichever module sorts first
# wins, silently, and only in a full run — every victim passes alone, which reads as
# flakiness rather than a collision. It also HIDES bugs: a NameError in
# test_delegation_async_callback could never fire because a sibling's stub won the race
# (KB #295045).
#
# ⚠️ DETECTION MUST USE __spec__, NOT __file__. These stubs carry a PEP 562 `__getattr__`
# catch-all that returns a MagicMock for ANY attribute — including __file__ — so an
# attribute-presence probe reports them as perfectly normal modules. Measured: the
# agent_loop stub answers `__file__` with <MagicMock id=...>. `__spec__` is a REAL
# attribute on types.ModuleType (always None), so __getattr__ is never consulted for it.
# A genuinely imported first-party module always has a ModuleSpec.
#
# The fix for an offender is tests/modstub.stub_module_scoped in a module-scoped autouse
# fixture — it restores BOTH sys.modules and the parent package attribute.

_FIRST_PARTY_ROOTS = ("tools", "services", "ai_bridge")

# Known offenders, with the file that installs each. This list may only SHRINK.
# EMPTY, and it should stay that way. The last entry —
# tools.consciousness.translation_scanners.orchestrator, leaked by test_delegation_service —
# was scoped to its own module rather than tolerated. It was the cause of
# tests/translation_scanners/test_orchestrator.py failing in a FULL run while passing alone.
#
# Before adding an entry here, try the fixture instead: wrap the stub in
# `stub_module_scoped` (tests/modstub.py), which restores sys.modules AND the parent package
# attribute. That is viable whenever the module under test imports its dependency LAZILY.
_ALLOWED_STUB_LEAKS: dict = {}

_leaked_stubs: set = set()
# How many items this run collected. The staleness half of the guard is only meaningful on
# a FULL run — collect one file and nothing leaks, which would make every allowlist entry
# look stale. Recorded rather than inferred so the test can skip honestly.
_collected_count: int = 0


def pytest_collection_finish(session):
    """Record first-party modules left as stubs once every test module is imported."""
    global _collected_count
    _collected_count = len(session.items)
    _leaked_stubs.clear()
    for name in sorted(sys.modules):
        if name.split(".")[0] not in _FIRST_PARTY_ROOTS:
            continue
        mod = sys.modules.get(name)
        if mod is None or getattr(mod, "__spec__", None) is None:
            _leaked_stubs.add(name)


# ── Seed the one admin user the auth-gated tests assume exists (#6015) ────────────────
# archie_test is built SCHEMA-ONLY from a prod dump, so `users` is EMPTY. Four test files
# authenticate by writing a flask-login session directly:
#     sess["_user_id"] = "2"
# With no matching row the user_loader returns None, the request is unauthenticated, and
# every assertion sees a 302-to-login (or a 401) instead of the status it expected —
# 19 failures across test_browser_session_routes, test_account_link_routes,
# test_signal_calendar_live_routes and test_backup_consolidation.
#
# The id is PINNED to 2 because those fixtures hardcode it. Seeding here rather than in each
# file keeps one definition; a future auth test can rely on it instead of inventing another.
#
# ⚠️ Additive and idempotent, deliberately. Nothing asserts on a user COUNT (checked), and
# test_agent_profile_patch's `SELECT MIN(id) FROM users` currently returns NULL — a seeded
# row makes that query meaningful rather than breaking it.
# Every id the auth-gated tests write into a flask-login session.
#
# ⚠️ Finding them takes TWO greps, not one. Direct assignments give 1, 2, 7:
#     sess["_user_id"] = "7"
# but test_backup_consolidation hides its id in a HELPER DEFAULT:
#     def _login_as_admin(client, user_id=62):  ->  sess["_user_id"] = str(user_id)
# Seeding only the literals left that file's 8 failures untouched and looking like a
# different bug. If a new auth test 302s or 403s, check for an id in a helper signature
# before assuming a new cause.
_TEST_ADMIN_IDS = (1, 2, 7, 62)


@pytest.fixture(scope="session", autouse=True)
def _seed_admin_user(_isolated_test_db):
    """Ensure the admin users the tests assume exist in archie_test.

    Runs after the DB is built/restored."""
    import psycopg2

    import database

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        port=os.environ.get("DB_PORT", "5432"),
        user=os.environ.get("DB_USER", "archie"),
        password=database._get_db_password(),
        dbname=TEST_DB_NAME,
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # Ask the CONNECTION which database it is on, not the environment: DB_NAME can be
            # unset and still resolve to prod through a module-level default (#6016).
            cur.execute("SELECT current_database()")
            if cur.fetchone()[0] == PROD_DB_NAME:
                raise RuntimeError("refusing to seed a test admin user into production")
            for uid in _TEST_ADMIN_IDS:
                # role='ADMIN' as well as is_admin: RBAC gates on the ROLE hierarchy
                # (GUEST 5 ... ADMIN 50 ... SUPER_ADMIN 100), so is_admin alone still
                # yields 403 on @admin_required routes. is_active matters for the loader.
                cur.execute(
                    """
                    INSERT INTO users (id, username, password_hash, is_admin, role, is_active)
                    VALUES (%s, %s, 'x-not-a-real-hash-tests-set-the-session-directly',
                            TRUE, 'ADMIN', TRUE)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid, f"kytran-test-admin-{uid}"),
                )

            # QA suite id 2. Three call sites across test_perf_gate_integration.py and
            # test_qa_baseline_routes.py insert qa_test_runs rows against a hardcoded
            # suite_id=2, commented "lowest active suite" — true of PRODUCTION, where the
            # suites are seeded. archie_test has never held data, so all three hit
            #   ForeignKeyViolation: Key (suite_id)=(2) is not present in qa_test_suites
            # One of them writes the literal `VALUES (2, ...)` inline, so seeding the id the
            # callers already assume is a smaller and less fragile change than rewiring
            # three sites to thread a fixture value through.
            # `name` and `spec` are NOT NULL; suite_type/is_active take their defaults.
            # FAIL-SOFT, and deliberately so. This block is a CONVENIENCE for three test
            # files; the fixture's actual contract is the admin user seeded above. It is
            # autouse and session-scoped, so anything that raises here fails the SETUP of
            # EVERY test in the repo — a bolt-on convenience taking down 100% of the suite.
            # That is exactly what happened (2026-09-13): `ON CONFLICT (id)` raised
            # InvalidColumnReference because archie_test's qa_test_suites has NO primary
            # key, and all 18 tests of an unrelated file errored at setup with a message
            # that named neither this table nor the real cause.
            #
            # ROOT CAUSE, not fixed here because it is far larger than this fixture:
            # archie_test has 723 tables with no primary key. The test database was built
            # without constraints, so ANY ON CONFLICT against it is a latent suite-killer.
            # Tracked separately; this change stops one missing constraint from being fatal.
            try:
                # Constraint-INDEPENDENT idempotent insert. `ON CONFLICT (id)` needs a
                # unique index on id; `WHERE NOT EXISTS` needs nothing, so it works whether
                # or not archie_test ever grows the PK that production has.
                cur.execute(
                    """
                    INSERT INTO qa_test_suites (id, name, description, spec)
                    SELECT 2, 'test-fixture-suite',
                           'Seeded by tests/conftest.py so qa_test_runs.suite_id FK resolves',
                           '{}'::jsonb
                     WHERE NOT EXISTS (SELECT 1 FROM qa_test_suites WHERE id = 2)
                    """
                )
                # Explicit ids do NOT advance the sequence, so a later plain INSERT would
                # try to reuse id 2 and fail on the PK. Push the sequence past what is now
                # present. pg_get_serial_sequence returns NULL when id is not a serial (it
                # is not, in archie_test); setval is STRICT, so that is a NULL no-op, not
                # an error — but it stays inside the guard rather than relying on that.
                cur.execute(
                    "SELECT setval(pg_get_serial_sequence('qa_test_suites','id'),"
                    " GREATEST((SELECT COALESCE(MAX(id), 1) FROM qa_test_suites), 1))"
                )
            except Exception as exc:  # noqa: BLE001 - a convenience seed must never be fatal
                # Loud enough to find, quiet enough not to fail unrelated tests. The three
                # files that need suite_id=2 will fail on their own FK, naming themselves.
                print(
                    "conftest: qa_test_suites seed skipped (%s: %s). Tests that assume "
                    "suite_id=2 will fail individually; the rest are unaffected." % (type(exc).__name__, exc)
                )
    finally:
        conn.close()
    yield


@pytest.fixture
def chronicle_import():
    """A throwaway mailbox_imports row + one mailbox_emails row, cleaned up after.

    Chronicle tests used to key off `import_id=16` — Terry's LIVE Gmail import in
    PRODUCTION. archie_test has never held it, so the SELECT returned None
    ("TypeError: 'NoneType' object is not subscriptable") and the INSERT hit
    mailbox_emails_import_id_fkey. Neither message pointed at the real cause: a test
    depending on a specific production row.

    filename and stored_path are NOT NULL with no default on mailbox_imports; import_id is
    the only required column on mailbox_emails.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            # source_kind/source_account_id are REQUIRED by the gmail attachment path:
            # run_attachment_download calls _account_for_import(import_id) and returns
            # early with 0 processed when it is None — which looked like the feature not
            # working ("404 email should be marked unavailable, got None") rather than a
            # fixture missing a column.
            "INSERT INTO mailbox_imports "
            "(owner_id, filename, stored_path, status, source_kind, source_account_id) "
            "VALUES (4, 'pytest-fixture.pst', '/tmp/pytest-chronicle', 'extracted', 'gmail', 7) "
            "RETURNING id"
        )
        import_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO mailbox_emails (import_id, message_id, subject) "
            "VALUES (%s, %s, 'pytest fixture email') RETURNING id",
            (import_id, f"pytest-chronicle-{import_id}"),
        )
        email_id = cur.fetchone()["id"]

    yield {"import_id": import_id, "email_id": email_id}

    with get_db_cursor(commit=True) as (_conn, cur):
        # attachments -> emails -> import (FK order)
        cur.execute(
            "DELETE FROM mailbox_attachments WHERE email_id IN " "(SELECT id FROM mailbox_emails WHERE import_id=%s)",
            (import_id,),
        )
        cur.execute("DELETE FROM mailbox_emails WHERE import_id=%s", (import_id,))
        cur.execute("DELETE FROM mailbox_imports WHERE id=%s", (import_id,))
