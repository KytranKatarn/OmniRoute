"""The Repair Bay merge button must carry the ROW's repo to the server, and the server
must use it for BOTH the verdict lookup and the merge.

Measured 2026-09-11 on archie-code #64 and #65: both held a clean F.O.R.G.E. APPROVE
(review_pr(repo=...) stores cross-repo rows and the tab lists them), yet the Merge button
answered 422 "no stored F.O.R.G.E. review — a dead review is not an approval". The route
called get_review(pr_number) and merge_pr(pr_number, ...) with no repo, so it searched
archie-platform for the same number. Had a same-numbered archie-platform PR carried an
approval, human_override would have merged THAT one.

These are source-level pins in the style of test_merge_state_ui: the route is a closure
inside register_github_routes, and the property that matters is which arguments it
forwards, which the text states unambiguously.
"""

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_ROUTES = Path(ROOT) / "tools" / "repair_bay" / "github_routes.py"
_TEMPLATE = Path(ROOT) / "templates" / "tools" / "repair_bay.html"


def _merge_route_source() -> str:
    src = _ROUTES.read_text()
    start = src.index("def forge_merge_pr(")
    end = src.index("@bp.route(", start)
    return src[start:end]


class TestRouteForwardsTheRepo(unittest.TestCase):
    def test_verdict_lookup_is_repo_scoped(self):
        body = _merge_route_source()
        self.assertRegex(body, r"get_review\(\s*pr_number\s*,\s*repo\s*=")

    def test_merge_is_repo_scoped(self):
        body = _merge_route_source()
        self.assertRegex(body, r"merge_pr\(\s*pr_number\s*,\s*method\s*,\s*repo\s*=")

    def test_no_repo_blind_calls_remain(self):
        """The two calls the bug lived in must not survive in their old shape."""
        body = _merge_route_source()
        self.assertNotRegex(body, r"get_review\(\s*pr_number\s*\)")
        self.assertNotRegex(body, r"merge_pr\(\s*pr_number\s*,\s*method\s*,\s*human_override")

    def test_a_malformed_repo_is_rejected_before_any_lookup(self):
        body = _merge_route_source()
        self.assertIn("_is_valid_repo", body)
        self.assertLess(body.index("_is_valid_repo"), body.index("get_review("))

    def test_approval_bookkeeping_stays_on_the_default_repo(self):
        """pr_merge approval rows are keyed by number alone and exist only for the polled
        repo — resolving one for a cross-repo PR would close a different PR's approval."""
        body = _merge_route_source()
        idx = body.index("resolve_pr_merge_approval(pr_number")
        guard = body[:idx].rsplit("if ", 1)[-1]
        self.assertIn("REPO_FULL", guard)


class TestTheSecondSurfaceIsRepoScopedToo(unittest.TestCase):
    """forge_pr_review_merge already merged with the ROW's repo but looked the row up
    without one — the same number in another repo shadowed it."""

    def test_lookup_is_repo_scoped(self):
        src = _ROUTES.read_text()
        start = src.index("def forge_pr_review_merge(")
        end = src.find("@bp.route(", start)
        body = src[start : end if end != -1 else len(src)]
        self.assertRegex(body, r"get_review\(\s*pr_number\s*,\s*repo\s*=")
        self.assertNotRegex(body, r"get_review\(\s*pr_number\s*\)")


class TestTheClickCarriesTheRepo(unittest.TestCase):
    def test_confirm_merge_accepts_and_sends_repo(self):
        src = _TEMPLATE.read_text()
        self.assertRegex(src, r"function confirmMergePR\(prNumber,\s*coverageAck,\s*repo\)")
        self.assertRegex(src, r"coverage_ack:\s*!!coverageAck,\s*repo:\s*repo\s*\|\|\s*null")

    def test_the_row_passes_its_own_repo(self):
        src = _TEMPLATE.read_text()
        self.assertIn("confirmMergePR(pr.pr_number, false, pr.repo)", src)

    def test_the_coverage_ack_retry_keeps_the_repo(self):
        src = _TEMPLATE.read_text()
        self.assertIn("confirmMergePR(prNumber, true, repo)", src)


