"""#5836 — a verdict may not out-run what the reviewer actually read.

The load-bearing test is `test_pr_2713_replay`: the real measured shape of the failure,
so a regression reproduces the original defect rather than an abstraction of it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.review_coverage import (  # noqa: E402
    MARKER,
    annotate,
    coverage,
    coverage_note,
    diff_files,
    is_low_signal_path,
    summarize,
)
from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    parse_verdict,
    verdict_is_approved,
)


def _hunk(path, body="+x = 1\n"):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n{body}"


class TestDiffFiles(unittest.TestCase):
    def test_parses_paths_in_order(self):
        d = _hunk("a/one.py") + _hunk("b/two.py")
        self.assertEqual(diff_files(d), ["a/one.py", "b/two.py"])

    def test_empty_and_none(self):
        self.assertEqual(diff_files(None), [])
        self.assertEqual(diff_files(""), [])


class TestCoverage(unittest.TestCase):
    def test_full_coverage(self):
        d = _hunk("one.py") + _hunk("two.py")
        cov = coverage(d, d)
        self.assertTrue(cov["complete"])
        self.assertEqual((cov["total"], cov["reviewed"], cov["dropped"]), (2, 2, []))

    def test_dropped_files_detected(self):
        full = _hunk("one.py") + _hunk("two.py") + _hunk("three.py")
        shown = _hunk("one.py")
        cov = coverage(full, shown)
        self.assertFalse(cov["complete"])
        self.assertEqual(cov["reviewed"], 1)
        self.assertEqual(cov["dropped"], ["two.py", "three.py"])

    def test_unparseable_diff_does_not_cry_wolf(self):
        """A diff with no file headers yields no dropped files — an unreadable diff must
        behave as it does today, not block every review."""
        cov = coverage("some prose with no diff headers", "")
        self.assertTrue(cov["complete"])
        self.assertEqual(cov["total"], 0)


class TestAnnotate(unittest.TestCase):
    def test_complete_coverage_leaves_summary_untouched(self):
        s = "SUMMARY\nfine\n\nVERDICT: APPROVE"
        d = _hunk("one.py")
        self.assertEqual(annotate(s, coverage(d, d)), s)
        self.assertTrue(verdict_is_approved(annotate(s, coverage(d, d))))

    def test_partial_coverage_demotes_approve(self):
        s = "SUMMARY\nlooks good\n\nISSUES\nNone.\n\nVERDICT: APPROVE"
        cov = coverage(_hunk("one.py") + _hunk("two.py"), _hunk("one.py"))
        out = annotate(s, cov)
        self.assertTrue(verdict_is_approved(s), "precondition: original WAS an approval")
        self.assertFalse(verdict_is_approved(out), "a partial review must not read as approved")
        self.assertEqual(parse_verdict(out), "NEEDS REVIEW")

    def test_demotion_is_needs_review_not_request_changes(self):
        """The model found nothing wrong with what it DID read. Manufacturing a blocking
        finding would be the very failure ADR-001's gates exist to prevent."""
        cov = coverage(_hunk("one.py") + _hunk("two.py"), _hunk("one.py"))
        out = annotate("SUMMARY\nok\n\nVERDICT: APPROVE", cov)
        self.assertNotEqual(parse_verdict(out), "REQUEST CHANGES")

    def test_original_text_survives_verbatim(self):
        s = "SUMMARY\nthe retry loop is unbounded\n\nVERDICT: APPROVE"
        cov = coverage(_hunk("one.py") + _hunk("two.py"), _hunk("one.py"))
        out = annotate(s, cov)
        self.assertIn("the retry loop is unbounded", out)
        self.assertIn("VERDICT: APPROVE", out, "the model's own verdict line is preserved")

    def test_dropped_paths_are_named_not_just_counted(self):
        cov = coverage(_hunk("a.py") + _hunk("services/deploy.py"), _hunk("a.py"))
        out = annotate("VERDICT: APPROVE", cov)
        self.assertIn("services/deploy.py", out)

    def test_idempotent(self):
        cov = coverage(_hunk("one.py") + _hunk("two.py"), _hunk("one.py"))
        once = annotate("VERDICT: APPROVE", cov)
        twice = annotate(once, cov)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count(MARKER), 1)

    def test_none_summary_passes_through(self):
        cov = coverage(_hunk("one.py") + _hunk("two.py"), _hunk("one.py"))
        self.assertIsNone(annotate(None, cov))

    def test_a_blocking_verdict_stays_blocking(self):
        """Partial coverage must not soften a REQUEST CHANGES into NEEDS REVIEW."""
        s = "SUMMARY\nbroken\n\nVERDICT: REQUEST CHANGES"
        cov = coverage(_hunk("one.py") + _hunk("two.py"), _hunk("one.py"))
        self.assertEqual(parse_verdict(annotate(s, cov)), "REQUEST CHANGES")

    def test_long_dropped_list_is_capped_but_says_so(self):
        full = "".join(_hunk(f"f{i}.py") for i in range(20))
        cov = coverage(full, _hunk("f0.py"))
        note = coverage_note(cov, max_listed=3)
        self.assertIn("and 16 more", note)


class TestPR2713Replay(unittest.TestCase):
    """The measured failure, replayed. PR #2713: 5 files, 2 kept, and F.O.R.G.E. reported
    'only a markdown file update' while approving a change to a pre-deploy BACKUP path."""

    FULL = (
        _hunk(".claude/rules/module-capability-index.md")
        + _hunk("platform_v2/services/predeploy_scope.py")
        + _hunk("platform_v2/services/proposal_service.py")
        + _hunk("platform_v2/tests/test_predeploy_scope.py")
        + _hunk("platform_v2/tools/backup_manager/routes_restore.py")
    )
    SHOWN = _hunk(".claude/rules/module-capability-index.md") + _hunk("platform_v2/services/predeploy_scope.py")
    REAL_SUMMARY = (
        "SUMMARY\nThe diff shows no relevant changes to the codebase, only a markdown file "
        "update which does not impact the functionality.\n\nISSUES\nNo issues found.\n\n"
        "VERDICT: APPROVE"
    )

    def test_pr_2713_replay(self):
        cov = coverage(self.FULL, self.SHOWN)
        self.assertEqual((cov["total"], cov["reviewed"]), (5, 2))
        self.assertIn("platform_v2/services/proposal_service.py", cov["dropped"])

        # Before: a confident approval of 49% of the PR.
        self.assertTrue(verdict_is_approved(self.REAL_SUMMARY))

        # After: it can no longer read as an approval, and the merge gate inherits that
        # through verdict_is_approved without any change at the gate itself.
        out = annotate(self.REAL_SUMMARY, cov)
        self.assertFalse(verdict_is_approved(out))
        self.assertIn("platform_v2/tests/test_predeploy_scope.py", out)
        self.assertIn("2 of 5 files", out)

    def test_summarize_for_logs(self):
        self.assertIn("PARTIAL: 2/5", summarize(coverage(self.FULL, self.SHOWN)))
        self.assertIn("full coverage", summarize(coverage(self.FULL, self.FULL)))


class TestLowSignalPath(unittest.TestCase):
    def test_matches_patterns(self):
        self.assertTrue(is_low_signal_path(".claude/rules/x.md", [r"^\.claude/.*\.md$"]))
        self.assertFalse(is_low_signal_path("services/deploy.py", [r"^\.claude/.*\.md$"]))

    def test_no_patterns_means_nothing_is_low_signal(self):
        self.assertFalse(is_low_signal_path(".claude/rules/x.md"))


if __name__ == "__main__":
    unittest.main()
