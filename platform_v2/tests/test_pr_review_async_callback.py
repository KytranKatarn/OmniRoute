"""Async F.O.R.G.E. review callback (project #375).

Queued passes retain their dispatch identity. Only the live owner may assemble
and publish a whole-review verdict; raw and legacy callbacks cannot overwrite it.
DB and dispatch boundaries are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---- callback handler: writes the verdict back to pr_reviews -----------------
def test_handle_callback_pr_review_cannot_publish_raw_pass():
    from services.model_dispatch_service import _handle_callback

    cur = MagicMock()
    cur.fetchone.return_value = {
        "callback_type": "pr_review_result",
        "callback_data": {"pr_number": 1527, "repo": "KytranKatarn/archie-platform"},
    }
    _handle_callback(cur, task_id=999, response="SUMMARY ok\nVERDICT: APPROVE")

    updates = [c for c in cur.execute.call_args_list if "UPDATE pr_reviews" in c.args[0]]
    assert updates == [], "raw/legacy callback must not replace the whole-review verdict"


def test_handle_callback_pr_review_skips_when_empty_response():
    from services.model_dispatch_service import _handle_callback

    cur = MagicMock()
    cur.fetchone.return_value = {
        "callback_type": "pr_review_result",
        "callback_data": {"pr_number": 1527, "repo": "r"},
    }
    _handle_callback(cur, task_id=999, response="   ")
    assert not [c for c in cur.execute.call_args_list if "UPDATE pr_reviews" in c.args[0]]


# ---- attach callback + queued dispatch flow ---------------------------------
def test_attach_pr_review_callback_tags_queue_row():
    from tools.repair_bay.services import pr_diff_analyzer as pda

    cur = MagicMock()
    cm = MagicMock()
    cm.__enter__ = lambda s: (MagicMock(), cur)
    cm.__exit__ = lambda s, *a: False
    with patch("database.get_db_cursor", return_value=cm):
        pda._attach_pr_review_callback(77, 1527, "KytranKatarn/archie-platform")

    assert cur.execute.called
    sql, params = cur.execute.call_args.args[0], cur.execute.call_args.args[1]
    assert "UPDATE dispatch_pending_queue" in sql and "pr_review_result" in sql
    # callback_data json + queue_id
    assert params[1] == 77


def test_run_forge_review_polls_original_dispatch_when_queued():
    from tools.repair_bay.services import pr_diff_analyzer as pda

    queued = MagicMock(queued=True, queue_id=77)
    fake_dispatch = MagicMock(return_value=queued)
    stub_mod = MagicMock(dispatch=fake_dispatch)

    with patch.dict(
        "sys.modules",
        {"tools.department_hq.services.department_dispatcher": stub_mod},
    ), patch("services.review_attempts.await_existing_queue", return_value=None) as poll:
        out = pda._run_forge_review("prompt", pr_number=1527, repo="repoX")

    assert out is None, "a pass without a result cannot manufacture a verdict"
    poll.assert_called_once_with(77)
    assert fake_dispatch.call_count == 1


def test_run_forge_review_returns_summary_when_synchronous():
    from tools.repair_bay.services import pr_diff_analyzer as pda

    done = MagicMock(queued=False, success=True, response="  VERDICT: APPROVE  ")
    stub_mod = MagicMock(dispatch=MagicMock(return_value=done))
    with patch.dict("sys.modules", {"tools.department_hq.services.department_dispatcher": stub_mod}):
        out = pda._run_forge_review("prompt", pr_number=1527, repo="repoX")
    assert out == "VERDICT: APPROVE"
