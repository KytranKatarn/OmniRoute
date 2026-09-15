"""Merge state must be visible BEFORE you click (#5853).

The Merge button used to render unconditionally green and enabled for every open PR,
beside a badge showing `review_status` — whose green "reviewed" is identical for an
APPROVE, a REQUEST CHANGES and a coverage demotion. So a PR the gate refuses displayed
as ready to merge, and you learned the truth by clicking. Measured live on PR #2736:
first click 422, second click (with the ack) 200.

Two things are tested, and the SECOND is the one that protects the safety property:

  1. The pure mapping summary -> state, including the case that must never be confused:
     a REQUEST CHANGES that ALSO carries a coverage block is changes_requested, never
     coverage_only. An ack is consent to unread files; it is never consent to a defect.

  2. A guard that the verdict rule has not leaked into the client. The UI renders a
     state the server computed; it must never derive one. #2722 existed specifically to
     collapse two implementations of that rule into one, and #2458 reached main because
     a safety rule lived in one path and not another.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.repair_bay.services.pr_review_service import merge_state  # noqa: E402

_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "tools" / "repair_bay.html"

APPROVED = "SUMMARY ok\nISSUES\nNo issues found.\nVERDICT: APPROVE"
REQUEST_CHANGES = "SUMMARY x\nISSUES\n- [CRITICAL] boom\nVERDICT: REQUEST CHANGES"
COVERAGE_DEMOTED = (
    "SUMMARY ok\nISSUES\nNo issues found.\nVERDICT: APPROVE\n\n"
    "[review-coverage] COVERAGE: 2 of 7 files were in the diff window this review read.\n"
    "NOT REVIEWED (truncated away before the model saw them):\n"
    "  - platform_v2/a.py\n  - platform_v2/b.py\n"
    "VERDICT: NEEDS REVIEW"
)
CHANGES_PLUS_COVERAGE = (
    "SUMMARY x\nISSUES\n- [CRITICAL] boom\nVERDICT: REQUEST CHANGES\n\n"
    "[review-coverage] COVERAGE: 1 of 5 files were in the diff window this review read.\n"
    "NOT REVIEWED (truncated away before the model saw them):\n  - platform_v2/c.py\n"
    "VERDICT: NEEDS REVIEW"
)


class TestMergeStateMapping(unittest.TestCase):
    def test_approved(self):
        ms = merge_state("reviewed", APPROVED)
        self.assertEqual(ms["state"], "approved")
        self.assertTrue(ms["mergeable"])

    def test_changes_requested_is_not_mergeable(self):
        ms = merge_state("reviewed", REQUEST_CHANGES)
        self.assertEqual(ms["state"], "changes_requested")
        self.assertFalse(ms["mergeable"])
        self.assertTrue(ms["hint"], "a blocked button must carry its reason")

    def test_coverage_demotion_is_its_own_state(self):
        ms = merge_state("reviewed", COVERAGE_DEMOTED)
        self.assertEqual(ms["state"], "coverage_only")
        self.assertEqual(len(ms["dropped_files"]), 2)
        self.assertIn("unread", ms["label"])

    def test_request_changes_plus_coverage_stays_changes_requested(self):
        """THE case that must never be confused.

        If this mapped to coverage_only the UI would offer an amber 'Merge (N unread)'
        on a PR carrying a real defect, and the coverage ack would look like the way
        through. The ack is consent to UNREAD FILES, never to a defect.
        """
        ms = merge_state("reviewed", CHANGES_PLUS_COVERAGE)
        self.assertEqual(ms["state"], "changes_requested")
        self.assertFalse(ms["mergeable"])

    def test_in_progress_and_empty(self):
        self.assertEqual(merge_state("in_progress", "")["state"], "reviewing")
        self.assertEqual(merge_state("pending", "")["state"], "awaiting_review")
        self.assertEqual(merge_state("reviewed", "")["state"], "awaiting_review")
        self.assertEqual(merge_state(None, None)["state"], "awaiting_review")

    def test_never_raises_and_always_shaped(self):
        for status in (None, "", "reviewed", "weird"):
            for summary in (None, "", "   ", APPROVED, "garbage"):
                ms = merge_state(status, summary)
                for key in ("state", "mergeable", "label", "hint", "dropped_files"):
                    self.assertIn(key, ms)

    def test_a_non_mergeable_state_always_explains_itself(self):
        for summary in (REQUEST_CHANGES, CHANGES_PLUS_COVERAGE):
            ms = merge_state("reviewed", summary)
            self.assertFalse(ms["mergeable"])
            self.assertTrue(ms["hint"].strip(), "disabled with no reason is the old bug")


class TestVerdictRuleHasNotLeakedIntoTheClient(unittest.TestCase):
    """The UI renders a state; it never derives one."""

    def test_template_does_not_parse_verdicts_itself(self):
        src = _TEMPLATE.read_text()
        # The row renderer must consume pr.merge_state, not re-read the summary.
        self.assertIn("pr.merge_state", src, "the row must consume the server's state")
        forbidden = [
            r"VERDICT:\s*APPROVE",  # parsing the verdict text client-side
            r"verdict_is_approved",  # calling the server predicate's name in JS
            r"coverage_only_demotion",
        ]
        for pattern in forbidden:
            hits = [
                ln
                for ln in src.splitlines()
                if re.search(pattern, ln) and not ln.strip().startswith(("//", "*", "<!--"))
            ]
            self.assertEqual(hits, [], f"verdict rule leaked into the client via {pattern!r}: {hits[:2]}")


class TestCoverageFilesVisibleBeforeTheClick(unittest.TestCase):
    """#6769 — 'COVERAGE · N unread' counted the files but never named them, so the
    decision 'is this a README or the deploy path' was unreachable until a refused
    merge. The row now carries an Info button, the detail panel LISTS the dropped
    files (clickable to read on GitHub, from the SERVER's dropped_files — never
    parsed from the summary client-side), and a re-review button routes the WHOLE
    diff through the coverage-aware full-window reviewer. This class guards
    disclosure before any click; the merge-gate tests own the blocked-until-clicked
    property.
    """

    def test_an_info_button_opens_the_detail(self):
        src = _TEMPLATE.read_text()
        self.assertIn("infoBtn.textContent = 'Info'", src)
        self.assertIn("showPRDetail(pr);", src)

    def test_the_detail_lists_the_dropped_files_from_server_state(self):
        src = _TEMPLATE.read_text()
        # The coverage box may render ONLY when the server state says coverage_only,
        # and it must consume the server's list, not build one.
        idx = src.index("msCov.dropped_files")
        self.assertIn("state === 'coverage_only'", src[:idx])
        self.assertIn("covList.appendChild(rowEl)", src)

    def test_the_dropped_files_are_clickable_to_read_at_the_pr_head(self):
        """Each dropped path opens GitHub blob/{head_branch} — the PR's own commit,
        not main's pre-merge state — with the host taken from the row (cross-repo)."""
        src = _TEMPLATE.read_text()
        self.assertIn("prFileUrl(pr, f)", src)
        self.assertIn("pr.head_branch", src)
        self.assertIn("'/blob/'", src)
        self.assertIn("fl.target = '_blank'", src)

    def test_re_review_routes_the_whole_diff(self):
        """The re-review button must post `wide`, not re-trigger the same capped pass."""
        src = _TEMPLATE.read_text()
        self.assertIn("triggerPRReReview", src)
        self.assertIn("{wide: true}", src)

    def test_the_client_never_rebuilds_the_unread_list_from_the_summary(self):
        """Re-deriving the dropped list from the review text would be the verdict rule
        leaking into the client (the same #2722/#2458 hazard) — the count already got
        that wrong once; the list must not."""
        src = _TEMPLATE.read_text()
        for pat in (r"coverage_dropped_paths", r"review_coverage", r"NOT\s*REVIEWED"):
            hits = [
                ln
                for ln in src.splitlines()
                if re.search(pat, ln) and not ln.strip().startswith(("//", "*", "<!--"))
            ]
            self.assertEqual(hits, [], f"client rebuilds the coverage list via {pat!r}: {hits[:2]}")


