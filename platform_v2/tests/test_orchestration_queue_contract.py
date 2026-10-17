"""Real SQL and Flask fixture; no production DB, model calls or scheduler starts."""

import ast
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from flask import Blueprint, Flask
import pytest

from services import model_dispatch_service as dispatch_queue
from services.cluster_orchestration_service import compute_overflow_score
from tools.department_hq import fleet_orchestration_routes as routes


@pytest.fixture
def queue(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE dispatch_pending_queue (capability TEXT, status TEXT)")
    conn.executemany(
        "INSERT INTO dispatch_pending_queue VALUES (?, ?)",
        [
            ("code_review", "queued"),
            ("code_review", "queued"),
            ("translate", "queued"),
            ("code_review", "running"),
            ("code_review", "done"),
            ("translate", "expired"),
        ],
    )

    @contextmanager
    def queue_db(**kwargs):
        yield conn, conn.cursor()

    monkeypatch.setattr(dispatch_queue, "get_db_cursor", queue_db)
    yield conn
    conn.close()


def test_depths_count_only_actual_waiting_rows(queue):
    assert dispatch_queue.get_queued_capability_depths() == {"code_review": 2, "translate": 1}
    queue.execute("DELETE FROM dispatch_pending_queue WHERE status='queued'")
    assert dispatch_queue.get_queued_capability_depths() == {}


def test_status_api_reports_real_depths_and_pause_state(queue, monkeypatch):
    cur = Mock()
    cur.fetchall.return_value = []
    cur.fetchone.return_value = {"overflow_paused": True}

    @contextmanager
    def status_db(**kwargs):
        yield Mock(), cur

    monkeypatch.setattr(routes, "get_db_cursor", status_db)
    app = Flask(__name__)
    bp = Blueprint("orchestration_fixture", __name__)
    routes.register_orchestration_routes(bp, lambda fn: fn)
    app.register_blueprint(bp)
    response = app.test_client().get("/api/orchestration/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["global_paused"] is True
    assert data["queues"] == [{"capability": "code_review", "depth": 2}, {"capability": "translate", "depth": 1}]


def test_scoring_worker_uses_same_depths_and_queue_pressure(queue):
    """Execute the worker's actual demand-read AST, without starting its scheduler."""
    tree = ast.parse((Path(routes.__file__).parent / "jobs.py").read_text())
    worker = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_cluster_orchestration_worker"
    )
    imports = [
        n
        for n in ast.walk(worker)
        if isinstance(n, ast.ImportFrom)
        and n.module == "services.model_dispatch_service"
        and any(alias.name == "get_queued_capability_depths" for alias in n.names)
    ]
    reads = [
        n
        for n in ast.walk(worker)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "queue_depths" for t in n.targets)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "get_queued_capability_depths"
    ]
    assert len(imports) == len(reads) == 1, "scorer must share the queue owner's demand query"
    namespace = {}
    code = ast.Module(body=imports + reads, type_ignores=[])
    exec(compile(ast.fix_missing_locations(code), "<worker-demand-read>", "exec"), namespace)
    depths = namespace["queue_depths"]
    assert depths == dispatch_queue.get_queued_capability_depths() == {"code_review": 2, "translate": 1}
    cfg = {
        "idle_threshold_minutes": 1,
        "utilization_threshold_pct": 50,
        "queue_pressure_threshold": 2,
        "idle_weight": 0,
        "utilization_weight": 0,
        "queue_pressure_weight": 1,
    }
    assert compute_overflow_score(0, 0, depths["code_review"], cfg) == 1
    assert compute_overflow_score(0, 0, 0, cfg) == 0


def test_queue_read_failure_is_not_reported_as_idle(queue, monkeypatch):
    def fail():
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(dispatch_queue, "get_queued_capability_depths", fail)
    cur = Mock()
    cur.fetchall.return_value = []

    @contextmanager
    def status_db(**kwargs):
        yield Mock(), cur

    monkeypatch.setattr(routes, "get_db_cursor", status_db)
    app = Flask(__name__)
    bp = Blueprint("orchestration_failure_fixture", __name__)
    routes.register_orchestration_routes(bp, lambda fn: fn)
    app.register_blueprint(bp)
    response = app.test_client().get("/api/orchestration/status")
    assert response.status_code == 500
    assert "queues" not in response.get_json()
