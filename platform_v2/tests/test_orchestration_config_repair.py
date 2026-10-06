"""Exercise real orchestration updates against an isolated database."""

import re
import sqlite3
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

import pytest
from flask import Blueprint, Flask, jsonify

from services.code_health_checks import sql_finding_present
from tools.department_hq import fleet_orchestration_routes as routes


FIELDS = {
    "idle_threshold_minutes": (5, 12),
    "utilization_threshold_pct": (60.0, 75.0),
    "queue_pressure_threshold": (10, 20),
    "idle_weight": (0.3, 0.2),
    "utilization_weight": (0.3, 0.5),
    "queue_pressure_weight": (0.4, 0.3),
    "overflow_enabled": (True, False),
    "overflow_paused": (False, True),
    "priority_boost": (0, 4),
    "max_overflow_concurrent": (3, 8),
}


@pytest.fixture
def config_api(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE cluster_orchestration_config ("
        "scope TEXT, agent_id INTEGER, capability TEXT, node_id TEXT, "
        "idle_threshold_minutes INTEGER, utilization_threshold_pct REAL, queue_pressure_threshold INTEGER, "
        "idle_weight REAL, utilization_weight REAL, queue_pressure_weight REAL, "
        "overflow_enabled BOOLEAN, overflow_paused BOOLEAN, priority_boost INTEGER, "
        "max_overflow_concurrent INTEGER, updated_at TEXT)"
    )
    state = {"admin": True, "queries": [], "commits": []}

    class Cursor:
        def execute(self, sql, params):
            state["queries"].append((sql, params))
            translated = re.sub(r"%\((\w+)\)s", r":\1", sql).replace("NOW()", "CURRENT_TIMESTAMP")
            self.cursor = conn.execute(translated, params)

        @property
        def rowcount(self):
            return self.cursor.rowcount

    @contextmanager
    def db(commit=False):
        state["commits"].append(commit)
        try:
            yield conn, Cursor()
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise

    monkeypatch.setattr(routes, "get_db_cursor", db)

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not state["admin"]:
                return jsonify({"error": "not_admin"}), 403
            return fn(*args, **kwargs)

        return wrapped

    app = Flask(__name__)
    app.config["TESTING"] = True
    bp = Blueprint("isolated-orchestration", __name__)
    routes.register_orchestration_routes(bp, admin_required)
    app.register_blueprint(bp)
    yield app.test_client(), conn, state
    conn.close()


def post(client, **body):
    return client.post("/api/orchestration/config", json=body)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("existing", [False, True])
def test_requested_fields_apply_and_omitted_values_survive(config_api, field, existing):
    client, conn, state = config_api
    original = {name: values[0] for name, values in FIELDS.items()}
    if existing:
        original["priority_boost"] = 17
        assert post(client, **original).status_code == 200
        state["queries"].clear()
        state["commits"].clear()
    requested = FIELDS[field][1]
    response = post(client, **{field: requested})
    assert response.status_code == 200
    rows = conn.execute("SELECT * FROM cluster_orchestration_config").fetchall()
    assert len(rows) == 1
    expected = dict(original, **{field: requested})
    for name, value in expected.items():
        assert rows[0][name] == value
    assert state["commits"] == [True]
    assert len(state["queries"]) == (1 if existing else 2)


@pytest.mark.parametrize(
    "selector",
    [
        {"scope": "global"},
        {"scope": "agent", "agent_id": 42},
        {"scope": "capability", "capability": "code_review"},
        {"scope": "node", "node_id": "node-1"},
        {"scope": "agent", "agent_id": 42, "capability": "code_review", "node_id": "node-1"},
        {"scope": "node", "node_id": "'; DELETE FROM cluster_orchestration_config; --"},
    ],
)
def test_selectors_match_nullable_keys_and_leave_other_rows_untouched(config_api, selector):
    client, conn, state = config_api
    assert post(client, scope="protected", agent_id=99, priority_boost=7).status_code == 200
    assert post(client, **selector, priority_boost=4, overflow_enabled=False).status_code == 200
    assert post(client, **selector, overflow_paused=True).status_code == 200
    rows = conn.execute("SELECT * FROM cluster_orchestration_config").fetchall()
    assert len(rows) == 2
    protected = next(row for row in rows if row["scope"] == "protected")
    target = next(row for row in rows if row["scope"] != "protected")
    assert protected["priority_boost"] == 7
    assert protected["overflow_paused"] == 0
    assert target["priority_boost"] == 4
    assert target["overflow_enabled"] == 0
    assert target["overflow_paused"] == 1
    for query, _ in state["queries"]:
        assert "DELETE" not in query


def test_unknown_fields_and_admin_denial_never_write(config_api):
    client, conn, state = config_api
    assert post(client, unknown=42).status_code == 400
    assert state["queries"] == []
    state["admin"] = False
    assert post(client, overflow_paused=True).status_code == 403
    assert state["queries"] == []
    assert conn.execute("SELECT COUNT(*) FROM cluster_orchestration_config").fetchone()[0] == 0


def test_explicit_null_is_not_treated_as_an_omitted_field(config_api):
    client, conn, _ = config_api
    assert post(client, priority_boost=7).status_code == 200
    assert post(client, priority_boost=None).status_code == 200
    assert conn.execute("SELECT priority_boost FROM cluster_orchestration_config").fetchone()[0] is None


def test_complete_orchestration_source_proves_literal_queries():
    assert sql_finding_present(Path(routes.__file__).read_text()) is False
