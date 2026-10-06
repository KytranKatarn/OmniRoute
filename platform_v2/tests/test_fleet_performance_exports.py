"""Optional performance helpers stay exported while removing false unused-import reports."""

import ast
from pathlib import Path
import sys
import types

import pytest
from services.code_issue_reconciler import finding_still_reproduces


FILES = ("fleet_helpers.py", "fleet_dashboard_routes.py")
EXPORTS = ("get_agent_performance", "update_agent_performance", "get_top_performers", "log_agent_action")


def export_block(name):
    source = (Path(__file__).parents[1] / "tools/department_hq" / name).read_text()
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Try) and "_HAS_PERFORMANCE_TRACKER" in ast.unparse(n))
    return compile(ast.Module(body=[node], type_ignores=[]), name, "exec"), source


@pytest.mark.parametrize("name", FILES)
def test_reexports_preserve_function_identity_and_clear_lint(monkeypatch, name):
    tracker = types.ModuleType("ai_bridge.agent_performance_tracker")
    for export in EXPORTS:
        setattr(tracker, export, lambda: None)
    package = types.ModuleType("ai_bridge")
    package.agent_performance_tracker = tracker
    monkeypatch.setitem(sys.modules, "ai_bridge", package)
    monkeypatch.setitem(sys.modules, tracker.__name__, tracker)
    code, source = export_block(name)
    namespace = {}
    exec(code, namespace)
    assert namespace["_HAS_PERFORMANCE_TRACKER"] is True
    for export in EXPORTS:
        assert namespace[export] is getattr(tracker, export)
    report = "PYFLAKES 'ai_bridge.agent_performance_tracker.get_agent_performance' imported but unused"
    assert finding_still_reproduces(report, source) is False


@pytest.mark.parametrize("name", FILES)
def test_incomplete_optional_tracker_does_not_break_import(monkeypatch, name):
    package = types.ModuleType("ai_bridge")
    package.agent_performance_tracker = types.ModuleType("ai_bridge.agent_performance_tracker")
    monkeypatch.setitem(sys.modules, "ai_bridge", package)
    code, _ = export_block(name)
    namespace = {}
    exec(code, namespace)
    assert namespace["_HAS_PERFORMANCE_TRACKER"] is False
