"""Integration tests for the perf gate end-to-end flow.

Each test seeds real qa_test_runs + qa_perf_regressions rows in the archie
DB, exercises a layer of the gate (service helper, route handler, or
sandbox queue), then cleans up. No mocking — these test the wiring.

Strategy mirrors test_qa_baseline_routes.py:
  - Direct psycopg2 ``db`` fixture against the real archie DB.
  - Mini Flask client only for the route-touching test (#3).
  - All seeded rows deleted in finally blocks even if assertions fail.
"""

from __future__ import annotations

import os
import sys
import pytest
import psycopg2
import psycopg2.extras


def _get_db_password():
    try:
        return open("/run/secrets/db_password").read().strip()
    except FileNotFoundError:
        return os.environ.get("DB_PASSWORD", "")


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=_get_db_password(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def import_helpers():
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")


@pytest.fixture(scope="module")
def qa_client():
    """Mini Flask client with only qa_routes mounted — used by the clear-endpoint test."""
    from flask import Flask, Blueprint
    from flask_login import LoginManager, UserMixin

    mini_app = Flask(__name__)
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["WTF_CSRF_ENABLED"] = False

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid
            self.username = "test_admin"

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    bp = Blueprint("repair_bay", __name__, url_prefix="/tools/repair-bay")

    def _no_op_admin_required(f):
        return f

    from tools.repair_bay.qa_routes import register_qa_routes

    register_qa_routes(bp, _no_op_admin_required)
    mini_app.register_blueprint(bp)
    return mini_app.test_client()


def _login(client, user_id=2):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


SEED_SUITE_ID = 2  # lowest active suite — satisfies qa_test_runs.suite_id FK


def _seed_run_and_regression(db, test_name, is_critical, status="pending"):
    """Insert a qa_test_runs row + a qa_perf_regressions row, return both ids."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO qa_test_runs (suite_id, triggered_by, status) "
            "VALUES (%s, 'integration_test', 'completed') RETURNING id",
            (SEED_SUITE_ID,),
        )
        run_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO qa_perf_regressions
                (run_id, suite_id, test_name, baseline_ms, observed_ms,
                 pct_over, is_critical, status)
            VALUES (%s, %s, %s, 100, 250, 150, %s, %s)
            RETURNING id
            """,
            (run_id, SEED_SUITE_ID, test_name, is_critical, status),
        )
        reg_id = cur.fetchone()["id"]
    return run_id, reg_id


def _cleanup_run(db, run_id):
    with db.cursor() as cur:
        # qa_perf_regressions cascades on qa_test_runs delete (FK ON DELETE CASCADE)
        cur.execute("DELETE FROM qa_test_runs WHERE id = %s", (run_id,))


# ---------------------------------------------------------------------------
# 1. Critical regression → 'rollback'
# ---------------------------------------------------------------------------


def test_critical_regression_returns_rollback(db):
    from services import qa_baseline_service

    run_id, _reg_id = _seed_run_and_regression(db, test_name="integration_t_critical", is_critical=True)
    try:
        action = qa_baseline_service.evaluate_post_deploy(run_id=run_id, proposal_id=None)
        assert action == "rollback"
    finally:
        _cleanup_run(db, run_id)


# ---------------------------------------------------------------------------
# 2. Non-critical first regression → 'flag' (count=1, below pause threshold)
# ---------------------------------------------------------------------------


def test_non_critical_first_regression_returns_flag(db):
    from services import qa_baseline_service

    # Use a unique test_name so historical pending count = 1 for this row only
    run_id, _reg_id = _seed_run_and_regression(db, test_name="integration_t_first_only_flag", is_critical=False)
    try:
        action = qa_baseline_service.evaluate_post_deploy(run_id=run_id, proposal_id=None)
        assert action == "flag"
    finally:
        _cleanup_run(db, run_id)


# ---------------------------------------------------------------------------
# 3. Clear endpoint lifts pause flag iff no other pending
# ---------------------------------------------------------------------------


def test_clear_endpoint_lifts_pause_flag_when_no_pending(db, qa_client):
    from database import get_db_cursor

    # Snapshot the pre-existing pause flag so we can restore it
    with db.cursor() as cur:
        cur.execute("SELECT value FROM system_config WHERE key = 'deploy_paused_perf'")
        prev = cur.fetchone()
        prev_value = prev["value"] if prev else None

    # Test only meaningful when the platform has zero pending regressions to start
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM qa_perf_regressions WHERE status = 'pending'")
        if cur.fetchone()["n"] != 0:
            pytest.skip("test requires no pre-existing pending regressions")

    # Force the pause flag on, seed exactly one pending regression
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO system_config (key, value, updated_at)
               VALUES ('deploy_paused_perf', 'true', NOW())
               ON CONFLICT (key) DO UPDATE
                   SET value = 'true', updated_at = NOW()"""
        )

    run_id, reg_id = _seed_run_and_regression(db, test_name="integration_t_clear_lifts_pause", is_critical=False)
    try:
        _login(qa_client)
        resp = qa_client.post(f"/tools/repair-bay/api/qa/regressions/{reg_id}/clear")
        assert resp.status_code == 200

        with db.cursor() as cur:
            cur.execute("SELECT value FROM system_config WHERE key = 'deploy_paused_perf'")
            row = cur.fetchone()
            assert row is not None
            assert row["value"] == "false", "clear endpoint must lift pause when no other pending"
    finally:
        _cleanup_run(db, run_id)
        # Restore prior pause-flag state
        if prev_value is not None:
            with db.cursor() as cur:
                cur.execute(
                    """INSERT INTO system_config (key, value, updated_at)
                       VALUES ('deploy_paused_perf', %s, NOW())
                       ON CONFLICT (key) DO UPDATE
                           SET value = EXCLUDED.value, updated_at = NOW()""",
                    (prev_value,),
                )


# ---------------------------------------------------------------------------
# 4. Sandbox queue returns empty when deploy_paused_perf=true
# ---------------------------------------------------------------------------


def test_sandbox_queue_refuses_claim_when_paused(db):
    from database import get_db_cursor
    from tools.repair_bay.services.sandbox_queue import SandboxQueue, _is_deploy_paused_for_perf

    # Snapshot prior flag
    with db.cursor() as cur:
        cur.execute("SELECT value FROM system_config WHERE key = 'deploy_paused_perf'")
        prev = cur.fetchone()
        prev_value = prev["value"] if prev else None

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO system_config (key, value, updated_at)
               VALUES ('deploy_paused_perf', 'true', NOW())
               ON CONFLICT (key) DO UPDATE
                   SET value = 'true', updated_at = NOW()"""
        )
    try:
        assert _is_deploy_paused_for_perf() is True
        sq = SandboxQueue()
        # get_queue must short-circuit to [] when the flag is set
        assert sq.get_queue() == []
        # can_use_sandbox must refuse direct claims with a clear reason
        decision = sq.can_use_sandbox(proposal_id=999_999_999)
        assert decision["can_use"] is False
        assert "paused" in decision["reason"].lower()
    finally:
        with db.cursor() as cur:
            if prev_value is None:
                cur.execute("DELETE FROM system_config WHERE key = 'deploy_paused_perf'")
            else:
                cur.execute(
                    "UPDATE system_config SET value = %s, updated_at = NOW() " "WHERE key = 'deploy_paused_perf'",
                    (prev_value,),
                )
