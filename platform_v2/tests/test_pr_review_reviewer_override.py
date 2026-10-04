"""Pin the per-send reviewer override behind the PR Review tab's agent selector.

Motivation: CodeRabbit reviews 1 PR/hour and this platform ships more than that, so
most PRs reached a human unreviewed. An operator needs to be able to move the review
seat — to P.R.O.B.E., the already-designated machine-PR reviewer — without editing
global settings.

Three properties, all asserted here:

1. THREAD-LOCAL. Reviews run in daemon threads; a module global would leak one PR's
   reviewer into a concurrent review of another. contextvars would not help either —
   threading.Thread does not copy the caller's context.

2. IT FAILS CLOSED. The request body's `reviewer` is untrusted input. Only names in
   REVIEWER_ALLOWLIST may ever become a `prefer_agent`, because `prefer_agent` decides
   WHICH AGENT reviews the code — an unvalidated name would let a caller aim a review
   at any agent, including themselves, which is the self-review class #2458/#6040
   exist to prevent.

3. AN OVERRIDE WINS OVER THE MACHINE-BRANCH RULE, but an invalid one does not. The
   tab exists so a human can move the seat; a default that silently overrode the
   choice would make the control a lie. Conversely a typo must degrade to normal
   routing rather than to a surprising reviewer.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402


class TestAllowlist(unittest.TestCase):
    def test_allowlist_is_a_tuple_of_known_agents(self):
        self.assertIsInstance(pda.REVIEWER_ALLOWLIST, tuple)
        self.assertIn("F.O.R.G.E.", pda.REVIEWER_ALLOWLIST)
        self.assertIn("P.R.O.B.E.", pda.REVIEWER_ALLOWLIST)

    def test_allowlist_excludes_agents_with_no_dispatch_history(self):
        """Codex (CLI) is registered and active but has 0 bridge_jobs and no skills.

        It is deliberately NOT selectable yet: making it the reviewer before its worker
        is verified would mean the first PR review it ever ran was also its first
        execution of any kind. This test is the reminder to add it once it can dispatch.
        """
        self.assertNotIn(
            "Codex (CLI)",
            pda.REVIEWER_ALLOWLIST,
            "Codex (CLI) has no skills and has never been dispatched. Only allowlist it "
            "after a real end-to-end dispatch has been verified.",
        )


class TestOverrideApplies(unittest.TestCase):
    def test_override_changes_the_reviewer(self):
        self.assertIsNone(pda._review_prefer_agent())
        with pda.reviewer_override("P.R.O.B.E."):
            self.assertEqual(pda._review_prefer_agent(), "P.R.O.B.E.")
        self.assertIsNone(pda._review_prefer_agent(), "must restore on exit")

    def test_unknown_name_is_ignored_not_honoured(self):
        """An unvalidated name must never become a prefer_agent."""
        with pda.reviewer_override("C.E.O."):
            self.assertIsNone(pda._review_prefer_agent())

    def test_none_and_empty_are_ignored(self):
        for value in (None, "", "   "):
            with pda.reviewer_override(value):
                self.assertIsNone(pda._review_prefer_agent())

    def test_nested_override_restores_the_outer_value(self):
        with pda.reviewer_override("P.R.O.B.E."):
            with pda.reviewer_override("F.O.R.G.E."):
                self.assertEqual(pda._review_prefer_agent(), "F.O.R.G.E.")
            self.assertEqual(pda._review_prefer_agent(), "P.R.O.B.E.")


class TestOverrideWinsOverMachineBranch(unittest.TestCase):
    def test_machine_branch_still_defaults_to_probe_when_unset(self):
        token = pda._REVIEW_HEAD_BRANCH.set("archie/forge/fix-1234")
        try:
            self.assertEqual(pda._review_prefer_agent(), "P.R.O.B.E.")
        finally:
            pda._REVIEW_HEAD_BRANCH.reset(token)

    def test_explicit_choice_overrides_the_machine_branch_default(self):
        """The whole point of the control: a human can move the seat on ANY PR."""
        token = pda._REVIEW_HEAD_BRANCH.set("archie/forge/fix-1234")
        try:
            with pda.reviewer_override("F.O.R.G.E."):
                self.assertEqual(pda._review_prefer_agent(), "F.O.R.G.E.")
        finally:
            pda._REVIEW_HEAD_BRANCH.reset(token)

    def test_human_branch_is_unaffected_by_the_machine_rule(self):
        token = pda._REVIEW_HEAD_BRANCH.set("feat/some-human-branch")
        try:
            self.assertIsNone(pda._review_prefer_agent())
        finally:
            pda._REVIEW_HEAD_BRANCH.reset(token)


class TestThreadLocality(unittest.TestCase):
    def test_one_threads_reviewer_does_not_leak_into_another(self):
        """The defect this guards: PR A's reviewer bleeding into PR B's review."""
        seen: dict[str, object] = {}
        started = threading.Event()
        release = threading.Event()

        def reviewer_b():
            started.wait(5)
            seen["b"] = pda._review_prefer_agent()
            release.set()

        t = threading.Thread(target=reviewer_b, daemon=True)
        t.start()
        try:
            with pda.reviewer_override("P.R.O.B.E."):
                seen["a"] = pda._review_prefer_agent()
                started.set()
                release.wait(5)
        finally:
            t.join(timeout=5)

        self.assertEqual(seen.get("a"), "P.R.O.B.E.", "override must apply in its own thread")
        self.assertIsNone(seen.get("b"), "reviewer leaked across threads")

    def test_override_does_not_survive_the_with_block(self):
        with pda.reviewer_override("P.R.O.B.E."):
            pass
        self.assertIsNone(pda._review_prefer_agent())
        self.assertNotIn("agent", vars(pda._reviewer_local), "exit must restore, not merely unset in this thread")


if __name__ == "__main__":
    unittest.main()
