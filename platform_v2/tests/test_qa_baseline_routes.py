"""Route tests for qa baseline + regression endpoints.

Strategy mirrors test_approvals_hire_routes.py:
  - Direct psycopg2 ``db`` fixture against the real archie DB (migration 369
    creates qa_perf_baselines / qa_perf_regressions / qa_perf_acceptances).
  - Minimal Flask ``qa_client`` fixture mounts only the qa_routes blueprint.
  - _login_as_admin() injects a Flask-Login session.
  - Seeded fixture rows are cleaned up after each test by deleting on the
    distinct test_name we used (no cross-test pollution).
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
    """Minimal Flask test client with only the qa_routes blueprint mounted."""
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


TEST_USER_ID = 2


def _login_as_admin(client, user_id=TEST_USER_ID):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _cleanup(db, test_name):
    """Remove fixture rows for a given test_name across all 3 perf tables."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM qa_perf_acceptances WHERE test_name = %s", (test_name,))
        cur.execute("DELETE FROM qa_perf_regressions WHERE test_name = %s", (test_name,))
        cur.execute("DELETE FROM qa_perf_baselines WHERE test_name = %s", (test_name,))


# ---------------------------------------------------------------------------
# GET /api/qa/baselines
# ---------------------------------------------------------------------------


def test_get_baselines_returns_list(qa_client, db):
    _login_as_admin(qa_client)
    resp = qa_client.get("/tools/repair-bay/api/qa/baselines")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "baselines" in data
    assert isinstance(data["baselines"], list)


# ---------------------------------------------------------------------------
# GET /api/qa/regressions?status=pending
# ---------------------------------------------------------------------------


def test_get_pending_regressions(qa_client, db):
    _login_as_admin(qa_client)
    resp = qa_client.get("/tools/repair-bay/api/qa/regressions?status=pending")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "regressions" in data
    for row in data["regressions"]:
        assert row["status"] == "pending"


# ---------------------------------------------------------------------------
# POST /api/qa/regressions/<id>/clear
# ---------------------------------------------------------------------------


def test_clear_regression_marks_cleared(qa_client, db):
    test_name = "fixture_test_clear_route"
    _cleanup(db, test_name)

    # Seed a regression row + a real qa_test_runs row to satisfy the FK
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO qa_test_runs (suite_id, triggered_by, status) "
            "VALUES (2, 'test_fixture', 'completed') RETURNING id"
        )
        run_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO qa_perf_regressions
                (run_id, suite_id, test_name, baseline_ms, observed_ms,
                 pct_over, is_critical, status)
            VALUES (%s, 2, %s, 100, 250, 150, FALSE, 'pending')
            RETURNING id
            """,
            (run_id, test_name),
        )
        regression_id = cur.fetchone()["id"]

    try:
        _login_as_admin(qa_client)
        resp = qa_client.post(f"/tools/repair-bay/api/qa/regressions/{regression_id}/clear")
        assert resp.status_code == 200

        with db.cursor() as cur:
            cur.execute(
                "SELECT status, cleared_at FROM qa_perf_regressions WHERE id = %s",
                (regression_id,),
            )
            row = cur.fetchone()
            assert row["status"] == "cleared"
            assert row["cleared_at"] is not None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM qa_perf_regressions WHERE id = %s", (regression_id,))
            cur.execute("DELETE FROM qa_test_runs WHERE id = %s", (run_id,))


# ---------------------------------------------------------------------------
# POST /api/qa/regressions/<id>/accept
# ---------------------------------------------------------------------------


def test_accept_regression_inserts_acceptance(qa_client, db):
    test_name = "fixture_test_accept_route"
    fixture_suite = 2  # lowest active suite_id in qa_test_suites
    _cleanup(db, test_name)

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO qa_test_runs (suite_id, triggered_by, status) "
            "VALUES (%s, 'test_fixture', 'completed') RETURNING id",
            (fixture_suite,),
        )
        run_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO qa_perf_regressions
                (run_id, suite_id, test_name, baseline_ms, observed_ms,
                 pct_over, is_critical, status)
            VALUES (%s, %s, %s, 100, 350, 250, FALSE, 'pending')
            RETURNING id
            """,
            (run_id, fixture_suite, test_name),
        )
        regression_id = cur.fetchone()["id"]

    try:
        _login_as_admin(qa_client)
        resp = qa_client.post(f"/tools/repair-bay/api/qa/regressions/{regression_id}/accept")
        assert resp.status_code == 200

        with db.cursor() as cur:
            cur.execute(
                "SELECT status FROM qa_perf_regressions WHERE id = %s",
                (regression_id,),
            )
            assert cur.fetchone()["status"] == "accepted"
            cur.execute(
                "SELECT 1 AS ok FROM qa_perf_acceptances WHERE suite_id = %s AND test_name = %s",
                (fixture_suite, test_name),
            )
            assert cur.fetchone() is not None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM qa_perf_acceptances WHERE test_name = %s", (test_name,))
            cur.execute("DELETE FROM qa_perf_regressions WHERE id = %s", (regression_id,))
            cur.execute("DELETE FROM qa_test_runs WHERE id = %s", (run_id,))
