"""#5910 — coverage must count BYTES per file, not merely file PRESENCE.

Why this file exists
--------------------
The #5836 coverage gate demotes a verdict when the reviewer never saw a file. It
computed that from file PATHS alone, so it was blind to the single-file case: a PR
whose diff exceeds the window but contains ONE file loses no *whole* file, so
``dropped`` was empty, ``complete`` was True, and it recorded a clean APPROVE while
the reviewer had seen only part of the change.

That is not hypothetical. PR #2749 was measured at **8,135 of 13,379 chars shown
(61%)** and merged on a "full coverage" APPROVE at confidence 0.95.

57 tests across test_review_coverage.py, test_coverage_discharge.py and
test_speculative_coverage_gate.py all passed against the buggy behaviour — which is
precisely why the bug survived. ``test_the_old_presence_only_logic_would_MISS_this``
below reproduces the old rule inline and asserts it gets the WRONG answer, so this
file provably fails if the fix is reverted.
"""

import sys

sys.path.insert(0, "/app")

from services.review_coverage import coverage, coverage_note  # noqa: E402
from tools.repair_bay.services.pr_review_service import coverage_dropped_paths  # noqa: E402

# One file, two hunks. The "shown" variant keeps the header + first hunk only —
# exactly what _truncate_diff produces when it cuts at a hunk boundary mid-file.
_FULL = """diff --git a/app/only.py b/app/only.py
index 1111111..2222222 100644
--- a/app/only.py
+++ b/app/only.py
@@ -1,3 +1,4 @@
 def alpha():
+    guard()
     return 1
@@ -20,3 +21,4 @@ def beta():
 def gamma():
+    THIS_LINE_WAS_NEVER_REVIEWED = True
     return 3
"""
_SHOWN = _FULL.split("@@ -20,3")[0]


def test_single_file_cut_mid_way_is_NOT_complete():
    """The #2749 case: one file, present in the window, but truncated part-way."""
    cov = coverage(_FULL, _SHOWN)
    assert cov["dropped"] == [], "no WHOLE file is missing — that is what made it invisible"
    assert cov["complete"] is False, "a part-read file must not report as full coverage"
    assert [e["path"] for e in cov["partial"]] == ["app/only.py"]
    assert 0 < cov["partial"][0]["shown_pct"] < 100


def test_a_part_read_file_is_not_counted_as_reviewed():
    cov = coverage(_FULL, _SHOWN)
    assert cov["total"] == 1
    assert cov["reviewed"] == 0, "counting a partial as reviewed is the overstatement itself"


def test_the_old_presence_only_logic_would_MISS_this():
    """Proves this file can fail: the pre-#5910 rule, reproduced inline, gets it wrong.

    If someone reverts coverage() to path-presence, the assertions above start failing
    while this one keeps passing — the contrast is the point.
    """
    from services.review_coverage import diff_files

    full = diff_files(_FULL)
    shown = set(diff_files(_SHOWN))
    old_dropped = [f for f in full if f not in shown]
    old_complete = not old_dropped
    assert old_complete is True, "the old rule saw full coverage on a 60%-read file"
    assert coverage(_FULL, _SHOWN)["complete"] is False, "the new rule must disagree"


def test_untruncated_diff_still_reports_complete():
    """Guard against over-flagging — the whole value of the gate is that it is trusted."""
    cov = coverage(_FULL, _FULL)
    assert cov["complete"] is True
    assert cov["partial"] == [] and cov["dropped"] == []
    assert cov["reviewed"] == cov["total"] == 1


def test_dropped_path_parser_must_not_read_a_partial_as_dropped():
    """`coverage_dropped_paths` keys on a leading '- '; partials render with '*'.

    It also stops at the first blank line only ONCE it has started collecting, so a
    partial listed with '- ' while `dropped` was empty would be silently misread as a
    wholly-dropped file. The '*' bullet is what prevents that.
    """
    note = coverage_note(coverage(_FULL, _SHOWN))
    assert coverage_dropped_paths("SUMMARY\n\n" + note) == []
    assert "app/only.py" in note, "the human still has to be told which file was cut"
    assert "VERDICT: NEEDS REVIEW" in note


def test_dropped_and_partial_can_coexist():
    two = (
        _FULL
        + """diff --git a/app/other.py b/app/other.py
--- a/app/other.py
+++ b/app/other.py
@@ -1,2 +1,3 @@
 def delta():
+    added()
     return 4
"""
    )
    cov = coverage(two, _SHOWN)
    assert cov["dropped"] == ["app/other.py"]
    assert [e["path"] for e in cov["partial"]] == ["app/only.py"]
    assert cov["complete"] is False
    # the wholly-dropped file IS still discharged through the '- ' listing
    assert coverage_dropped_paths("S\n\n" + coverage_note(cov)) == ["app/other.py"]
