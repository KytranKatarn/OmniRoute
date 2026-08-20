"""#5839 — a half-real evidence string must not ground a finding.

Measured live on PR #2715, whose own subject was review integrity. F.O.R.G.E. blocked it
with:

    [WARNING] New function `prioritize` introduced ...
    Evidence: +def prioritize(diff: str | None, cap: int | None = None) -> str | None:
              +    pass

The first line is REAL. `+    pass` was INVENTED — no standalone `pass` exists on the added
side at all. The finding was nonetheless graded `added` (grounded) and returned
REQUEST CHANGES.

TWO compounding causes, and fixing either alone leaves the bug alive:

  1. The whole multi-line evidence was normalised into ONE string, so the fabricated
     line's tokens were diluted by the real line's — 12/12 tokens "present", overlap 1.00.
  2. Token matching was a bare substring test, so the invented token `pass` matched inside
     the real word `passed`. (`\\bpass\\b` -> False; the only hits were `passed`, `passed`.)

Note the trap that made this non-obvious: `_cites` returns True on a whole-core substring
match BEFORE it ever reaches the token loop, so per-line evaluation alone still passed —
the boundary rule has to apply to both paths.

THE OTHER DIRECTION MATTERS MORE. Dropping a REAL finding lets a defect ship, which is
strictly worse than one false block. So the boundary deliberately treats `_` as a
SEPARATOR, not a word character: a model citing `coverage` when the code says
`review_coverage` is making a REAL citation and must stay grounded. Only same-alphabet
extensions (`pass` -> `passed`) are refused. TestDoesNotOverDrop pins that.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repair_bay.services.pr_diff_analyzer import (  # noqa: E402
    _cites,
    _evidence_in_diff,
    _evidence_polarity,
    _side_text,
    _token_present,
)

DIFF = (
    "diff --git a/services/review_coverage.py b/services/review_coverage.py\n"
    "--- a/services/review_coverage.py\n"
    "+++ b/services/review_coverage.py\n"
    "@@ -1,3 +1,9 @@\n"
    "+def prioritize(diff, cap=None):\n"
    "+    blocks = split_blocks(diff)\n"
    "+    return join(blocks)\n"
    "+# every assertion passed the review_coverage checks\n"
    "-def legacy_helper(x):\n"
    "-    return x\n"
)


class TestTokenPresent(unittest.TestCase):
    def setUp(self):
        self.added = _side_text(DIFF, "+")

    def test_invented_token_does_not_match_inside_a_longer_word(self):
        """`pass` must not match inside `passed` — the exact #2715 bypass."""
        self.assertIn("passed", self.added)
        self.assertFalse(_token_present("pass", self.added))

    def test_prefix_extension_also_refused(self):
        self.assertFalse(_token_present("cap", "capability handling"))

    def test_underscore_is_a_separator_so_prefixed_identifiers_still_match(self):
        """`coverage` MUST still match `review_coverage` — a real citation of a prefixed
        identifier. This is why the rule is not \\b (where `_` is a word char)."""
        self.assertTrue(_token_present("coverage", self.added))

    def test_exact_token_matches(self):
        self.assertTrue(_token_present("prioritize", self.added))
        self.assertTrue(_token_present("blocks", self.added))


class TestCitesFastPath(unittest.TestCase):
    def test_whole_core_substring_path_is_boundary_aware(self):
        """_cites returns early on a whole-core match, so the boundary rule has to apply
        there too — fixing only the token loop left the bug alive."""
        self.assertFalse(_cites("pass", _side_text(DIFF, "+")))

    def test_real_line_still_cites(self):
        self.assertTrue(_cites("def prioritize(diff, cap=none):", _side_text(DIFF, "+")))


class TestPolarityPerLine(unittest.TestCase):
    def test_pr_2715_replay_fabricated_second_line(self):
        ev = "+def prioritize(diff, cap=None):\n+    pass"
        self.assertEqual(_evidence_polarity(ev, DIFF), "absent")
        self.assertFalse(_evidence_in_diff(ev, DIFF))

    def test_single_real_line_is_grounded(self):
        self.assertEqual(_evidence_polarity("+def prioritize(diff, cap=None):", DIFF), "added")

    def test_multi_line_all_real_is_grounded(self):
        ev = "+def prioritize(diff, cap=None):\n+    blocks = split_blocks(diff)"
        self.assertEqual(_evidence_polarity(ev, DIFF), "added")

    def test_punctuation_only_line_is_skipped_not_counted_against(self):
        ev = "+def prioritize(diff, cap=None):\n+}"
        self.assertEqual(_evidence_polarity(ev, DIFF), "added")

    def test_removed_side_still_detected(self):
        self.assertEqual(_evidence_polarity("-def legacy_helper(x):", DIFF), "removed_only")

    def test_mixed_added_and_removed_prefers_added(self):
        ev = "+def prioritize(diff, cap=None):\n-def legacy_helper(x):"
        self.assertEqual(_evidence_polarity(ev, DIFF), "added")

    def test_wholly_invented_multiline_is_absent(self):
        ev = "+def nonexistent_thing(zzz):\n+    raise SystemExit(42)"
        self.assertEqual(_evidence_polarity(ev, DIFF), "absent")


class TestDoesNotOverDrop(unittest.TestCase):
    """Dropping a REAL finding lets a defect ship — strictly worse than one false block.
    These pin the fail-open behaviours."""

    def test_no_diff_never_drops(self):
        self.assertEqual(_evidence_polarity("+anything at all", ""), "added")

    def test_no_evidence_never_drops(self):
        self.assertEqual(_evidence_polarity("", DIFF), "added")

    def test_trivially_short_single_line_never_drops(self):
        self.assertEqual(_evidence_polarity("+x=1", DIFF), "added")

    def test_whitespace_reformatted_real_line_still_grounded(self):
        """Normalisation slack survives — a re-spaced quotation of a real line grounds."""
        ev = "+def   prioritize( diff ,  cap = None ) :"
        self.assertEqual(_evidence_polarity(ev, DIFF), "added")

    def test_token_overlap_threshold_is_tight_and_that_is_PRE_EXISTING(self):
        """`capacity` vs the real `cap` scores 4/5 = 0.80, under the 0.85 bar, so it reads
        as absent. That is NOT a regression from #5839: `capacity` is not a substring of
        the added side either, so the old bare-substring token test scored it identically.
        Pinned so the tightness is a known, deliberate property rather than a surprise."""
        ev = "+def prioritize(diff, capacity=None):"
        self.assertEqual(_evidence_polarity(ev, DIFF), "absent")


if __name__ == "__main__":
    unittest.main()
