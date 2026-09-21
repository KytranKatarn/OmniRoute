"""Pin the per-send review-scope override.

The Repair Bay PR Review tab can now set `plan`/`max_files` on an individual
analyze/re-review send, instead of editing the global `forge:review_*` settings
to clear one PR and leaving every later review changed.

Two properties matter and are both asserted here:

1. THREAD-LOCAL. Each review runs in its own daemon thread, so a module-level
   global would leak one PR's scope into a concurrent review of another. A
   `contextvars` ContextVar would not work either — `threading.Thread` does not
   copy the caller's context — which is why this is `threading.local()`.

2. IT CANNOT RELAX A GATE. The override changes only how much the model is
   SHOWN. Coverage is measured from what was actually read, so widening the
   bound reduces dropped files while a bound that still drops files still
   reports them. `max_files` is clamped by the same [1, 25] rule as the stored
   setting, so an operator cannot widen past the ceiling.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402


class TestOverrideApplies(unittest.TestCase):
    def test_max_files_override_wins_over_the_stored_setting(self):
        baseline = pda._review_max_files()
        with pda.review_scope_override(max_files=baseline + 3):
            self.assertEqual(pda._review_max_files(), min(baseline + 3, 25))
        self.assertEqual(pda._review_max_files(), baseline)

    def test_plan_override_wins_over_the_stored_setting(self):
        baseline = pda._review_plan()
        other = "packed" if baseline == "per_file" else "per_file"
        with pda.review_scope_override(plan=other):
            self.assertEqual(pda._review_plan(), other)
        self.assertEqual(pda._review_plan(), baseline)

    def test_None_means_leave_that_knob_alone(self):
        """A partial override must not silently reset the other knob."""
        base_plan, base_files = pda._review_plan(), pda._review_max_files()
        with pda.review_scope_override(max_files=7):
            self.assertEqual(pda._review_plan(), base_plan)
        with pda.review_scope_override(plan=base_plan):
            self.assertEqual(pda._review_max_files(), base_files)

    def test_restores_rather_than_clears_so_nesting_works(self):
        with pda.review_scope_override(max_files=5):
            with pda.review_scope_override(max_files=9):
                self.assertEqual(pda._review_max_files(), 9)
            self.assertEqual(pda._review_max_files(), 5, "inner exit wiped the outer override")

    def test_override_is_released_even_when_the_body_raises(self):
        baseline = pda._review_max_files()
        with self.assertRaises(RuntimeError):
            with pda.review_scope_override(max_files=baseline + 4):
                raise RuntimeError("review blew up")
        self.assertEqual(pda._review_max_files(), baseline)


class TestClamp(unittest.TestCase):
    def test_cannot_widen_past_the_ceiling(self):
        with pda.review_scope_override(max_files=9999):
            self.assertEqual(pda._review_max_files(), 25)

    def test_cannot_go_below_one(self):
        for bad in (0, -5):
            with pda.review_scope_override(max_files=bad):
                self.assertEqual(pda._review_max_files(), 1)

    def test_garbage_falls_back_to_the_stored_setting(self):
        baseline = pda._review_max_files()
        for bad in ("lots", None, object()):
            with pda.review_scope_override(max_files=bad):
                self.assertEqual(pda._review_max_files(), baseline)

    def test_an_unrecognised_plan_falls_back_to_the_stored_setting(self):
        baseline = pda._review_plan()
        with pda.review_scope_override(plan="turbo"):
            self.assertEqual(pda._review_plan(), baseline)


class TestThreadLocality(unittest.TestCase):
    def test_one_threads_override_does_not_leak_into_another(self):
        """The whole reason this is threading.local() and not a global."""
        baseline = pda._review_max_files()
        seen = {}
        started = threading.Event()
        release = threading.Event()

        def holder():
            with pda.review_scope_override(max_files=23):
                seen["holder_inside"] = pda._review_max_files()
                started.set()
                release.wait(5)

        def observer():
            started.wait(5)
            # Concurrent review, no override of its own: must see the default.
            seen["observer"] = pda._review_max_files()
            release.set()

        h = threading.Thread(target=holder)
        o = threading.Thread(target=observer)
        h.start()
        o.start()
        h.join(10)
        o.join(10)

        self.assertEqual(seen.get("holder_inside"), 23)
        self.assertEqual(
            seen.get("observer"),
            baseline,
            "a concurrent review inherited another PR's scope — the override leaked",
        )

    def test_a_global_would_have_failed_that_test(self):
        """Non-vacuity: show the same test shape fails for a module global."""
        state = {"v": None}
        baseline = object()
        state["v"] = baseline
        started, release = threading.Event(), threading.Event()
        seen = {}

        def holder():
            state["v"] = "overridden"  # a GLOBAL, not thread-local
            started.set()
            release.wait(5)
            state["v"] = baseline

        def observer():
            started.wait(5)
            seen["observer"] = state["v"]
            release.set()

        h, o = threading.Thread(target=holder), threading.Thread(target=observer)
        h.start()
        o.start()
        h.join(10)
        o.join(10)
        self.assertEqual(
            seen.get("observer"),
            "overridden",
            "control case broken — a global is supposed to leak here",
        )


class TestGateIsNotRelaxed(unittest.TestCase):
    def test_a_narrow_scope_still_reports_dropped_files(self):
        """The override may shrink what is read; it may not hide that it did.

        file_plan is the planner the bound feeds. With a bound below the file
        count, the plan must still cover fewer files than the diff contains --
        which is what the coverage gate reads to demote a verdict.
        """
        from services.review_coverage import file_plan

        diff = "".join(
            f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n" f"@@ -0,0 +1 @@\n+x = {i}\n"
            for i in range(6)
        )
        wide = file_plan(diff, 6, 100000)
        narrow = file_plan(diff, 2, 100000)
        self.assertGreater(len(wide), len(narrow), "the bound had no effect on the plan")
        self.assertLessEqual(len(narrow), 2)

    def test_the_override_reaches_the_planner_the_gate_measures(self):
        with pda.review_scope_override(max_files=2):
            self.assertEqual(pda._review_max_files(), 2)
        with pda.review_scope_override(max_files=12):
            self.assertEqual(pda._review_max_files(), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
