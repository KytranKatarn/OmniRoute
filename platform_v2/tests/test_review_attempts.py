from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from services import review_attempts as attempts
from services import model_dispatch_service as worker


@pytest.fixture
def db(monkeypatch):
    cursor = Mock()
    cursor.rowcount = 1
    cursor.fetchone.side_effect = [{"acquired": True}, None]
    connection = Mock()

    @contextmanager
    def database(**kwargs):
        yield connection, cursor

    monkeypatch.setattr(attempts, "get_db_cursor", database)
    return connection, cursor


def test_owner_lock_held_for_whole_attempt_and_released_on_failure(db):
    conn, cur = db
    with pytest.raises(RuntimeError, match="failure"):
        with attempts.owned_attempt("o/r", 1, "a" * 40):
            assert attempts.CURRENT.get()["head_sha"] == "a" * 40
            assert not any("pg_advisory_unlock" in c.args[0] for c in cur.execute.call_args_list)
            raise RuntimeError("failure")
    assert attempts.CURRENT.get() is None
    assert "pg_advisory_unlock" in cur.execute.call_args_list[-1].args[0]
    assert conn.rollback.called


def test_competing_owner_cannot_enter(db):
    _, cur = db
    cur.fetchone.side_effect = [{"acquired": False}]
    with pytest.raises(attempts.ReviewBusy):
        with attempts.owned_attempt("o/r", 1, "a" * 40):
            pytest.fail("duplicate review entered")
    assert cur.execute.call_count == 1


def test_probe_failure_releases_acquired_session_lock(db):
    _, cur = db
    cur.fetchone.side_effect = [{"acquired": True}, RuntimeError("probe failure")]
    with pytest.raises(RuntimeError, match="probe failure"):
        with attempts.owned_attempt("o/r", 1, "a" * 40):
            pytest.fail("failed probe entered review")
    assert "pg_advisory_unlock" in cur.execute.call_args_list[-1].args[0]


def test_outstanding_dispatch_blocks_retry_even_after_old_process_exits(db):
    _, cur = db
    cur.fetchone.side_effect = [{"acquired": True}, {"id": 42}]
    with pytest.raises(attempts.ReviewBusy, match="dispatch"):
        with attempts.owned_attempt("o/r", 1, "a" * 40):
            pytest.fail("orphaned dispatch duplicated")
    assert "pg_advisory_unlock" in cur.execute.call_args_list[-1].args[0]


def test_cancelled_owner_cannot_publish_or_reset_new_attempt(db):
    _, cur = db
    token = attempts.CURRENT.set({"id": "old", "head_sha": "a" * 40})
    try:
        cur.rowcount = 0
        with pytest.raises(attempts.ReviewCancelled):
            attempts.guarded_cursor(cur).execute(
                "UPDATE pr_reviews SET ai_summary=%s WHERE pr_number=%s", ("verdict", 1)
            )
        sql, values = cur.execute.call_args.args
        assert "review_attempt_id" in sql and "head_sha" in sql and "review_cancelled" in sql
        assert values[-2:] == ("old", "a" * 40)
    finally:
        attempts.CURRENT.reset(token)


def test_legacy_writer_cannot_overwrite_owned_attempt(db):
    _, cur = db
    attempts.guarded_cursor(cur).execute("UPDATE pr_reviews SET review_status=%s WHERE pr_number=%s", ("pending", 1))
    assert "? 'review_attempt_id'" in cur.execute.call_args.args[0]


def test_cancel_expires_queued_jobs_but_does_not_falsely_stop_running_jobs(db):
    _, cur = db
    cur.fetchone.side_effect = [{"attempt_id": "old"}]
    assert attempts.cancel_review(1, "o/r", retry=True)
    first, second = cur.execute.call_args_list
    assert first.args[1][0] == "pending"
    assert "'review_cancelled',true" in first.args[0]
    assert "status='queued'" in second.args[0]
    assert "status='running'" not in second.args[0]


def test_no_raw_pass_or_legacy_callback_can_publish_whole_review():
    for data in [{"pr_number": 1, "repo": "o/r"}, {"pr_number": 1, "attempt_id": "old", "pass_only": True}]:
        cur = Mock()
        cur.fetchone.return_value = {"callback_type": "pr_review_result", "callback_data": data}
        worker._handle_callback(cur, 42, "VERDICT: APPROVE")
        assert cur.execute.call_count == 1  # Read callback only; no verdict UPDATE.


def test_queue_wait_consumes_same_id_and_cancellation_prevents_polling(db, monkeypatch):
    _, cur = db
    cur.fetchone.side_effect = [True]
    token = attempts.CURRENT.set({"id": "owned", "repo": "o/r", "number": 1, "head_sha": "a" * 40})
    monkeypatch.setattr(attempts, "assert_active", Mock())
    poll = Mock(return_value={"status": "completed", "result_response": "answer"})
    monkeypatch.setattr(worker, "get_pending_queue_result", poll)
    try:
        assert attempts.await_existing_queue(42) == "answer"
        poll.assert_called_once_with(42)
        cur.fetchone.side_effect = [True]
        monkeypatch.setattr(attempts, "assert_active", Mock(side_effect=attempts.ReviewCancelled("cancelled")))
        with pytest.raises(attempts.ReviewCancelled):
            attempts.await_existing_queue(42)
        assert poll.call_count == 1
    finally:
        attempts.CURRENT.reset(token)


def test_lock_identity_includes_repo_and_pr_and_is_stable():
    assert attempts.lock_key("o/r", 1) == attempts.lock_key("o/r", 1)
    assert len({attempts.lock_key("o/r", 1), attempts.lock_key("o/other", 1), attempts.lock_key("o/r", 2)}) == 3


def test_cancel_between_enqueue_and_link_expires_new_queued_job(db):
    _, cur = db
    cur.fetchone.side_effect = [None]
    token = attempts.CURRENT.set({"id": "owned", "repo": "o/r", "number": 1, "head_sha": "a" * 40})
    try:
        with pytest.raises(attempts.ReviewCancelled, match="before queue link"):
            attempts.await_existing_queue(42)
        assert "callback_data" in cur.execute.call_args_list[1].args[0]
        assert "status='expired'" in cur.execute.call_args_list[2].args[0]
        assert "status='queued'" in cur.execute.call_args_list[2].args[0]
    finally:
        attempts.CURRENT.reset(token)
