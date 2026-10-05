"""Behavior and closure checks for Department HQ repair follow-ups."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from flask import Flask, Blueprint
from flask_login import LoginManager, login_required
from services.code_issue_reconciler import finding_still_reproduces
from tools.department_hq.services.orchestration_engine import OrchestrationEngine
from tools.department_hq import fleet_node_routes


@pytest.mark.parametrize(
    "message,source,expected",
    [
        (
            "WRONG_SUBMODULE_IMPORT import from 'old.dispatcher' does not resolve in the runtime",
            "from new.dispatcher import dispatch",
            False,
        ),
        (
            "WRONG_SUBMODULE_IMPORT import from 'old.dispatcher' does not resolve in the runtime",
            "from old.dispatcher import dispatch",
            None,
        ),
        ("WRONG_ROOT_IMPORT import 'old' does not resolve in the runtime", "import old", None),
        (
            "WRONG_ROOT_IMPORT import 'old' does not resolve in the runtime",
            "# import old\nfrom .old import dispatch",
            False,
        ),
        ("MISSING_SYMBOL 'helper' is not exported by 'old'", "from old import other", False),
        ("MISSING_SYMBOL 'helper' is not exported by 'old'", "from old import helper", None),
        ("MISSING_SYMBOL 'helper' is not exported by 'old'", "def broken(", None),
    ],
)
def test_removed_imports_close_but_runtime_ambiguity_is_preserved(message, source, expected):
    assert finding_still_reproduces(message, source) is expected


def test_fallback_uses_governed_dispatch_and_keeps_user_context(monkeypatch):
    calls = []
    result = SimpleNamespace(success=True, response="reply", model_used="served", error=None)

    def request_work(**kwargs):
        calls.append(kwargs)
        return result

    dispatcher = SimpleNamespace(request_work=request_work)
    monkeypatch.setitem(
        sys.modules,
        "tools.department_hq.services.department_dispatcher",
        SimpleNamespace(get_dispatcher=lambda: dispatcher),
    )
    engine = OrchestrationEngine.__new__(OrchestrationEngine)
    engine._load_conversation_history = lambda *args: [{"role": "user", "content": "earlier"}]
    context = {"project_id": 7}
    assert engine._execute_ollama("hello", "requested", 42, "session", True, context) == ("reply", "served")
    assert calls[0]["user_id"] == 42
    assert calls[0]["local_only"] is True
    assert calls[0]["context"]["conversation_history"][0]["content"] == "earlier"
    assert "concise" in calls[0]["system_prompt"]
    assert context == {"project_id": 7}
    result.success = False
    result.error = "welfare blocked"
    with pytest.raises(RuntimeError, match="welfare blocked"):
        engine._execute_ollama("hello", "requested", 42, "session", False, context)


def test_station_command_uses_existing_dispatcher(monkeypatch):
    calls = []

    def request_work(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    monkeypatch.setitem(
        sys.modules,
        "tools.department_hq.services.department_dispatcher",
        SimpleNamespace(get_dispatcher=lambda: SimpleNamespace(request_work=request_work)),
    )

    class Cursor:
        def execute(self, *args):
            pass

        def fetchone(self):
            return {
                "capability": "code",
                "description": "description",
                "command_name": "Review",
                "station_code": "ENGINEERING",
            }

    @contextmanager
    def db(*args, **kwargs):
        yield None, Cursor()

    monkeypatch.setattr(fleet_node_routes, "get_db_cursor", db)
    app = Flask("station-test")
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    LoginManager(app)
    bp = Blueprint("station-test", __name__)
    fleet_node_routes.register_node_routes(bp, login_required, lambda fn: fn)
    app.register_blueprint(bp)
    response = app.test_client().post("/api/station-commands/execute", json={"command_id": 1, "prompt": "test"})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert calls == [{"capability": "code", "prompt": "test", "module_id": "station_command"}]


def test_mechanical_findings_no_longer_reproduce():
    root = Path(__file__).resolve().parents[1] / "tools/department_hq"
    cases = [
        ("creed_routes.py", "PYFLAKES local variable 'fatal_error' is assigned to but never used"),
        ("work_routes.py", "PYFLAKES local variable 'score_map' is assigned to but never used"),
        ("jobs.py", "PYFLAKES local variable '_run_cluster_orchestration_worker_fn' is assigned to but never used"),
        ("fleet_node_routes.py", "PYFLAKES local variable 'ps1_path' is assigned to but never used"),
        (
            "services/orchestration_engine.py",
            "PYFLAKES local variable 'capabilities_json' is assigned to but never used",
        ),
    ]
    for path, message in cases:
        assert finding_still_reproduces(message, (root / path).read_text()) is False, path


@pytest.mark.parametrize("helper", ["_load_agent_skills", "_load_agent_welfare"])
def test_agent_lists_are_bound_parameters(monkeypatch, helper):
    from tools.department_hq import creed_routes

    calls = []

    class Cursor:
        def execute(self, query, params):
            calls.append((query, params))

        def fetchall(self):
            return []

    @contextmanager
    def db(*args, **kwargs):
        yield None, Cursor()

    monkeypatch.setattr(creed_routes, "get_db_cursor", db)
    assert getattr(creed_routes, helper)([]) == {}
    assert calls == []
    ids = [1, 3]
    assert getattr(creed_routes, helper)(ids) == {}
    assert calls[0][1] == (ids,)
    assert "ANY(%s)" in calls[0][0]
    assert "IN (1,3)" not in calls[0][0]
