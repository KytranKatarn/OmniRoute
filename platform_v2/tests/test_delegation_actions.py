"""Unit tests for the DHQ Dispatch blocked-job queue actions
(requeue / dismiss / fix) — feat/dispatch-blocked-queue-actions.

DB boundaries are mocked with a context-manager cursor (same pattern as
test_delegation_service.py). No real DB, dispatcher, or KB is touched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _cursor_cm(row=None, rows=None):
    """Return (cur, cm): a MagicMock cursor + a context-manager that yields
    (conn, cur) to match ``with get_db_cursor(commit=True) as (conn, cur)``."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    return cur, _CM()


@pytest.fixture
def ds():
    from services import delegation_service

    return delegation_service


def _row(**kw):
    base = {
        "id": 4407,
        "status": "blocked",
        "title": "[DELEGATE:claude] documentation",
        "description": "",
        "delegation_source": "claude",
        "delegation_args": {
            "capability": "documentation",
            "reason": "Document PR #1883",
            "args": {},
        },
    }
    base.update(kw)
    return base


# ── _parse_pr_number ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Document PR #1883 (P2-C right-sizing)", 1883),
        ("PR #42", 42),
        ("PR1234", 1234),
        ("see pull #7 please", 7),
        ("no pr here", None),
        ("", None),
    ],
)
def test_parse_pr_number(ds, text, expected):
    assert ds._parse_pr_number(text) == expected


# ── requeue_blocked_delegation ───────────────────────────────────────
def test_requeue_llm_flips_to_pending(ds):
    cur, cm = _cursor_cm(row=_row(delegation_args={"capability": "documentation"}))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.requeue_blocked_delegation(4407)
    assert res["success"] is True
    assert res["new_status"] == "pending"
    # an UPDATE carrying 'pending' was issued
    assert any("pending" in str(c.args) for c in cur.execute.call_args_list)


def test_requeue_codex_flips_to_deferred(ds):
    cur, cm = _cursor_cm(row=_row(delegation_source="automation", delegation_args={"capability": "codex_task"}))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.requeue_blocked_delegation(4100)
    assert res["success"] is True
    assert res["new_status"] == "deferred"
    assert res["capability"] == "codex_task"


def test_requeue_codex_with_pr_refused(ds):
    # #4422: a codex_task that already opened a PR must NOT be re-run (would
    # redo merged work + open a duplicate PR). Retry must refuse it.
    cur, cm = _cursor_cm(
        row=_row(
            delegation_source="automation",
            delegation_args={"capability": "codex_task"},
            metadata={"codex_pr": 1894, "codex_branch": "codex/foo"},
        )
    )
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.requeue_blocked_delegation(4100)
    assert res["success"] is False
    assert res["error"] == "already_has_pr"
    assert res["codex_pr"] == 1894


def test_requeue_rejects_non_retryable_status(ds):
    cur, cm = _cursor_cm(row=_row(status="in_progress"))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.requeue_blocked_delegation(4407)
    assert res["success"] is False
    assert res["error"].startswith("status_not_retryable")


def test_requeue_task_not_found(ds):
    cur, cm = _cursor_cm(row=None)
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.requeue_blocked_delegation(999999)
    assert res == {"success": False, "error": "task_not_found"}


def test_requeue_rejects_non_delegation(ds):
    cur, cm = _cursor_cm(row=_row(delegation_source=None))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.requeue_blocked_delegation(4407)
    assert res["success"] is False
    assert res["error"] == "not_a_delegation"


# ── dismiss_delegation ───────────────────────────────────────────────
def test_dismiss_sets_cancelled(ds):
    cur, cm = _cursor_cm(row=_row(status="blocked"))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.dismiss_delegation(4407, reason="not needed")
    assert res["success"] is True
    assert res["new_status"] == "cancelled"
    assert any("cancelled" in str(c.args) for c in cur.execute.call_args_list)


def test_dismiss_rejects_already_completed(ds):
    cur, cm = _cursor_cm(row=_row(status="completed"))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.dismiss_delegation(4407)
    assert res["success"] is False
    assert res["error"] == "already_completed"


# ── fix_documentation_delegation ─────────────────────────────────────
def test_fix_rejects_non_documentation(ds):
    cur, cm = _cursor_cm(row=_row(delegation_args={"capability": "code", "args": {}}))
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.fix_documentation_delegation(4407)
    assert res["success"] is False
    assert res["error"].startswith("not_documentation")


def test_fix_requires_pr_number(ds):
    cur, cm = _cursor_cm(
        row=_row(
            title="[DELEGATE:claude] documentation",
            description="",
            delegation_args={"capability": "documentation", "reason": "write some docs", "args": {}},
        )
    )
    with patch.object(ds, "get_db_cursor", return_value=cm):
        res = ds.fix_documentation_delegation(4407)
    assert res["success"] is False
    assert res["error"] == "no_pr_number_found"


def test_fix_runs_document_pr_and_completes(ds):
    cur, cm = _cursor_cm(
        row=_row(delegation_args={"capability": "documentation", "reason": "Document PR #1883", "args": {}})
    )
    doc_mock = MagicMock(
        return_value={
            "success": True,
            "summary": "Documented PR #1883 -> KB vault_note #999",
            "result": {"knowledge_base_id": 999, "pr_number": 1883},
        }
    )
    complete_mock = MagicMock()
    with patch.object(ds, "get_db_cursor", return_value=cm), patch.object(ds, "_document_pr", doc_mock), patch.object(
        ds, "mark_task_completed", complete_mock
    ):
        res = ds.fix_documentation_delegation(4407)
    assert res["success"] is True
    assert res["pr_number"] == 1883
    # _document_pr called with the parsed PR number
    assert doc_mock.call_args.args[0]["pr_number"] == 1883
    complete_mock.assert_called_once()


def test_fix_propagates_document_pr_failure(ds):
    cur, cm = _cursor_cm(
        row=_row(delegation_args={"capability": "documentation", "reason": "Document PR #1883", "args": {}})
    )
    doc_mock = MagicMock(return_value={"success": False, "error": "kb_insert_failed"})
    complete_mock = MagicMock()
    with patch.object(ds, "get_db_cursor", return_value=cm), patch.object(ds, "_document_pr", doc_mock), patch.object(
        ds, "mark_task_completed", complete_mock
    ):
        res = ds.fix_documentation_delegation(4407)
    assert res["success"] is False
    assert res["error"] == "kb_insert_failed"
    complete_mock.assert_not_called()
