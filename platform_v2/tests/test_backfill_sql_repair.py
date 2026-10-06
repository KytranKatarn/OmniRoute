"""Exercise the real nested backfill worker without registering live jobs."""

import ast
import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

import database
from services import fleet_dispatch_profile as profile
from services.code_health_checks import sql_finding_present


SOURCE_PATH = Path(__file__).resolve().parents[1] / "tools/department_hq/jobs.py"


def worker():
    tree = ast.parse(SOURCE_PATH.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_dispatch_backfill")
    namespace = {"logger": logging.getLogger("isolated-backfill")}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<backfill-copy>", "exec"), namespace)
    return namespace[node.name]


@pytest.fixture
def backfill(monkeypatch):
    queries = []
    state = {"items": []}
    dispatch = Mock(return_value=SimpleNamespace(success=True, response="done", error=""))
    module = ModuleType("tools.department_hq.services.department_dispatcher")
    module.dispatch = dispatch
    monkeypatch.setitem(sys.modules, module.__name__, module)
    coordinator = ModuleType("services.department_coordinator")
    coordinator.CAPABILITY_DEPARTMENT_MAP = {"news_cap": profile.NEWS_DEPARTMENT, "code_review": "Engineering"}
    monkeypatch.setitem(sys.modules, coordinator.__name__, coordinator)
    telemetry = ModuleType("services.telemetry_writer")
    telemetry.log_marker = Mock()
    monkeypatch.setitem(sys.modules, telemetry.__name__, telemetry)

    class Cursor:
        def execute(self, query, params):
            queries.append((query, params))

        def fetchall(self):
            return state["items"]

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    monkeypatch.setattr(database, "get_db_cursor", db)
    return worker(), queries, state, dispatch


@pytest.mark.parametrize("mode", ["auto", "news", "platform", "invalid"])
def test_profile_queries_preserve_filters_parameters_and_ordering(backfill, monkeypatch, mode):
    run, queries, _, dispatch = backfill
    monkeypatch.setattr(profile, "get_dispatch_mode", lambda: mode)
    run()
    assert len(queries) == 1
    query, params = queries[0]
    assert "status = 'queued'" in query
    assert "INTERVAL '10 minutes'" in query and "INTERVAL '2 hours'" in query
    assert "priority DESC, queued_at ASC" in query and "LIMIT 5" in query
    if mode in ("news", "platform"):
        assert params == [["news_cap"], ["%%%s%%" % k for k in profile.NEWS_MODULE_KEYWORDS], mode == "news"]
        assert "capability = ANY(%s)" in query
        assert "LIKE ANY(%s)" in query
        assert "THEN 1 ELSE 0 END) DESC" in query
    else:
        assert params == []
        assert "CASE" not in query
    dispatch.assert_not_called()


def test_profile_failure_falls_back_to_unbiased_queue(backfill, monkeypatch):
    run, queries, _, _ = backfill
    monkeypatch.setattr(profile, "get_dispatch_mode", Mock(side_effect=RuntimeError("unavailable")))
    run()
    assert len(queries) == 1
    assert queries[0][1] == []
    assert "ORDER BY priority DESC, queued_at ASC" in queries[0][0]


def test_successful_backfill_dispatches_and_marks_only_selected_queued_item(backfill, monkeypatch):
    run, queries, state, dispatch = backfill
    monkeypatch.setattr(profile, "get_dispatch_mode", lambda: "platform")
    state["items"] = [
        {
            "id": 42,
            "capability": "code_review",
            "prompt": "fix",
            "system_prompt": "system",
            "json_mode": True,
            "module_id": "department_hq",
            "source_product": "archie_platform",
            "priority": 7,
        }
    ]
    run()
    dispatch.assert_called_once_with(
        capability="code_review",
        prompt="fix",
        system_prompt="system",
        json_mode=True,
        module_id="department_hq",
        priority="high",
    )
    assert len(queries) == 2
    assert "WHERE id = %s AND status = 'queued'" in queries[1][0]
    assert queries[1][1] == ("done", 42)


def test_failed_dispatch_does_not_mark_item_completed(backfill, monkeypatch):
    run, queries, state, dispatch = backfill
    monkeypatch.setattr(profile, "get_dispatch_mode", lambda: "auto")
    state["items"] = [
        {
            "id": 42,
            "capability": "code_review",
            "prompt": "fix",
            "system_prompt": None,
            "json_mode": False,
            "module_id": None,
        }
    ]
    dispatch.return_value = SimpleNamespace(success=False, error="resting")
    run()
    assert len(queries) == 1


def test_backfill_source_proves_literal_sql_without_hiding_full_file_uncertainty():
    tree = ast.parse(SOURCE_PATH.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_dispatch_backfill")
    assert sql_finding_present(ast.unparse(node)) is False
    assert sql_finding_present(SOURCE_PATH.read_text()) is None
