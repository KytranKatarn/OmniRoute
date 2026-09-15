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

    def test_hub_deploy_uses_heredoc_style_branching(self):
        body = _merge_route_source()
        # Enqueue failure must never fail the merge.
        self.assertIn("enqueue failure never fails the merge", body)


class TestRepoValidator(unittest.TestCase):
    def test_shapes(self):
        from tools.repair_bay.services.pr_review_service import _is_valid_repo

        self.assertTrue(_is_valid_repo("KytranKatarn/archie-code"))
        self.assertFalse(_is_valid_repo("../../etc"))
        self.assertFalse(_is_valid_repo("no-slash"))
        self.assertFalse(_is_valid_repo(""))
        self.assertFalse(_is_valid_repo(None))


if __name__ == "__main__":
    unittest.main()
