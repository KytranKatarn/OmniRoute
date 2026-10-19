"""The warm-up demand count is REAL model usage (task_execution_log.model_used), not agent activity (#7348)."""

from __future__ import annotations

import ast
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "app.py").read_text()


def _fn(name):
    tree = ast.parse(APP)
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(APP, node)


def test_demand_is_counted_by_model_used_not_by_agent_join():
    src = _fn("_get_agent_models")
    assert "model_used" in src
    assert "tel.agent_name = a.name" not in src  # the old join: every dispatch of every agent on the model


def test_latest_tag_is_normalised_on_both_sides():
    """arctic-embed-cpu is assigned as 'arctic-embed-cpu:latest' but logged as 'arctic-embed-cpu'; without
    normalisation its real usage read 0 and the embedding model would be dropped from the warm-up."""
    src = _fn("_get_agent_models")
    assert "replace(model_used, ':latest', '')" in src
    assert "replace(a.model, ':latest', '')" in src


def test_window_and_columns_the_filter_reads_are_unchanged():
    src = _fn("_get_agent_models")
    assert "INTERVAL '7 days'" in src
    for col in ("dispatch_count", "agent_count"):  # services/warmup_demand.filter_by_demand reads these
        assert col in src
