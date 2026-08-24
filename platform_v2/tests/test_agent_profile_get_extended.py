"""Verify GET /api/agent/<id>/profile returns the full editable field set."""

from __future__ import annotations

import os
import sys

import pytest
import psycopg2
import psycopg2.extras


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


@pytest.fixture(scope="module")
def client():
    from flask import Flask, Blueprint
    from flask_login import LoginManager, UserMixin

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["TESTING"] = True

    lm = LoginManager(app)

    class _User(UserMixin):
        id = 1
        is_admin = True
        username = "test_admin"

    _user = _User()

    @lm.user_loader
    def _load_user(uid):
        return _user

    from tools.department_hq.agent_detail_routes import register_agent_detail_routes

    def admin_required(f):
        return f

    bp = Blueprint("dhq", __name__, url_prefix="/tools/department-hq")
    register_agent_detail_routes(bp, admin_required)
    app.register_blueprint(bp)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield c


EXPECTED_FIELDS = {
    "id",
    "name",
    "display_name",
    "title",
    "bio",
    "acronym",
    "acronym_expansion",
    "pronouns",
    "current_grade",
    "department",
    "floor",
    "writing_tone",
    "is_department_ai",
    "reports_to_agent_id",
    "model",
    "temperature",
    "max_tokens",
    "system_prompt",
    "communication_style",
    "appearance_notes",
    "age_range",
    "gender",
    "ethnicity",
    "social_topics",
    "auto_approve_threshold",
    "shift_state",
    "status",
    "avatar_url",
}


_TEST_AGENT_NAME = "T.E.S.T.-profile-get-fixture"


def test_profile_returns_all_editable_fields(db, client):
    # Create the agent this test needs rather than borrowing whatever comes back first
    # (#6016). `archie_test` is EMPTY — schema, no rows — so the old SELECT returned None
    # and the test died on `assert row` before exercising anything. It only surfaced once
    # the suite could finish at all (#5998).
    cur = db.cursor()
    cur.execute("SELECT current_database() AS db")
    assert cur.fetchone()["db"] != "archie", "refusing to create test agents in production"
    cur.execute("DELETE FROM agents WHERE name = %s", (_TEST_AGENT_NAME,))
    cur.execute(
        """
        INSERT INTO agents (name, model, department, floor, worker_type)
        VALUES (%s, 'qwen2.5:1.5b', 'Engineering & Technology', 'ENGINEERING', 'ai')
        RETURNING id
        """,
        (_TEST_AGENT_NAME,),
    )
    agent_id = cur.fetchone()["id"]

    resp = client.get(f"/tools/department-hq/api/agent/{agent_id}/profile")
    assert resp.status_code == 200, resp.data

    body = resp.get_json()
    assert "agent" in body
    agent = body["agent"]

    missing = EXPECTED_FIELDS - set(agent.keys())
    assert not missing, f"missing fields in profile response: {missing}"

    # This test only READS through the API, so no FK rows are created; a plain delete is
    # enough. Kept explicit so a repeat run cannot trip the name collision above.
    cur.execute("DELETE FROM agents WHERE name = %s", (_TEST_AGENT_NAME,))