class TestHubDeployEnqueueIsRepoScoped(unittest.TestCase):
    """Merging the DEFAULT repo must enqueue the hub auto-deploy (host pull + restart),
    and a cross-repo merge must NEVER deploy the hub."""

    def test_cross_repo_merge_never_deploys_the_hub(self):
        body = _merge_route_source()
        # The refusal line must be the else-branch of the default-repo gate: the gate
        # appears before it and an `else:` separates them.
        idx = body.index('"cross-repo merge does not deploy the hub"')
        prefix = body[:idx]
        gate = prefix.rfind("if not _repo or _repo == REPO_FULL:")
        self.assertGreaterEqual(gate, 0)
        self.assertIn("else:", prefix[gate:])

    def test_hub_deploy_enqueue_is_async_never_sync_wait(self):
        body = _merge_route_source()
        # The host restarts archie_platform — the container this request runs in. A
        # submit_and_wait() call would kill the reply mid-request, so only submit_host_command
        # is acceptable here. (The words appear in the doc comment; the CALL must not.)
        self.assertIn("submit_host_command(", body)
        self.assertNotRegex(body, r"submit_and_wait\s*\(")

    def test_hub_deploy_surfaces_in_the_merge_response(self):
        body = _merge_route_source()
        self.assertIn('result["deploy"]', body)
        self.assertIn('"enqueued"', body)

    def test_an_enqueue_failure_never_fails_the_merge(self):
        """⚠️ Pins the BEHAVIOUR, not the prose.

        This asserted that the literal string "enqueue failure never fails the merge"
        appeared in the source. The comment was later reworded to "bookkeeping never
        fails a real merge" and the test went red while the behaviour was perfectly
        intact. A test pinning a COMMENT fails on an edit that changes nothing, and
        passes when the comment is right and the code is wrong — useless in both
        directions. (Its old name, "uses_heredoc_style_branching", described neither.)

        What actually matters: the merge has already happened by the time the deploy is
        enqueued, so an enqueue failure must be caught, reported as enqueued:false, and
        never propagate — a merged PR reported as failed is worse than an un-deployed one.
        """
        tail = _merge_route_source()
        tail = tail[tail.index("submit_host_command(") :]
        self.assertRegex(tail, r"except\s+Exception\s+as\s+deploy_exc")
        self.assertIn('"enqueued": False', tail)
        self.assertRegex(tail, r"logger\.warning\(")


class TestRepoValidator(unittest.TestCase):
    def test_shapes(self):
        from tools.repair_bay.services.pr_review_service import _is_valid_repo

        self.assertTrue(_is_valid_repo("KytranKatarn/archie-code"))
        self.assertFalse(_is_valid_repo("../../etc"))
        self.assertFalse(_is_valid_repo("no-slash"))
        self.assertFalse(_is_valid_repo(""))
        self.assertFalse(_is_valid_repo(None))


def _get_route_source() -> str:
    src = _ROUTES.read_text()
    start = src.index("def forge_pr_review_get(")
    end = src.index("@bp.route(", start)
    return src[start:end]


class TestTheSingleReviewGetIsRepoAware(unittest.TestCase):
    """THE THIRD INSTANCE of the defect this file already documents.

    The merge route was fixed (above). `forge_pr_review_send_back`, two routes down, was
    written repo-aware from the start (`repo=data.get("repo")`). `forge_pr_review_get`
    sat between them still calling `get_review(pr_number)` bare.

    `get_review` pins a bare call to `_DEFAULT_REPO` through an equality predicate, so it
    could never "resolve to an unintended repository" — the failure is the other
    direction: for a PR in ANY other repo the route answered 404 "not found" while a
    review existed, and for a colliding number (archie-code #71 vs archie-platform #71,
    measured 2026-09-16, #6776) it returned the WRONG PR's review under a 200.

    Source-level pins, in this file's established style: the route is a closure inside
    register_github_routes, and what matters is which arguments it forwards.
    """

    def test_the_lookup_is_repo_scoped(self):
        self.assertRegex(_get_route_source(), r"get_review\(\s*pr_number\s*,\s*repo\s*=")

    def test_it_accepts_an_explicit_repo(self):
        self.assertIn('request.args.get("repo")', _get_route_source())

    def test_it_resolves_through_the_ambiguity_gate(self):
        # Never guess: the same gate the rest of the pipeline uses.
        self.assertIn("repos_for_pr_number", _get_route_source())

    def test_it_refuses_rather_than_guessing_on_a_collision(self):
        body = _get_route_source()
        self.assertIn("409", body)
        self.assertIn("ambiguous", body)

    def test_an_unreadable_lookup_fails_CLOSED(self):
        """#6787 is exactly this: `repos_for_pr_number` returns None for a FAILED lookup
        and [] for "genuinely no rows", and collapsing them let a DB blip sail through a
        `len(...) > 1` test. A 503 is honest; defaulting to archie-platform on an
        unreadable lookup is how #6776 became re-enterable by a transient error."""
        body = _get_route_source()
        self.assertRegex(body, r"candidates\s+is\s+None")
        self.assertIn("503", body)


if __name__ == "__main__":
    unittest.main()
