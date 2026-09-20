"""A closed or merged PR must never render as mergeable (#6792).

Measured live 2026-09-20: five rows in the PR Review tab carried a CORRECT
`state='closed'` and still rendered `mergeable=True` behind a green Merge button —
three of them already MERGED. The data was right; `merge_state()` was simply never
handed the field, even though `list_reviews()` stamps its result onto the same row.

⚠️ THE WIRING IS THE BUG. A test that only exercises merge_state(pr_state=...) passes
against the pre-fix code, because the pre-fix function was fine in isolation — nothing
called it with the argument. `test_list_reviews_call_site_passes_pr_state` is therefore
the load-bearing test here, not the behaviour ones.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    MERGE_STATE_CLOSED,
    merge_state,
)

_APPROVED = "Looks good.\n\nVERDICT: APPROVE"
_CHANGES = "Problems found.\n\nVERDICT: REQUEST CHANGES"


class TestClosedPrIsNeverMergeable(unittest.TestCase):
    def test_closed_pr_with_an_APPROVED_verdict_is_not_mergeable(self):
        ms = merge_state("reviewed", _APPROVED, pr_state="closed")
        self.assertEqual(ms["state"], MERGE_STATE_CLOSED)
        self.assertFalse(ms["mergeable"], "a closed PR rendered as mergeable")
        self.assertEqual(ms["label"], "CLOSED")

    def test_merged_pr_says_MERGED_not_CLOSED(self):
        ms = merge_state("reviewed", _APPROVED, pr_state="merged")
        self.assertEqual(ms["label"], "MERGED")
        self.assertFalse(ms["mergeable"])

    def test_closed_beats_in_progress(self):
        """Ordering: 'REVIEWING…' on a dead PR is noise, not information."""
        ms = merge_state("in_progress", "", pr_state="closed")
        self.assertEqual(ms["state"], MERGE_STATE_CLOSED)
        self.assertFalse(ms["mergeable"])

    def test_case_and_whitespace_are_tolerated(self):
        for raw in ("CLOSED", " closed ", "Merged"):
            self.assertEqual(
                merge_state("reviewed", _APPROVED, pr_state=raw)["state"],
                MERGE_STATE_CLOSED,
                f"{raw!r} was not recognised as a terminal state",
            )


class TestAbsenceFailsSafeToOpen(unittest.TestCase):
    """Unknown state must behave EXACTLY as before — blocking an open PR stops work."""

    def test_none_and_empty_leave_an_approval_mergeable(self):
        for raw in (None, "", "   ", "open"):
            ms = merge_state("reviewed", _APPROVED, pr_state=raw)
            self.assertTrue(
                ms["mergeable"],
                f"pr_state={raw!r} blocked a genuinely open, approved PR",
            )
            self.assertNotEqual(ms["state"], MERGE_STATE_CLOSED)

    def test_omitting_the_argument_is_byte_identical_to_before(self):
        self.assertEqual(
            merge_state("reviewed", _APPROVED),
            merge_state("reviewed", _APPROVED, pr_state=None),
        )

    def test_an_open_rejection_is_still_a_rejection(self):
        ms = merge_state("reviewed", _CHANGES, pr_state="open")
        self.assertFalse(ms["mergeable"])
        self.assertNotEqual(ms["state"], MERGE_STATE_CLOSED)


class TestTheWiring(unittest.TestCase):
    """THE bug. Without these, the fix is a function nobody calls correctly."""

    @staticmethod
    def _source():
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools",
            "repair_bay",
            "services",
            "pr_review_service.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_every_merge_state_call_site_passes_pr_state(self):
        import re

        src = self._source()
        # calls that STAMP a row (assignment into a dict), not the def or the tests
        calls = re.findall(r'\["merge_state"\]\s*=\s*merge_state\((.*?)\)\n', src, re.S)
        self.assertGreaterEqual(len(calls), 2, "expected at least 2 stamping call sites")
        for args in calls:
            self.assertIn(
                "pr_state=",
                args,
                "a merge_state() stamping call site does not pass pr_state — "
                "this is exactly the #6792 defect: correct data, never handed over",
            )


if __name__ == "__main__":
    unittest.main()
