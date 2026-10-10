"""Host worker ownership tests; never invoke Docker, inference, or production writes."""

import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock
import uuid

import pytest


@pytest.fixture
def worker():
    path = Path(__file__).resolve().parents[2] / "scripts/agents/codex-delegation-worker.py"
    spec = importlib.util.spec_from_file_location("host_codex_worker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_claim_is_durable_before_returning_task(worker, monkeypatch):
    sql = Mock(return_value="41|7|reason with | delimiter")
    monkeypatch.setattr(worker, "psql", sql)
    task = worker.claim_one()
    assert uuid.UUID(task["attempt_id"])
    assert task["reason"] == "reason with | delimiter"
    query = sql.call_args.args[0]
    assert "'codex_worker_attempt'" in query
    assert "lease_expires_at" in query
    assert "FOR UPDATE SKIP LOCKED" in query
    assert "AND NOT (coalesce(metadata,'{}'::jsonb) ? 'codex_worker_attempt')" in query
    identity = worker.worker_identity()
    assert identity["pid"] > 0 and identity["boot_id"] and identity["process_start"]
    assert identity["stop_confirmed"] is False


@pytest.mark.parametrize("response,expected", [("41", True), ("", False)])
def test_status_write_requires_matching_attempt_and_in_progress(worker, monkeypatch, response, expected):
    sql = Mock(return_value=response)
    monkeypatch.setattr(worker, "psql", sql)
    attempt = str(uuid.uuid4())
    assert worker.set_status(41, "blocked", attempt_id=attempt) is expected
    query = sql.call_args.args[0]
    assert "AND status='in_progress'" in query
    assert f"metadata->'codex_worker_attempt'->>'id'='{attempt}'" in query
    assert "RETURNING id" in query


def test_metadata_cannot_inject_sql_or_assert_stop(worker, monkeypatch):
    sql = Mock()
    monkeypatch.setattr(worker, "psql", sql)
    attempt = str(uuid.uuid4())
    for extra in [
        {"stop_confirmed": True},
        {"codex_branch": "codex/x'; DELETE"},
        {"codex_pr": True},
    ]:
        with pytest.raises(ValueError):
            worker.set_status(41, "blocked", extra, attempt_id=attempt)
    with pytest.raises(ValueError):
        worker.set_status(41, "blocked", attempt_id="'; DELETE")
    sql.assert_not_called()
    expression = worker._json_sql({"text": "O'Reilly\\newline\n"})
    encoded = expression.split("decode('")[1].split("'")[0]
    assert json.loads(bytes.fromhex(encoded)) == {"text": "O'Reilly\\newline\n"}


def test_only_dry_run_can_release_claim(worker, monkeypatch):
    sql = Mock(return_value="41")
    monkeypatch.setattr(worker, "psql", sql)
    attempt = str(uuid.uuid4())
    with pytest.raises(ValueError):
        worker.set_status(41, "deferred", attempt_id=attempt)
    assert worker.set_status(41, "deferred", attempt_id=attempt, outcome="dry_run")
    assert "metadata-'codex_worker_attempt'" in sql.call_args.args[0]


@pytest.fixture
def running(worker, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "LOCK", str(tmp_path / "worker.lock"))
    monkeypatch.setattr(worker.sys, "argv", ["worker"])
    monkeypatch.setattr(
        worker,
        "claim_one",
        lambda: {
            "id": 41,
            "project_id": "",
            "reason": "repair",
            "attempt_id": str(uuid.uuid4()),
        },
    )
    monkeypatch.setattr(worker, "compose_prompt", lambda task: "repair")
    monkeypatch.setattr(worker, "owns_attempt", Mock(return_value=True))
    monkeypatch.setattr(worker, "set_status", Mock(return_value=True))
    monkeypatch.setattr(worker, "fallback_pr", Mock(return_value=9))
    monkeypatch.setattr(worker, "queue_promote", Mock())
    return worker


def test_timeout_preserves_partial_pr_without_fallback_or_promotion(running, monkeypatch):
    monkeypatch.setattr(
        running.subprocess,
        "run",
        Mock(
            side_effect=subprocess.TimeoutExpired(
                "runner",
                1,
                output=b"codex/repair\nPR #9 created: url",
                stderr=b"partial",
            )
        ),
    )
    assert running.main() == 0
    args, kwargs = running.set_status.call_args
    assert args == (41, "blocked", {"codex_branch": "codex/repair", "codex_pr": 9})
    assert kwargs["outcome"] == "runner_timeout_stop_unconfirmed"
    running.fallback_pr.assert_not_called()
    running.queue_promote.assert_not_called()


def test_lost_claim_never_starts_runner(running, monkeypatch):
    running.owns_attempt.return_value = False
    run = Mock()
    monkeypatch.setattr(running.subprocess, "run", run)
    assert running.main() == 0
    run.assert_not_called()


def test_stale_completion_cannot_promote(running, monkeypatch):
    monkeypatch.setattr(
        running.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess("runner", 0, "codex/repair\nPR #9 created: url", "")),
    )
    running.set_status.return_value = False
    assert running.main() == 0
    running.queue_promote.assert_not_called()


def test_branch_retained_when_pr_fallback_fails(running, monkeypatch):
    monkeypatch.setattr(
        running.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess("runner", 1, "codex/repair", "")),
    )
    running.fallback_pr.return_value = None
    assert running.main() == 0
    assert running.set_status.call_args.args == (
        41,
        "blocked",
        {"codex_branch": "codex/repair"},
    )


def test_start_failure_remains_unconfirmed(running, monkeypatch):
    monkeypatch.setattr(running.subprocess, "run", Mock(side_effect=OSError("missing runner")))
    with pytest.raises(OSError):
        running.main()
    assert running.set_status.call_args.kwargs["outcome"] == "runner_start_failed"
    running.queue_promote.assert_not_called()
