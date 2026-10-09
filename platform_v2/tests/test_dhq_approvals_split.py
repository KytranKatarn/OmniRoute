"""Preserve approval executors, route contracts and fail-closed guards."""

import ast
from functools import wraps
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from flask import abort, Blueprint, Flask
import pytest

ROOT = Path(__file__).parents[1] / "tools/department_hq"
FILES = ("approvals_routes", "approvals_helpers", "approvals_queue", "approvals_hire_routes")
CONTRACT = json.loads((Path(__file__).parent / "fixtures/dhq_approvals_contract.json").read_text())


def test_all_original_function_bodies_and_file_sizes():
    actual = {}
    for name in FILES:
        source = (ROOT / (name + ".py")).read_text()
        assert len(source.splitlines()) <= 600
        for node in ast.parse(source).body:
            if not isinstance(node, ast.FunctionDef):
                continue
            selected = node.body if node.name.startswith("register_") else [node]
            for function in selected:
                if not isinstance(function, ast.FunctionDef):
                    continue
                for child in ast.walk(function):
                    if isinstance(child, ast.FunctionDef) and child.body:
                        doc = child.body[0]
                        if (
                            isinstance(doc, ast.Expr)
                            and isinstance(doc.value, ast.Constant)
                            and isinstance(doc.value.value, str)
                        ):
                            doc.value.value = inspect.cleandoc(doc.value.value)
                assert function.name not in actual
                actual[function.name] = list(
                    hashlib.sha256(ast.dump(function, include_attributes=False).encode()).digest()
                )
    assert actual == CONTRACT["functions"]


@pytest.fixture
def approvals_modules(monkeypatch):
    package = ModuleType("dhq_approvals_split_test")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    names = [package.__name__ + "." + name for name in FILES]
    try:
        modules = {name: importlib.import_module(package.__name__ + "." + name) for name in FILES}
        yield modules
    finally:
        for name in names:
            sys.modules.pop(name, None)


def make_app(modules, guard):
    app = Flask(__name__)
    bp = Blueprint("approval_split", __name__, url_prefix="/tools/department-hq")
    modules["approvals_routes"].register_approvals_routes(bp, guard)
    app.register_blueprint(bp)
    return app


def test_original_callable_import_surface(approvals_modules):
    entry = approvals_modules["approvals_routes"]
    helpers = approvals_modules["approvals_helpers"]
    for name in CONTRACT["functions"]:
        if hasattr(helpers, name):
            assert getattr(entry, name) is getattr(helpers, name)
    assert entry.list_pending_approvals is approvals_modules["approvals_queue"].list_pending_approvals


def test_every_url_method_and_admin_guard_is_preserved(approvals_modules):
    def deny(fn):
        @wraps(fn)
        def denied(*a, **k):
            abort(403)

        return denied

    app = make_app(approvals_modules, deny)
    rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith("approval_split.")]
    expected = {
        (name, "/tools/department-hq" + route["path"], method)
        for name, route in CONTRACT["routes"].items()
        for method in route["methods"]
    }
    assert {
        (r.endpoint.split(".")[-1], r.rule, method) for r in rules for method in r.methods - {"HEAD", "OPTIONS"}
    } == expected
    assert len(rules) == len(CONTRACT["routes"])
    client = app.test_client()
    for rule in rules:
        path = (
            rule.rule.replace("<int:hire_id>", "1")
            .replace("<path:approval_id>", "autonomy:1")
            .replace("<job_id>", "test")
        )
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert client.open(path, method=method, json={}).status_code == 403


@pytest.mark.parametrize("approval_id", ["hire:1", "junk:1", "1", "autonomy:", "autonomy:bad"])
@pytest.mark.parametrize("action", ["approve", "deny"])
def test_generic_routes_still_reject_invalid_source_or_id(approvals_modules, monkeypatch, approval_id, action):
    entry = approvals_modules["approvals_routes"]
    monkeypatch.setattr(entry, "current_user", SimpleNamespace(id=7))
    for source in ("autonomy", "contractor", "bridge"):
        for operation in ("approve", "deny"):
            monkeypatch.setattr(
                entry, "_" + operation + "_" + source, lambda *a, **k: pytest.fail("Invalid request reached executor")
            )
    app = make_app(approvals_modules, lambda fn: fn)
    response = app.test_client().post("/tools/department-hq/api/approvals/" + approval_id + "/" + action, json={})
    assert response.status_code == 400
    assert response.json["success"] is False


@pytest.mark.parametrize("value", ["5", "autonomy:", "autonomy:x", ":1"])
def test_parser_never_guesses_a_source(approvals_modules, value):
    with pytest.raises(ValueError, match="malformed approval id"):
        approvals_modules["approvals_routes"].parse_approval_id(value)


def test_hiring_requires_selection_before_executor(approvals_modules, monkeypatch):
    hiring = ModuleType("services.hiring_service")
    hiring.approve_candidate = lambda *a, **k: pytest.fail("Malformed hire reached executor")
    monkeypatch.setitem(sys.modules, hiring.__name__, hiring)
    app = make_app(approvals_modules, lambda fn: fn)
    response = app.test_client().post("/tools/department-hq/api/approvals/hire/1/approve", json={})
    assert response.status_code == 400
    assert response.json["reason"] == "chosen_agent_id or new_agent required"
