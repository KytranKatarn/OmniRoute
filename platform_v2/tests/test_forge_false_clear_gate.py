"""GATE 5 — the false CLEAR (#5647).

Gates 1-4 in pr_diff_analyzer all interrogate FINDINGS (grounding / polarity /
checkable-claim / severity). An APPROVE carries NO findings, so the summary PROSE of a
clear was never checked against the diff. These fixtures are the three REAL reviews that
exposed it on 2026-08-16.

THE INVARIANT UNDER TEST: the gate strips the fabricated claim and KEEPS THE APPROVE. It
must never convert a clear into a block — a fabricated compliment is a reporting defect,
not evidence the code is broken.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.repair_bay.services.pr_diff_analyzer import (  # noqa: E402
    review_quality_flags,
    strip_unsupported_claims,
    unsupported_artifact_claims,
)

# ---------------------------------------------------------------- real fixtures

# PR #2603 — the wholesale fabrication. 1 file, no SQL, no tests.
PR2603_SUMMARY = (
    "The code changes appear to address the LinkedIn post comments issue by adapting to "
    "the new server-driven UI. The parameterized SQL usage and test addition are correct."
)
PR2603_DIFF = """--- a/archie-browser/skills/linkedin_post_comments.py
+++ b/archie-browser/skills/linkedin_post_comments.py
@@ -48,7 +48,7 @@
-  const SEL = 'article.comments-comment-entity, .comments-comment-item';
+  const NODE_SEL = '[componentkey^="replaceableComment_urn:li:comment:"]';
+  const body = card.querySelector('[data-testid="expandable-text-box"]');
"""

# A clean review of the SAME diff — nothing to strip.
PR2603_HONEST_SUMMARY = (
    "The change replaces dead class selectors with the SDUI component key. "
    "The extraction anchors on an attribute that survives a css-hash rebuild."
)


class TestUnsupportedArtifactClaims:
    def test_pr2603_sql_and_tests_are_both_fabricated(self):
        claims = unsupported_artifact_claims(PR2603_SUMMARY, PR2603_DIFF)
        assert "sql" in claims
        assert "tests" in claims

    def test_honest_summary_of_the_same_diff_is_untouched(self):
        assert unsupported_artifact_claims(PR2603_HONEST_SUMMARY, PR2603_DIFF) == []

    def test_empty_inputs_never_flag(self):
        assert unsupported_artifact_claims("", PR2603_DIFF) == []
        assert unsupported_artifact_claims(PR2603_SUMMARY, "") == []
        assert unsupported_artifact_claims(None, None) == []


class TestAbsenceObservationsAreLegitimate:
    """A reviewer NOTING that tests are missing is doing its job — never strip that."""

    @pytest.mark.parametrize(
        "summary",
        [
            "No tests were added for this change.",
            "The PR does not include tests.",
            "Consider adding a migration for the new column.",
            "This lacks SQL parameterisation and should be fixed.",
            "Tests are missing.",
        ],
    )
    def test_absence_observations_are_not_stripped(self, summary):
        assert unsupported_artifact_claims(summary, PR2603_DIFF) == []
        cleaned, claims = strip_unsupported_claims(summary, PR2603_DIFF)
        assert cleaned == summary
        assert claims == []


class TestClaimsBackedByTheDiffSurvive:
    def test_test_claim_is_kept_when_the_diff_really_adds_tests(self):
        diff = """--- /dev/null
+++ b/platform_v2/tests/test_thing.py
@@ -0,0 +1,3 @@
+def test_thing():
+    assert thing() == 1
"""
        assert unsupported_artifact_claims("Adds tests covering the new path.", diff) == []

    def test_sql_claim_is_kept_when_the_diff_really_has_sql(self):
        diff = """--- a/svc.py
+++ b/svc.py
@@ -1 +1,2 @@
+    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
"""
        assert unsupported_artifact_claims("The parameterized SQL usage is correct.", diff) == []

    def test_migration_claim_is_kept_when_the_diff_touches_migrations(self):
        diff = """--- /dev/null
+++ b/database/migrations/470_add_col.sql
@@ -0,0 +1 @@
+ALTER TABLE agents ADD COLUMN foo text;
"""
        assert unsupported_artifact_claims("Includes the migration.", diff) == []


class TestStripKeepsTheRestOfTheSummary:
    def test_only_the_fabricated_sentence_is_removed(self):
        cleaned, claims = strip_unsupported_claims(PR2603_SUMMARY, PR2603_DIFF)
        assert set(claims) == {"sql", "tests"}
        # the real observation survives...
        assert "server-driven UI" in cleaned
        # ...and the fabrication does not
        assert "parameterized SQL" not in cleaned
        assert "test addition" not in cleaned

    def test_summary_is_never_left_empty(self):
        cleaned, claims = strip_unsupported_claims(
            "The parameterized SQL usage and test addition are correct.", PR2603_DIFF
        )
        assert claims
        assert cleaned.strip()
        assert "withheld" in cleaned


class TestTheVerdictIsNeverTouched:
    """THE load-bearing invariant of #5647."""

    def test_flags_are_provenance_only_and_name_the_claim(self):
        flags = review_quality_flags("json", 0, [], ["sql", "tests"])
        assert "unsupported_summary_claim:sql" in flags
        assert "unsupported_summary_claim:tests" in flags
        # no flag implies or encodes a verdict
        assert not any("REQUEST" in f or "APPROVE" in f or "BLOCK" in f.upper() for f in flags)

    def test_clean_review_gets_no_flags(self):
        assert review_quality_flags("json", 0, [], []) == []
        assert review_quality_flags("json", 0, [], None) == []

    def test_existing_flags_still_work_alongside(self):
        flags = review_quality_flags("freeform", 2, [], ["sql"])
        assert "freeform_fallback" in flags
        assert "no_grounded_evidence" in flags
        assert "unsupported_summary_claim:sql" in flags
