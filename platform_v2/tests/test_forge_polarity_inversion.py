"""Regression: a review finding may only be raised against an ADDED line (#5075).

OBSERVED 5x in the 2026-07-21 session; gov-watch PR #45 gives a clean controlled A/B on the
SAME diff, two consecutive runs:

    RUN 1 — "[BridgeDispatcher] Fleet dispatch timeout (240s)"
            VERDICT: REQUEST CHANGES
            "contract_date is being marked as retrospective ... which is incorrect
             because it represents a START date"
    RUN 2 — no timeout
            VERDICT: APPROVE
            "correctly removes the unnecessary event=True"

Run 1's finding is the EXACT INVERSE of the change. ``event=True`` is on the REMOVED line —
the PR deletes it. The reviewer described the removed state as the proposed state and flagged
it as the defect. The evidence gate did not catch it because it judged '+' and '-' as one
undifferentiated "changed" blob, so quoting deleted code counted as grounded.

Why it matters: per feedback_forge-no-silent-override a REQUEST CHANGES is not a clear, so a
false one either blocks a correct fix or trains the operator to override F.O.R.G.E. reflexively
— which destroys the value of the gate entirely.

The fix is deterministic, not a prompt plea: a defect can only exist in code that SURVIVES the
merge. All externals are pure; no DB, no GitHub, no model.
"""

import tools.repair_bay.services.pr_diff_analyzer as pda
from tools.repair_bay.services.pr_diff_analyzer import (
    _count_ungrounded,
    _evidence_polarity,
    _should_floor_ungrounded,
    _verify_evidence,
)

# The real PR #45 change: event=True is REMOVED from contract_date.
DIFF_45 = """diff --git a/procure/contract_history.py b/procure/contract_history.py
index 1111111..2222222 100644
--- a/procure/contract_history.py
+++ b/procure/contract_history.py
@@ -40,7 +40,7 @@ def _row(row):
     return {
-        "contract_date": _to_date(_first(row, _DATE_COLS), "contract_date", event=True),
+        "contract_date": _to_date(_first(row, _DATE_COLS), "contract_date"),
         "vendor": row.get("vendor"),
     }
"""

REMOVED_LINE = '"contract_date": _to_date(_first(row, _DATE_COLS), "contract_date", event=True),'


def _issue(evidence, severity="WARNING", title="contract_date marked retrospective"):
    return {"severity": severity, "title": title, "why": "w", "evidence": evidence}


class TestTheInversionIsCaught:
    def test_finding_citing_the_removed_line_is_dropped(self):
        """THE REGRESSION. The reviewer quoted the line the PR DELETED and called it the
        defect. That finding describes code that will not exist after the merge."""
        kept, dropped = _verify_evidence([_issue(REMOVED_LINE)], DIFF_45)
        assert kept == [], "a defect cannot live on a line the PR removes"
        assert len(dropped) == 1
        assert dropped[0]["_drop_reason"] == "evidence_only_removed"

    def test_polarity_of_the_removed_line_is_removed_only(self):
        assert _evidence_polarity(REMOVED_LINE, DIFF_45) == "removed_only"

    def test_a_polarity_drop_is_not_a_grounding_failure(self):
        """The model WAS reading its input — it read the wrong side. Counting this as
        ungrounded would wrongly floor the APPROVE that run 2 correctly produced."""
        _, dropped = _verify_evidence([_issue(REMOVED_LINE)], DIFF_45)
        assert _count_ungrounded(dropped) == 0
        assert _should_floor_ungrounded("APPROVE", _count_ungrounded(dropped), []) is False


