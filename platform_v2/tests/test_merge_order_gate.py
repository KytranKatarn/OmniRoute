"""The HARD half of merge order: a PR that declares "Depends on #N" does not merge
while #N is open — for every actor, including the human click — and the display half
is stamped server-side onto both Repair Bay surfaces.

Style follows test_merge_state_ui / test_forge_merge_route_repo: pure calls with
monkeypatched GitHub reads, plus source-level pins for the wiring that a closure-based
route makes awkward to exercise directly.
"""

import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.repair_bay.services import github_service as gs  # noqa: E402
from tools.repair_bay.services import merge_order_service as mos  # noqa: E402

_ROUTES = Path(ROOT) / "tools" / "repair_bay" / "github_routes.py"
_TEMPLATE = Path(ROOT) / "templates" / "tools" / "repair_bay.html"
_MAIN_JS = Path(ROOT) / "static" / "js" / "repair-bay-main.js"
_GS = Path(ROOT) / "tools" / "repair_bay" / "services" / "github_service.py"


class TestDependencyRefusal(unittest.TestCase):
    def _refusal(self, body, states):
        with mock.patch.object(gs, "pr_body", return_value=body), mock.patch.object(
            gs, "pr_is_open", side_effect=lambda n, repo=None: states.get(n)
        ):
            return gs._dependency_refusal(50, "KytranKatarn/archie-platform")

    def test_no_declared_dependency_is_no_refusal(self):
        self.assertIsNone(self._refusal("Fixes #12, see #13.", {12: True, 13: True}))

    def test_an_open_dependency_refuses_and_names_it(self):
        why = self._refusal("Depends on #12", {12: True})
        self.assertIsNotNone(why)
        self.assertIn("#12", why)
        self.assertIn("open", why)

    def test_a_merged_dependency_is_satisfied(self):
        self.assertIsNone(self._refusal("Depends on #12", {12: False}))

    def test_an_unreadable_dependency_state_fails_closed(self):
        """pr_is_open() -> None means "could not determine"; its contract says treat
        as still open. A merge is unrevertable; guessing is not an option."""
        why = self._refusal("Blocked by #12", {12: None})
        self.assertIsNotNone(why)
        self.assertIn("#12", why)

    def test_an_unreadable_body_fails_closed(self):
        why = self._refusal(None, {})
        self.assertIsNotNone(why)
        self.assertIn("body", why.lower())

    def test_an_empty_body_is_fine(self):
        self.assertIsNone(self._refusal("", {}))

    def test_self_reference_is_ignored(self):
        self.assertIsNone(self._refusal("Depends on #50", {50: True}))


class TestGateIsWiredForEveryActor(unittest.TestCase):
    def test_merge_pr_checks_dependencies_after_governance_and_before_github(self):
        src = _GS.read_text()
        start = src.index("def merge_pr(")
        body = src[start:]
        i_override = body.index("_override_stale_verdict_check(pr_number, repo)")
        i_dep = body.index("_dependency_refusal(pr_number, repo)")
        i_pre = body.index("pre_ok, pre = _api_get(")
        self.assertLess(i_override, i_dep, "dependency check must come after the override/staleness branch")
        self.assertLess(i_dep, i_pre, "dependency check must run before any GitHub merge pre-check")
        # It must sit OUTSIDE the `if not human_override:` / `else:` split, i.e. at the
        # same indentation as the pre-check — otherwise one actor escapes it.
        line = body[:i_dep].splitlines()[-1]
        pre_line = body[:i_pre].splitlines()[-1]
        self.assertEqual(len(line) - len(line.lstrip()), len(pre_line) - len(pre_line.lstrip()))


