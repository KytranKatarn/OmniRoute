"""
Tests for code_service.py — session CRUD + event persistence.
Uses unittest.mock.patch (decorator form) to mock get_db_cursor so no live DB is needed.
"""

import sys
import os

import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tools.archie_chat.code_service as code_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db(fetchone_val=None, fetchall_val=None):
    """
    Build a mock context manager that behaves like:
        with get_db_cursor(...) as (conn, cur):
            ...
    """
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_val or {}
    cur.fetchall.return_value = fetchall_val or []
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=(conn, cur))
    cm.__exit__ = MagicMock(return_value=False)
    return cm, cur


# ---------------------------------------------------------------------------
# Test 1: create_session returns the id from RETURNING
# ---------------------------------------------------------------------------


@patch("tools.archie_chat.code_service.get_db_cursor")
def test_create_session_returns_id(mock_db):
    """create_session should INSERT and return the new row's id."""
    cm, cur = _make_mock_db(fetchone_val={"id": 42})
    mock_db.return_value = cm

    result = code_service.create_session(
        title="Test session",
        source="repair_bay",
        tier=1,
        created_by="archie",
    )

    assert result == 42
    sql_called = cur.execute.call_args[0][0].upper()
    assert "INSERT" in sql_called
    assert "CODE_SESSIONS" in sql_called


# ---------------------------------------------------------------------------
# Test 2: get_session returns a plain dict with id and status fields
# ---------------------------------------------------------------------------


@patch("tools.archie_chat.code_service.get_db_cursor")
def test_get_session_returns_dict(mock_db):
    """get_session should SELECT and return a dict with at least id and status."""
    cm, cur = _make_mock_db(
        fetchone_val={"id": 1, "title": "Fix bug", "source": "repair_bay", "status": "active", "tier": 2}
    )
    mock_db.return_value = cm

    result = code_service.get_session(1)

    assert result is not None
    assert result["id"] == 1
    assert result["status"] == "active"


# ---------------------------------------------------------------------------
# Test 3: append_event inserts into code_session_events
# ---------------------------------------------------------------------------


@patch("tools.archie_chat.code_service.get_db_cursor")
def test_append_event_inserts_row(mock_db):
    """append_event should INSERT into code_session_events."""
    cm, cur = _make_mock_db()
    mock_db.return_value = cm

    code_service.append_event(session_id=1, event_type="message", content={"text": "hello"})

    sql = cur.execute.call_args[0][0]
    assert "INSERT INTO code_session_events" in sql


# ---------------------------------------------------------------------------
# Test 4: start_opencode spawns subprocess and stores it in _PROCESSES
# ---------------------------------------------------------------------------


@patch("tools.archie_chat.code_service.subprocess.Popen")
@patch("tools.archie_chat.code_service.get_db_cursor")
def test_start_opencode_stores_pid(mock_db, mock_popen):
    cm, cur = _make_mock_db()
    mock_db.return_value = cm

    proc = MagicMock()
    proc.pid = 1234
    proc.poll.return_value = None
    proc.stdout.__iter__ = MagicMock(return_value=iter([]))
    mock_popen.return_value = proc

    code_service.start_opencode(session_id=99)
    assert code_service._PROCESSES.get(99) is proc
    # cleanup
    code_service._PROCESSES.pop(99, None)
    code_service._SSE_QUEUES.pop(99, None)
    code_service._SESSION_MODE.pop(99, None)


# ---------------------------------------------------------------------------
# Test 5: finalize_session (tier 1) calls subprocess.run with git + gh commands
# ---------------------------------------------------------------------------


@patch("tools.archie_chat.code_service.subprocess.run")
@patch("tools.archie_chat.code_service.get_db_cursor")
def test_finalize_tier1_calls_subprocess_run(mock_db, mock_run):
    # get_session returns a tier-1 session; terminate_session and _auto_pr should call subprocess.run
    session_row = {
        "id": 1,
        "tier": 1,
        "proposal_id": None,
        "title": "Fix bug",
        "status": "active",
        "source": "user",
        "created_by": "user",
        "opencode_pid": None,
        "project_id": None,
        "conversation_id": None,
        "created_at": None,
        "completed_at": None,
        "result_branch": None,
        "result_pr_url": None,
    }
    cm, cur = _make_mock_db(fetchone_val=session_row)
    mock_db.return_value = cm
    mock_run.return_value = MagicMock(stdout="https://github.com/x/y/pull/1\n", returncode=0)

    code_service.finalize_session(1)

    # subprocess.run must have been called (git + gh commands)
    assert mock_run.called
    all_args = [call_args[0][0] for call_args in mock_run.call_args_list]
    # at least one call should include 'gh'
    assert any("gh" in args for args in all_args)
