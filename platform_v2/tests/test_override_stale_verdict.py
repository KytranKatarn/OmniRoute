"""#5672 — human_override clears AUTHORITY limits, never the stale-verdict SAFETY check.

PROVEN on PR #2614 (2026-08-16): merge_pr correctly refused a stale verdict, and
`human_override=True` then merged commits the review had never seen — the override
skipped the whole governance gate instead of only its authority half.

The fix adds `_override_stale_verdict_check`, run on EVERY interactive override
merge: a PROVEN mismatch (recorded reviewed_head_sha != readable current head)
refuses; anything unprovable (no row, no stamp, unreadable head, errors) allows —
the override contract already requires the human to have verified the verdict.

The merge_pr-level test uses a BaseException tripwire on `_api_get`: a regression
(override skipping the check again) is caught as an attempted GitHub call, and a
plain-Exception sentinel would risk being swallowed by defensive handlers
(measured on the #5707 tests — pytest.fail is BaseException-derived for the same
reason).
"""

from tools.repair_bay.services import github_service, pr_review_service


_STALE_REVIEW = {"ai_summary": "VERDICT: APPROVE", "metadata": {"reviewed_head_sha": "aaaa1111bbbb"}}


def _patch_review(monkeypatch, review, head_sha):
    monkeypatch.setattr(pr_review_service, "get_review", lambda pr, repo=None: review)
    monkeypatch.setattr(pr_review_service, "pr_head_sha", lambda pr, repo=None: head_sha)


def test_proven_stale_refuses(monkeypatch):
    _patch_review(monkeypatch, dict(_STALE_REVIEW), "cccc2222dddd")
    ok, why = github_service._override_stale_verdict_check(9999)
    assert ok is False
    assert "STALE VERDICT" in why


def test_fresh_sha_allows(monkeypatch):
    _patch_review(monkeypatch, dict(_STALE_REVIEW), "aaaa1111bbbb")
    ok, why = github_service._override_stale_verdict_check(9999)
    assert ok is True


def test_missing_stamp_allows_unprovable(monkeypatch):
    _patch_review(monkeypatch, {"ai_summary": "VERDICT: APPROVE", "metadata": {}}, "cccc2222dddd")
    ok, why = github_service._override_stale_verdict_check(9999)
    assert ok is True
    assert "unprovable" in why


def test_no_review_row_allows_unprovable(monkeypatch):
    _patch_review(monkeypatch, None, "cccc2222dddd")
    ok, why = github_service._override_stale_verdict_check(9999)
    assert ok is True


def test_unreadable_head_allows_unprovable(monkeypatch):
    _patch_review(monkeypatch, dict(_STALE_REVIEW), None)
    ok, why = github_service._override_stale_verdict_check(9999)
    assert ok is True


class _GitHubReached(BaseException):
    """BaseException so no defensive `except Exception` can swallow the tripwire."""


def test_merge_pr_override_refuses_proven_stale_before_github(monkeypatch):
    _patch_review(monkeypatch, dict(_STALE_REVIEW), "cccc2222dddd")

    def _explode(*a, **kw):
        raise _GitHubReached("merge_pr reached GitHub despite a proven-stale verdict under override")

    monkeypatch.setattr(github_service, "_api_get", _explode)
    result = github_service.merge_pr(9999, method="squash", human_override=True)
    assert result["success"] is False
    assert result["merged"] is False
    assert result.get("governance_blocked") is True
    assert result.get("stale_verdict") is True
    assert "STALE VERDICT" in result["error"]
