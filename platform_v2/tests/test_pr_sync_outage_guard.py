"""#5707 — a FAILED GitHub open-PR list must never read as an EMPTY list.

During the 2026-08-17 GitHub partial outage the pulls-list endpoint 403'd with
valid tokens. list_all_prs_enriched reports that as {"success": False, "error":
...} (no "prs" key) — it does not raise — and sync_closed_prs's unchecked
.get("prs", []) turned the outage into "zero open PRs", closing every live
pr_reviews row and terminating their pending reviews as 'skipped'. Twice.

These tests pin the guard: on success=False both entry points bail out before
touching the database. The DB cursor is patched to a sentinel that FAILS the
test if entered, so a regression (removing the guard) is caught as an attempted
DB write, not silently absorbed by a mock.
"""

from unittest import mock

import pytest

from tools.repair_bay.services import pr_review_service


_FAILURE = {"success": False, "error": "HTTP 403 - Resource not accessible by personal access token"}


class _ExplodingCursorCtx:
    """Context manager that fails the test if the code reaches the DB at all."""

    def __enter__(self):
        pytest.fail("DB access attempted despite failed GitHub list — the #5707 guard is gone")

    def __exit__(self, *exc):
        return False


def test_sync_closed_prs_skips_on_failed_list(monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.list_all_prs_enriched",
        lambda state, repo=None: dict(_FAILURE),
    )
    monkeypatch.setattr(pr_review_service, "get_db_cursor", lambda **kw: _ExplodingCursorCtx())
    assert pr_review_service.sync_closed_prs() == 0


def test_poll_open_prs_reports_error_on_failed_list(monkeypatch):
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.list_all_prs_enriched",
        lambda state, repo=None: dict(_FAILURE),
    )
    monkeypatch.setattr(pr_review_service, "get_db_cursor", lambda **kw: _ExplodingCursorCtx())
    result = pr_review_service.poll_open_prs()
    assert result["errors"] == 1
    assert result["polled"] == 0


def test_sync_closed_prs_still_works_on_genuinely_empty_list(monkeypatch):
    """A repo with zero open PRs is a legitimate state — the guard must not block it."""
    monkeypatch.setattr(
        "tools.repair_bay.services.github_service.list_all_prs_enriched",
        lambda state, repo=None: {"success": True, "prs": [], "count": 0},
    )
    entered = {}

    class _Cursor:
        rowcount = 0

        def execute(self, *a, **kw):
            entered["executed"] = True

    class _Ctx:
        def __enter__(self):
            return (mock.Mock(), _Cursor())

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pr_review_service, "get_db_cursor", lambda **kw: _Ctx())
    pr_review_service.sync_closed_prs()
    assert entered.get("executed"), "an honest empty list must still run the close sweep"
