"""Form inventory uses the text node key belonging to the numeric route ID."""

import ast
from contextlib import contextmanager
import logging
from pathlib import Path
import sqlite3

from flask import Flask, jsonify
import pytest

SOURCE = Path(__file__).parents[1] / "tools/department_hq/fleet_crew_routes.py"


@pytest.mark.parametrize("node_id,expected", [(7, ["model-a"]), (8, ["model-b"]), (999, [])])
def test_form_inventory_is_scoped_to_numeric_node_id(node_id, expected):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE remote_nodes (id INTEGER PRIMARY KEY, node_id TEXT);
        INSERT INTO remote_nodes VALUES (7, 'node-alpha'), (8, 'node-beta');
        CREATE TABLE node_ollama_models (node_id TEXT, model_name TEXT);
        INSERT INTO node_ollama_models VALUES ('node-alpha', 'model-a'), ('node-beta', 'model-b');
        CREATE TABLE model_catalog (model_name TEXT, display_name TEXT, description TEXT,
            tier TEXT, category TEXT, size_gb REAL, parameter_size TEXT, is_active BOOLEAN);
        INSERT INTO model_catalog VALUES ('catalog-a', 'A', '', 'small', 'text', 1, '1b', 1);
        INSERT INTO model_catalog VALUES ('inactive', 'I', '', 'small', 'text', 1, '1b', 0);
    """
    )
    queries = []

    class Cursor:
        def execute(self, sql, params=()):
            queries.append((sql, params))
            self.cursor = conn.execute(sql.replace("%s", "?"), params)

        def fetchall(self):
            return self.cursor.fetchall()

    @contextmanager
    def db():
        yield conn, Cursor()

    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "api_node_agent_form_context")
    node.decorator_list = []
    namespace = {"get_db_cursor": db, "jsonify": jsonify, "logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    try:
        app = Flask(__name__)
        with app.app_context():
            response = app.make_response(namespace["api_node_agent_form_context"](node_id))
            assert response.status_code == 200
            data = response.get_json()
        assert data["installed_models"] == expected
        assert [row["model_name"] for row in data["catalog"]] == ["catalog-a"]
        assert queries[0][1] == (node_id,)
    finally:
        conn.close()
