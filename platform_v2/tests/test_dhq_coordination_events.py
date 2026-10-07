"""Exercise the actual coordination endpoint with dictionary cursor rows."""

import ast
from contextlib import contextmanager
from pathlib import Path
import logging

import pytest
from flask import Flask, jsonify, request

SOURCE = Path(__file__).parents[1] / "tools/department_hq/creed_routes.py"


@pytest.mark.parametrize("outcome", [None, "flagged", "__probe_absent__' OR '1'='1"])
def test_coordination_count_and_bound_filter(outcome):
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "creed_coordination_events")
    node.decorator_list = []
    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchall(self):
            return []

        def fetchone(self):
            assert "COUNT(*) AS total" in calls[-1][0]
            return {"total": 7}

    @contextmanager
    def db(commit=False):
        yield None, Cursor()

    namespace = {"get_db_cursor": db, "request": request, "jsonify": jsonify, "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    app = Flask(__name__)
    params = {"limit": "5", "offset": "2"}
    if outcome is not None:
        params["outcome"] = outcome
    with app.test_request_context(query_string=params):
        response = app.make_response(namespace["creed_coordination_events"]())
        assert response.status_code == 200
        assert response.get_json() == {"success": True, "events": [], "total": 7, "limit": 5, "offset": 2}
    expected = [outcome] if outcome is not None else []
    assert calls[0][1] == expected + [5, 2]
    assert calls[1][1] == expected
    if outcome is not None:
        assert all(outcome not in sql for sql, _ in calls)
