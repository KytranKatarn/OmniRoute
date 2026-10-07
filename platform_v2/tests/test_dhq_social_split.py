"""Prove a route split preserves handler bodies, routes and admin guards."""

import ast
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType
from functools import wraps

from flask import Blueprint, Flask, jsonify

ROOT = Path(__file__).parents[1] / "tools/department_hq"
MODULES = (
    "social_routes",
    "social_session_routes",
    "signal_monitor_routes",
    "signal_action_routes",
)


def test_social_handlers_preserved_and_below_size_threshold():
    expected = json.loads((Path(__file__).parent / "fixtures/dhq_social_handlers.json").read_text())
    actual = {}
    for module in MODULES:
        source = (ROOT / (module + ".py")).read_text()
        assert source.count("\n") + 1 <= 600
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.decorator_list:
                assert node.name not in actual
                doc = node.body[0] if node.body else None
                if (
                    isinstance(doc, ast.Expr)
                    and isinstance(doc.value, ast.Constant)
                    and isinstance(doc.value.value, str)
                ):
                    doc.value.value = inspect.cleandoc(doc.value.value)
                actual[node.name] = list(hashlib.sha256(ast.dump(node, include_attributes=False).encode()).digest())
    assert actual == expected


def test_route_registration_and_admin_guards(monkeypatch):
    package = ModuleType("dhq_social_split_test")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    agents = ModuleType("services.agent_service")
    agents.get_agent = lambda _: None
    social = ModuleType("services.agent_social_service")
    for name in (
        "get_social_profiles",
        "add_social_profile",
        "remove_social_profile",
        "get_writing_voice",
        "update_writing_voice",
        "get_posts",
        "create_post",
        "publish_post",
        "generate_post_content",
    ):
        setattr(social, name, lambda *a, **kw: None)
    monkeypatch.setitem(sys.modules, agents.__name__, agents)
    monkeypatch.setitem(sys.modules, social.__name__, social)
    imported = []
    try:
        module = importlib.import_module(package.__name__ + ".social_routes")
        imported = [package.__name__ + "." + name for name in MODULES]
        app = Flask(__name__)
        bp = Blueprint("social_split", __name__, url_prefix="/tools/department-hq")

        def admin_required(fn):
            @wraps(fn)
            def denied(*args, **kwargs):
                return jsonify({"error": "admin required"}), 403

            return denied

        module.register_social_routes(bp, admin_required)
        app.register_blueprint(bp)
        expected = set(json.loads((Path(__file__).parent / "fixtures/dhq_social_handlers.json").read_text()))
        rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("social_split.")]
        assert {rule.endpoint.split(".")[-1] for rule in rules} == expected
        assert len(rules) == len(expected)
        client = app.test_client()
        for rule in rules:
            path = rule.rule
            for arg in rule.arguments:
                path = path.replace("<int:" + arg + ">", "1").replace("<" + arg + ">", "test")
            method = next(m for m in rule.methods if m not in ("OPTIONS", "HEAD"))
            assert client.open(path, method=method).status_code == 403, (method, path)
    finally:
        for name in imported:
            sys.modules.pop(name, None)
