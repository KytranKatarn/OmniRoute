"""Closing a PR is the missing half of the F.O.R.G.E. review lifecycle.

``github_service`` could DETECT a closed PR (``pr_merge_state``/``pr_is_open``/
``pr_was_merged``) and could close an ISSUE (``close_issue``), but nothing could produce a
closed PR. So a PR the reviewer flagged NEEDS REVIEW, or a lane branch abandoned
mid-task, could only be dealt with by leaving it open forever or by a human leaving the
platform for github.com.

The properties pinned here are the ones that make a close safe rather than convenient:

1. A written reason is REQUIRED and is posted onto the PR before it closes, so the
   operator's justification is attributed and survives the close.
2. It fails CLOSED on an unreadable state (decision #953 — safety is universal). A
   GitHub outage must never be reported as a successful close.
3. Already-merged and already-closed are reported as refusals, never as success. A
   "closed" on a merged PR would read as "we reverted it".
4. There is NO unattended caller. Closing has no server-side verdict gate behind it the
   way a merge does, so the only thing preventing an agent from closing a PR on a stale
   read of the review is that nothing automated calls it.

Style follows test_merge_order_gate: pure calls with monkeypatched GitHub reads, plus
source-level pins for the wiring that a closure-based route makes awkward to exercise.
"""

import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.repair_bay.services import github_service as gs  # noqa: E402

_ROUTES = Path(ROOT) / "tools" / "repair_bay" / "github_routes.py"
_TEMPLATE = Path(ROOT) / "templates" / "tools" / "repair_bay.html"
_MAIN_JS = Path(ROOT) / "static" / "js" / "repair-bay-main.js"
_MJS = Path(ROOT) / "tests" / "repair_bay_merge_affordance.mjs"
_REPO = "KytranKatarn/archie-platform"


def _helper_source() -> str:
    """The _prMergeAffordance body, sliced between the two helpers."""
    js = _MAIN_JS.read_text()
    helper = js[js.index("function _prMergeAffordance("):]
    return helper[: helper.index("function _prStyleMergeBtn(")]


def _close_pr_source() -> str:
    """Slice from the route decorator down to the next decorator.

    Searching backwards for the ``@bp.route(`` that owns the def (rather than a fixed
    offset) keeps this honest if the route is ever reformatted or moved.
    """
    src = _ROUTES.read_text()
    def_at = src.index("def forge_close_pr(")
    route_at = src.rindex("@bp.route(", 0, def_at)
    end = src.index("@bp.route(", def_at)
    return src[route_at:end]


class TestReasonAndAttributionAreRequired(unittest.TestCase):
    """A close must be attributable in writing, or it is not allowed at all."""

    def test_blank_reason_refuses_and_touches_nothing(self):
        with mock.patch.object(gs, "pr_merge_state", return_value="open"), mock.patch.object(
            gs, "_api_post"
        ) as post, mock.patch.object(gs, "_api_patch") as patch:
            for bad in ("", "   ", None, "\n\t "):
                res = gs.close_pr(1, reason=bad, authored_by="kytran")
                self.assertFalse(res["success"], f"reason={bad!r} must refuse")
                self.assertFalse(res["closed"])
        # No GitHub write at all — refusing must cost nothing.
        post.assert_not_called()
        patch.assert_not_called()

    def test_blank_author_refuses(self):
        with mock.patch.object(gs, "pr_merge_state", return_value="open"), mock.patch.object(
            gs, "_api_post"
        ) as post, mock.patch.object(gs, "_api_patch") as patch:
            res = gs.close_pr(1, reason="superseded", authored_by="  ")
            self.assertFalse(res["success"])
            self.assertIn("authored_by", res["error"])
        post.assert_not_called()
        patch.assert_not_called()

    def test_reason_is_trimmed_into_the_comment_and_the_result(self):
        with mock.patch.object(gs, "pr_merge_state", return_value="open"), mock.patch.object(
            gs, "_api_post", return_value=(True, {})
        ) as post, mock.patch.object(gs, "_api_patch", return_value=(True, {})):
            res = gs.close_pr(1, reason="  superseded by #2  ", authored_by="kytran")
        self.assertTrue(res["success"])
        self.assertEqual(res["reason"], "superseded by #2")
        body = post.call_args[0][1]["body"]
        self.assertIn("superseded by #2", body)
        self.assertIn("kytran", body)


class TestFailsClosedOnUnreadableState(unittest.TestCase):
    def test_unreadable_state_refuses_instead_of_guessing(self):
        with mock.patch.object(gs, "pr_merge_state", return_value=None), mock.patch.object(
            gs, "_api_post"
        ) as post, mock.patch.object(gs, "_api_patch") as patch:
            res = gs.close_pr(1, reason="cleanup", authored_by="kytran")
        self.assertFalse(res["success"])
        self.assertIn("refusing to guess", res["error"])
        post.assert_not_called()
        patch.assert_not_called()


