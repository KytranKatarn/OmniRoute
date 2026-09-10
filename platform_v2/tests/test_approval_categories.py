"""Approvals tab: category grouping + stale merge-approval reconciliation (#5862).

Two features, one tab:

  * `category_of` drives the sub-tab filter. The tests that matter are not "does
    pr_merge say ship" — they are the two INVARIANTS a filter can silently violate:
    a prerequisite must never end up in a different tab from the thing it gates, and
    a NEW outbound action must not default into a tab nobody reviews.

  * `close_stale_pr_merge_approvals` closes approvals whose PR already merged. The
    test that matters is the FAIL-SAFE: an unreadable GitHub response must leave the
    row alone, because cancelling a real merge request on an API blip is worse than
    showing one stale row.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.department_hq.services.approvals_bulk import (  # noqa: E402
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    CATEGORY_PRIORITY,
    PREREQUISITES,
    category_of,
)


class TestCategoryMapping(unittest.TestCase):
    def test_known_types_land_in_the_expected_tab(self):
        cases = {
            "pr_merge": "ship",
            "deploy_approve": "ship",
            "backup_before_deploy": "ship",
            "improvement_approve": "ship",
            "improvement_approve_red": "ship",
            "website_deploy": "ship",
            # #6653/#6680 — the cloud coding lane. BOTH halves must be Ship: the apply
            # is gated by the dispatch that precedes it, and the invariant pinned by
            # test_prerequisite_and_gated_action_share_a_category says a prerequisite
            # and the action it gates share a category, or a filtered view hides the
            # blocker from the blocked item. "cloud_code_" is NOT a _CATEGORY_PREFIXES
            # entry, so each one has to be named.
            "cloud_code_dispatch": "ship",
            "cloud_code_apply": "ship",
            "linkedin_post": "social",
            "linkedin_comment_reply": "social",
            "email_reply": "mail",
            "hire_candidate": "agents",
            "create_agent": "agents",
        }
        for action, expected in cases.items():
            self.assertEqual(category_of(action), expected, f"{action} miscategorised")

    def test_unknown_and_empty_never_raise(self):
        for value in (None, "", "   ", "totally_made_up", 123):
            self.assertIsInstance(category_of(value), str)
        self.assertEqual(category_of(None), "other")
        self.assertEqual(category_of("totally_made_up"), "other")

    def test_case_and_whitespace_insensitive(self):
        self.assertEqual(category_of("  PR_Merge "), "ship")

    def test_a_brand_new_linkedin_action_is_social_not_other(self):
        """Prefix-matching exists so a NEW publish action cannot hide in 'Other'.

        linkedin_comment_like and linkedin_reply both arrived after the original four.
        An exhaustive list would have dropped them into a tab the operator does not
        use to review outbound content — the one category where being missed matters.
        """
        self.assertEqual(category_of("linkedin_some_future_skill"), "social")
        self.assertEqual(category_of("linkedin_comment_like"), "social")

    def test_every_prioritised_type_has_a_category(self):
        """CATEGORY_PRIORITY is the platform's list of known approval types.

        Anything it sorts must also be placeable in a tab, or the sub-tab counts stop
        summing to the total the badge shows.
        """
        for action in CATEGORY_PRIORITY:
            self.assertIn(category_of(action), CATEGORY_ORDER, f"{action} has no valid category")

    def test_every_category_has_a_label(self):
        for key in CATEGORY_ORDER:
            self.assertIn(key, CATEGORY_LABELS)

    def test_prerequisite_and_gated_action_share_a_category(self):
        """THE INVARIANT the filter could silently break.

        The tab filters an already-sorted, already-gated list. If a blocked action sat
        in one tab while the approval that unblocks it sat in another, a filtered view
        would show something un-actionable with no visible way to clear it. Today
        deploy_approve/improvement_approve_red/website_deploy all depend on
        backup_before_deploy + pr_merge, and all five are 'ship'. This test fails the
        moment that stops being true.
        """
        for gated, prereqs in PREREQUISITES.items():
            for prereq_type, _why in prereqs:
                self.assertEqual(
                    category_of(gated),
                    category_of(prereq_type),
                    f"{gated} is in '{category_of(gated)}' but its prerequisite "
                    f"{prereq_type} is in '{category_of(prereq_type)}' — a filtered "
                    "view would hide the blocker",
                )


def _fake_cursor(rows):
    """A cursor stub that returns `rows` for the SELECT and echoes UPDATE RETURNING."""
    cur = mock.MagicMock()
    state = {"last_sql": ""}

    def execute(sql, params=None):
        state["last_sql"] = sql
        state["params"] = params

    def fetchall():
        return rows

    def fetchone():
        # Only the UPDATE ... RETURNING id path calls fetchone here.
        return {"id": state.get("params", [None, None, None])[-1]}

    cur.execute.side_effect = execute
    cur.fetchall.side_effect = fetchall
    cur.fetchone.side_effect = fetchone
    return cur


class _CursorCtx:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return (mock.MagicMock(), self.cur)

    def __exit__(self, *a):
        return False


class TestStaleMergeApprovalSweep(unittest.TestCase):
    """#5862 — 4 of 4 pending merge approvals pointed at already-merged PRs."""

    def _run(self, rows, pr_is_open_result):
        from tools.department_hq.services import approvals_reconcile as ar

        cur = _fake_cursor(rows)
        fake_db = types.ModuleType("database")
        fake_db.get_db_cursor = lambda commit=False: _CursorCtx(cur)
        fake_gh = types.ModuleType("github_service")
        if isinstance(pr_is_open_result, Exception):
            fake_gh.pr_is_open = mock.Mock(side_effect=pr_is_open_result)
        else:
            fake_gh.pr_is_open = mock.Mock(return_value=pr_is_open_result)

        with mock.patch.dict(
            sys.modules,
            {
                "database": fake_db,
                "tools.repair_bay.services.github_service": fake_gh,
            },
        ):
            return ar.close_stale_pr_merge_approvals()

    ROW = [{"id": 11696, "pr_number": 2713, "repo": "KytranKatarn/archie-platform"}]

    def test_merged_pr_closes_the_approval(self):
        result = self._run(self.ROW, False)
        self.assertEqual(result["closed"], [11696])
        self.assertEqual(result["undetermined"], [])

    def test_still_open_pr_is_left_alone(self):
        result = self._run(self.ROW, True)
        self.assertEqual(result["closed"], [])
        self.assertEqual(result["left_open"], [11696])

    def test_unreadable_github_leaves_the_row_pending(self):
        """FAIL-SAFE. `pr_is_open` returns None when GitHub cannot be read.

        Treating None as 'merged' would cancel a real, actionable merge approval every
        time the API blipped — silently discarding work. One stale row costs a glance;
        a discarded approval costs a merge nobody remembers to redo.
        """
        result = self._run(self.ROW, None)
        self.assertEqual(result["closed"], [])
        self.assertEqual(result["undetermined"], [11696])

    def test_an_exception_is_also_treated_as_undetermined(self):
        result = self._run(self.ROW, RuntimeError("boom"))
        self.assertEqual(result["closed"], [])
        self.assertEqual(result["undetermined"], [11696])

    def test_row_without_a_pr_number_is_not_judged(self):
        rows = [{"id": 999, "pr_number": None, "repo": None}]
        result = self._run(rows, False)
        self.assertEqual(result["closed"], [])
        self.assertEqual(result["undetermined"], [999])

    def test_never_raises_when_the_database_is_unavailable(self):
        """Runs inside sync_closed_prs — its other work must survive a failure here."""
        from tools.department_hq.services import approvals_reconcile as ar

        broken = types.ModuleType("database")

        def _boom(commit=False):
            raise RuntimeError("db down")

        broken.get_db_cursor = _boom
        fake_gh = types.ModuleType("github_service")
        fake_gh.pr_is_open = mock.Mock(return_value=False)
        with mock.patch.dict(
            sys.modules,
            {"database": broken, "tools.repair_bay.services.github_service": fake_gh},
        ):
            result = ar.close_stale_pr_merge_approvals()
        self.assertEqual(result["closed"], [])


class TestWiring(unittest.TestCase):
    def test_sync_closed_prs_invokes_the_reconcile(self):
        """Wired at sync_closed_prs, not per-caller — it has three callers."""
        import inspect

        from tools.repair_bay.services import pr_review_service

        src = inspect.getsource(pr_review_service.sync_closed_prs)
        self.assertIn("close_stale_pr_merge_approvals", src)

    def test_merge_pr_closes_approvals_at_the_choke_point(self):
        import inspect

        from tools.repair_bay.services import github_service

        src = inspect.getsource(github_service.merge_pr)
        self.assertIn("close_pr_merge_approvals_for", src)

    def test_pending_endpoint_stamps_category_server_side(self):
        """A second copy of the taxonomy in JS would drift from the backend's."""
        import inspect

        from tools.department_hq import approvals_routes

        src = inspect.getsource(approvals_routes.register_approvals_routes)
        self.assertIn('a["category"] = category_of(', src)


if __name__ == "__main__":
    unittest.main()
