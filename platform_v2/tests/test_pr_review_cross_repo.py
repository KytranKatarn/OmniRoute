"""Unit tests for pr_review_service cross-repo tracking (#3941, KB #272111).

Pure-logic tests — an injected fake cursor for get_tracked_repos and the
malformed-repo early-return guards mean NO live DB is touched (and nothing is
written). Covers:
  - _is_valid_repo owner/repo validation
  - get_tracked_repos union (configured + discovered), dedupe/order, junk filter,
    and fail-open on a DB read error
  - poll_open_prs / sync_closed_prs refusing a malformed repo label
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # platform_v2 on path

from tools.repair_bay.services import pr_review_service as prs  # noqa: E402


class FakeReposCursor:
    """Returns canned DISTINCT-repo rows; can simulate a read failure."""

    def __init__(self, repos, raise_on_execute=False):
        self._repos = list(repos)
        self._raise = raise_on_execute

    def execute(self, sql, params=None):
        assert "pr_reviews" in sql
        if self._raise:
            raise RuntimeError("simulated DB failure")

    def fetchall(self):
        return [{"repo": r} for r in self._repos]


def test_is_valid_repo():
    assert prs._is_valid_repo("KytranKatarn/archie-platform")
    assert prs._is_valid_repo("KytranKatarn/archie-code")
    assert prs._is_valid_repo("KytranKatarn/kytran-creed")
    # The malformed phantom label from the pre-#4295 mis-stamp bug:
    assert not prs._is_valid_repo("kytran-creed")
    assert not prs._is_valid_repo("")
    assert not prs._is_valid_repo(None)
    assert not prs._is_valid_repo("a/b/c")


def test_tracked_repos_unions_discovered_and_filters_junk(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOS", raising=False)
    cur = FakeReposCursor(["KytranKatarn/archie-platform", "KytranKatarn/archie-code", "kytran-creed"])
    out = prs.get_tracked_repos(cur=cur)
    # configured (_DEFAULT_REPO) first, then discovered archie-code; bare junk dropped.
    assert out == ["KytranKatarn/archie-platform", "KytranKatarn/archie-code"]


def test_tracked_repos_dedupes_and_preserves_order(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOS", "KytranKatarn/archie-platform, KytranKatarn/archie-code")
    cur = FakeReposCursor(["KytranKatarn/archie-code", "KytranKatarn/new-repo"])
    out = prs.get_tracked_repos(cur=cur)
    assert out == [
        "KytranKatarn/archie-platform",
        "KytranKatarn/archie-code",
        "KytranKatarn/new-repo",
    ]


def test_tracked_repos_fail_open_on_db_error(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOS", raising=False)
    cur = FakeReposCursor([], raise_on_execute=True)
    out = prs.get_tracked_repos(cur=cur)
    assert out == [prs._DEFAULT_REPO]  # falls back to configured only, never raises


def test_poll_open_prs_rejects_malformed_repo():
    res = prs.poll_open_prs(repo="kytran-creed")
    assert res == {"polled": 0, "inserted": 0, "updated": 0, "errors": 1}


def test_sync_closed_prs_rejects_malformed_repo():
    assert prs.sync_closed_prs(repo="kytran-creed") == 0
