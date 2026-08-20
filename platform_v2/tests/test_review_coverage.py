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
    file_band,
    is_low_signal_path,
    prioritize,
    split_blocks,
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


class TestFileBand(unittest.TestCase):
    def test_code_is_first(self):
        for p in ("platform_v2/services/deploy.py", "src/app.js", "migrations/001.sql"):
            self.assertEqual(file_band(p), 0, p)

    def test_tests_are_middle(self):
        for p in (
            "platform_v2/tests/test_x.py",
            "app/spec/thing.spec.ts",
            "pkg/foo_test.go",
            "test_top_level.py",
        ):
            self.assertEqual(file_band(p), 1, p)

    def test_docs_and_generated_are_last(self):
        for p in (
            ".claude/rules/module-capability-index.md",
            "README.md",
            "docs/design.rst",
            "package-lock.json",
            "poetry.lock",
            "static/js/app.min.js",
            "CHANGELOG",
        ):
            self.assertEqual(file_band(p), 2, p)

    def test_tests_outrank_docs_so_the_false_no_tests_flag_is_not_resurrected(self):
        """A sliced-off test file is the documented cause of the false 'no tests added'
        finding. Demoting tests below docs would manufacture it on exactly the PRs that
        DO add tests."""
        self.assertLess(file_band("platform_v2/tests/test_x.py"), file_band("README.md"))


class TestSplitBlocks(unittest.TestCase):
    def test_round_trip_is_byte_exact(self):
        d = _hunk("a.py") + _hunk("b.md")
        self.assertEqual("".join(b for _, b in split_blocks(d)), d)

    def test_preamble_is_kept_under_empty_path(self):
        d = "some preamble\n" + _hunk("a.py")
        blocks = split_blocks(d)
        self.assertEqual(blocks[0][0], "")
        self.assertEqual("".join(b for _, b in blocks), d)

    def test_no_headers_returns_one_block(self):
        self.assertEqual(split_blocks("no headers here"), [("", "no headers here")])


class TestPrioritize(unittest.TestCase):
    def test_no_op_when_the_diff_fits(self):
        d = _hunk("z.md") + _hunk("a.py")
        self.assertEqual(prioritize(d, cap=10_000), d, "a fitting diff must be byte-identical")

    def test_no_op_when_no_cap_given(self):
        d = _hunk("z.md") + _hunk("a.py")
        self.assertEqual(prioritize(d, None), d)

    def test_reorders_when_truncating(self):
        d = _hunk(".claude/rules/x.md") + _hunk("services/deploy.py") + _hunk("tests/test_d.py")
        out = prioritize(d, cap=1)
        self.assertEqual(
            diff_files(out),
            ["services/deploy.py", "tests/test_d.py", ".claude/rules/x.md"],
        )

    def test_reordering_loses_nothing(self):
        d = _hunk("z.md") + _hunk("a.py") + _hunk("tests/test_a.py")
        out = prioritize(d, cap=1)
        self.assertEqual(sorted(diff_files(out)), sorted(diff_files(d)))
        self.assertEqual(len(out), len(d), "no bytes added or dropped")

    def test_stable_within_a_band(self):
        d = _hunk("b.py") + _hunk("a.py")
        self.assertEqual(diff_files(prioritize(d, cap=1)), ["b.py", "a.py"])

    def test_preamble_stays_in_front(self):
        d = "PREAMBLE\n" + _hunk("z.md") + _hunk("a.py")
        self.assertTrue(prioritize(d, cap=1).startswith("PREAMBLE\n"))

    def test_coverage_is_unaffected_by_ordering(self):
        """coverage() compares SETS, so it stays exactly as honest either way."""
        d = _hunk("z.md") + _hunk("a.py")
        self.assertEqual(coverage(d, d)["complete"], coverage(prioritize(d, cap=1), d)["complete"])


class TestPR2713OrderingReplay(unittest.TestCase):
    """With ordering, the budget that a one-line rules edit used to consume goes to code."""

    def test_code_survives_a_tight_window(self):
        big_doc = "diff --git a/.claude/rules/big.md b/.claude/rules/big.md\n" + ("X" * 4000) + "\n"
        code = _hunk("platform_v2/services/proposal_service.py")
        tests = _hunk("platform_v2/tests/test_scope.py")
        full = big_doc + code + tests

        # Before: alphabetical order puts the 4 KB doc first and it eats the window.
        cap = len(code) + len(tests) + 10
        self.assertEqual(diff_files(full)[0], ".claude/rules/big.md")

        # After: both code files lead, so a cap that can hold them does.
        ordered = prioritize(full, cap)
        self.assertEqual(
            diff_files(ordered)[:2],
            ["platform_v2/services/proposal_service.py", "platform_v2/tests/test_scope.py"],
        )
        self.assertEqual(diff_files(ordered)[-1], ".claude/rules/big.md")