class TestNonOpenStatesAreRefusalsNotSuccesses(unittest.TestCase):
    """A merged PR must never be reported as 'closed' — that reads as a revert."""

    def test_already_merged_refuses_and_does_not_write(self):
        with mock.patch.object(gs, "pr_merge_state", return_value="merged"), mock.patch.object(
            gs, "_api_post"
        ) as post, mock.patch.object(gs, "_api_patch") as patch:
            res = gs.close_pr(1, reason="cleanup", authored_by="kytran")
        self.assertFalse(res["success"])
        self.assertTrue(res["already_merged"])
        self.assertIn("not a revert", res["error"])
        post.assert_not_called()
        patch.assert_not_called()

    def test_already_closed_refuses_and_does_not_write(self):
        with mock.patch.object(gs, "pr_merge_state", return_value="closed"), mock.patch.object(
            gs, "_api_post"
        ) as post, mock.patch.object(gs, "_api_patch") as patch:
            res = gs.close_pr(1, reason="cleanup", authored_by="kytran")
        self.assertFalse(res["success"])
        self.assertTrue(res["already_closed"])
        post.assert_not_called()
        patch.assert_not_called()


class TestHappyPathOrdering(unittest.TestCase):
    """The reason goes on the PR BEFORE it closes, so it survives the close."""

    def _run(self, state="open", post=(True, {}), patch_ret=(True, {}), repo=None):
        calls = []
        with mock.patch.object(gs, "pr_merge_state", return_value=state), mock.patch.object(
            gs, "_api_post", side_effect=lambda *a, **k: (calls.append("post"), post)[1]
        ), mock.patch.object(gs, "_api_patch", side_effect=lambda *a, **k: (calls.append("patch"), patch_ret)[1]):
            return gs.close_pr(7, reason="abandoned lane branch", authored_by="kytran", repo=repo), calls

    def test_comment_precedes_the_close(self):
        res, calls = self._run()
        self.assertTrue(res["success"])
        self.assertTrue(res["closed"])
        self.assertEqual(calls, ["post", "patch"])

    def test_comment_failure_prevents_the_close(self):
        # Never close silently: if the reason cannot be recorded, do not close.
        res, calls = self._run(post=(False, {"error": "HTTP 403"}))
        self.assertFalse(res["success"])
        self.assertFalse(res["closed"])
        self.assertEqual(calls, ["post"], "must not patch when the reason did not land")

    def test_patch_failure_reports_that_the_reason_already_landed(self):
        res, calls = self._run(patch_ret=(False, {"error": "HTTP 422"}))
        self.assertFalse(res["success"])
        self.assertFalse(res["closed"])
        self.assertTrue(res["reason_posted"], "the PR now carries a 'closing' note; say so")
        self.assertEqual(calls, ["post", "patch"])

    def test_repo_is_threaded_to_every_call(self):
        """#4494 — a non-default PR must not be closed against the default repo."""
        other = "KytranKatarn/archie-code"
        with mock.patch.object(gs, "pr_merge_state", return_value="open") as state, mock.patch.object(
            gs, "_api_post", return_value=(True, {})
        ) as post, mock.patch.object(gs, "_api_patch", return_value=(True, {})) as patch:
            res = gs.close_pr(7, reason="dup", authored_by="kytran", repo=other)
        state.assert_called_once_with(7, other)
        self.assertIn(other, post.call_args[0][0])
        self.assertIn(other, patch.call_args[0][0])
        self.assertEqual(res["repo"], other)

    def test_defaults_to_the_default_repo_when_omitted(self):
        with mock.patch.object(gs, "pr_merge_state", return_value="open") as state, mock.patch.object(
            gs, "_api_post", return_value=(True, {})
        ), mock.patch.object(gs, "_api_patch", return_value=(True, {})) as patch:
            gs.close_pr(7, reason="dup", authored_by="kytran")
        state.assert_called_once_with(7, gs.REPO_FULL)
        self.assertIn(gs.REPO_FULL, patch.call_args[0][0])


