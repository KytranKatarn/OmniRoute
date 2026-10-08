"""Preserve dispatch routes and job registry contents through file-size repairs."""

import ast
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType

from flask import Blueprint, Flask
from flask_login import LoginManager
import pytest

ROOT = Path(__file__).parents[1] / "tools/department_hq"
FIXTURES = Path(__file__).parent / "fixtures"


def test_dispatch_handlers_and_file_sizes():
    actual = {}
    for name in ("fleet_dispatch_routes", "fleet_dispatch_job_routes"):
        source = (ROOT / (name + ".py")).read_text()
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
    assert actual == json.loads((FIXTURES / "dhq_dispatch_handlers.json").read_text())


def test_dispatch_registration_and_login_guards(monkeypatch):
    package = ModuleType("dhq_dispatch_split_test")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    helpers = ModuleType(package.__name__ + ".fleet_helpers")
    helpers.LEGACY_STATION_COLORS = {}
    helpers.DEPARTMENT_TO_STATION = {}
    monkeypatch.setitem(sys.modules, helpers.__name__, helpers)
    db = ModuleType("database")
    db.get_db_cursor = lambda *a, **kw: pytest.fail("Unauthenticated request reached database")
    monkeypatch.setitem(sys.modules, "database", db)
    names = [package.__name__ + "." + n for n in ("fleet_dispatch_routes", "fleet_dispatch_job_routes")]
    try:
        module = importlib.import_module(names[0])
        app = Flask(__name__)
        app.secret_key = "local-test-only"
        login = LoginManager(app)
        login.user_loader(lambda _: None)
        bp = Blueprint("dispatch_split", __name__, url_prefix="/tools/department-hq")
        module.register_dispatch_routes(bp, lambda fn: fn)
        app.register_blueprint(bp)
        expected = set(json.loads((FIXTURES / "dhq_dispatch_handlers.json").read_text()))
        rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith("dispatch_split.")]
        assert {r.endpoint.split(".")[-1] for r in rules} == expected
        assert len(rules) == len(expected)
        # Explicit runtime contract, independent of handler fingerprints.
        prefix = "/tools/department-hq"
        expected_routes = {
            (prefix + "/api/bridge/dispatch-status", "GET"),
            (prefix + "/api/bridge/dispatch-history", "GET"),
            (prefix + "/api/bridge/dispatch-overview", "GET"),
            (prefix + "/api/bridge/jobs", "GET"),
            (prefix + "/api/bridge/jobs/<int:job_id>", "GET"),
            (prefix + "/api/bridge/jobs/<int:job_id>/resume", "POST"),
            (prefix + "/api/bridge/jobs/<int:job_id>/delegate", "POST"),
            (prefix + "/api/dispatch/cross-station-analytics", "GET"),
            (prefix + "/api/dispatch/reassignment-recommendations", "GET"),
        }
        assert {(r.rule, method) for r in rules for method in r.methods - {"HEAD", "OPTIONS"}} == expected_routes
        for rule in rules:
            path = rule.rule.replace("<int:job_id>", "1")
            method = next(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
            assert app.test_client().open(path, method=method).status_code == 401, (method, path)
    finally:
        for name in names:
            sys.modules.pop(name, None)


def test_job_registry_metadata_order_and_lookup_api(monkeypatch):
    package = ModuleType("dhq_registry_split_test")
    package.__path__ = [str(ROOT / "services")]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    names = [package.__name__ + ".job_registry"] + [
        package.__name__ + "._job_registry_entries_" + str(i) for i in (1, 2, 3)
    ]
    try:
        module = importlib.import_module(names[0])
        registry = module.JOB_REGISTRY
        snapshot = json.loads((FIXTURES / "dhq_job_registry_snapshot.json").read_text())
        assert list(registry) == snapshot["keys"]
        assert (
            list(hashlib.sha256(json.dumps(registry, sort_keys=True, ensure_ascii=False).encode()).digest())
            == snapshot["metadata_digest"]
        )
        assert len(registry) == 137
        # Review questioned this entry's description; it remains byte-identical.
        assert registry["social_video_auto_approve"]["description"] == ("Auto-approve generated social video content")
        assert module.get_jobs_by_department() is registry
        for job, meta in registry.items():
            assert module.get_job_info(job) is meta
            assert module.get_department_for_job(job) == meta["department"]
            assert job in module.get_jobs_by_department(meta["department"])
            if job.startswith("agent_") and job[6:] not in registry:
                assert module.get_department_for_job(job[6:]) == meta["department"]
        assert sum(d["count"] for d in module.get_all_departments().values()) == len(registry)
        assert module.get_unregistered_jobs([*registry, "unknown-job"]) == ["unknown-job"]
        assert module.get_department_for_job("unknown-job") == "UNKNOWN"
        assert module.get_job_info("unknown-job") is None
        for name in ("job_registry", "_job_registry_entries_1", "_job_registry_entries_2", "_job_registry_entries_3"):
            assert (ROOT / "services" / (name + ".py")).read_text().count("\n") + 1 <= 600
    finally:
        for name in names:
            sys.modules.pop(name, None)
