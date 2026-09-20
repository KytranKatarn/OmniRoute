"""A "read all of it" button must be able to read all of it (#6779 follow-on).

#3398 made the wide re-review REACHABLE and pointed it at the right PR and model. It still
could not guarantee coverage, because two bounds sit downstream of every flag:

  1. `forge:review_max_files` — the planner drops files past the bound before the model
     sees anything. Measured on #3398: 11 files, bound 10, one file never sent.
  2. the per-file cap — a single file bigger than one window is truncated no matter which
     model reads it. Measured on #3399: faith/routes.py is 57,945 chars against an 18,768
     wide cap, i.e. 32% at absolute best.

And a third problem made both worse: the note said "truncated away before the model saw
them" for BOTH causes, which points a reader at a wider re-review that cannot help a file
the planner never sent. Different cause, opposite remedy.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.review_coverage import (  # noqa: E402
    MARKER,
    coverage,
    coverage_note,
    file_plan,
    file_plan_detail,
    split_blocks,
    split_oversized_block,
)


def _blk(path, nlines):
    body = "".join(f"+line {i} of {path}\n" for i in range(nlines))
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{nlines} @@\n{body}"


HUGE = _blk("big.py", 4000)  # comfortably over any test cap
SMALL = _blk("small.py", 3)


class TestSplittingAnOversizedFile(unittest.TestCase):
    def test_every_part_fits_the_cap(self):
        parts = split_oversized_block("big.py", HUGE, 5000)
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertLessEqual(len(p), 5000)

    def test_every_part_is_attributed_to_the_same_file(self):
        """Parts after the first repeat the `diff --git` line so split_blocks still knows
        whose bytes they are. Without that the continuation is an orphan and coverage
        counts it against nothing."""
        parts = split_oversized_block("big.py", HUGE, 5000)
        for p in parts:
            paths = [q for q, _b in split_blocks(p) if q]
            self.assertEqual(paths, ["big.py"])

    def test_it_is_inert_when_not_needed(self):
        """KILLSWITCH. cap=None/0, or a block that already fits, must pass through
        byte-identical — so this cannot perturb a diff that never had the problem."""
        self.assertEqual(split_oversized_block("s.py", SMALL, 0), [SMALL])
        self.assertEqual(split_oversized_block("s.py", SMALL, 10_000), [SMALL])

    def test_it_splits_on_line_boundaries(self):
        """A mid-line cut produces a hunk the model cannot parse — the defect
        _truncate_diff's boundary logic already exists to avoid."""
        for p in split_oversized_block("big.py", HUGE, 5000):
            self.assertTrue(p.endswith("\n"), "a part ended mid-line")


class TestCoverageSumsSamePathBlocks(unittest.TestCase):
    """THE CHANGE SPLITTING DEPENDS ON. coverage() built shown_blocks with a dict
    comprehension, so a path appearing twice kept only the LAST part — which would make a
    split file measure *smaller* and still report partial. Splitting and this summation
    are one change; neither is correct alone."""

    def test_a_split_file_measures_complete(self):
        parts = split_oversized_block("big.py", HUGE, 5000)
        cov = coverage(HUGE, "\n".join(parts))
        self.assertEqual(cov["partial"], [])
        self.assertTrue(cov["complete"])

    def test_non_vacuity_the_old_behaviour_would_fail_this(self):
        """Prove the assertion above is not true by accident: measure the same split the
        OLD way (last-part-wins) and confirm it reports partial."""
        parts = split_oversized_block("big.py", HUGE, 5000)
        shown = "\n".join(parts)
        old_shown_blocks = {p: b for p, b in split_blocks(shown) if p}  # the pre-fix line
        saw = len(old_shown_blocks["big.py"])
        self.assertLess(saw, len(HUGE), "old measurement should undercount a split file")

    def test_a_genuinely_truncated_file_is_still_partial(self):
        """NON-VACUITY the other way: the summation must not turn every file complete."""
        cov = coverage(HUGE, HUGE[: len(HUGE) // 3])
        self.assertTrue(cov["partial"])
        self.assertFalse(cov["complete"])


class TestTheBoundIsReportedSeparately(unittest.TestCase):
    """#3 — cause decides remedy, and the two remedies are opposite."""

    def setUp(self):
        self.diff = SMALL + _blk("a.py", 3) + _blk("b.py", 3)

    def test_file_plan_detail_names_what_the_bound_refused(self):
        chunks, refused = file_plan_detail(self.diff, 2)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(refused), 1)

    def test_coverage_records_it(self):
        chunks, refused = file_plan_detail(self.diff, 2)
        cov = coverage(self.diff, "\n".join(chunks), bound_dropped=refused)
        self.assertEqual(cov["dropped_by_bound"], refused)

    def test_the_note_says_a_wider_window_will_not_help(self):
        chunks, refused = file_plan_detail(self.diff, 2)
        cov = coverage(self.diff, "\n".join(chunks), bound_dropped=refused)
        note = coverage_note(cov)
        self.assertIn("NOT SENT TO THE REVIEWER AT ALL", note)
        self.assertIn("will NOT help", note)

    def test_window_drops_keep_the_original_wording(self):
        """NON-REGRESSION: a genuine truncation must still read as one."""
        cov = coverage(self.diff, SMALL)  # a.py and b.py absent, no bound info
        note = coverage_note(cov)
        self.assertIn("truncated away before the model saw them", note)
        self.assertNotIn("NOT SENT TO THE REVIEWER AT ALL", note)

    def test_the_ack_parser_still_sees_EVERY_dropped_path(self):
        """THE ONE THAT MATTERS. coverage_dropped_paths() feeds the merge ack: it collects
        "- " lines and STOPS at the first blank line. Putting the second group behind a
        blank line would silently shorten the ack list — a human consenting to fewer files
        than are actually unread. That is the exact silent-undercount this area keeps
        producing, so it is pinned here."""
        chunks, refused = file_plan_detail(self.diff, 1)
        cov = coverage(self.diff, "\n".join(chunks), bound_dropped=refused)
        block = coverage_note(cov).split(MARKER, 1)[1]
        seen = []
        for line in block.splitlines():
            st = line.strip()
            if st.startswith("- ") and not st.startswith("- ...and "):
                seen.append(st[2:].strip())
            elif seen and not st:
                break
        self.assertEqual(sorted(seen), sorted(cov["dropped"]))


class TestBackCompat(unittest.TestCase):
    def test_file_plan_without_a_cap_is_unchanged(self):
        """cap defaults to None so every existing caller keeps its exact behaviour."""
        diff = SMALL + _blk("a.py", 3)
        self.assertEqual(file_plan(diff, 5), file_plan_detail(diff, 5, None)[0])

    def test_max_files_1_is_still_the_killswitch(self):
        diff = SMALL + _blk("a.py", 3)
        self.assertEqual(file_plan(diff, 1), [diff])


if __name__ == "__main__":
    unittest.main()
