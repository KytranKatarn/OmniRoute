"""Merge order should INFER a stacked dependency, not rely on the author declaring it.

The declared half (PR #3302) works and is enforcing — `Depends on #N` / `Blocked by #N` /
`Merge after #N` / `Requires #N` refuse a merge while #N is open. It is also the ONLY
signal, so it binds exactly when the author remembers the vocabulary.

CAUGHT LIVE 2026-09-22: PR #3434 was opened with base `fix/send-alert-cooldown` — the head
branch of open PR #3433 — and its body said "Stacked on #3433". That is not in the
vocabulary, so `declared_dependencies` returned an empty set and `_dependency_refusal`
returned None. GitHub already knew the relationship; nothing consulted it.

THE HAZARD this closes is specific, and it is NOT "main gets corrupted": merging a stacked
CHILD into its parent branch silently EXPANDS the parent's diff beyond what was reviewed and
approved. #3433's approval would then cover code no reviewer saw.

⚠️ THE DEFAULT-BRANCH GUARD IS LOAD-BEARING. Almost every PR is based on `main`. Without the
guard, one open PR whose head happened to be `main` would make every other PR look stacked on
it and freeze all merges.

⚠️ FAIL-CLOSED, BUT ONLY WHERE IT IS CHEAP. A base that IS the default branch needs no lookup
at all, so a GitHub blip cannot block a normal PR. A base that is NOT the default branch is a
stacked PR by definition — there, an unreadable parent means we cannot verify a real
dependency, and it refuses.
"""

from __future__ import annotations

import pytest

from tools.repair_bay.services.merge_order import is_stacked_base, pick_parent_pr


# --- pure: is this PR stacked at all? ---------------------------------------


@pytest.mark.parametrize("base", ["main", "master", "", None])
def test_default_or_missing_base_is_not_stacked(base):
    """The guard that stops every ordinary PR being dragged into this."""
    assert is_stacked_base(base) is False


def test_a_feature_base_is_stacked():
    assert is_stacked_base("fix/send-alert-cooldown") is True


def test_the_default_branch_is_configurable_and_main_master_are_ALWAYS_safe():
    """A configured default is honoured, and main/master are treated as defaults regardless.

    ⚠️ DELIBERATE ASYMMETRY, decided when this test first disagreed with the code. The
    catastrophic failure mode here is treating a widely-used branch as a stackable parent and
    freezing every merge; the cost of the extra safety is nil, because no open PR has `main`
    as its HEAD, so the lookup would find no parent anyway. Union, not replace.
    """
    assert is_stacked_base("develop", default_branch="develop") is False
    assert is_stacked_base("main", default_branch="develop") is False
    assert is_stacked_base("master", default_branch="develop") is False
    assert is_stacked_base("feature/x", default_branch="develop") is True


# --- pure: which open PR is the parent? -------------------------------------


def test_the_open_pr_whose_head_is_our_base_is_the_parent():
    assert pick_parent_pr([{"number": 3433, "head": "fix/send-alert-cooldown"}], self_number=3434) == 3433


def test_no_candidates_means_no_parent():
    assert pick_parent_pr([], self_number=3434) is None


def test_a_pr_is_never_its_own_parent():
    assert pick_parent_pr([{"number": 3434, "head": "x"}], self_number=3434) is None


def test_multiple_candidates_pick_deterministically():
    """Two open PRs with the same head is degenerate; the answer must not vary by dict order."""
    cands = [{"number": 88, "head": "b"}, {"number": 42, "head": "b"}]
    assert pick_parent_pr(cands, self_number=99) == 42
    assert pick_parent_pr(list(reversed(cands)), self_number=99) == 42


# --- integration with the merge gate ----------------------------------------


@pytest.fixture
def gs():
    from tools.repair_bay.services import github_service

    return github_service


def test_a_stacked_pr_is_refused_while_its_parent_is_open(gs, monkeypatch):
    monkeypatch.setattr(gs, "pr_body", lambda *a, **k: "no declaration here")
    monkeypatch.setattr(gs, "pr_base_branch", lambda *a, **k: "fix/send-alert-cooldown")
    monkeypatch.setattr(gs, "_open_pr_with_head", lambda *a, **k: (3433, True))
    reason = gs._dependency_refusal(3434)
    assert reason is not None
    assert "3433" in reason


def test_an_ordinary_pr_needs_no_parent_lookup_at_all(gs, monkeypatch):
    """A GitHub blip must never block a normal main-based PR."""
    monkeypatch.setattr(gs, "pr_body", lambda *a, **k: "")
    monkeypatch.setattr(gs, "pr_base_branch", lambda *a, **k: "main")

    def must_not_be_called(*a, **k):
        raise AssertionError("looked up a parent for a main-based PR")

    monkeypatch.setattr(gs, "_open_pr_with_head", must_not_be_called)
    assert gs._dependency_refusal(1234) is None


def test_a_stacked_pr_with_an_unreadable_parent_is_refused(gs, monkeypatch):
    """Base is not main, so it IS stacked — an unverifiable parent must not merge."""
    monkeypatch.setattr(gs, "pr_body", lambda *a, **k: "")
    monkeypatch.setattr(gs, "pr_base_branch", lambda *a, **k: "some/feature")
    monkeypatch.setattr(gs, "_open_pr_with_head", lambda *a, **k: (None, False))
    reason = gs._dependency_refusal(4321)
    assert reason is not None
    assert "could not" in reason.lower() or "refus" in reason.lower()


def test_a_stacked_pr_whose_parent_already_merged_is_allowed(gs, monkeypatch):
    """Parent merged -> GitHub retargets the child; nothing left to wait for."""
    monkeypatch.setattr(gs, "pr_body", lambda *a, **k: "")
    monkeypatch.setattr(gs, "pr_base_branch", lambda *a, **k: "some/feature")
    monkeypatch.setattr(gs, "_open_pr_with_head", lambda *a, **k: (None, True))
    assert gs._dependency_refusal(4321) is None


def test_the_declared_path_still_wins_independently(gs, monkeypatch):
    """Inference is ADDITIVE — it must not weaken the declared half (#3302)."""
    monkeypatch.setattr(gs, "pr_body", lambda *a, **k: "Depends on #999")
    monkeypatch.setattr(gs, "pr_base_branch", lambda *a, **k: "main")
    monkeypatch.setattr(gs, "pr_is_open", lambda n, *a, **k: True)
    reason = gs._dependency_refusal(1000)
    assert reason is not None and "999" in reason
