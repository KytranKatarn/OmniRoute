"""A coverage demotion is dischargeable by a human; a REQUEST CHANGES is not (#5834 follow-up).

The #5836 coverage gate appends its block to the model's summary and terminates it with
``VERDICT: NEEDS REVIEW``. parse_verdict reads the LAST verdict, so a review the model
APPROVED became indistinguishable from one it REJECTED — both False from
verdict_is_approved. The standing rule has always distinguished them; the code did not, so
the UI could offer neither and every coverage-demoted PR required the CLI.

THE DANGEROUS CASE, and the reason this file exists: a REQUEST CHANGES that ALSO got
coverage-demoted must NOT become dischargeable. If it did, this feature would convert the
strongest refusal the reviewer can issue into a click-through.
"""

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from services.review_coverage import MARKER  # noqa: E402
from tools.repair_bay.services.github_service import verdict_refusal  # noqa: E402
from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    coverage_dropped_paths,
    coverage_only_demotion,
)

_COVERAGE_BLOCK = (
    f"\n\n{MARKER} COVERAGE: 1 of 2 files were in the diff window this review actually read.\n"
    "NOT REVIEWED (truncated away before the model saw them):\n"
    "  - platform_v2/tests/test_thing.py\n"
    "\n"
    "A verdict cannot cover a file the reviewer never read, so this review is recorded as "
    "NEEDS REVIEW rather than an approval (#5836). The findings above still stand for the "
    "files that WERE read.\n"
    "VERDICT: NEEDS REVIEW"
)

_APPROVED_THEN_DEMOTED = "SUMMARY\nLooks fine.\n\nVERDICT: APPROVE" + _COVERAGE_BLOCK
_REJECTED_THEN_DEMOTED = (
    "SUMMARY\nBroken.\n\nISSUES\n- [CRITICAL] real defect\n\nVERDICT: REQUEST CHANGES" + _COVERAGE_BLOCK
)
_REJECTED_NO_COVERAGE = "SUMMARY\nBroken.\n\nVERDICT: REQUEST CHANGES"


class TestDetection(unittest.TestCase):
    def test_approved_then_demoted_is_coverage_only(self):
        self.assertTrue(coverage_only_demotion(_APPROVED_THEN_DEMOTED))

    def test_rejected_then_demoted_is_NOT_coverage_only(self):
        """THE case this file exists for. A real rejection must never look dischargeable."""
        self.assertFalse(coverage_only_demotion(_REJECTED_THEN_DEMOTED))

    def test_rejection_without_coverage_is_not_coverage_only(self):
        self.assertFalse(coverage_only_demotion(_REJECTED_NO_COVERAGE))

    def test_empty_is_not_coverage_only(self):
        self.assertFalse(coverage_only_demotion(""))
        self.assertFalse(coverage_only_demotion(None))

    def test_dropped_paths_are_named(self):
        self.assertEqual(
            coverage_dropped_paths(_APPROVED_THEN_DEMOTED),
            ["platform_v2/tests/test_thing.py"],
        )

    def test_dropped_paths_empty_without_coverage(self):
        self.assertEqual(coverage_dropped_paths(_REJECTED_NO_COVERAGE), [])


class TestRefusalRespectsTheDistinction(unittest.TestCase):
    def test_coverage_demotion_refuses_without_ack(self):
        why = verdict_refusal(_APPROVED_THEN_DEMOTED, False)
        self.assertIsNotNone(why)
        self.assertTrue(why.startswith("COVERAGE ONLY"), why)

    def test_coverage_demotion_clears_with_ack(self):
        self.assertIsNone(verdict_refusal(_APPROVED_THEN_DEMOTED, False, coverage_ack=True))

    def test_ack_does_NOT_clear_a_real_rejection(self):
        """An ack is consent to unread files, never consent to a defect."""
        why = verdict_refusal(_REJECTED_THEN_DEMOTED, False, coverage_ack=True)
        self.assertIsNotNone(why)
        self.assertIn("NOT an approval", why)

    def test_ack_does_NOT_clear_a_rejection_without_coverage(self):
        why = verdict_refusal(_REJECTED_NO_COVERAGE, False, coverage_ack=True)
        self.assertIsNotNone(why)
        self.assertIn("NOT an approval", why)

    def test_ack_does_NOT_manufacture_a_review(self):
        """No stored review is still no review, ack or not."""
        self.assertIsNotNone(verdict_refusal("", False, coverage_ack=True))

    def test_a_real_approval_is_unaffected(self):
        self.assertIsNone(verdict_refusal("VERDICT: APPROVE", True))
        self.assertIsNone(verdict_refusal("VERDICT: APPROVE", True, coverage_ack=True))


class TestRoutesForwardTheAck(unittest.TestCase):
    """The flag is worthless if a route drops it on the floor."""

    @staticmethod
    def _src() -> str:
        return (_ROOT / "tools" / "repair_bay" / "github_routes.py").read_text()

    def test_both_routes_read_coverage_ack(self):
        self.assertEqual(self._src().count("coverage_ack"), 4, "expected read+forward in both routes")

    def test_both_routes_report_dropped_files(self):
        self.assertEqual(self._src().count("dropped_files"), 2)


if __name__ == "__main__":
    unittest.main()