class TestRealFindingsStillSurvive:
    """The gate must only remove confident noise — it must never soften a real review."""

    def test_finding_on_the_added_line_is_kept(self):
        kept, dropped = _verify_evidence(
            [_issue('"contract_date": _to_date(_first(row, _DATE_COLS), "contract_date"),')],
            DIFF_45,
        )
        assert len(kept) == 1 and dropped == []

    def test_modified_line_present_on_both_sides_stays_grounded(self):
        """A line the PR EDITS appears as both - and +. 'added' is checked first precisely so
        an ordinary modification keeps supporting a real finding."""
        diff = (
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n"
            "-x = compute(a, b)\n+x = compute(a, b, c)\n"
        )
        assert _evidence_polarity("x = compute(a, b, c)", diff) == "added"
        kept, _ = _verify_evidence([_issue("x = compute(a, b, c)")], diff)
        assert len(kept) == 1

    def test_pure_addition_is_unaffected(self):
        # NOTE: this is INERT TEST DATA — a string containing a fake unified diff. Nothing here
        # is executed; os.system appears only as the text of a diff line, chosen because it is
        # the kind of genuinely dangerous addition the reviewer MUST still be able to flag.
        diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1,2 @@\n" " import os\n+os.system(cmd)\n"
        assert _evidence_polarity("os.system(cmd)", diff) == "added"


class TestCritiquingTheDeletionStillWorks:
    """The gate must not cost us the ability to flag a DANGEROUS DELETION. "This PR removes a
    guard that was needed" is legitimate and its evidence can only ever be a removed line —
    near-identical to the inversion in evidence, opposite in meaning."""

    def test_a_finding_about_the_removal_is_kept(self):
        kept, dropped = _verify_evidence(
            [
                _issue(
                    REMOVED_LINE,
                    title="PR removes the event=True guard",
                    severity="CRITICAL",
                )
            ],
            DIFF_45,
        )
        assert len(kept) == 1, "critiquing a deletion must survive the polarity gate"
        assert dropped == []

    def test_the_inversion_and_the_critique_are_separated_by_prose_not_evidence(self):
        """Same cited line, opposite meaning -> opposite outcome. This is the whole carve-out."""
        inversion = _issue(REMOVED_LINE, title="contract_date is being marked retrospective")
        critique = _issue(REMOVED_LINE, title="this PR deletes a needed retrospective marker")
        kept_i, dropped_i = _verify_evidence([inversion], DIFF_45)
        kept_c, dropped_c = _verify_evidence([critique], DIFF_45)
        assert kept_i == [] and dropped_i[0]["_drop_reason"] == "evidence_only_removed"
        assert len(kept_c) == 1 and dropped_c == []


class TestRubricBarsUnverifiableClaims:
    """A SECOND false-REQUEST-CHANGES mode, caught live while reviewing this very PR (#2401):

        "[WARNING] The test case for the regression is added but not executed"
        Evidence: the test file's own DOCSTRING line.

    Disproved directly — pytest resolved the node ID and ran it:
        tests/test_forge_polarity_inversion.py::TestTheInversionIsCaught::
        test_finding_citing_the_removed_line_is_dropped PASSED

    This is NOT the polarity bug: the cited line really is an ADDED line, so the polarity gate
    correctly leaves it alone. It is a claim about RUNTIME behaviour the reviewer cannot observe
    from a diff. Only the rubric can prevent it, so pin the rule.
    """

    def test_rubric_forbids_claiming_a_test_does_not_run(self):
        rubric = pda._FALSE_POSITIVE_RUBRIC.lower()
        assert "not executed" in rubric or "not run" in rubric
        assert "cannot run" in rubric

    def test_rubric_still_allows_flagging_a_visibly_skipped_test(self):
        """The bar must not blind the reviewer to a test that is genuinely disabled IN the diff."""
        assert "skip" in pda._FALSE_POSITIVE_RUBRIC.lower()


class TestGroundingSemanticsPreserved:
    def test_fabricated_evidence_is_still_ungrounded(self):
        """Polarity must not cannibalise the #5009 grounding signal: evidence on NEITHER
        side is still a fabrication, and still counts toward the ungrounded floor."""
        kept, dropped = _verify_evidence([_issue("this line is nowhere in the diff")], DIFF_45)
        assert kept == []
        assert dropped[0]["_drop_reason"] == "evidence_not_in_diff"
        assert _count_ungrounded(dropped) == 1

    def test_empty_or_trivial_evidence_is_never_dropped(self):
        """This gate only ever removes confident noise — ambiguity is kept."""
        assert _evidence_polarity("", DIFF_45) == "added"
        assert _evidence_polarity("x,", DIFF_45) == "added"
