import copy
from unittest.mock import Mock

import pytest
from services import review_checkpoints as rc


def review():
    return {
        "title": "same code",
        "author": "coder",
        "metadata": {},
        "_checkpoint_identity": {"head_sha": "a" * 40, "base_sha": "b" * 40},
    }


@pytest.fixture
def saved(monkeypatch):
    rows = []
    monkeypatch.setattr(rc, "persist_checkpoint", lambda *args: rows.append(copy.deepcopy(args[-1])) or True)
    return rows


def test_interrupted_pass_can_resume_but_completed_review_cannot(saved):
    r = review()
    first = rc.checkpoint_for(r, "full-diff", "o/r", 1, "policy", "F.O.R.G.E.")
    first.remember("chunk", "VERDICT: APPROVE", 9000)
    r["metadata"]["review_pass_checkpoint"] = saved[-1]
    resumed = rc.checkpoint_for(r, "full-diff", "o/r", 1, "policy", "F.O.R.G.E.")
    assert resumed.lookup("chunk", 9000) == "VERDICT: APPROVE"
    resumed.save(True)
    r["metadata"]["review_pass_checkpoint"] = saved[-1]
    assert rc.checkpoint_for(r, "full-diff", "o/r", 1, "policy", "F.O.R.G.E.").lookup("chunk", 9000) is None


@pytest.mark.parametrize("change", ["head", "base", "diff", "repo", "policy", "reviewer", "context", "title"])
def test_any_context_change_invalidates_reuse(saved, change):
    r = review()
    rc.checkpoint_for(r, "diff", "o/r", 1, "policy", "F.O.R.G.E.").remember("chunk", "VERDICT: APPROVE", 9000)
    r["metadata"]["review_pass_checkpoint"] = saved[-1]
    diff, repo, policy, reviewer = "diff", "o/r", "policy", "F.O.R.G.E."
    if change in ("head", "base"):
        r["_checkpoint_identity"][change + "_sha"] = "c" * 40
    elif change == "diff":
        diff = "changed"
    elif change == "repo":
        repo = "other/repo"
    elif change == "policy":
        policy = "new"
    elif change == "reviewer":
        reviewer = "P.R.O.B.E."
    elif change == "context":
        r["repository_context"] = "new indexed reference"
    else:
        r["title"] = "new title"
    assert rc.checkpoint_for(r, diff, repo, 1, policy, reviewer).lookup("chunk", 9000) is None


def test_wide_review_or_unknown_identity_disables_reuse():
    assert rc.checkpoint_for(review(), "diff", "o/r", 1, "p", "F.O.R.G.E.", wide=True) is None
    r = review()
    r["_checkpoint_identity"]["head_sha"] = "a" * 41
    assert rc.checkpoint_for(r, "diff", "o/r", 1, "p", "F.O.R.G.E.") is None
    assert rc.checkpoint_for(review(), "diff", "o/r", 1, "p", None) is None


def test_corrupt_summary_or_changed_window_is_not_reused(saved):
    r = review()
    c = rc.checkpoint_for(r, "diff", "o/r", 1, "p", "F.O.R.G.E.")
    c.remember("chunk", "VERDICT: APPROVE", 9000)
    assert c.lookup("chunk", 8000) is None
    next(iter(c.passes.values()))["summary"] = "VERDICT: REQUEST CHANGES"
    assert c.lookup("chunk", 9000) is None


def test_checkpoint_write_error_does_not_break_review(monkeypatch):
    monkeypatch.setattr(rc, "persist_checkpoint", Mock(side_effect=RuntimeError("fixture")))
    c = rc.checkpoint_for(review(), "diff", "o/r", 1, "p", "F.O.R.G.E.")
    c.remember("chunk", "VERDICT: NEEDS REVIEW", 9000)
    assert c.save(False) is False
