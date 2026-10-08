"""Keep work/OTA route contracts and authorization intact during file splits."""

import ast
from contextlib import contextmanager
from functools import wraps
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType

from flask import abort, Blueprint, Flask
import pytest

ROOT = Path(__file__).parents[1] / "tools/department_hq"
CONTRACT = json.loads((Path(__file__).parent / "fixtures/dhq_work_ota_contract.json").read_text())


@pytest.mark.parametrize("group", list(CONTRACT))
def test_original_handlers_and_file_sizes(group):
    actual = {}
    bindings = []
    for name in CONTRACT[group]["files"]:
        source = (ROOT / (name + ".py")).read_text()
        assert len(source.splitlines()) <= 600
        tree = ast.parse(source)
        for register in tree.body:
            if not isinstance(register, ast.FunctionDef) or not register.name.startswith("register_"):
                continue
            for node in register.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    bindings.append(list(hashlib.sha256(ast.dump(node, include_attributes=False).encode()).digest()))
                if not isinstance(node, ast.FunctionDef):
                    continue
                assert node.name not in actual
                for function in ast.walk(node):
                    if isinstance(function, ast.FunctionDef) and function.body:
                        doc = function.body[0]
                        if (
                            isinstance(doc, ast.Expr)
                            and isinstance(doc.value, ast.Constant)
                            and isinstance(doc.value.value, str)
                        ):
                            doc.value.value = inspect.cleandoc(doc.value.value)
                actual[node.name] = list(hashlib.sha256(ast.dump(node, include_attributes=False).encode()).digest())
    assert actual == CONTRACT[group]["handlers"]
    assert bindings == CONTRACT[group]["bindings"]


@pytest.fixture
def route_app(monkeypatch):
    package = ModuleType("dhq_work_ota_test")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    db = ModuleType("database")
    db.get_db_cursor = lambda *a, **k: pytest.fail("Unauthorized request reached database")
    monkeypatch.setitem(sys.modules, "database", db)
    helpers = ModuleType(package.__name__ + ".fleet_helpers")
    helpers._get_node_for_user_by_int_id = lambda *a, **k: pytest.fail("Unauthorized request accessed a node")
    helpers.LATEST_NODE_VERSION = "test"
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)

    def deny(fn):
        @wraps(fn)
        def denied(*a, **k):
            abort(403)

        return denied

    app = Flask(__name__)
    bp = Blueprint("work_ota", __name__, url_prefix="/tools/department-hq")
    modules = {}
    names = [package.__name__ + "." + name for group in CONTRACT.values() for name in group["files"]]
    try:
        for group, contract in CONTRACT.items():
            module = importlib.import_module(package.__name__ + "." + group)
            getattr(module, contract["register"])(bp, deny)
        for name in names:
            modules[name.rsplit(".", 1)[-1]] = sys.modules[name]
        app.register_blueprint(bp)
        yield app, modules
    finally:
        for name in names:
            sys.modules.pop(name, None)


def test_all_original_urls_methods_and_admin_guards(route_app):
    app, _ = route_app
    expected = {
        ("/tools/department-hq" + route["path"], method)
        for group in CONTRACT.values()
        for route in group["routes"].values()
        for method in route["methods"]
    }
    rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith("work_ota.")]
    actual = {(r.rule, method) for r in rules for method in r.methods - {"HEAD", "OPTIONS"}}
    assert actual == expected
    assert len(rules) == sum(len(g["routes"]) for g in CONTRACT.values())
    client = app.test_client()
    for group in CONTRACT.values():
        for route in group["routes"].values():
            if not route["guarded"]:
                continue
            path = (
                route["path"]
                .replace("<int:node_id>", "1")
                .replace("<int:agent_id>", "1")
                .replace("<department>", "test")
            )
            for method in route["methods"]:
                assert client.open("/tools/department-hq" + path, method=method).status_code == 403


@pytest.mark.parametrize("header", [None, "invalid-key"])
def test_node_poll_and_ack_deny_missing_or_invalid_key(route_app, monkeypatch, header):
    app, modules = route_app

    class Cursor:
        def execute(self, query, params):
            assert "SELECT api_key_hash FROM remote_nodes" in query
            assert params == ("test-node",)

        def fetchone(self):
            return {"api_key_hash": "unmatched"}

    @contextmanager
    def db(*a, **k):
        yield None, Cursor()

    monkeypatch.setattr(modules["fleet_ota_delivery_routes"], "get_db_cursor", db)
    headers = {"X-Node-API-Key": header} if header else {}
    client = app.test_client()
    for suffix, method in (("pending-commands", "GET"), ("ack-command/7", "POST")):
        response = client.open(
            "/tools/department-hq/api/nodes/test-node/" + suffix, method=method, headers=headers, json={}
        )
        assert response.status_code == 401


def test_valid_node_key_polling_stays_scoped_to_its_node(route_app, monkeypatch):
    app, modules = route_app
    key = "test-node-only"
    queries = []

    class Cursor:
        def execute(self, query, params):
            queries.append((query, params))
            assert params == ("test-node",)

        def fetchone(self):
            return {"api_key_hash": hashlib.sha256(key.encode()).hexdigest()}

        def fetchall(self):
            return [{"id": 7, "sync_type": "test", "payload": None}]

    @contextmanager
    def db(*a, **k):
        yield None, Cursor()

    monkeypatch.setattr(modules["fleet_ota_delivery_routes"], "get_db_cursor", db)
    response = app.test_client().get(
        "/tools/department-hq/api/nodes/test-node/pending-commands", headers={"X-Node-API-Key": key}
    )
    assert response.status_code == 200
    assert response.json["commands"] == [{"id": 7, "sync_type": "test", "payload": {}}]
    assert len(queries) == 2
    assert "WHERE node_id = %s" in queries[-1][0]


def test_ota_file_allowlist_and_checkpoint_filename_guards(route_app):
    app, _ = route_app
    client = app.test_client()
    assert client.get("/tools/department-hq/api/nodes/ota/secret.txt").status_code == 403
    assert client.get("/tools/department-hq/api/fleet/checkpoints/bad%24name").status_code == 400


def test_work_detail_keeps_the_original_inference_filter(route_app):
    _, modules = route_app
    assert modules["work_detail_routes"]._REAL_INFERENCE_SQL is modules["work_routes"]._REAL_INFERENCE_SQL
    assert "bridge-managed" in modules["work_detail_routes"]._REAL_INFERENCE_SQL
    assert "worker_type IS NOT NULL" in modules["work_detail_routes"]._REAL_INFERENCE_SQL