class TestWideReReviewUsesTheCoverageAwarePath(unittest.TestCase):
    """#6769 — the `wide` re-review must use the machinery that ESCALATES and MEASURES
    the window (_obtain_review_summary: size-rule model escalation + honest coverage
    note). A re-review down the freeform prompt would reuse the SAME capped window and
    re-drop the same files while looking like progress — the #5836 failure shape."""

    _ROUTES = Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "github_routes.py"

    def test_route_reads_wide_from_the_body(self):
        routes = self._ROUTES.read_text()
        self.assertIn('wide = bool((request.get_json(silent=True) or {}).get("wide"))', routes)

    def test_wide_branch_calls_the_coverage_aware_summary(self):
        routes = self._ROUTES.read_text()
        self.assertIn("_obtain_review_summary(review, diff, pr_number, repo)", routes)
        self.assertIn(
            "_build_prompt",
            routes,
            "the default (non-wide) path must stay the original freeform prompt",
        )


class TestOverviewLivesOnTheDashboard(unittest.TestCase):
    def test_overview_block_is_inside_a_tab_panel(self):
        """It used to sit outside every .tab-content, so it rendered on EVERY tab."""
        src = _TEMPLATE.read_text()
        idx = src.index("REPAIR BAY OVERVIEW")
        dash = src.rfind('<div id="tab-reviews" class="tab-content active">', 0, idx)
        self.assertNotEqual(dash, -1, "overview is not inside the dashboard tab panel")


class TestShippedTileReadsARealColumn(unittest.TestCase):
    def test_template_uses_deployed_at_not_a_phantom_column(self):
        """`implemented_at` does not exist; reading it silently fell back to proposed_at."""
        src = _TEMPLATE.read_text()
        self.assertNotIn("p.implemented_at", src, "implemented_at is not a column on improvement_proposals")
        self.assertIn("p.deployed_at", src)

    def test_service_serialises_deployed_at(self):
        """A client fix is useless if the field never reaches the payload (#5853 live find)."""
        svc = (Path(__file__).resolve().parents[1] / "services" / "proposal_service.py").read_text()
        self.assertIn("ip.deployed_at", svc)


if __name__ == "__main__":
    unittest.main()