class TestStamping(unittest.TestCase):
    def setUp(self):
        mos.clear_cache()

    def test_open_rows_are_ranked_per_repo_and_closed_rows_get_none(self):
        bodies = {("r/a", 1): "", ("r/a", 2): "Depends on #1", ("r/b", 1): ""}
        files = {("r/a", 1): ["x.py"], ("r/a", 2): ["y.py"], ("r/b", 1): ["z.py"]}
        with mock.patch.object(gs, "pr_body", side_effect=lambda n, repo=None: bodies[(repo, n)]), mock.patch.object(
            gs, "pr_files", side_effect=lambda n, repo=None: files[(repo, n)]
        ):
            rows = [
                {"pr_number": 1, "repo": "r/a", "state": "open"},
                {"pr_number": 2, "repo": "r/a", "state": "open"},
                {"pr_number": 1, "repo": "r/b", "state": "open"},
                {"pr_number": 3, "repo": "r/a", "state": "closed"},
            ]
            mos.stamp_merge_order(rows)
        self.assertEqual(rows[0]["merge_order"]["rank"], 1)
        self.assertEqual(rows[1]["merge_order"]["rank"], 2)
        self.assertTrue(rows[1]["merge_order"]["blocked"])
        self.assertEqual(
            rows[2]["merge_order"]["rank"], 1, "repos are ranked independently — same number, different PR"
        )
        self.assertIsNone(rows[3]["merge_order"])

    def test_github_shaped_rows_use_number_and_the_default_repo(self):
        with mock.patch.object(gs, "pr_body", return_value=""), mock.patch.object(gs, "pr_files", return_value=["a"]):
            rows = [{"number": 7, "state": "open"}]
            mos.stamp_merge_order(rows, number_key="number", default_repo="r/a")
        self.assertEqual(rows[0]["merge_order"]["rank"], 1)

    def test_a_fetch_failure_is_reported_as_unavailable_not_invented(self):
        with mock.patch.object(gs, "pr_body", return_value=None), mock.patch.object(gs, "pr_files", return_value=None):
            rows = [{"pr_number": 9, "repo": "r/a", "state": "open"}]
            mos.stamp_merge_order(rows)
        mo = rows[0]["merge_order"]
        self.assertTrue(mo["unavailable"])
        self.assertIsNone(mo["rank"])
        self.assertFalse(mo["blocked"], "display never blocks on its own; the gate does that at merge time")

    def test_a_raising_fetch_never_takes_the_listing_down(self):
        with mock.patch.object(gs, "pr_body", side_effect=RuntimeError("boom")), mock.patch.object(
            gs, "pr_files", side_effect=RuntimeError("boom")
        ):
            rows = [{"pr_number": 9, "repo": "r/a", "state": "open"}]
            mos.stamp_merge_order(rows)
        self.assertTrue(rows[0]["merge_order"]["unavailable"])

    def test_second_call_within_ttl_does_not_refetch(self):
        calls = []
        with mock.patch.object(
            gs, "pr_body", side_effect=lambda n, repo=None: calls.append(n) or ""
        ), mock.patch.object(gs, "pr_files", return_value=[]):
            mos.stamp_merge_order([{"pr_number": 1, "repo": "r/a", "state": "open"}])
            mos.stamp_merge_order([{"pr_number": 1, "repo": "r/a", "state": "open"}])
        self.assertEqual(calls, [1])


class TestBothSurfacesAreStamped(unittest.TestCase):
    def test_both_list_routes_call_the_stamper(self):
        src = _ROUTES.read_text()
        i_prs = src.index('@bp.route("/api/forge/prs", methods=["GET"])')
        i_prs_end = src.index("@bp.route(", i_prs + 10)
        i_rev = src.index('@bp.route("/api/forge/pr-reviews", methods=["GET"])')
        i_rev_end = src.index("@bp.route(", i_rev + 10)
        self.assertIn("stamp_merge_order(", src[i_prs:i_prs_end])
        self.assertIn("stamp_merge_order(", src[i_rev:i_rev_end])


class TestTheClientOnlyRenders(unittest.TestCase):
    def test_template_and_js_consume_merge_order_and_do_not_derive_it(self):
        for path in (_TEMPLATE, _MAIN_JS):
            src = path.read_text()
            self.assertIn("pr.merge_order", src, f"{path.name} must render the server's merge_order")
            hits = [
                ln
                for ln in src.splitlines()
                if re.search(r"depends\s*on|blocked\s*by|merge\s*after", ln, re.I)
                and not ln.strip().startswith(("//", "*", "<!--"))
                and "merge_order" not in ln
            ]
            self.assertEqual(hits, [], f"{path.name} parses dependencies client-side: {hits[:2]}")


if __name__ == "__main__":
    unittest.main()
