"""Tier must reflect what a PR TOUCHES, not only how big it is (#5986).

Background. `classify_pr_tier` read size, title, verdict and BRANCH NAME — never the
changed paths. Tier is not only a merge ceiling: `pr_diff_analyzer._review_is_strong` is
`tier >= 3`, and that picks the REVIEW MODEL. Tier 3 gets gemma3:12b at the wide cap;
everything else gets qwen2.5:7b at the tight one. So a SMALL diff to the dispatch kernel,
the merge kernel, rbac.py or auth_service.py drew the WEAKEST review available — the most
dangerous changes getting the least capable reviewer.

The pre-existing branch-name check (`"migration" in branch`) is a proxy for "touches a
migration" and is trivially missed, which is why a path-based gate is the right shape.

NOT claimed here: this was never an open unattended-MERGE hole. `_automerge_paths_allowed`
(CONDITION 2 of the auto-merge gate) already refuses sensitive paths for every actor,
fails closed, and runs BEFORE the tier check. This fixes review strength and adds
defence in depth.
"""

import pytest

from services.lane_classifier import KERNEL_PATTERNS, is_kernel_path
from tools.repair_bay.services.pr_diff_analyzer import _review_is_strong
from tools.repair_bay.services.pr_review_service import classify_pr_tier


def _tiny_approved(**kw):
    """A PR that every size-based rule calls Tier 1: small, few files, APPROVE."""
    base = {
        "additions": 4,
        "deletions": 1,
        "changed_files": 1,
        "title": "fix: tidy a helper",  # no tier-3 keyword
        "head_branch": "fix/tidy-helper",  # no migration proxy
        "ai_summary": "VERDICT: APPROVE",
        "metadata": {},
    }
    base.update(kw)
    return base


def test_a_tiny_approved_kernel_change_is_tier_3():
    """THE BUG: four lines in auth_service.py used to classify Tier 1."""
    r = _tiny_approved(changed_paths=["platform_v2/services/auth_service.py"])
    assert classify_pr_tier(r) == 3


def test_the_same_pr_without_paths_keeps_the_OLD_tier():
    """Proves the test above is measuring the new gate and nothing else.

    Also pins the documented inert case: a review dict loaded from the DB carries no
    changed_paths, so the gate cannot fire there. That is safe because the merge path
    refuses sensitive paths earlier via _automerge_paths_allowed, and it must stay a
    conscious decision rather than an accident.
    """
    assert classify_pr_tier(_tiny_approved()) == 1


def test_ordinary_code_is_not_escalated():
    """No false escalation — otherwise every PR becomes Tier 3 and the ladder is noise."""
    r = _tiny_approved(changed_paths=["platform_v2/tools/fitness/routes.py", "README.md"])
    assert classify_pr_tier(r) == 1


def test_a_migration_escapes_the_branch_name_proxy_but_not_the_path_gate():
    """`fix/tidy-helper` defeats the "migration" branch check; the path gate still catches it."""
    r = _tiny_approved(changed_paths=["database/migrations/479_whatever.sql"])
    assert classify_pr_tier(r) == 3


def test_the_kernel_pr_now_gets_the_STRONG_reviewer():
    """The live consequence, asserted through the real consumer rather than inferred.

    _review_is_strong is what selects gemma3:12b and the wide diff cap.
    """
    kernel = _tiny_approved(changed_paths=["platform_v2/tools/repair_bay/services/github_service.py"])
    assert _review_is_strong(kernel) is True
    assert _review_is_strong(_tiny_approved(changed_paths=["docs/notes.md"])) is False


@pytest.mark.parametrize("pattern", list(KERNEL_PATTERNS))
def test_every_kernel_pattern_escalates(pattern):
    """ONE definition, enforced. Adding a pattern to KERNEL_PATTERNS must move the tier
    ladder too — a second, drifting list of "sensitive paths" is the shape behind #5194
    and #5862, where a correct guard existed and some other surface never consulted it."""
    path = f"platform_v2/{pattern}" if not pattern.startswith(("scripts/", "database/", ".git")) else pattern
    assert is_kernel_path(path), "sanity: the pattern should match its own sample path"
    assert classify_pr_tier(_tiny_approved(changed_paths=[path])) == 3


def test_one_kernel_file_among_many_innocuous_ones_still_escalates():
    """Any kernel file taints the PR — the gate is `any`, not `all`."""
    r = _tiny_approved(
        changed_paths=["README.md", "platform_v2/tests/test_x.py", "platform_v2/rbac.py"],
    )
    assert classify_pr_tier(r) == 3


def test_malformed_changed_paths_do_not_raise():
    """classify_pr_tier sits on hot paths; a junk value must not take the review down."""
    for bad in (None, [], ""):
        assert classify_pr_tier(_tiny_approved(changed_paths=bad)) == 1


def test_the_stamp_actually_REACHES_the_tier_decision(monkeypatch):
    """Wiring, not intent. A correct guard that no choke point calls is the failure mode
    behind #5194, #5862 and #5863 — three times in one week. So assert the paths reach
    _structured_review, which is what the strong-path model selection reads.

    _structured_review is stubbed, so nothing dispatches.
    """
    from tools.repair_bay.services import pr_diff_analyzer as pda

    diff = (
        "diff --git a/platform_v2/rbac.py b/platform_v2/rbac.py\n"
        "--- a/platform_v2/rbac.py\n"
        "+++ b/platform_v2/rbac.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    seen = {}

    def _fake_structured(review, chunk, pr_number=None, repo=None, **kw):
        seen["review"] = review
        return "SUMMARY\nISSUES\nNo issues found.\nVERDICT: APPROVE"

    monkeypatch.setattr(pda, "_structured_review", _fake_structured)

    # The review row as it arrives from the DB: NO changed_paths, and small enough that
    # every size-based rule says Tier 1.
    row = _tiny_approved()
    pda._obtain_review_summary(row, diff, pr_number=1, repo="KytranKatarn/archie-platform")

    assert "review" in seen, "_structured_review was never reached"
    assert seen["review"].get("changed_paths") == ["platform_v2/rbac.py"]
    assert classify_pr_tier(seen["review"]) == 3, "the stamped dict must classify Tier 3"
    assert _review_is_strong(seen["review"]) is True, "so it takes the gemma3:12b wide-window path"
    assert "changed_paths" not in row, "the caller's dict must not be mutated"
