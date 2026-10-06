"""Exercise profile routes with isolated service and database dependencies."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify
from flask_login import LoginManager, UserMixin, current_user

import database
from services.code_issue_reconciler import finding_still_reproduces
from tools.department_hq import agent_detail_routes as routes


@pytest.fixture
def profile(monkeypatch):
    agent = {"id": 7, "name": "test-agent", "bio": "before", "department": "Engineering & Technology"}
    update = Mock()
    lookup = Mock(side_effect=lambda aid: agent if aid == 7 else None)
    model = Mock(return_value=(True, "available"))
    monkeypatch.setattr(routes, "get_agent", lookup)
    monkeypatch.setattr(routes, "update_agent", update)
    monkeypatch.setattr(routes, "get_skills", Mock(return_value=[]))
    monkeypatch.setattr(routes, "get_welfare", Mock(return_value=None))
    monkeypatch.setattr(routes, "get_performance", Mock(return_value={}))
    monkeypatch.setattr(routes, "is_model_available", model)
    state = {"admin": True, "db_error": False, "queries": [], "commits": []}
    voice = {
        "profile_name": "test",
        "speed": Decimal("1.25"),
        "pitch_shift": Decimal("0.5"),
        "warmth": Decimal("0.75"),
        "updated_at": datetime(2026, 10, 5, tzinfo=timezone.utc),
    }

    class Cursor:
        def execute(self, sql, params):
            state["queries"].append((sql, params))
            self.sql = sql

        def fetchone(self):
            if "agent_voice_profiles" in self.sql:
                return voice
            return {"identity_prompt": "the original portrait"}

    @contextmanager
    def db(commit=False):
        if state["db_error"]:
            raise RuntimeError("isolated database failure")
        state["commits"].append(commit)
        yield None, Cursor()

    monkeypatch.setattr(database, "get_db_cursor", db)
    app = Flask(__name__)
    app.config.update(SECRET_KEY="isolated-test-key", TESTING=True)
    lm = LoginManager(app)

    class User(UserMixin):
        id = "42"

        @property
        def is_admin(self):
            return state["admin"]

    lm.user_loader(lambda uid: User())

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not current_user.is_admin:
                return jsonify({"error": "not_admin"}), 403
            return fn(*args, **kwargs)

        return wrapped

    bp = Blueprint("profile-test", __name__)
    routes.register_agent_detail_routes(bp, admin_required)
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "42"
        session["_fresh"] = True
    return client, state, update, lookup, model


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"temperature": True}, "invalid_value"),
        ({"temperature": 2.1}, "invalid_value"),
        ({"max_tokens": True}, "invalid_value"),
        ({"max_tokens": 0}, "invalid_value"),
        ({"max_tokens": 8193}, "invalid_value"),
        ({"auto_approve_threshold": False}, "invalid_value"),
        ({"auto_approve_threshold": 1001}, "invalid_value"),
        ({"is_department_ai": 1}, "invalid_value"),
        ({"social_topics": ["valid", 1]}, "invalid_value"),
        ({"department": "unknown"}, "invalid_value"),
        ({"reports_to_agent_id": 7}, "reports_to_self"),
        ({"reports_to_agent_id": 999}, "reports_to_missing"),
        ({"unlisted": "value"}, "unknown_field"),
        ({}, "empty_body"),
    ],
)
def test_invalid_patch_never_updates_or_writes_an_audit(profile, payload, error):
    client, state, update, _, _ = profile
    response = client.patch("/api/agent/7", json=payload)
    assert response.status_code == 400
    assert response.json["error"] == error
    update.assert_not_called()
    assert not state["queries"]


@pytest.mark.parametrize(
    "payload",
    [
        {"temperature": 0.0},
        {"temperature": 2.0},
        {"max_tokens": 1},
        {"max_tokens": 8192},
        {"auto_approve_threshold": 0},
        {"auto_approve_threshold": 1000},
        {"reports_to_agent_id": None},
        {"social_topics": ["first", "second"]},
        {"is_department_ai": False},
    ],
)
def test_valid_patch_preserves_service_write_and_bound_audit(profile, payload):
    client, state, update, _, _ = profile
    response = client.patch("/api/agent/7", json=payload)
    assert response.status_code == 200
    update.assert_called_once_with(7, **payload)
    sql, params = state["queries"][-1]
    assert "INSERT INTO governance_audit_log" in sql
    assert "VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())" in sql
    assert params[2:4] == (7, "42")
    assert json.loads(params[-1])["after"] == payload
    assert state["commits"] == [True]


def test_model_validation_uses_existing_route_override(profile):
    client, state, update, _, model = profile
    model.return_value = (False, "not available")
    response = client.patch("/api/agent/7", json={"model": "missing:model"})
    assert response.status_code == 400
    assert response.json["error"] == "model_not_available"
    model.assert_called_once_with("missing:model")
    update.assert_not_called()
    assert not state["queries"]


@pytest.mark.parametrize("method,path", [("get", "/api/agent/7/profile"), ("patch", "/api/agent/7")])
def test_profile_routes_still_require_admin(profile, method, path):
    client, state, update, lookup, _ = profile
    state["admin"] = False
    assert getattr(client, method)(path, json={"bio": "updated"}).status_code == 403
    lookup.assert_not_called()
    update.assert_not_called()
    assert not state["queries"]


def test_profile_read_preserves_identity_voice_and_bound_agent_id(profile):
    client, state, _, _, _ = profile
    response = client.get("/api/agent/7/profile")
    assert response.status_code == 200
    agent = response.json["agent"]
    assert agent["identity_prompt"] == "the original portrait"
    assert agent["voice_profile"]["speed"] == 1.25
    assert agent["voice_profile"]["updated_at"] == "2026-10-05T00:00:00+00:00"
    assert all(params == (7,) for _, params in state["queries"])
    voice_sql = next(sql for sql, _ in state["queries"] if "agent_voice_profiles" in sql)
    assert "is_active = TRUE" in voice_sql and "ORDER BY updated_at DESC NULLS LAST, id DESC" in voice_sql


def test_audit_retains_before_and_after_values(profile):
    client, state, _, _, _ = profile
    assert client.patch("/api/agent/7", json={"bio": "updated"}).status_code == 200
    assert json.loads(state["queries"][-1][1][-1]) == {"before": {"bio": "before"}, "after": {"bio": "updated"}}


def test_database_failure_keeps_read_fallbacks_and_successful_service_write(profile):
    client, state, update, _, _ = profile
    state["db_error"] = True
    assert routes._get_identity_prompt(7) is None
    assert routes._get_voice_profile(7) is None
    assert client.patch("/api/agent/7", json={"bio": "updated"}).status_code == 200
    update.assert_called_once_with(7, bio="updated")


def test_route_and_extracted_helper_are_below_the_original_size_limit():
    root = Path(__file__).parents[1] / "tools/department_hq"
    for path in [root / "agent_detail_routes.py", root / "services/agent_profile_helpers.py"]:
        assert finding_still_reproduces("LARGE_FILE historical size", path.read_text()) is False
