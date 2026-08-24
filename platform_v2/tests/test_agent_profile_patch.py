"""PATCH /tools/department-hq/api/agent/<id> — allowlist, validation, audit."""

from __future__ import annotations

import json
import os
import sys

import pytest
import psycopg2
import psycopg2.extras


_TEST_AGENT_NAME = "T.E.S.T.-profile-patch-fixture"

# Tables that reference agents.id and that THESE tests cause writes to. The PATCH route
# writes a governance_audit_log row, so the agent cannot be deleted until that row is gone.
# Deliberately an explicit list, not a generic cascade: if a future route writes to another
# FK table, teardown fails LOUDLY and someone extends this line — which is better than a
# silent swallow that leaves rows behind in a database everyone assumes is clean.
_AGENT_FK_TABLES = ("governance_audit_log",)


def _purge_test_agents(cur):
    """Remove any agent this fixture created, plus its dependent rows.

    Runs before the INSERT as well as after: a run that dies mid-test (or an earlier
    teardown that hit the FK) leaves the row behind, and the next run then fails on it.
    """
    cur.execute("SELECT id FROM agents WHERE name = %s", (_TEST_AGENT_NAME,))
    for row in cur.fetchall():
        for table in _AGENT_FK_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE agent_id = %s", (row["id"],))
        cur.execute("DELETE FROM agents WHERE id = %s", (row["id"],))


def _pw():
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
        password=_pw(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def _syspath():
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")


def _real_user_id():
    """Return a real users.id so FK constraints on audit writes succeed."""
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=_pw(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT MIN(id) AS id FROM users")
        row = cur.fetchone()
        return row["id"] if row else 1
    finally:
        conn.close()


def _build_client(is_admin: bool = True):
    from functools import wraps

    from flask import Flask, Blueprint, jsonify
    from flask_login import LoginManager, UserMixin, current_user

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    _admin_flag = is_admin  # alias to escape class-body scoping
    _username = "test_admin" if is_admin else "test_user"
    _uid = _real_user_id()

    class _User(UserMixin):
        id = _uid
        is_admin = _admin_flag
        username = _username

    lm = LoginManager(app)
    _user = _User()

    @lm.user_loader
    def _load(uid):
        return _user

    def admin_required(f):
        @wraps(f)
        def _inner(*a, **k):
            if not getattr(current_user, "is_admin", False):
                return jsonify({"ok": False, "error": "not_admin"}), 403
            return f(*a, **k)

        return _inner

    from tools.department_hq.agent_detail_routes import register_agent_detail_routes

    bp = Blueprint("dhq", __name__, url_prefix="/tools/department-hq")
    register_agent_detail_routes(bp, admin_required)
    app.register_blueprint(bp)

    c = app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(_uid)
        s["_fresh"] = True
    return c


@pytest.fixture(scope="module")
def admin_client():
    return _build_client(is_admin=True)


@pytest.fixture(scope="module")
def user_client():
    return _build_client(is_admin=False)


@pytest.fixture(scope="module")
def agent_id(db):
    """Create a purpose-made agent instead of mutating whatever row comes back first (#6016).

    The old fixture did `SELECT id FROM agents ... LIMIT 1`, and these tests then PATCH that
    row (e.g. bio='updated-by-test'). Two separate problems:

    1. `archie_test` is EMPTY — schema, no rows — so the SELECT returned None and all 11
       tests ERRORed at setup on a bare `assert None`. That was the largest single family in
       the #6016 backlog, and it only surfaced once the suite could finish at all (#5998).

    2. Grabbing an arbitrary row and WRITING to it is safe only because conftest hard-
       overrides DB_NAME to archie_test. Should that override ever regress, these tests would
       rewrite a REAL agent's bio. Creating our own row removes the hazard instead of leaning
       on the guard.

    The safety check below asks the CONNECTION which database it is on, not the environment:
    `os.environ["DB_NAME"]` can be unset and still connect to `archie` via this module's own
    `os.environ.get("DB_NAME", "archie")` default.
    """
    cur = db.cursor()
    cur.execute("SELECT current_database() AS db")
    assert cur.fetchone()["db"] != "archie", "refusing to create test agents in production"

    _purge_test_agents(cur)
    cur.execute(
        """
        INSERT INTO agents (name, model, department, floor, worker_type)
        VALUES (%s, 'qwen2.5:1.5b', 'Engineering & Technology', 'ENGINEERING', 'ai')
        RETURNING id
        """,
        (_TEST_AGENT_NAME,),
    )
    aid = cur.fetchone()["id"]
    yield aid
    _purge_test_agents(cur)


def test_patch_unknown_field_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"tier": 99}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unknown_field"


def test_patch_non_admin_forbidden(user_client, agent_id):
    resp = user_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "hello"}),
        content_type="application/json",
    )
    assert resp.status_code == 403