class TestRouteIsAdminGatedAndAttributed(unittest.TestCase):
    def setUp(self):
        self.body = _close_pr_source()

    def test_route_requires_login_and_admin(self):
        self.assertIn('"/api/forge/pr/<int:pr_number>/close"', self.body)
        self.assertIn("@login_required", self.body)
        self.assertIn("@admin_required", self.body)

    def test_route_takes_the_reason_from_the_request_and_the_actor_from_the_session(self):
        self.assertRegex(self.body, r'reason\s*=\s*\(body\.get\("reason"\)')
        self.assertRegex(self.body, r"current_user")

    def test_route_refuses_a_missing_reason_with_400(self):
        # (?s) inline: assertRegex's 3rd positional arg is `msg`, not flags, so a
        # re.S passed there is silently ignored and the match fails across newlines.
        self.assertRegex(self.body, r"(?s)if not reason:.*?400")

    def test_route_maps_a_meaningless_state_to_409_not_a_server_fault(self):
        self.assertRegex(self.body, r"code\s*=\s*409\s+if")

    def test_route_calls_close_pr_with_explicit_attribution(self):
        self.assertRegex(
            self.body,
            r"close_pr\(\s*pr_number\s*,\s*reason\s*=\s*reason\s*,\s*authored_by\s*=\s*who",
        )


class TestThereIsNoUnattendedCaller(unittest.TestCase):
    """The contract that nothing automated can close a PR — pinned, not just documented.

    A merge has ``_automerge_governance_ok`` behind it, so a bad merge is refused at the
    server even if a loop calls it. A close has no such gate: the server would do exactly
    what it was told. The only thing preventing an unattended close is that the ONLY
    caller is the admin-gated route. If this test ever fails, that is the reason.
    """

    def _call_sites(self):
        hits = []
        for path in Path(ROOT).rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            for m in re.finditer(r"\bclose_pr\s*\(", text):
                line = text[: m.start()].count("\n") + 1
                hits.append((path.relative_to(ROOT).as_posix(), line, text[m.start() - 40 : m.start() + 60]))
        return hits

    def test_the_only_production_caller_is_the_admin_route(self):
        callers = sorted(
            {(p, ln) for p, ln, _ in self._call_sites() if not p.endswith("github_service.py")}
        )
        self.assertTrue(callers, "expected the admin route to be the caller")
        outside = [(p, ln) for p, ln in callers if p != "tools/repair_bay/github_routes.py"]
        self.assertEqual(
            outside,
            [],
            f"close_pr gained a caller outside the admin route at {outside} — an automated "
            "path can now close a PR with no verdict gate behind it",
        )

    def test_no_loop_or_pipeline_references_close_pr(self):
        """The unattended surfaces must not grow a close. Named explicitly rather than
        globbed, so the assertion says which file it is about."""
        for rel in (
            "tools/department_hq/services/agent_loop.py",
            "tools/repair_bay/services/forge_pipeline.py",
            "tools/repair_bay/services/background_workflow_runner.py",
            "tools/repair_bay/services/forge_self_heal.py",
        ):
            path = Path(ROOT) / rel
            if not path.exists():
                continue
            self.assertNotIn(
                "close_pr",
                path.read_text(errors="ignore"),
                f"{rel} references close_pr — closing must stay human-only",
            )


class TestCloseControlIsWiredInTheUI(unittest.TestCase):
    def setUp(self):
        self.js = _MAIN_JS.read_text()
        self.html = _TEMPLATE.read_text()

    def test_prompt_modal_exists_and_refuses_to_submit_empty(self):
        self.assertIn("function _rbLcarsPrompt(", self.js)
        self.assertRegex(self.js, r"if \(!val\) return;")
        # The confirm button starts disabled and is enabled by input, so the server's
        # "reason is required" rule is not reachable as a dead end.
        self.assertRegex(self.js, r"confirmBtn\.disabled = !has")

    def test_close_helper_posts_to_the_new_endpoint(self):
        self.assertIn("function forgeClosePR(", self.js)
        self.assertIn("api/forge/pr/' + prNumber + '/close", self.js)

    def test_close_helper_distinguishes_a_refusal_from_a_success(self):
        body = self.js[self.js.index("function forgeClosePR("):]
        body = body[: body.index("/* LCARS info modal")] if "/* LCARS info modal" in body else body
        self.assertIn("CLOSE REFUSED", body)
        self.assertIn("was not closed", body)

    def test_reviews_tab_exposes_a_close_control(self):
        self.assertIn("forgeClosePR(pr.pr_number, pr.repo)", self.html)

    def test_stats_panel_exposes_a_close_control(self):
        self.assertIn("forgeClosePR(pr.number, pr.repo)", self.html)

    def test_close_is_available_on_any_open_pr(self):
        """Close must NOT be gated on merge_order — that gate was wrong, not merely unused.

        ``merge_order.blocked`` marks THIS row as the DEPENDENT of an open ``#X``
        (merge_order.py: ``blocked = bool(declared_after)``). Closing the dependent
        strands nothing: ``#X`` still merges on its own. Gating Close on it would
        invent a restriction ``close_pr`` does not enforce, would make the two
        surfaces answer the same question differently, and would contradict the
        operator's decision that close works on any open PR. Only the MERGE button
        is dependency-gated, because the server actually refuses that merge.
        """
        self.assertNotIn("Cannot close:", self.html)
        for fragment in (
            "cursor:' + (_orderBlocked ? 'not-allowed' : 'pointer') + ';",
            "cursor:' + (_ob ? 'not-allowed' : 'pointer') + ';",
        ):
            self.assertNotIn(fragment, self.html, "the Close button must not be dependency-gated")
        # ...and it is still present and wired on both surfaces.
        self.assertIn("forgeClosePR(pr.pr_number, pr.repo)", self.html)
        self.assertIn("forgeClosePR(pr.number, pr.repo)", self.html)

    def test_the_merge_button_is_still_dependency_gated(self):
        """The asymmetry above is deliberate — keep the merge gate in place."""
        self.assertIn("if (orderBlocked)", _helper_source())


