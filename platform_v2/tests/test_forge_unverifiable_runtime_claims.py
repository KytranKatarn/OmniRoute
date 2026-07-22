"""Regression: the reviewer may not BLOCK on a claim it cannot check (#5098).

Caught live on PR #2401 — the fix for #5075 — where F.O.R.G.E. returned REQUEST CHANGES on:

    [WARNING] "The test case for the regression is added but not executed"
    Evidence: the test file's own DOCSTRING line.

Disproved by running the node ID:
    tests/test_forge_polarity_inversion.py::TestTheInversionIsCaught::
    test_finding_citing_the_removed_line_is_dropped PASSED

Neither existing gate can catch it, and that is the point of a separate guard:
  * the evidence-grounding gate (#5009) sees a REAL added line -> grounded,
  * the polarity gate (#5075) sees an ADDED line -> correctly leaves it alone.
The CITATION is real. The CLAIM is unfalsifiable from a diff, because the reviewer cannot run
anything and pytest collects test_*.py / class Test* / def test_* automatically.

The guard is deliberately narrow — the findings next door are worth keeping. All externals are
pure; no DB, no GitHub, no model.
"""

from tools.repair_bay.services.pr_diff_analyzer import (
    _count_ungrounded,
    _is_unverifiable_test_execution_claim,
    _verify_evidence,
)

# The shape of the PR #2401 diff: a brand-new, perfectly ordinary pytest file.
DIFF_NEW_TEST = '''diff --git a/platform_v2/tests/test_forge_polarity_inversion.py b/platform_v2/tests/test_forge_polarity_inversion.py
new file mode 100644
--- /dev/null
+++ b/platform_v2/tests/test_forge_polarity_inversion.py
@@ -0,0 +1,5 @@
+"""Regression: a review finding may only be raised against an ADDED line (#5075)."""
+
+class TestTheInversionIsCaught:
+    def test_finding_citing_the_removed_line_is_dropped(self):
+        assert True
'''

DOCSTRING_EVIDENCE = '+"""Regression: a review finding may only be raised against an ADDED line (#5075)."""'


def _issue(title, evidence=DOCSTRING_EVIDENCE, why="w", severity="WARNING"):
    return {"severity": severity, "title": title, "why": why, "evidence": evidence}


class TestTheUnverifiableClaimIsDropped:
    def test_the_exact_2401_finding_is_dropped(self):
        """THE REGRESSION, verbatim from the live review."""
        issue = _issue("The test case for the regression is added but not executed")
        kept, dropped = _verify_evidence([issue], DIFF_NEW_TEST)
        assert kept == [], "a blocking claim the reviewer cannot check must not survive"
        assert dropped[0]["_drop_reason"] == "unverifiable_runtime_claim"

    def test_phrasing_variants_are_caught(self):
        for title in (
            "this test is never run",
            "the new test will not be executed",
            "test is added but not wired up",
            "these tests are never collected",
        ):
            assert _is_unverifiable_test_execution_claim(_issue(title), DIFF_NEW_TEST), title

    def test_it_is_a_trusted_correction_not_a_grounding_failure(self):
        """The model WAS reading its input — it asserted something unknowable. Counting this as
        ungrounded would wrongly floor an otherwise clean APPROVE (#5009)."""
        _, dropped = _verify_evidence(
            [_issue("The test case for the regression is added but not executed")], DIFF_NEW_TEST
        )
        assert _count_ungrounded(dropped) == 0


class TestTheGuardStaysNarrow:
    """Each of these is a finding worth KEEPING — the guard must not reach them."""

    def test_a_visibly_skipped_test_can_still_be_flagged(self):
        """If the diff SHOWS the test disabled, 'it does not run' is TRUE and must survive."""
        diff = DIFF_NEW_TEST.replace(
            "+class TestTheInversionIsCaught:",
            "+@pytest.mark.skip(reason='wip')\n+class TestTheInversionIsCaught:",
        )
        assert not _is_unverifiable_test_execution_claim(_issue("this test is never run"), diff)
        kept, _ = _verify_evidence([_issue("this test is never run")], diff)
        assert len(kept) == 1

    def test_dead_code_in_production_is_untouched(self):
        """'This helper is never called' about NON-test code is verifiable from the diff and is a
        genuinely valuable finding — it must not be swept up."""
        diff = (
            "diff --git a/app/util.py b/app/util.py\n--- a/app/util.py\n+++ b/app/util.py\n"
            "@@ -1 +1,3 @@\n+def orphan_helper():\n+    return 1\n"
        )
        issue = _issue("orphan_helper is never called", evidence="+def orphan_helper():")
        assert not _is_unverifiable_test_execution_claim(issue, diff)
        kept, _ = _verify_evidence([issue], diff)
        assert len(kept) == 1

    def test_non_execution_wording_without_a_pytest_construct_is_untouched(self):
        diff = (
            "diff --git a/app/util.py b/app/util.py\n--- a/app/util.py\n+++ b/app/util.py\n"
            "@@ -1 +1,2 @@\n+CONFIG = {}\n"
        )
        assert not _is_unverifiable_test_execution_claim(_issue("the test suite is not executed"), diff)

    def test_an_ordinary_finding_on_a_test_file_is_untouched(self):
        """Only the non-execution CLAIM is filtered — normal review of test code is unaffected."""
        issue = _issue(
            "assert True is a vacuous assertion",
            evidence="+        assert True",
        )
        assert not _is_unverifiable_test_execution_claim(issue, DIFF_NEW_TEST)
        kept, _ = _verify_evidence([issue], DIFF_NEW_TEST)
        assert len(kept) == 1
