"""A draft PR must not be merge-attempted every tick (#5362).

GitHub answers HTTP 405 "Pull Request is still a draft", and nothing marks the
attempt processed on failure — correctly, since it must still merge once
undrafted. So the tier worker retried forever: 35 attempts in 6 hours for PR
#2444 alone, and worse after the tick moved 10 min -> 2 min. That burns API
quota and emits a WARNING every cycle, which is how a log line stops being read.

The fix records `draft` at POLL time (the PR-list response already carries it)
so the worker's skip costs ZERO extra API calls.

The dangerous part of this change is NOT the skip — it is that `poll_open_prs`
now writes `metadata`, a column that already carries `tier_processed`,
`forge_escalated_tier` and `review_path`. A poll that REPLACED it would silently
undo the #5363 escalation fix and re-open the merge-loop bug. Hence the
merge-not-replace tests below.
"""

import re


import tools.repair_bay.services.pr_review_service as prs


class TestPollPreservesExistingMetadata:
    """`||` merges; `=` would wipe. This is the regression that would hurt."""

    @staticmethod
    def _upsert_sql():
        import inspect

        src = inspect.getsource(prs.poll_open_prs)
        m = re.search(r"INSERT INTO pr_reviews.*?RETURNING", src, re.S)
        assert m, "upsert statement not found — test is stale"
        return " ".join(m.group(0).split())

    def test_conflict_clause_merges_metadata_rather_than_replacing(self):
        sql = self._upsert_sql()
        assert "metadata       = COALESCE(pr_reviews.metadata, '{}'::jsonb) || EXCLUDED.metadata".replace(
            "       ", " "
        ) in sql.replace("  ", " "), (
            "poll must MERGE metadata — a plain assignment would wipe tier_processed / "
            "forge_escalated_tier and silently undo #5363"
        )

    def test_conflict_clause_never_plainly_assigns_metadata(self):
        sql = self._upsert_sql()
        # after the ON CONFLICT, `metadata = EXCLUDED.metadata` (no COALESCE/||) is the bug
        after = sql.split("ON CONFLICT", 1)[1]
        assert "metadata = EXCLUDED.metadata" not in after.replace("  ", " ")

    def test_metadata_is_actually_written(self):
        sql = self._upsert_sql()
        assert "metadata" in sql.split("ON CONFLICT", 1)[0], "metadata must be in the INSERT column list"

    def test_json_adapter_is_in_scope(self):
        """`_Json` is imported function-locally in this module; poll_open_prs needs its own."""
        import inspect

        src = inspect.getsource(prs.poll_open_prs)
        assert "from psycopg2.extras import Json as _Json" in src, (
            "_Json is imported per-function in this file — without a local import "
            "the upsert raises NameError at runtime"
        )
        assert "_Json({" in src


class TestDraftFlagCapture:
    def test_draft_is_read_from_the_poll_response(self):
        """The PR-list payload already carries `draft` — that is why this is free."""
        import inspect

        src = inspect.getsource(prs.poll_open_prs)
        assert 'pr.get("draft")' in src
        assert 'bool(pr.get("draft"))' in src, "coerce to a real bool — GitHub may omit the key"


class TestWorkerSkipsDrafts:
    """Mirrors the guard in _run_archie_pr_review_worker."""

    @staticmethod
    def _is_skipped(review):
        # the exact predicate used in agent_loop
        return bool((review.get("metadata") or {}).get("draft"))

    def test_draft_true_is_skipped(self):
        assert self._is_skipped({"metadata": {"draft": True}}) is True

    def test_draft_false_is_not_skipped(self):
        assert self._is_skipped({"metadata": {"draft": False}}) is False

    def test_absent_draft_is_not_skipped(self):
        """FAIL-OPEN. Pre-existing rows have no draft key; they must still merge."""
        assert self._is_skipped({"metadata": {"tier_processed": 1}}) is False

    def test_null_metadata_is_not_skipped(self):
        assert self._is_skipped({"metadata": None}) is False
        assert self._is_skipped({}) is False

    def test_skip_does_not_mark_the_pr_processed(self):
        """A skipped draft must remain eligible once it is marked ready."""
        import inspect

        import ai_bridge.agent_loop as al  # noqa: PLC0415

        src = inspect.getsource(al.AgentLoop._run_archie_pr_review_worker)
        m = re.search(r'\.get\("draft"\).*?continue', src, re.S)
        assert m, "draft guard not found in the worker"
        block = m.group(0)
        assert (
            "_mark_tier_processed" not in block
        ), "a draft skip must NOT mark the PR processed — it has to merge later"

    def test_guard_sits_before_any_merge_work(self):
        """Pin the ORDER so the skip stays deliberate.

        Compare against the CALL `classify_pr_tier(review)`, not the bare name —
        the name also appears in the function's import block near the top, which
        made an earlier version of this test compare against index 356 and fail
        for the wrong reason.
        """
        import inspect

        import ai_bridge.agent_loop as al  # noqa: PLC0415

        src = inspect.getsource(al.AgentLoop._run_archie_pr_review_worker)
        draft_at = src.index('.get("draft")')
        assert src.index("if not verdict_is_approved(summary)") < draft_at, "cheapest rejection first"
        assert draft_at < src.index("classify_pr_tier(review)"), "skip before any tier/merge work"
        assert draft_at < src.index('merge_pr(pr_num, "squash")'), "skip before the API call it exists to avoid"
