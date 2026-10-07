"""Preserve crew handlers, authentication and ownership boundaries during a split."""

import ast
from functools import wraps
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from flask import Blueprint, Flask, jsonify
import pytest

ROOT = Path(__file__).parents[1] / "tools/department_hq"
MODULES = ("fleet_crew_routes", "fleet_crew_action_routes")
MANIFEST = Path(__file__).parent / "fixtures/dhq_crew_handlers.json"


def test_crew_handlers_and_size():
    actual = {}
    for module in MODULES:
        source = (ROOT / (module + ".py")).read_text()
        assert source.count("\n") + 1 <= 600
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.decorator_list:
                assert node.name not in actual
                doc = node.body[0]
                if (
                    isinstance(doc, ast.Expr)
                    and isinstance(doc.value, ast.Constant)
                    and isinstance(doc.value.value, str)
                ):
                    doc.value.value = inspect.cleandoc(doc.value.value)
                actual[node.name] = list(hashlib.sha256(ast.dump(node, include_attributes=False).encode()).digest())
    assert actual == json.loads(MANIFEST.read_text())


@pytest.fixture
def crew_app(monkeypatch):
    package = ModuleType("dhq_crew_split_test")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    db = ModuleType("database")

    def forbidden_db(*args, **kwargs):
        pytest.fail("Denied request reached the database")

    db.get_db_cursor = forbidden_db
    db.check_fleet_model_unique = forbidden_db
    monkeypatch.setitem(sys.modules, "database", db)
    helpers = ModuleType(package.__name__ + ".fleet_helpers")
    ownership = []
    helpers._get_node_for_user_by_int_id = lambda node, user: ownership.append((node, user))
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)
    imported = []
    try:
        module = importlib.import_module(package.__name__ + ".fleet_crew_routes")
        app = Flask(__name__)
        bp = Blueprint("crew_split", __name__, url_prefix="/tools/department-hq")
        auth = {"allowed": False}

        def guard(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not auth["allowed"]:
                    return jsonify({"error": "authentication required"}), 403
                return fn(*args, **kwargs)

            return wrapped

        module.register_crew_routes(bp, guard)
        app.register_blueprint(bp)
        imported = [package.__name__ + "." + name for name in MODULES]
        actions = sys.modules[imported[1]]
        monkeypatch.setattr(actions, "current_user", SimpleNamespace(id=42))
        yield app, auth, ownership
    finally:
        for name in imported:
            sys.modules.pop(name, None)


def test_all_eight_routes_keep_authentication(crew_app):
    app, _, ownership = crew_app
    expected = set(json.loads(MANIFEST.read_text()))
    rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith("crew_split.")]
    assert {r.endpoint.split(".")[-1] for r in rules} == expected
    assert len(rules) == 8
    client = app.test_client()
    for rule in rules:
        path = rule.rule
        for arg in rule.arguments:
            path = path.replace("<int:" + arg + ">", "1")
        method = next(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
        assert client.open(path, method=method, json={"agent_id": 1}).status_code == 403
    assert not ownership


@pytest.mark.parametrize(
    "method,path",
    [
        ("PUT", "/api/nodes/7/agents/1"),
        ("POST", "/api/nodes/7/agents/add"),
        ("DELETE", "/api/nodes/7/agents/1"),
        ("POST", "/api/nodes/7/assign-agents"),
    ],
)
def test_crew_writes_require_node_ownership(crew_app, method, path):
    app, auth, ownership = crew_app
    auth["allowed"] = True
    response = app.test_client().open("/tools/department-hq" + path, method=method, json={"agent_id": 1})
    assert response.status_code == 404
    assert ownership == [(7, 42)]
