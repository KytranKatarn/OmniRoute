"""#5853 — the SECOND merge surface must obey the server's merge_state.

#2737 fixed the Repair Bay PR-Review template, which renders from ``list_reviews()``
(already merge_state-stamped). It did NOT touch ``static/js/repair-bay-main.js``, which
renders the Reviews tab from the GitHub-shaped ``GET /api/forge/prs`` payload and gated
its Merge button on ``pr.mergeable === 'MERGEABLE' && pr.review_decision !==
'CHANGES_REQUESTED'``.

Both of those are GitHub's own fields. F.O.R.G.E. posts **no GitHub review** — its verdict
lives in ``pr_reviews.ai_summary`` — so ``review_decision`` is ~always null and the whole
condition degenerated to "mergeable => enabled green button". A REQUEST CHANGES, a
coverage demotion, and a never-reviewed PR all rendered as a green ``Merge ✓``.

⚠️ The existing guard ``test_merge_state_ui.test_template_does_not_parse_verdicts_itself``
greps the TEMPLATE only, which is precisely why this surface stayed unguarded. The JS
guards below close that hole.
"""

import re
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tools.repair_bay.services import pr_review_service as prs

_JS = Path(__file__).resolve().parents[1] / "static" / "js" / "repair-bay-main.js"

_APPROVED = "SUMMARY\nfine\n\nVERDICT: APPROVE"
_REJECTED = "SUMMARY\nbroken\n\nVERDICT: REQUEST CHANGES"


@contextmanager
def _fake_cursor(rows):
    class _Cur:
        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return rows

    yield (None, _Cur())


class TestStampMergeStates(unittest.TestCase):
    def test_unreviewed_pr_is_not_mergeable(self):
        """No stored row => awaiting_review, which is what the ROUTE also says.

        verdict_refusal("", False) returns "no stored F.O.R.G.E. review — a dead review
        is not an approval", so a green button here would be the UI contradicting the
        server it is about to call.
        """
        with patch.object(prs, "get_db_cursor", lambda *a, **k: _fake_cursor([])):
            out = prs.stamp_merge_states([{"number": 7}])
        self.assertEqual(out[0]["merge_state"]["state"], "awaiting_review")
        self.assertFalse(out[0]["merge_state"]["mergeable"])

    def test_approved_is_mergeable(self):
        rows = [{"pr_number": 7, "review_status": "reviewed", "ai_summary": _APPROVED}]
        with patch.object(prs, "get_db_cursor", lambda *a, **k: _fake_cursor(rows)):
            out = prs.stamp_merge_states([{"number": 7}])
        self.assertEqual(out[0]["merge_state"]["state"], "approved")
        self.assertTrue(out[0]["merge_state"]["mergeable"])

    def test_request_changes_is_not_mergeable(self):
        """THE bug: this PR used to render an enabled green Merge button."""
        rows = [{"pr_number": 7, "review_status": "reviewed", "ai_summary": _REJECTED}]
        with patch.object(prs, "get_db_cursor", lambda *a, **k: _fake_cursor(rows)):
            out = prs.stamp_merge_states([{"number": 7}])
        self.assertEqual(out[0]["merge_state"]["state"], "changes_requested")
        self.assertFalse(out[0]["merge_state"]["mergeable"])

    def test_db_error_fails_CLOSED(self):
        """A UI that cannot READ the verdict must not IMPLY one."""

        def _boom(*a, **k):
            raise RuntimeError("db down")

        with patch.object(prs, "get_db_cursor", _boom):
            out = prs.stamp_merge_states([{"number": 7}, {"number": 8}])
        for pr in out:
            self.assertFalse(pr["merge_state"]["mergeable"])
            self.assertEqual(pr["merge_state"]["state"], "awaiting_review")

    def test_every_row_is_stamped_and_nothing_raises(self):
        """Mixed/garbage input must still yield a shaped merge_state on every row."""
        rows = [{"pr_number": 7, "review_status": "reviewed", "ai_summary": _APPROVED}]
        prs_in = [{"number": 7}, {"number": 8}, {"no_number": True}]
        with patch.object(prs, "get_db_cursor", lambda *a, **k: _fake_cursor(rows)):
            out = prs.stamp_merge_states(prs_in)
        self.assertEqual(len(out), 3)
        for pr in out:
            self.assertIn("mergeable", pr["merge_state"])

    def test_empty_and_none_short_circuit_to_a_list(self):
        """None normalises to [] so callers can always iterate the result."""
        self.assertEqual(prs.stamp_merge_states([]), [])
        self.assertEqual(prs.stamp_merge_states(None), [])


class TestSecondSurfaceJs(unittest.TestCase):
    """The verdict rule stays SERVER-side; the JS may only consume the decision."""

    def setUp(self):
        self.src = _JS.read_text()
        # Strip line comments so the guards match CODE, not prose about the fix.
        self.code = re.sub(r"^\s*//.*$", "", self.src, flags=re.MULTILINE)

    def test_js_does_not_parse_verdicts_itself(self):
        for pattern in ("VERDICT:", "verdict_is_approved", "coverage_only_demotion", "REQUEST CHANGES"):
            self.assertNotIn(
                pattern,
                self.code,
                f"{pattern!r} in repair-bay-main.js — a client-side copy of the verdict "
                "rule is exactly what #2722 collapsed into one definition.",
            )

    def test_js_consumes_server_merge_state(self):
        self.assertIn("pr.merge_state", self.code)

    def test_the_github_only_merge_gate_is_gone(self):
        """Regression: the exact condition that made the button lie.

        Verified to FAIL against the pre-fix file, so it is not a test that cannot fail.
        """
        self.assertNotIn(
            "pr.review_decision !== 'CHANGES_REQUESTED'",
            self.code,
            "the Merge button is gated on GitHub's review_decision again — F.O.R.G.E. "
            "posts no GitHub review, so that field is ~always null and the gate "
            "degenerates to 'mergeable => green button'.",
        )


if __name__ == "__main__":
    unittest.main()
