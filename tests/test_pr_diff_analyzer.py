"""Tests for PR diff analyzer — Phase 2 of PR Review Pipeline."""
import importlib.util
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


def _load_pr_review_service():
    """Load pr_review_service directly by file path to avoid __init__ DB connection."""
    service_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "platform_v2",
        "tools",
        "repair_bay",
        "services",
        "pr_review_service.py",
    )
    spec = importlib.util.spec_from_file_location("pr_review_service", service_path)
    module = importlib.util.module_from_spec(spec)
    # Stub out get_db_cursor so module-level code doesn't connect
    sys.modules.setdefault("database", MagicMock())
    with patch("builtins.__import__", side_effect=_patched_import):
        spec.loader.exec_module(module)
    return module


def _patched_import(name, *args, **kwargs):
    if name in ("database",):
        return MagicMock()
    return __builtins__.__import__(name, *args, **kwargs)  # type: ignore[attr-defined]


class TestMarkReviewPending:
    def test_mark_review_pending_exists(self):
        """mark_review_pending must be importable from pr_review_service."""
        service_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "platform_v2",
            "tools",
            "repair_bay",
            "services",
            "pr_review_service.py",
        )
        spec = importlib.util.spec_from_file_location("pr_review_service_isolated", service_path)
        module = importlib.util.module_from_spec(spec)
        # Stub database before exec so get_db_cursor import succeeds without a live DB
        stub_db = MagicMock()
        sys.modules["database"] = stub_db
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop("database", None)
        assert callable(getattr(module, "mark_review_pending", None))


def _setup_analyzer_imports():
    """Ensure platform_v2 is on sys.path and database is stubbed with all needed attrs."""
    import sys, os
    platform_path = os.path.join(os.path.dirname(__file__), '..', 'platform_v2')
    if platform_path not in sys.path:
        sys.path.insert(0, platform_path)
    # Provide a full MagicMock for database so `from database import X` always succeeds
    if "database" not in sys.modules or not hasattr(sys.modules["database"], "_get_db_password"):
        sys.modules["database"] = MagicMock()
    # Also stub psycopg2 if not present (github_routes imports it)
    if "psycopg2" not in sys.modules:
        sys.modules["psycopg2"] = MagicMock()
        sys.modules["psycopg2.extras"] = MagicMock()
    # Clear repair_bay package cache so __init__.py re-runs with correct stubs
    for key in list(sys.modules.keys()):
        if "repair_bay" in key or "github_routes" in key:
            sys.modules.pop(key, None)


class TestFetchDiff:
    def test_returns_diff_string_on_success(self):
        """_fetch_diff returns the response text on HTTP 200."""
        _setup_analyzer_imports()
        from tools.repair_bay.services.pr_diff_analyzer import _fetch_diff

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "diff --git a/foo.py b/foo.py\n+print('hello')"

        with patch("tools.repair_bay.services.pr_diff_analyzer.requests.get", return_value=mock_resp):
            result = _fetch_diff("https://github.com/org/repo/pull/1.diff")

        assert result == mock_resp.text

    def test_raises_on_non_200(self):
        """_fetch_diff raises RuntimeError when GitHub returns non-200."""
        _setup_analyzer_imports()
        from tools.repair_bay.services.pr_diff_analyzer import _fetch_diff

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"

        with patch("tools.repair_bay.services.pr_diff_analyzer.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="403"):
                _fetch_diff("https://github.com/org/repo/pull/1.diff")


class TestBuildPrompt:
    def test_includes_pr_metadata(self):
        """_build_prompt includes PR number, title, author, and diff."""
        _setup_analyzer_imports()
        from tools.repair_bay.services.pr_diff_analyzer import _build_prompt

        review = {
            "pr_number": 42, "title": "Add feature X", "author": "dev1",
            "repo": "KytranKatarn/archie-platform",
            "additions": 100, "deletions": 20, "changed_files": 3,
        }
        diff = "diff --git a/foo.py b/foo.py\n+print('x')"
        prompt = _build_prompt(review, diff)

        assert "#42" in prompt
        assert "Add feature X" in prompt
        assert "dev1" in prompt
        assert diff in prompt

    def test_truncates_large_diff(self):
        """_build_prompt truncates diff over 6000 chars and adds a note."""
        _setup_analyzer_imports()
        from tools.repair_bay.services.pr_diff_analyzer import _build_prompt

        review = {
            "pr_number": 1, "title": "Big PR", "author": "dev",
            "repo": "repo", "additions": 1000, "deletions": 0, "changed_files": 10,
        }
        large_diff = "x" * 7000
        prompt = _build_prompt(review, large_diff)

        assert "truncated" in prompt.lower()
        assert "x" * 7000 not in prompt


class TestAnalyzePendingPrs:
    def test_returns_empty_stats_when_no_pending(self):
        """analyze_pending_prs returns {processed:0, failed:0, skipped:0} with no pending."""
        _setup_analyzer_imports()
        from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs

        with patch("tools.repair_bay.services.pr_diff_analyzer.get_pending_reviews", return_value=[]):
            result = analyze_pending_prs(max_prs=3)

        assert result == {"processed": 0, "failed": 0, "skipped": 0}

    def test_reverts_to_pending_on_fetch_failure(self):
        """analyze_pending_prs resets status to pending when diff fetch fails."""
        _setup_analyzer_imports()
        from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs

        fake_review = {
            "pr_number": 99, "repo": "KytranKatarn/archie-platform",
            "title": "Test PR", "author": "dev",
            "additions": 10, "deletions": 2, "changed_files": 1,
            "diff_url": "https://github.com/org/repo/pull/99.diff",
        }

        with (
            patch("tools.repair_bay.services.pr_diff_analyzer.get_pending_reviews", return_value=[fake_review]),
            patch("tools.repair_bay.services.pr_diff_analyzer.mark_review_started"),
            patch("tools.repair_bay.services.pr_diff_analyzer._fetch_diff", side_effect=RuntimeError("403")),
            patch("tools.repair_bay.services.pr_diff_analyzer.mark_review_pending") as mock_reset,
        ):
            result = analyze_pending_prs(max_prs=3)

        assert result["failed"] == 1
        mock_reset.assert_called_once_with(99, "KytranKatarn/archie-platform")
