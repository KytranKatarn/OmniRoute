"""merge_order — the pure ranking the PR Review tab renders.

Built 2026-09-11 after four approved PRs sat in the tab with no order. GitHub's
``mergeable`` only sees conflicts against main; a PR that needs another one first
(declared, or by shared files) rendered identically to one that needs nothing.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.repair_bay.services.merge_order import compute_merge_order, declared_dependencies  # noqa: E402

T0 = datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc)


def _pr(n, body="", files=(), minutes=0):
    return {"pr_number": n, "body": body, "files": list(files), "created_at": T0 + timedelta(minutes=minutes)}


class TestDeclaredDependencies(unittest.TestCase):
    def test_the_three_marker_forms(self):
        body = "Depends on #3300.\nBlocked by #64\nmerge after #65\nRequires: #7"
        self.assertEqual(declared_dependencies(body), {3300, 64, 65, 7})

    def test_case_and_hyphens(self):
        self.assertEqual(declared_dependencies("DEPENDS-ON #12 and blocked-by #13"), {12, 13})

    def test_a_bare_reference_is_not_a_dependency(self):
        """PR bodies cite PRs and issues constantly; a false HARD dependency blocks a merge."""
        self.assertEqual(declared_dependencies("Fixes #12. See #13 and the follow-up after #14."), set())

    def test_empty(self):
        self.assertEqual(declared_dependencies(None), set())
        self.assertEqual(declared_dependencies(""), set())


class TestTheLiveCase(unittest.TestCase):
    """The four PRs of 2026-09-11: 0 overlapping files between #3300/#3298 — no order."""

    def test_independent_prs_get_distinct_ranks_and_no_constraints(self):
        order = compute_merge_order(
            [
                _pr(3298, files=["a.py", "b.html"], minutes=0),
                _pr(3300, files=["c.py", "tests/t.py"], minutes=5),
            ]
        )
        self.assertEqual({order[3298]["rank"], order[3300]["rank"]}, {1, 2})
        for n in (3298, 3300):
            self.assertEqual(order[n]["after"], [])
            self.assertFalse(order[n]["blocked"])
            self.assertIn("no ordering constraint", order[n]["reason"])
            self.assertRegex(order[n]["label"], r"^[①②]$")


class TestDeclaredOrder(unittest.TestCase):
    def test_a_declared_dependency_is_hard_and_blocks(self):
        order = compute_merge_order(
            [
                _pr(10, files=["x.py"], minutes=0),
                _pr(11, body="Depends on #10", files=["y.py"], minutes=1),
            ]
        )
        self.assertEqual(order[10]["rank"], 1)
        self.assertEqual(order[11]["rank"], 2)
        self.assertEqual(order[11]["declared_after"], [10])
        self.assertTrue(order[11]["blocked"])
        self.assertFalse(order[10]["blocked"])
        self.assertEqual(order[11]["label"], "② after #10")

    def test_the_dependency_wins_even_when_it_is_newer(self):
        """Age is only a tiebreak; a declaration is an instruction."""
        order = compute_merge_order(
            [
                _pr(20, body="Depends on #21", files=[], minutes=0),
                _pr(21, files=[], minutes=30),
            ]
        )
        self.assertEqual(order[21]["rank"], 1)
        self.assertEqual(order[20]["rank"], 2)

    def test_a_dependency_that_is_not_open_here_does_not_block(self):
        """Merged or untracked — satisfied or unknowable; never a phantom block."""
        order = compute_merge_order([_pr(30, body="Depends on #29", files=[])])
        self.assertFalse(order[30]["blocked"])
        self.assertEqual(order[30]["after"], [])

    def test_a_self_reference_is_ignored(self):
        order = compute_merge_order([_pr(40, body="Depends on #40")])
        self.assertFalse(order[40]["blocked"])

    def test_a_cycle_is_flagged_not_hung(self):
        order = compute_merge_order(
            [
                _pr(50, body="Depends on #51"),
                _pr(51, body="Depends on #50"),
            ]
        )
        self.assertTrue(order[50]["cycle"] and order[51]["cycle"])
        self.assertTrue(order[50]["blocked"] and order[51]["blocked"])
        self.assertEqual({order[50]["rank"], order[51]["rank"]}, {1, 2})
        self.assertIn("circular", order[50]["reason"])


class TestFileOverlap(unittest.TestCase):
    def test_older_pr_first_and_the_newer_one_says_so(self):
        order = compute_merge_order(
            [
                _pr(60, files=["shared.py", "a.py"], minutes=0),
                _pr(61, files=["shared.py", "b.py"], minutes=10),
            ]
        )
        self.assertEqual(order[60]["rank"], 1)
        self.assertEqual(order[61]["rank"], 2)
        self.assertEqual(order[61]["after"], [60])
        self.assertEqual(order[61]["shares_files_with"], {60: ["shared.py"]})
        self.assertEqual(order[60]["shares_files_with"], {61: ["shared.py"]})
        self.assertFalse(order[61]["blocked"], "overlap warns; it never blocks — GitHub surfaces the conflict")
        self.assertEqual(order[61]["label"], "② shares files with #60")
        self.assertIn("1 shared file", order[61]["reason"])

    def test_no_created_at_falls_back_to_pr_number(self):
        order = compute_merge_order(
            [
                {"pr_number": 71, "files": ["s.py"]},
                {"pr_number": 70, "files": ["s.py"]},
            ]
        )
        self.assertEqual(order[70]["rank"], 1)
        self.assertEqual(order[71]["after"], [70])

    def test_declared_and_overlap_combine_hard_first(self):
        order = compute_merge_order(
            [
                _pr(80, files=["s.py"], minutes=0),
                _pr(81, files=["other.py"], minutes=1),
                _pr(82, body="Depends on #81", files=["s.py"], minutes=2),
            ]
        )
        self.assertEqual(order[82]["declared_after"], [81])
        self.assertEqual(order[82]["after"], [81, 80])
        self.assertTrue(order[82]["blocked"])
        self.assertEqual(order[82]["rank"], 3)


class TestShape(unittest.TestCase):
    def test_every_pr_is_ranked_exactly_once(self):
        prs = [_pr(n, files=[f"{n % 3}.py"], minutes=n) for n in range(100, 112)]
        order = compute_merge_order(prs)
        self.assertEqual(sorted(o["rank"] for o in order.values()), list(range(1, 13)))

    def test_accepts_github_shaped_number_key(self):
        order = compute_merge_order([{"number": 5, "files": [], "body": ""}])
        self.assertEqual(order[5]["rank"], 1)

    def test_empty_input(self):
        self.assertEqual(compute_merge_order([]), {})


if __name__ == "__main__":
    unittest.main()
