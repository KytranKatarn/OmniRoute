"""Route tests for the Brainstorm module."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))


class FakeCursor:
    def __init__(self, *, fetchone=None, fetchall=None):
        self.fetchone_results = list(fetchone or [])
        self.fetchall_results = list(fetchall or [])
        self.execute_calls = []

    def execute(self, sql, params=None):
        self.execute_calls.append((sql, params))

    def fetchone(self):
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None

    def fetchall(self):
        if self.fetchall_results:
            return self.fetchall_results.pop(0)
        return []


@contextmanager
def fake_db_cursor(cursor):
    yield object(), cursor


@pytest.fixture
def brainstorm_app():
    """Minimal app with only the brainstorm blueprint registered."""
    mini_app = Flask(__name__, template_folder=str(PLATFORM_ROOT / "templates"))
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["WTF_CSRF_ENABLED"] = False

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = int(uid)

    @login_manager.user_loader
    def load_user(uid):
        return _User(uid)

    from tools.brainstorm import brainstorm_bp

    mini_app.register_blueprint(brainstorm_bp)
    return mini_app


@pytest.fixture
def brainstorm_client(brainstorm_app):
    with brainstorm_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
        yield client


@pytest.fixture
def anon_brainstorm_client(brainstorm_app):
    return brainstorm_app.test_client()


@pytest.fixture
def now():
    return datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


def patch_db(cursor):
    """Patch `get_db_cursor` so EVERY call gets its OWN context manager (#6015).

    `return_value=fake_db_cursor(cursor)` evaluates once, so all calls share a single
    `_GeneratorContextManager`. `__enter__` does `del self.args` on first use, so the
    SECOND `with get_db_cursor(...)` in a route raises
    `AttributeError: '_GeneratorContextManager' object has no attribute 'args'` — which
    surfaces as an HTTP 500 and reads like a production defect. It is not: the route
    correctly calls get_db_cursor() afresh each time; the fixture handed it a used object.

    `side_effect` re-evaluates per call, which is what a real context-manager factory does.
    The cursor stays shared on purpose — tests assert against `cursor.execute_calls`.
    """
    return patch(
        "tools.brainstorm.routes.get_db_cursor",
        side_effect=lambda *_a, **_k: fake_db_cursor(cursor),
    )


def test_brainstorm_validators_normalize_boundaries():
    from tools.brainstorm.validators import (
        validate_cluster,
        validate_content,
        validate_goal,
        validate_tags,
        validate_title,
        validate_vote_delta,
    )

    assert validate_title(f" {'x' * 200} ") == "x" * 200
    assert validate_goal(" ") is None
    assert validate_goal(f" {'x' * 500} ") == "x" * 500
    assert validate_content(f" {'x' * 1000} ") == "x" * 1000
    assert validate_cluster(" ") is None
    assert validate_cluster(f" {'x' * 100} ") == "x" * 100
    assert validate_tags([" one ", "", "two"]) == ["one", "two"]
    assert validate_vote_delta(1) == 1
    assert validate_vote_delta(-1) == -1


@pytest.mark.parametrize(
    "validator,value,error",
    [
        ("validate_title", "x" * 201, "title must be 200 characters or fewer"),
        ("validate_goal", "x" * 501, "goal must be 500 characters or fewer"),
        ("validate_content", "x" * 1001, "content must be 1000 characters or fewer"),
        ("validate_cluster", "x" * 101, "cluster must be 100 characters or fewer"),
        ("validate_tags", ["tag"] * 11, "tags cannot include more than 10 items"),
        ("validate_tags", ["x" * 51], "tags must be 50 characters or fewer"),
        ("validate_vote_delta", "1", "vote_delta must be +1 or -1"),
        ("validate_vote_delta", 0, "vote_delta must be +1 or -1"),
    ],
)
def test_brainstorm_validators_reject_invalid_values(validator, value, error):
    import tools.brainstorm.validators as validators

    with pytest.raises(ValueError) as excinfo:
        getattr(validators, validator)(value)
    assert str(excinfo.value) == error


def test_requires_login_for_status(anon_brainstorm_client):
    resp = anon_brainstorm_client.get("/tools/brainstorm/api/status")

    assert resp.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/tools/brainstorm/api/sessions"),
        ("post", "/tools/brainstorm/api/sessions"),
        ("get", "/tools/brainstorm/api/sessions/1"),
        ("patch", "/tools/brainstorm/api/sessions/1"),
        ("delete", "/tools/brainstorm/api/sessions/1"),
        ("post", "/tools/brainstorm/api/sessions/1/ideas"),
        ("patch", "/tools/brainstorm/api/ideas/1"),
        ("delete", "/tools/brainstorm/api/ideas/1"),
        ("post", "/tools/brainstorm/api/sessions/1/export-kb"),
    ],
)
def test_api_endpoints_require_login(anon_brainstorm_client, method, path):
    resp = getattr(anon_brainstorm_client, method)(path, json={})

    assert resp.status_code == 401


def test_status_returns_active(brainstorm_client):
    resp = brainstorm_client.get("/tools/brainstorm/api/status")

    assert resp.status_code == 200
    assert resp.get_json() == {"module": "brainstorm", "status": "active", "healthy": True}


def test_create_session_success_trims_fields(brainstorm_client, now):
    row = {
        "id": 7,
        "title": "Launch Ideas",
        "goal": "Pick a direction",
        "status": "active",
        "tags": ["growth", "launch"],
        "idea_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    cursor = FakeCursor(fetchone=[row])

    with patch_db(cursor):
        resp = brainstorm_client.post(
            "/tools/brainstorm/api/sessions",
            json={"title": "  Launch Ideas  ", "goal": " Pick a direction ", "tags": [" growth ", "", "launch"]},
        )

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    assert data["session"]["title"] == "Launch Ideas"
    assert data["session"]["tags"] == ["growth", "launch"]
    assert cursor.execute_calls[0][1] == (1, "Launch Ideas", "Pick a direction", ["growth", "launch"])


@pytest.mark.parametrize("payload", [{}, {"title": ""}, {"title": "   "}])
def test_create_session_requires_title(brainstorm_client, payload):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "title is required"
    get_db_cursor.assert_not_called()


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"title": "x" * 201}, "title must be 200 characters or fewer"),
        ({"title": 123}, "title must be a string"),
        ({"title": "Valid", "goal": "x" * 501}, "goal must be 500 characters or fewer"),
        ({"title": "Valid", "goal": 123}, "goal must be a string"),
        ({"title": "Valid", "tags": ["tag"] * 11}, "tags cannot include more than 10 items"),
        ({"title": "Valid", "tags": ["x" * 51]}, "tags must be 50 characters or fewer"),
        ({"title": "Valid", "tags": "tag"}, "tags must be a list"),
        ({"title": "Valid", "tags": [3]}, "tags must be strings"),
    ],
)
def test_create_session_validator_limits(brainstorm_client, payload, error):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    get_db_cursor.assert_not_called()


def test_list_sessions_success(brainstorm_client, now):
    cursor = FakeCursor(
        fetchall=[
            [
                {
                    "id": 2,
                    "title": "Roadmap",
                    "goal": None,
                    "status": "active",
                    "tags": None,
                    "idea_count": 3,
                    "created_at": now,
                    "updated_at": now,
                }
            ]
        ]
    )

    with patch_db(cursor):
        resp = brainstorm_client.get("/tools/brainstorm/api/sessions")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["sessions"][0]["tags"] == []
    assert cursor.execute_calls[0][1] == (1,)


def test_get_session_returns_ideas(brainstorm_client, now):
    cursor = FakeCursor(
        fetchone=[
            {
                "id": 3,
                "title": "Offer",
                "goal": "Clarify",
                "status": "active",
                "tags": ["sales"],
                "idea_count": 1,
                "created_at": now,
                "updated_at": now,
            }
        ],
        fetchall=[[{"id": 4, "content": "Bundle services", "cluster": "Packaging", "votes": 2, "created_at": now}]],
    )

    with patch_db(cursor):
        resp = brainstorm_client.get("/tools/brainstorm/api/sessions/3")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["session"]["id"] == 3
    assert data["ideas"][0]["content"] == "Bundle services"


def test_get_session_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.get("/tools/brainstorm/api/sessions/999")

    assert resp.status_code == 404
    assert resp.get_json()["error"] == "Session not found"


def test_update_session_success(brainstorm_client):
    cursor = FakeCursor(fetchone=[{"id": 5}])

    with patch_db(cursor):
        resp = brainstorm_client.patch(
            "/tools/brainstorm/api/sessions/5",
            json={"title": " Updated ", "goal": " ", "tags": [" x ", ""], "status": "archived"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    sql, params = cursor.execute_calls[0]
    assert "title = %s" in sql
    assert "status = %s" in sql
    assert params == ("Updated", None, ["x"], "archived", 5, 1)


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, "Nothing to update"),
        ({"title": " "}, "title cannot be empty"),
        ({"title": "x" * 201}, "title must be 200 characters or fewer"),
        ({"goal": "x" * 501}, "goal must be 500 characters or fewer"),
        ({"tags": ["tag"] * 11}, "tags cannot include more than 10 items"),
        ({"status": "deleted"}, "status must be active or archived"),
        ({"owner_id": 2}, "Unknown field(s): owner_id"),
        (
            {"status = 'archived' --": "ignored"},
            "Unknown field(s): status = 'archived' --",
        ),
    ],
)
def test_update_session_validation_edges(brainstorm_client, payload, error):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.patch("/tools/brainstorm/api/sessions/5", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    get_db_cursor.assert_not_called()


def test_update_session_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.patch("/tools/brainstorm/api/sessions/999", json={"title": "Still safe"})

    assert resp.status_code == 404


def test_delete_session_success(brainstorm_client):
    cursor = FakeCursor(fetchone=[{"id": 6}])

    with patch_db(cursor):
        resp = brainstorm_client.delete("/tools/brainstorm/api/sessions/6")

    assert resp.status_code == 200
    assert cursor.execute_calls[0][1] == (6, 1)


def test_delete_session_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.delete("/tools/brainstorm/api/sessions/404")

    assert resp.status_code == 404


def test_add_idea_success_refreshes_count(brainstorm_client, now):
    cursor = FakeCursor(
        fetchone=[
            {"id": 9},
            {"id": 10, "content": "Ship the prototype", "cluster": "Build", "votes": 0, "created_at": now},
        ]
    )

    with patch_db(cursor):
        resp = brainstorm_client.post(
            "/tools/brainstorm/api/sessions/9/ideas",
            json={"content": " Ship the prototype ", "cluster": " Build "},
        )

    assert resp.status_code == 201
    data = resp.get_json()
    assert data["idea"]["cluster"] == "Build"
    assert len(cursor.execute_calls) == 3
    assert cursor.execute_calls[1][1] == (9, "Ship the prototype", "Build")


@pytest.mark.parametrize("payload", [{}, {"content": ""}, {"content": "   "}])
def test_add_idea_requires_content(brainstorm_client, payload):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/9/ideas", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "content is required"
    get_db_cursor.assert_not_called()


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"content": "x" * 1001}, "content must be 1000 characters or fewer"),
        ({"content": 123}, "content must be a string"),
        ({"content": "Valid", "cluster": "x" * 101}, "cluster must be 100 characters or fewer"),
        ({"content": "Valid", "cluster": 123}, "cluster must be a string"),
    ],
)
def test_add_idea_validator_limits(brainstorm_client, payload, error):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/9/ideas", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    get_db_cursor.assert_not_called()


def test_add_idea_session_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/999/ideas", json={"content": "Idea"})

    assert resp.status_code == 404


def test_update_idea_content_and_cluster(brainstorm_client):
    cursor = FakeCursor(fetchone=[{"id": 11}])

    with patch_db(cursor):
        resp = brainstorm_client.patch(
            "/tools/brainstorm/api/ideas/11",
            json={"content": " Better idea ", "cluster": " Revenue "},
        )

    assert resp.status_code == 200
    sql, params = cursor.execute_calls[0]
    assert "content = %s" in sql
    assert "cluster = %s" in sql
    assert params == ("Better idea", "Revenue", 11, 1)


@pytest.mark.parametrize("delta,expected_votes", [(1, 4), (-1, 0)])
def test_update_idea_vote_delta(brainstorm_client, delta, expected_votes):
    cursor = FakeCursor(fetchone=[{"id": 11, "votes": expected_votes}])

    with patch_db(cursor):
        resp = brainstorm_client.patch("/tools/brainstorm/api/ideas/11", json={"vote_delta": delta})

    assert resp.status_code == 200
    assert resp.get_json()["votes"] == expected_votes
    assert cursor.execute_calls[0][1] == (delta, 11, 1)


@pytest.mark.parametrize(
    "payload,error",
    [
        ({}, "Nothing to update"),
        ({"content": " "}, "content cannot be empty"),
        ({"content": "x" * 1001}, "content must be 1000 characters or fewer"),
        ({"cluster": "x" * 101}, "cluster must be 100 characters or fewer"),
        ({"vote_delta": 0}, "vote_delta must be +1 or -1"),
        ({"vote_delta": "bad"}, "vote_delta must be +1 or -1"),
        ({"vote_delta": 1.2}, "vote_delta must be +1 or -1"),
        ({"vote_delta": True}, "vote_delta must be +1 or -1"),
        ({"votes": 99}, "Unknown field(s): votes"),
        (
            {"cluster = 'x', votes = 999 --": "ignored"},
            "Unknown field(s): cluster = 'x', votes = 999 --",
        ),
    ],
)
def test_update_idea_validation_edges(brainstorm_client, payload, error):
    with patch("tools.brainstorm.routes.get_db_cursor") as get_db_cursor:
        resp = brainstorm_client.patch("/tools/brainstorm/api/ideas/11", json=payload)

    assert resp.status_code == 400
    assert resp.get_json()["error"] == error
    get_db_cursor.assert_not_called()


def test_update_idea_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.patch("/tools/brainstorm/api/ideas/999", json={"content": "Still safe"})

    assert resp.status_code == 404


def test_delete_idea_success_refreshes_count(brainstorm_client):
    cursor = FakeCursor(fetchone=[{"session_id": 12}])

    with patch_db(cursor):
        resp = brainstorm_client.delete("/tools/brainstorm/api/ideas/15")

    assert resp.status_code == 200
    assert len(cursor.execute_calls) == 2
    assert cursor.execute_calls[0][1] == (15, 1)
    assert cursor.execute_calls[1][1] == (12, 12)


def test_delete_idea_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.delete("/tools/brainstorm/api/ideas/999")

    assert resp.status_code == 404


def test_export_to_kb_success_uses_knowledge_service(brainstorm_client):
    cursor = FakeCursor(
        fetchone=[{"title": "Growth", "goal": "Find channels", "tags": ["marketing"]}],
        fetchall=[
            [
                {"content": "Partner referrals", "cluster": "Channels", "votes": 3},
                {"content": "Landing page test", "cluster": None, "votes": 0},
            ]
        ],
    )
    module = types.ModuleType("services.knowledge_service")
    module.store_knowledge = lambda **kwargs: 321

    with patch_db(cursor), patch.dict(sys.modules, {"services.knowledge_service": module}):
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/20/export-kb")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["kb_id"] == 321


def test_export_to_kb_fallback_insert_when_service_missing(brainstorm_client):
    cursor = FakeCursor(
        fetchone=[{"title": "Fallback", "goal": None, "tags": []}, {"id": 654}],
        fetchall=[[{"content": "Offline-safe export", "cluster": "Reliability", "votes": 1}]],
    )

    with patch_db(cursor), patch.dict(sys.modules, {"services.knowledge_service": None}):
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/21/export-kb")

    assert resp.status_code == 200
    assert resp.get_json()["kb_id"] == 654
    assert "INSERT INTO knowledge_base" in cursor.execute_calls[2][0]
    assert cursor.execute_calls[2][1][2] == ["brainstorm", "export"]


def test_export_to_kb_empty_session_success(brainstorm_client):
    captured = {}
    cursor = FakeCursor(fetchone=[{"title": "Empty", "goal": "", "tags": None}], fetchall=[[]])

    def store_knowledge(**kwargs):
        captured.update(kwargs)
        return 987

    module = types.ModuleType("services.knowledge_service")
    module.store_knowledge = store_knowledge

    with patch_db(cursor), patch.dict(sys.modules, {"services.knowledge_service": module}):
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/22/export-kb")

    assert resp.status_code == 200
    assert "*(no ideas)*" in captured["content"]
    assert captured["tags"] == ["brainstorm", "export"]


def test_export_to_kb_session_not_found(brainstorm_client):
    cursor = FakeCursor(fetchone=[None])

    with patch_db(cursor):
        resp = brainstorm_client.post("/tools/brainstorm/api/sessions/404/export-kb")

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/tools/brainstorm/api/sessions", {"title": "Robert'); DROP TABLE brainstorm_sessions;--"}),
        ("/tools/brainstorm/api/sessions/1/ideas", {"content": "x'); DROP TABLE brainstorm_ideas;--"}),
        ("/tools/brainstorm/api/ideas/1", {"content": "safe", "cluster = 'x', votes = 999 --": "boom"}),
        ("/tools/brainstorm/api/sessions/1", {"title": "safe", "status = 'archived' --": "boom"}),
    ],
)
def test_sql_injection_payloads_are_parameters_or_rejected(brainstorm_client, now, path, payload):
    cursor = FakeCursor(
        fetchone=[
            {
                "id": 1,
                "title": payload.get("title", "Safe"),
                "goal": None,
                "status": "active",
                "tags": [],
                "idea_count": 0,
                "created_at": now,
                "updated_at": now,
            },
            {"id": 2, "content": payload.get("content", "Safe"), "cluster": None, "votes": 0, "created_at": now},
            {"id": 2, "content": payload.get("content", "Safe"), "cluster": None, "votes": 0, "created_at": now},
        ]
    )

    with patch_db(cursor):
        resp = (
            brainstorm_client.post(path, json=payload)
            if "/ideas" in path or path.endswith("sessions")
            else brainstorm_client.patch(path, json=payload)
        )

    if resp.status_code == 400:
        assert "Unknown field" in resp.get_json()["error"]
        assert not cursor.execute_calls
    else:
        executed_sql = " ".join(sql for sql, _params in cursor.execute_calls)
        assert "DROP TABLE" not in executed_sql
