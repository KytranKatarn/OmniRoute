"""A MIXED-polarity citation is a polarity failure, not a grounded one (#5857).

THE LIVE CASE THIS FIXES. On 2026-09-11 PR #3298 was blocked by a WARNING whose
evidence stitched together lines from BOTH sides of the diff:

    @app.route("/claude")                                          <- added   (real)
    def claude_terminal():                                         <- REMOVED (deleted by this PR)
    ...                                                            <- unevaluable
    logger.warning("terminal page refused: off-mesh lane=%s", ...)  <- added   (real)

_evidence_polarity's multi-line branch ended `return "added" if "added" in verdicts`,
so ONE genuinely-added line laundered the whole block. The finding read as grounded,
passed every ADR-001 gate, and the REQUEST CHANGES stood on a defect described against
a function that does not exist after the merge.

#5839 had already settled the principle one branch above — "a finding is only as
grounded as its weakest cited line" — but applied it to ABSENT lines only. Extending
it to REMOVED lines is this change.

WHAT MUST NOT REGRESS, and why each case is here:
  * an ordinary MODIFIED line is on BOTH sides, so it votes "added" (the loop checks
    the added side FIRST, deliberately) — it must stay grounded;
  * a finding that legitimately critiques the REMOVAL keeps its carve-out downstream;
  * evidence_only_removed must NOT count toward _count_ungrounded, or this change
    would start flooring correct APPROVEs via the #5009 rule.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

p = pytest.importorskip("tools.repair_bay.services.pr_diff_analyzer")


# A diff that ADDS the lane plumbing and REMOVES the old hardcoded claude route —
# the shape of PR #3298, reduced to what the gate actually reads.
DIFF = """diff --git a/archie-comms/app_comms.py b/archie-comms/app_comms.py
--- a/archie-comms/app_comms.py
+++ b/archie-comms/app_comms.py
@@ -10,7 +10,12 @@
-@app.route("/claude")
-def claude_terminal():
-    return render_template("claude_terminal.html")
+def _lane_terminal(lane_key):
+    lane = _tl.LANES[lane_key]
+    if not _mesh_clearance():
+        logger.warning("terminal page refused: off-mesh lane=%s", lane_key)
+        return redirect("/" + lane_key)
+    return render_template("lane_terminal.html", **_lane_view_context(lane_key))
"""

# The verbatim evidence from the blocking WARNING on PR #3298.
MIXED_CITATION = (
    '@app.route("/claude")\n'
    "def claude_terminal():\n"
    "    ...\n"
    '    logger.warning("terminal page refused: off-mesh lane=%s", lane_key)'
)


class TestTheLiveRegression:
    def test_the_pr_3298_citation_is_no_longer_grounded(self):
        """THE test. Before the fix this returned 'added' and the PR stayed blocked."""
        assert p._evidence_polarity(MIXED_CITATION, DIFF) == "removed_only"

    def test_the_added_lines_in_that_citation_are_genuinely_real(self):
        """Guards against a vacuous pass: if the 'added' halves stopped matching, the
        test above would go green for the wrong reason — everything absent."""
        added = p._side_text(DIFF, "+")
        assert p._cites(
            p._normalize_match('logger.warning("terminal page refused: off-mesh lane=%s", lane_key)'),
            added,
        ), "the added half of the citation no longer matches — this test is now vacuous"

    def test_the_removed_line_is_genuinely_on_the_removed_side(self):
        """The other half of non-vacuity: claude_terminal must really be deleted here."""
        assert p._cites(p._normalize_match("def claude_terminal():"), p._side_text(DIFF, "-"))
        assert not p._cites(p._normalize_match("def claude_terminal():"), p._side_text(DIFF, "+"))


class TestPolarityVerdicts:
    def test_an_all_added_citation_stays_grounded(self):
        ev = "+def _lane_terminal(lane_key):\n+    lane = _tl.LANES[lane_key]"
        assert p._evidence_polarity(ev, DIFF) == "added"

    def test_an_all_removed_citation_is_removed_only(self):
        ev = '-def claude_terminal():\n-    return render_template("claude_terminal.html")'
        assert p._evidence_polarity(ev, DIFF) == "removed_only"

    def test_a_fabricated_line_still_short_circuits_to_absent(self):
        """The #5839 behaviour must survive: absent beats everything."""
        ev = "+def _lane_terminal(lane_key):\n+    nonexistent_helper_xyzzy()"
        assert p._evidence_polarity(ev, DIFF) == "absent"

    def test_a_modified_line_present_on_both_sides_stays_added(self):
        """THE false-positive risk of this change, pinned.

        A line a PR MODIFIES appears on both sides. The loop checks the added side
        first, so it votes 'added' and the citation stays grounded. If this ever
        fails, the fix has started demoting ordinary modifications.
        """
        diff = (
            "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n"
            "-    total = compute_total(rows, rate)\n"
            "+    total = compute_total(rows, rate, cap)\n"
        )
        ev = "    total = compute_total(rows, rate, cap)"
        assert p._evidence_polarity(ev, diff) == "added"

    def test_unevaluable_lines_do_not_vote(self):
        """Punctuation-only lines cannot confirm or refute; they must not tip a
        citation into removed_only on their own."""
        ev = "+def _lane_terminal(lane_key):\n    ...\n    )"
        assert p._evidence_polarity(ev, DIFF) == "added"

    def test_the_single_line_path_is_untouched(self):
        assert (
            p._evidence_polarity('logger.warning("terminal page refused: off-mesh lane=%s", lane_key)', DIFF) == "added"
        )
        assert p._evidence_polarity("def claude_terminal():", DIFF) == "removed_only"

    @pytest.mark.parametrize("ev", ["", None])
    def test_no_evidence_never_drops(self, ev):
        assert p._evidence_polarity(ev, DIFF) == "added"


class TestDownstreamBehaviour:
    def _issue(self, **kw):
        base = {
            "severity": "WARNING",
            "title": "Logging statement in sensitive context",
            "why": "Sensitive information could be exposed if logs are compromised.",
            "evidence": MIXED_CITATION,
        }
        base.update(kw)
        return base

    def test_the_finding_is_dropped_as_a_polarity_error(self):
        kept, dropped = p._verify_evidence([self._issue()], DIFF)
        assert kept == []
        assert dropped[0]["_drop_reason"] == "evidence_only_removed"

    def test_it_does_not_count_as_ungrounded(self):
        """Load-bearing. evidence_only_removed means the model WAS reading — counting
        it would let this change floor correct APPROVEs through the #5009 rule."""
        _kept, dropped = p._verify_evidence([self._issue()], DIFF)
        assert p._count_ungrounded(dropped) == 0

    def test_a_finding_that_critiques_the_removal_is_still_kept(self):
        """The one legitimate reason to cite deleted code — "this PR drops a needed
        guard" — must survive, or the gate starts hiding real regressions."""
        issue = self._issue(
            title="This PR removes the off-mesh guard",
            why="The change deletes claude_terminal without replacing its mesh check.",
        )
        kept, dropped = p._verify_evidence([issue], DIFF)
        assert kept, f"a removal critique was dropped: {dropped and dropped[0].get('_drop_reason')}"

    def test_dropping_the_only_blocking_issue_clears_the_verdict(self):
        """End to end: with the finding dropped there is no blocking issue left, so
        the recomputed verdict is not REQUEST CHANGES."""
        kept, _dropped = p._verify_evidence([self._issue()], DIFF)
        verdict = p._recompute_verdict(kept, 0.95, p._review_confidence_min())
        assert verdict != "REQUEST CHANGES"
