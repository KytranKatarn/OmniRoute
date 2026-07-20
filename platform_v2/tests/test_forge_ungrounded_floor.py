"""Regression: an APPROVE that rests on NOTHING grounded in the diff must not auto-merge (#5009).

OBSERVED 2026-07-20 on PR #2351 (scripts/dr/setup_replica.sh, +147/-23). F.O.R.G.E. returned
APPROVE with a summary stating the diff "does not contain any actual code changes" — it had
described only the diff HEADER (mode change + index line). Truncation was ruled out: the model
received all 9,782 chars (cap 18,768, truncated=False).

The mechanism is the anti-hallucination filter working against itself:

    model misreads diff -> raises ungrounded issue(s)
      -> _verify_evidence drops them all (evidence not in the diff)
        -> _recompute_verdict sees ZERO surviving issues
          -> APPROVE   <- an approval CAUSED by the reviewer being wrong about everything

Since auto-merge fires on APPROVE, the gate could rubber-stamp a change nobody read.

The floor is deliberately NARROW — it must not add friction to genuinely clean PRs, which are
the ones that legitimately auto-merge (e.g. #2350). All externals are pure; no DB/GitHub.
"""

from tools.repair_bay.services.pr_diff_analyzer import (
    _count_ungrounded,
    _should_floor_ungrounded,
    _verify_evidence,
)

DIFF = """diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 import os
+total = compute_total(items)
 print("hi")
"""


def _issue(evidence, severity="WARNING", title="t"):
    return {"severity": severity, "title": title, "why": "w", "evidence": evidence}


# --- _verify_evidence must record WHY an issue was dropped -------------------------------------


def test_ungrounded_evidence_is_tagged():
    kept, dropped = _verify_evidence([_issue("this line is nowhere in the diff")], DIFF)
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["_drop_reason"] == "evidence_not_in_diff"
    assert _count_ungrounded(dropped) == 1


def test_grounded_evidence_is_kept_and_not_counted():
    kept, dropped = _verify_evidence([_issue("total = compute_total(items)")], DIFF)
    assert len(kept) == 1
    assert dropped == []
    assert _count_ungrounded(dropped) == 0


def test_spurious_injection_drop_is_not_counted_as_ungrounded():
    """A parameterized-query 'SQL injection' flag IS in the diff — the deterministic guard drops it
    as a known false positive. The model WAS reading; that must not poison the verdict."""
    diff = "diff --git a/db.py b/db.py\n@@ -1 +1,2 @@\n" '+cur.execute("SELECT * FROM t WHERE id = %s", (uid,))\n'
    issue = _issue('cur.execute("SELECT * FROM t WHERE id = %s", (uid,))', severity="CRITICAL", title="SQL injection")
    kept, dropped = _verify_evidence([issue], diff)
    assert kept == []
    assert dropped[0]["_drop_reason"] == "spurious_injection"
    assert _count_ungrounded(dropped) == 0, "a trusted correction must not look like a grounding failure"


# --- the floor predicate ------------------------------------------------------------------------


def test_floors_when_every_issue_was_ungrounded():
    """The PR #2351 case: issues raised, all ungrounded, none survived -> APPROVE is meaningless."""
    assert _should_floor_ungrounded("APPROVE", 1, []) is True
    assert _should_floor_ungrounded("APPROVE", 3, []) is True


def test_does_NOT_floor_a_genuinely_clean_review():
    """No issues raised at all -> nothing was fabricated -> a real APPROVE. This is the #2350
    path; flooring it would break legitimate auto-merge and is the main regression risk."""
    assert _should_floor_ungrounded("APPROVE", 0, []) is False


def test_does_NOT_floor_when_something_was_grounded():
    """One grounded issue proves the model read the diff, even if another was fabricated."""
    assert _should_floor_ungrounded("APPROVE", 1, [_issue("total = compute_total(items)", "INFO")]) is False


def test_never_relaxes_a_stricter_verdict():
    """The floor may only tighten APPROVE. It must never touch a blocking or already-human verdict."""
    assert _should_floor_ungrounded("REQUEST CHANGES", 5, []) is False
    assert _should_floor_ungrounded("NEEDS REVIEW", 5, []) is False


def test_end_to_end_shape_of_the_2351_failure():
    """Wire the real pieces together: an ungrounded issue against a real diff floors the verdict."""
    issues = [_issue("a mode change and an index update")]  # cites nothing in the diff body
    kept, dropped = _verify_evidence(issues, DIFF)
    n_ungrounded = _count_ungrounded(dropped)
    # _recompute_verdict would return APPROVE here: zero surviving issues, no blockers.
    assert kept == [] and n_ungrounded == 1
    assert _should_floor_ungrounded("APPROVE", n_ungrounded, kept) is True
