"""Unit tests for the S6-P1-8b sidecar idempotency plumbing.

POST /task accepts idempotency_key + post_metadata, stores them on the task, and threads
them into _log_task_to_db (browser_task_log columns from migration 441). The DB write is
best-effort (no DB in tests); we assert the in-memory plumbing + signatures.

Run from archie-browser/:
    python3 -m pytest tests/test_idempotency.py -v
"""

import os
import sys
import inspect

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")

import app as appmod  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_modules():
    # create_app(testing=True) injects MagicMock skill_runner/session_manager into
    # sys.modules; evict before+after so other suites get the real modules.
    for m in ("skill_runner", "session_manager"):
        sys.modules.pop(m, None)
    yield
    for m in ("skill_runner", "session_manager"):
        sys.modules.pop(m, None)


def test_post_task_stores_and_returns_idempotency_key():
    application = appmod.create_app(testing=True)
    client = application.test_client()
    r = client.post(
        "/task",
        json={
            "agent_id": 342,
            "skill": "linkedin_post",
            "params": {"content": "x"},
            "wait": True,  # run synchronously so the task settles in-process
            "idempotency_key": "abc123",
            "post_metadata": {"scheduled_post_id": 7, "post_type": "personal"},
        },
    )
    assert r.status_code == 200
    task_id = r.get_json()["task_id"]
    state = client.get(f"/task/{task_id}").get_json()
    assert state["idempotency_key"] == "abc123"
    assert state["task_id"] == task_id


def test_post_task_without_key_is_backward_compatible():
    application = appmod.create_app(testing=True)
    client = application.test_client()
    r = client.post("/task", json={"agent_id": 342, "skill": "linkedin_feed", "params": {}, "wait": True})
    assert r.status_code == 200
    state = client.get(f"/task/{r.get_json()['task_id']}").get_json()
    assert state.get("idempotency_key") is None


def test_log_task_to_db_accepts_idempotency_args():
    # The signature must accept the new kwargs (the DB write itself is best-effort).
    sig = inspect.signature(appmod._log_task_to_db)
    assert "idempotency_key" in sig.parameters
    assert "post_metadata" in sig.parameters
    # _execute_task must thread them through too.
    esig = inspect.signature(appmod._execute_task)
    assert "idempotency_key" in esig.parameters
    assert "post_metadata" in esig.parameters
