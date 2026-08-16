"""Regression: engine-authored PRs must NEVER auto-merge (#380 safety gate).

The A.R.C.H.I.E. build engine opens PRs (branch ``engine/<slug>`` / title ``[engine] ...``)
against archie-platform. Those must pass a human merge gate even on a F.O.R.G.E. APPROVE —
autonomous code is never auto-merged. Normal (human/codex) PRs must keep auto-merging.

All externals are mocked, so this never touches the real DB, GitHub, or Telegram.

⚠️ That sentence was FALSE between #5370 and 2026-08-16, and these tests were red the whole
time. #5370 added a sensitive-path gate to mark_review_done that runs BEFORE merge_pr and
calls `_automerge_paths_allowed` — which was NOT stubbed here, so the "fully mocked" suite
reached the LIVE GitHub API, got the real files of an unrelated PR #999, took the
non-allowlisted early-return, and never called merge_pr at all. The assertion failed as
`[] == [999]`, which reads like the safety gate misfiring rather than a missing stub.
The stub now lives in the `merges` fixture; the path behaviour itself is covered in
test_automerge_path_gate.py.
"""

import contextlib

import pytest

from tools.repair_bay.services import github_service
from tools.repair_bay.services import pr_review_service as prs


@contextlib.contextmanager
def _fake_cursor(*_a, **_k):
    class _Cur:
        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    yield (None, _Cur())


@pytest.fixture
def merges(monkeypatch):
    """Patch the externals; return the list that records merge_pr() calls."""
    recorded = []
    monkeypatch.setattr(prs, "verdict_is_approved", lambda _s: True)
    monkeypatch.setattr(prs, "classify_pr_tier", lambda _r: 1)  # tier 1 → would auto-merge if not gated
    monkeypatch.setattr(prs, "get_db_cursor", _fake_cursor)
    # #5370's sensitive-path gate runs BEFORE merge_pr and hits the GitHub API. Unstubbed,
    # it made this "fully mocked" suite call the network and early-return, so merge_pr was
    # never reached and the engine-gate assertions could not run at all. Held "allowed"
    # here because these tests are about the ENGINE gate; paths are pinned separately in
    # test_automerge_path_gate.py.
    monkeypatch.setattr(prs, "_automerge_paths_allowed", lambda _pr, repo=None: (True, []))
    monkeypatch.setattr(
        github_service,
        "merge_pr",
        lambda pr, method="squash", repo=None: (recorded.append(pr) or {"merged": True, "sha": "deadbeef"}),
    )
    import services.telegram_service as tg

    monkeypatch.setattr(tg, "send_info", lambda *_a, **_k: None)
    return recorded


def _review(monkeypatch, *, branch="", title=""):
    rev = {"branch": branch, "head_branch": branch, "title": title, "pr_number": 999}
    monkeypatch.setattr(prs, "get_review", lambda _pr, repo=None: dict(rev))


def test_engine_branch_pr_is_gated(merges, monkeypatch):
    _review(monkeypatch, branch="engine/fix-something", title="[engine] fix something")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == []  # merge_pr must NOT be called for an engine branch


def test_engine_title_pr_is_gated(merges, monkeypatch):
    _review(monkeypatch, branch="fix/normal-looking", title="[engine] sneaky")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == []  # gated by the [engine] title even on a normal branch


def test_normal_human_pr_still_auto_merges(merges, monkeypatch):
    _review(monkeypatch, branch="fix/normal-human", title="fix: a normal human PR")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == [999]  # the gate must NOT block ordinary auto-merge


def test_non_default_repo_pr_is_review_only(merges, monkeypatch):
    # Watch-product (non-default) repos are REVIEW-ONLY: never auto-merged, because the
    # auto-merge write token is scoped to archie-platform and the review token is
    # read-only — an auto-merge there would target the wrong repo (#4494).
    _review(monkeypatch, branch="fix/normal-looking", title="feat: a watch-repo PR")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/kytran-legal-watch")
    assert merges == []  # non-default repo → review-only, merge_pr must NOT be called


def test_prefix_is_env_tunable(merges, monkeypatch):
    monkeypatch.setenv("FORGE_NO_AUTOMERGE_BRANCH_PREFIXES", "bot/")
    _review(monkeypatch, branch="bot/xyz", title="bot work")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == []  # gated by the custom prefix
    # 'engine/' is no longer in the list → an engine branch now auto-merges
    _review(monkeypatch, branch="engine/zzz", title="x")
    prs.mark_review_done(999, "VERDICT: APPROVE", repo="KytranKatarn/archie-platform")
    assert merges == [999]