def test_patch_missing_agent(admin_client):
    resp = admin_client.patch(
        "/tools/department-hq/api/agent/9999999",
        data=json.dumps({"bio": "x"}),
        content_type="application/json",
    )
    assert resp.status_code == 404


def test_patch_valid_identity_fields(admin_client, agent_id, db):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "updated-by-test"}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.data
    body = resp.get_json()
    assert body["ok"] is True
    assert "bio" in body["updated_fields"]

    cur = db.cursor()
    cur.execute("SELECT bio FROM agents WHERE id=%s", (agent_id,))
    assert cur.fetchone()["bio"] == "updated-by-test"


def test_patch_temperature_bounds(admin_client, agent_id):
    for bad in [-0.1, 2.1, "hot"]:
        resp = admin_client.patch(
            f"/tools/department-hq/api/agent/{agent_id}",
            data=json.dumps({"temperature": bad}),
            content_type="application/json",
        )
        assert resp.status_code == 400, f"expected 400 for temperature={bad}"
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"temperature": 0.5}),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_patch_reports_to_self_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"reports_to_agent_id": agent_id}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "reports_to_self"


def test_patch_reports_to_missing_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"reports_to_agent_id": 99999999}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "reports_to_missing"


def test_patch_sensitive_model_invalid(admin_client, agent_id, monkeypatch):
    from tools.department_hq import agent_detail_routes

    monkeypatch.setattr(
        agent_detail_routes,
        "is_model_available",
        lambda model, hub_host=None: (False, "not there"),
    )
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"model": "bogus:99b"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "model_not_available"


def test_patch_sensitive_model_valid(admin_client, agent_id, monkeypatch):
    from tools.department_hq import agent_detail_routes

    monkeypatch.setattr(
        agent_detail_routes,
        "is_model_available",
        lambda model, hub_host=None: (True, "ok"),
    )
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"model": "mistral:7b"}),
        content_type="application/json",
    )
    assert resp.status_code == 200


def test_patch_writes_audit_row(admin_client, agent_id, db):
    cur = db.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n FROM governance_audit_log " "WHERE event_type='agent_profile_update' AND agent_id=%s",
        (agent_id,),
    )
    before_count = cur.fetchone()["n"]

    admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "audit-test"}),
        content_type="application/json",
    )

    cur.execute(
        "SELECT details FROM governance_audit_log "
        "WHERE event_type='agent_profile_update' AND agent_id=%s "
        "ORDER BY timestamp DESC LIMIT 1",
        (agent_id,),
    )
    row = cur.fetchone()
    details = row["details"]
    if isinstance(details, str):
        details = json.loads(details)
    assert details["after"]["bio"] == "audit-test"

    cur.execute(
        "SELECT COUNT(*) AS n FROM governance_audit_log " "WHERE event_type='agent_profile_update' AND agent_id=%s",
        (agent_id,),
    )
    assert cur.fetchone()["n"] == before_count + 1


def test_patch_partial_body_preserves_other_columns(admin_client, agent_id, db):
    cur = db.cursor()
    cur.execute("SELECT title FROM agents WHERE id=%s", (agent_id,))
    original_title = cur.fetchone()["title"]

    admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({"bio": "partial-test"}),
        content_type="application/json",
    )

    cur.execute("SELECT title, bio FROM agents WHERE id=%s", (agent_id,))
    row = cur.fetchone()
    assert row["title"] == original_title
    assert row["bio"] == "partial-test"


def test_patch_empty_body_rejected(admin_client, agent_id):
    resp = admin_client.patch(
        f"/tools/department-hq/api/agent/{agent_id}",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "empty_body"
