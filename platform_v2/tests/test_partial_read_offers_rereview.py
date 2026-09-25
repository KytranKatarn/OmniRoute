"""A coverage demotion must always offer the way out of it (#6780).

THE DEFECT. #5836 demoted a review when a whole file was DROPPED; #5910 widened the
demotion to a file the review window cut MID-FILE. Only the first half ever got a
reader. ``coverage_dropped_paths`` matches the note's "  - " listing, so a partial
read returned ``[]`` — and the detail pane gated its entire coverage panel on
``dropped_files.length``. The panel carries the "F.O.R.G.E. re-review — full diff"
button.

Net effect: a PR demoted BECAUSE a file was truncated offered no button to re-read it.
The row said NEEDS REVIEW, the label said "0 unread", and the only remaining path was
the CLI. Measured 2026-09-16 on archie-code #71 (inference.py at 89%) and
archie-platform #3390 (patch_sanity.py at 49%).

The invariant: if the gate demoted the row, the panel that explains it — and the
control that clears it — must render. Anything else is a dead end the operator cannot
see out of.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.review_coverage import MARKER  # noqa: E402
from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    coverage_dropped_paths,
    coverage_partial_paths,
    merge_state,
)

_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "tools" / "repair_bay.html"

# The real archie-code #71 note, verbatim in shape — the case that had no button.
PARTIAL_ONLY = (
    "VERDICT: APPROVE\n\n"
    f"{MARKER} COVERAGE: 3 of 4 files were read IN FULL by this review.\n"
    "READ ONLY IN PART (the window cut mid-file — #5910):\n"
    "  * archie_engine/inference.py — about 89% shown\n"
    "\n"
    "A verdict cannot cover code the reviewer never read.\n"
    "VERDICT: NEEDS REVIEW\n"
)

DROPPED_ONLY = (
    "VERDICT: APPROVE\n\n"
    f"{MARKER} COVERAGE: 2 of 3 files were read IN FULL by this review.\n"
    "  - platform_v2/deploy.py\n"
    "\n"
    "VERDICT: NEEDS REVIEW\n"
)

BOTH = (
    "VERDICT: APPROVE\n\n"
    f"{MARKER} COVERAGE: 1 of 3 files were read IN FULL by this review.\n"
    "  - platform_v2/deploy.py\n"
    "READ ONLY IN PART (the window cut mid-file — #5910):\n"
    "  * platform_v2/services/patch_sanity.py — about 49% shown\n"
    "\n"
    "VERDICT: NEEDS REVIEW\n"
)


class TestPartialPathsAreParsed(unittest.TestCase):
    def test_the_real_71_note(self):
        self.assertEqual(
            coverage_partial_paths(PARTIAL_ONLY),
            [{"path": "archie_engine/inference.py", "shown_pct": 89}],
        )

    def test_dropped_and_partial_do_not_bleed_into_each_other(self):
        """Each reader must claim only its own listing, or one file is counted twice."""
        self.assertEqual(coverage_dropped_paths(BOTH), ["platform_v2/deploy.py"])
        self.assertEqual(
            coverage_partial_paths(BOTH),
            [{"path": "platform_v2/services/patch_sanity.py", "shown_pct": 49}],
        )

    def test_dropped_only_has_no_partials(self):
        self.assertEqual(coverage_partial_paths(DROPPED_ONLY), [])

    def test_a_malformed_percentage_keeps_the_path(self):
        """The PATH is what a human acts on. Discarding the row over an unparseable
        percentage would re-create the very blind spot this module exists to close."""
        note = (
            f"VERDICT: APPROVE\n\n{MARKER} COVERAGE: 1 of 2 files were read IN FULL.\n"
            "READ ONLY IN PART (the window cut mid-file — #5910):\n"
            "  * some/file.py — about ???% shown\n\nVERDICT: NEEDS REVIEW\n"
        )
        got = coverage_partial_paths(note)
        self.assertEqual(len(got), 1)
        self.assertIn("some/file.py", got[0]["path"])

    def test_no_marker_and_empty_are_safe(self):
        for bad in (None, "", "VERDICT: APPROVE"):
            self.assertEqual(coverage_partial_paths(bad), [])


class TestMergeStateTellsTheTruth(unittest.TestCase):
    def test_partial_only_is_still_a_coverage_demotion(self):
        ms = merge_state("reviewed", PARTIAL_ONLY)
        self.assertEqual(ms["state"], "coverage_only")
        self.assertTrue(ms["partial_files"], "the panel's render gate reads this")

    def test_label_never_says_zero_unread_for_a_partial_read(self):
        """THE FABRICATION GUARD. "COVERAGE · 0 unread" states the opposite of why the
        row was demoted, and reads to an operator as 'nothing is unread'."""
        label = merge_state("reviewed", PARTIAL_ONLY)["label"]
        self.assertNotIn("0 unread", label)
        self.assertIn("partly read", label)

    def test_label_counts_both_kinds_when_both_exist(self):
        label = merge_state("reviewed", BOTH)["label"]
        self.assertIn("1 unread", label)
        self.assertIn("1 partial", label)

    def test_dropped_only_label_is_unchanged(self):
        """NON-REGRESSION: the case that always worked must keep its wording."""
        self.assertEqual(merge_state("reviewed", DROPPED_ONLY)["label"], "COVERAGE · 1 unread")

    def test_every_state_carries_the_key(self):
        """A renderer reading ms.partial_files must never hit undefined."""
        for status, summary in (
            ("in_progress", ""),
            ("pending", ""),
            ("reviewed", "VERDICT: APPROVE"),
            ("reviewed", "VERDICT: REQUEST CHANGES"),
            ("reviewed", PARTIAL_ONLY),
        ):
            self.assertIn("partial_files", merge_state(status, summary), (status, summary[:20]))


class TestTheButtonIsReachable(unittest.TestCase):
    """The regression guard proper — this is the assertion that was missing."""

    def setUp(self):
        self.tpl = _TEMPLATE.read_text(encoding="utf-8")

    def test_panel_is_gated_on_the_state_not_on_a_list_length(self):
        """Coverage detail renders whenever the server supplies a missing or partial file."""
        self.assertIn("covDropped.length || covPartial.length", self.tpl)
        self.assertNotIn("msCov.state === 'coverage_only')", self.tpl)

    def test_the_rereview_button_lives_inside_that_panel(self):
        """If the button moves out from under the gate this test stops meaning anything,
        so pin that it is still the panel that carries it."""
        start = self.tpl.index("msCov.state === 'coverage_only'")
        panel = self.tpl[start : start + 6000]
        self.assertIn("F.O.R.G.E. re-review — full diff", panel)
        self.assertIn("triggerPRReReview", panel)

    def test_the_button_requests_the_wide_path(self):
        """A button that re-runs the SAME narrow window would be theatre. `wide: true` is
        what routes the whole diff through the coverage-aware reviewer."""
        fn = self.tpl[self.tpl.index("function triggerPRReReview") :][:1200]
        self.assertIn("wide: true", fn)
        self.assertIn("/analyze", fn)

    def test_completed_reviews_without_coverage_have_a_rereview_action(self):
        source = self.tpl
        self.assertIn("pr.review_status === 'reviewed'", source)
        self.assertIn("!coverageReviewActionRendered", source)
        self.assertIn("generalReBtn.onclick", source)
        self.assertIn("triggerPRReReview", source)

    def test_notifications_use_the_lcars_modal(self):
        start = self.tpl.index("function triggerPRReReview")
        end = self.tpl.index("function prFileUrl", start)
        fn = self.tpl[start:end]
        self.assertIn("_rbLcarsAlert", fn)
        self.assertNotRegex(fn, r"\balert\s*\(")

    def test_partial_files_are_rendered_with_their_percentage(self):
        self.assertIn("partial_files", self.tpl)
        self.assertIn("shown_pct", self.tpl)


if __name__ == "__main__":
    unittest.main()


class TestTheButtonReviewsTheRightPR(unittest.TestCase):
    """#6776 on the live path — found by actually clicking the button (2026-09-16).

    The render fix above made the control reachable. Clicking it then re-reviewed the
    WRONG PR: the detail pane showed archie-code #71 ("feat(engine): fleet | omniroute
    provider switch") and the server reviewed archie-platform #71 ("chore(deps): bump
    pytest 8.1.1 -> 9.0.3"), because the route called a bare get_review(pr_number).

    The failure is quiet in the worst way — the re-review "comes back unchanged" in
    seconds, which reads as a stable verdict rather than as a review that never ran on
    the PR in front of you.
    """

    def setUp(self):
        self.tpl = _TEMPLATE.read_text(encoding="utf-8")
        self.routes = (Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "github_routes.py").read_text(
            encoding="utf-8"
        )
        start = self.routes.index("def forge_pr_review_analyze(pr_number):")
        self.body = self.routes[start : self.routes.index("def forge_pr_review_analyze_all")]

    def test_route_no_longer_resolves_a_bare_pr_number(self):
        self.assertNotIn("get_review(pr_number)\n", self.body)
        self.assertIn("get_review(pr_number, repo=", self.body)

    def test_route_fails_closed_when_the_number_is_ambiguous(self):
        """Choosing a repo for the caller is how this stayed invisible. 409, with names."""
        self.assertIn("repos_for_pr_number", self.body)
        self.assertIn("409", self.body)

    def test_route_validates_a_supplied_repo(self):
        self.assertIn("_is_valid_repo", self.body)
        self.assertIn("400", self.body)

    def test_background_thread_does_not_fall_back_to_a_hardcoded_repo(self):
        """The thread's `repo` is what mark_review_done writes against — a hardcoded
        default there is what stored the verdict on the wrong row."""
        self.assertNotIn('review.get("repo", "KytranKatarn/archie-platform")', self.body)

    def test_every_analyze_caller_sends_a_repo(self):
        for fn in ("triggerPRReReview", "triggerPRAnalysis"):
            sig = f"function {fn}(prNumber, repo)"
            self.assertIn(sig, self.tpl, f"{fn} still takes only a PR number")
        for call in ("triggerPRReReview(pr.pr_number, pr.repo)", "triggerPRAnalysis(pr.pr_number, pr.repo)"):
            self.assertIn(call, self.tpl, f"a caller still passes the number alone: {call}")

    def test_repos_for_pr_number_sees_the_collision(self):
        """NON-VACUITY against live data: if PR 71 stopped existing in two repos this
        whole class would pass for the wrong reason, so assert the collision is real."""
        from tools.repair_bay.services.pr_review_service import repos_for_pr_number

        repos = repos_for_pr_number(71)
        if not repos:
            self.skipTest("no DB access from this test environment")
        self.assertGreater(len(repos), 1, f"expected PR 71 in >1 repo, got {repos}")


class TestRepoLookupFailsClosed(unittest.TestCase):
    """A failed repo lookup must not read as "no collision" (#6787).

    `repos_for_pr_number` used to fail OPEN to []. Its only consumer is the ambiguity
    gate in forge_pr_review_analyze, whose test is `len(candidates) > 1` — which [] passes
    silently. So a transient DB error restored exactly the pre-#6776 behaviour of reviewing
    whichever repo get_review(pr_number) picked. Found by F.O.R.G.E. reviewing #3401.
    """

    def test_db_error_returns_None_not_empty_list(self):
        import tools.repair_bay.services.pr_review_service as svc

        def _boom(*a, **k):
            raise RuntimeError("simulated DB outage")

        orig = svc.get_db_cursor
        svc.get_db_cursor = _boom
        try:
            got = svc.repos_for_pr_number(71)
        finally:
            svc.get_db_cursor = orig

        self.assertIsNone(
            got,
            "a failed lookup returned %r — [] is indistinguishable from 'no collision' "
            "and sails through the caller's len(...) > 1 gate" % (got,),
        )

    def test_route_checks_None_before_the_length_gate(self):
        """Ordering is the invariant: a None check placed after `len()` never runs."""
        import os

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools",
            "repair_bay",
            "github_routes.py",
        )
        with open(path, encoding="utf-8") as fh:
            src = fh.read()

        none_at = src.find("if _candidates is None:")
        len_at = src.find("if len(_candidates) > 1:")
        self.assertNotEqual(none_at, -1, "the None guard is missing — a failed lookup falls through")
        self.assertNotEqual(len_at, -1, "the ambiguity gate itself is missing")
        self.assertLess(
            none_at,
            len_at,
            "the None guard must precede the length gate; after it, len(None) raises instead",
        )
