"""#4344 — telemetry_writer.log_marker integration tests.

Locks the canonical non-LLM MARKER shape so a future edit can't silently
reintroduce the convention drift the Token Economy BY MODEL view
(code_health_routes.py, PR #1816) depends on: marker rows MUST be
``worker_type NULL`` + sentinel ``model_used`` + ``tokens_used=0`` so they stay
excluded from the "real LLM" per-model breakdown.

Integration tests — they need a live DB. Run from platform_v2/:
    docker exec archie_platform python3 -m pytest services/tests/test_telemetry_writer.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor

from services.telemetry_writer import MARKER_MODEL_SENTINEL, log_marker

_NAME = "_TestTelemetryMarkerAgent"
_DEPT = "Analytics & Intelligence"  # real dept — agents.department has a CHECK constraint
_CAP = "_test_marker_orchestration"


def _purge(cur):
    cur.execute("DELETE FROM task_execution_log WHERE capability = %s OR agent_name = %s", (_CAP, _NAME))
    cur.execute("DELETE FROM agents WHERE name = %s", (_NAME,))


@pytest.fixture
def marker_agent():
    """An active AI agent so log_marker's name->id COALESCE resolves; cleans up after."""
    agent_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        _purge(cur)  # clear leftovers from a crashed prior run
        cur.execute(
            """
            INSERT INTO agents (name, display_name, department, floor, status, shift_state, worker_type, model)
            VALUES (%s, 'Test Marker Agent', %s, 'SERVICES', 'active', 'active', 'ai', 'test-model')
            RETURNING id
            """,
            (_NAME, _DEPT),
        )
        agent_id = cur.fetchone()["id"]
    yield agent_id
    with get_db_cursor(commit=True) as (conn, cur):
        _purge(cur)


def _fetch_latest(cur):
    cur.execute(
        "SELECT agent_id, agent_name, worker_type, model_used, module_source, tokens_used "
        "FROM task_execution_log WHERE capability = %s ORDER BY id DESC LIMIT 1",
        (_CAP,),
    )
    return cur.fetchone()


def test_log_marker_canonical_shape(marker_agent):
    """Defaults write the canonical marker: NULL worker_type, sentinel model, 0 tokens,
    'agent_loop' module_source, and agent_id resolved from agent_name."""
    assert log_marker(capability=_CAP, agent_name=_NAME) is True
    with get_db_cursor() as (conn, cur):
        row = _fetch_latest(cur)
    assert row is not None
    assert row["worker_type"] is None  # NULL == marker convention (BY MODEL excludes via IS NOT NULL)
    assert row["model_used"] == MARKER_MODEL_SENTINEL  # 'bridge-managed'
    assert row["tokens_used"] == 0
    assert row["module_source"] == "agent_loop"  # default matches the table column DEFAULT
    assert row["agent_id"] == marker_agent  # resolved from agent_name via COALESCE subquery


def test_log_marker_explicit_overrides(marker_agent):
    """Explicit module_source / node_used_id are honored; worker_type stays NULL."""
    assert log_marker(capability=_CAP, agent_name=_NAME, module_source="wtf_dhq_llm", node_used_id=68) is True
    with get_db_cursor() as (conn, cur):
        row = _fetch_latest(cur)
    assert row["module_source"] == "wtf_dhq_llm"
    assert row["worker_type"] is None
    assert row["model_used"] == MARKER_MODEL_SENTINEL


def test_marker_excluded_by_by_model_filter(marker_agent):
    """The whole point of #4344: a marker row is invisible to the BY MODEL 'real LLM'
    view. Uses the exact predicate from code_health_routes.py — the marker must be
    dropped on BOTH guards (worker_type IS NOT NULL AND the model sentinel list)."""
    assert log_marker(capability=_CAP, agent_name=_NAME) is True
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS n FROM task_execution_log "
            "WHERE capability = %s "
            "  AND worker_type IS NOT NULL "
            "  AND model_used NOT IN ('internal','batch','bridge-managed','browser') "
            "  AND model_used NOT ILIKE '%%embed%%'",
            (_CAP,),
        )
        assert cur.fetchone()["n"] == 0