class TestMergeAffordanceIsSharedNotDuplicated(unittest.TestCase):
    """#5853's own comment says both surfaces should agree; the server half landed and
    only the Reviews-tab renderer was updated, so the stats panel kept showing an
    unconditional green Merge on PRs the server refuses. Both must now derive their
    button from ONE helper, so the two renderers cannot drift again.
    """

    def setUp(self):
        self.js = _MAIN_JS.read_text()
        self.html = _TEMPLATE.read_text()

    def test_single_helper_exists(self):
        self.assertIn("function _prMergeAffordance(", self.js)
        self.assertIn("function _prStyleMergeBtn(", self.js)

    def test_both_surfaces_use_it(self):
        self.assertEqual(self.html.count("_prMergeAffordance("), 2, "expected Reviews tab + stats panel")

    def test_stats_panel_no_longer_renders_an_unconditional_merge(self):
        # Anchor on the JS that populates the panel, not the container div (which is
        # far earlier in the file and would slice in half the template).
        js_at = self.html.index("getElementById('forgePRList')")
        panel = self.html[js_at : js_at + 3000]
        self.assertIn("_prStyleMergeBtn(", panel)
        self.assertNotIn("mergeBtn.textContent = 'Merge';", panel)
        # The old bug: an unconditional, always-enabled, always-green Merge.
        self.assertNotIn("color:#22c55e; border-radius:3px; cursor:pointer;'", panel)

    def test_the_old_inline_state_mapping_is_gone(self):
        # The per-surface duplicate is what let the two surfaces disagree.
        for gone in ("'Waiting for review';", "'Blocked — re-review'"):
            self.assertNotIn(
                gone,
                self.html,
                "the inline merge-state mapping should live in _prMergeAffordance now",
            )

    def test_absent_merge_state_degrades_to_legacy_not_to_disabled(self):
        """stamp_merge_states is best-effort; a stale payload must not disable every
        button on the panel. The server stays the authority either way."""
        helper = _helper_source()
        self.assertIn("if (!ms) return o;", helper)
        self.assertIn("can: true", helper)

    def test_dependency_order_outranks_the_legacy_fallback(self):
        """A missing merge_state must NOT rescue a row the merge order blocks.

        merge_state and merge_order are stamped by two independent best-effort
        steps (github_routes.forge_list_prs), each with its own try/except. If the
        state stamp raises and the order stamp succeeds, a row arrives with no
        merge_state AND a live merge_order.blocked. An early `if (!ms) return o;`
        before the order check would then advertise an enabled green Merge for a
        dependency the server refuses — the exact defect #2736/#5853 exist to
        prevent. Assert the order structurally, not by substring luck.
        """
        helper = _helper_source()
        block_at = helper.index("if (orderBlocked)")
        legacy_at = helper.index("if (!ms) return o;")
        self.assertLess(
            block_at, legacy_at,
            "the dependency block must be applied BEFORE the unstamped-row fallback",
        )

    def test_dropped_file_count_only_reaches_the_coverage_label(self):
        helper = _helper_source()
        unread = helper.index("'Merge (' + d + ' unread)'")
        self.assertIn("var d = droppedCount || 0;", helper)
        self.assertLess(helper.index("coverage_only"), unread)


class TestMergeAffordanceBehaviourHolds(unittest.TestCase):
    """Execute the real helpers in node.

    The pins above read the JS as text, which cannot see a behavioural regression
    inside the function — an early return or an inverted comparison leaves every
    string in place. ``repair_bay_merge_affordance.mjs`` lifts the actual helpers out
    of the shipped file and runs them, so the behaviour is checked, not the spelling.
    """

    def test_every_affordance_behaviour_holds(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed; run the .mjs in CI or in the platform image")
        proc = subprocess.run(
            [node, str(_MJS)], capture_output=True, text=True, timeout=120
        )
        self.assertEqual(
            proc.returncode, 0,
            "merge-affordance behaviour regressed:\n"
            f"{proc.stdout}\n{proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
