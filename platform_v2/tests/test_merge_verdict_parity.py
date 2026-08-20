"""#5834 PARITY — every attended merge surface enforces the SAME verdict rule.

The Approvals tab gained a verdict + freshness check in #2712. The two
@admin_required Repair Bay routes did not, so the SAME PR that the tab refused
could be merged from the Repair Bay UI on a needs_changes verdict. A safety rule
implemented in one place and not another is how #2458 reached main.

These tests pin BOTH halves:
  1. verdict_refusal's decision table (pure — no DB, no GitHub, no Flask).
  2. that each route actually CALLS it, and calls it BEFORE merge_pr — a check
     that runs after the merge is not a check.

Deliberately NOT asserted: that the routes re-impose the allowlist or the tier
ceiling. Those are AUTHORITY limits and an authenticated human clicking Merge is
exactly the authority they exist to require (decision #953). Asserting them here
would lock in the opposite of the intended design.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services.github_service import verdict_refusal  # noqa: E402

_ROUTES = _ROOT / "tools" / "repair_bay" / "github_routes.py"


class TestVerdictRefusalTable(unittest.TestCase):
    def test_missing_review_refuses(self):
        why = verdict_refusal("", False)
        self.assertIsNotNone(why)
        self.assertIn("dead review", why)

    def test_non_approval_refuses(self):
        why = verdict_refusal("VERDICT: REQUEST CHANGES", False)
        self.assertIsNotNone(why)
        self.assertIn("NOT an approval", why)

    def test_approval_allows(self):
        self.assertIsNone(verdict_refusal("VERDICT: APPROVE", True))

    def test_summary_present_but_verdict_false_still_refuses(self):
        """A stored summary is not consent. Only verdict_ok clears it."""
        self.assertIsNotNone(verdict_refusal("SUMMARY ... VERDICT: NEEDS REVIEW", False))


class TestTabDelegatesToTheSameRule(unittest.TestCase):
    """The tab must not keep a private copy of the verdict branches."""

    def test_tab_refusal_agrees_with_verdict_refusal(self):
        from ai_bridge.agent_loop import tab_merge_refusal

        # gate_ok=True so only the verdict half can be responsible for a refusal.
        for summary, vok in (("", False), ("VERDICT: REQUEST CHANGES", False), ("VERDICT: APPROVE", True)):
            self.assertEqual(
                tab_merge_refusal(summary, vok, True, ""),
                verdict_refusal(summary, vok),
                f"tab and shared rule disagree for {summary!r}",
            )


class TestBothAdminRoutesCheckBeforeMerging(unittest.TestCase):
    """Source-order: the guard must precede the merge call it exists to prevent."""

    @staticmethod
    def _route_body(name: str) -> str:
        tree = ast.parse(_ROUTES.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(_ROUTES.read_text(), node) or ""
        raise AssertionError(f"route {name} not found — did it get renamed?")

    def _assert_guarded(self, name: str):
        body = self._route_body(name)
        self.assertIn("verdict_refusal", body, f"{name} does not consult the shared verdict rule")
        guard = body.index("verdict_refusal")
        # \b matters: `def forge_merge_pr(` CONTAINS the substring `merge_pr(`, so a plain
        # .index() finds the function's own NAME at offset ~10 and every guard looks late.
        # `_` is a word character, so \bmerge_pr\( cannot match inside forge_merge_pr(.
        call = re.search(r"\bmerge_pr\(", body)
        self.assertIsNotNone(call, f"{name} never calls merge_pr — did it get refactored?")
        self.assertLess(guard, call.start(), f"{name} checks the verdict AFTER merging — that is not a check")

    def test_forge_merge_pr_is_guarded(self):
        self._assert_guarded("forge_merge_pr")

    def test_forge_pr_review_merge_is_guarded(self):
        self._assert_guarded("forge_pr_review_merge")

    def test_both_routes_still_pass_human_override(self):
        """Parity is about SAFETY. The routes must keep clearing AUTHORITY, or the
        allowlist — which exists to require a human — would block the human."""
        for name in ("forge_merge_pr", "forge_pr_review_merge"):
            self.assertIn("human_override=True", self._route_body(name), name)


if __name__ == "__main__":
    unittest.main()
