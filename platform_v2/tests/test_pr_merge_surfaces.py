"""One PR-merge decision, three surfaces that agree (#5283 + #5338).

Kytran, 2026-07-28: "I already get a Telegram alert when it was approved… can we
add buttons there? …can we have this all connected with the approvals tab".

What was actually broken:
  * the SENSITIVE-PATH gate only wrote an informational notification — no
    approval row, no buttons — so an APPROVED PR had to be merged by typing
    /merge-pr from memory;
  * the Approvals-tab tap was a DEAD END: `_execute_approved_action` had no
    `pr_merge` branch, so approving there flipped the row and merged nothing;
  * the Telegram button merges *then* flips the row to 'approved', so the
    executor meets an already-merged PR — approval #5816 recorded 'failed' for
    PR #2522, which had merged successfully 18 seconds earlier.

These pin the contract: ask on every surface, execute on any surface, and
already-merged is success.
"""

import tools.repair_bay.services.pr_review_service as prs


class TestGateAsksInsteadOfAnnouncing:
    def test_send_pr_merge_buttons_uses_the_shared_callback_ids(self, monkeypatch):
        """One gateway handler (^pr_merge_) must serve every surface."""
        sent = {}

        import services.telegram_service as tg

        monkeypatch.setattr(tg, "send_with_buttons", lambda **kw: sent.update(kw) or {"sent": True})
        prs.send_pr_merge_buttons(2533, "fix(deploy): honest chain", "F.O.R.G.E. approved.")

        labels = [b["callback_data"] for b in sent["buttons"]]
        assert labels == ["pr_merge_approve_2533", "pr_merge_deny_2533"]
        assert "2533" in sent["title"]

    def test_button_send_failure_never_raises(self, monkeypatch):
        import services.telegram_service as tg

        def boom(**kw):
            raise RuntimeError("telegram down")

        monkeypatch.setattr(tg, "send_with_buttons", boom)
        prs.send_pr_merge_buttons(1, "t", "s")  # must not raise

    def test_open_pr_merge_approval_files_queue_tier_2_not_1(self, monkeypatch):
        """PR-authority tier 3 != queue tier. Queue tier 1 would AUTO-APPROVE."""
        captured = {}
        import ai_bridge.agent_loop as al

        monkeypatch.setattr(al, "request_approval", lambda **kw: captured.update(kw) or 99)
        assert prs.open_pr_merge_approval(2533, "title", "summary", repo="o/r") == 99
        assert captured["action_type"] == "pr_merge"
        assert captured["tier"] == 2
        assert captured["action_data"]["pr_number"] == 2533
        assert captured["action_data"]["repo"] == "o/r"


class TestResolveConvergesTheSurfaces:
    def test_resolve_only_touches_pending_rows_for_that_pr(self, monkeypatch):
        seen = {}

        class Cur:
            def execute(self, sql, params=None):
                seen["sql"] = " ".join(sql.split())
                seen["params"] = params

        import contextlib

        import tools.repair_bay.services.pr_review_service as mod

        @contextlib.contextmanager
        def fake(commit=False):
            yield None, Cur()

        monkeypatch.setattr(mod, "get_db_cursor", fake)
        prs.resolve_pr_merge_approval(2533, approved=True, user_id=4)

        sql = seen["sql"]
        assert "action_type = 'pr_merge'" in sql
        assert "status = 'pending'" in sql, "must be idempotent — never re-resolve a settled row"
        assert seen["params"] == ("approved", 4, 2533)

    def test_denial_records_rejected(self, monkeypatch):
        seen = {}

        class Cur:
            def execute(self, sql, params=None):
                seen["params"] = params

        import contextlib

        import tools.repair_bay.services.pr_review_service as mod

        @contextlib.contextmanager
        def fake(commit=False):
            yield None, Cur()

        monkeypatch.setattr(mod, "get_db_cursor", fake)
        prs.resolve_pr_merge_approval(2533, approved=False)
        assert seen["params"][0] == "rejected"


class TestEscalationIsNotCompletion:
    """#5363 — F.O.R.G.E. handing a PR UP must not look like the job being DONE.

    `metadata.tier_processed` is what the tiered-merge worker skips on. The
    escalation path wrote it, so 'above my ceiling, pass to the COO' told
    A.R.C.H.I.E. 'already handled': Tier 2 never reached her merge and Tier 3
    never reached Kytran's buttons. Measured on PRs #2523/#2524/#2528/#2533.
    """

    @staticmethod
    def _capture(monkeypatch):
        import contextlib

        import tools.repair_bay.services.pr_review_service as mod

        seen = {}

        class Cur:
            def execute(self, sql, params=None):
                seen["payload"] = params[0].adapted if hasattr(params[0], "adapted") else params[0]
                seen["pr"] = params[1]

        @contextlib.contextmanager
        def fake(commit=False):
            yield None, Cur()

        monkeypatch.setattr(mod, "get_db_cursor", fake)
        return seen

    def test_escalation_never_writes_the_worker_skip_flag(self, monkeypatch):
        seen = self._capture(monkeypatch)
        prs._mark_forge_escalated(2533, 2)
        payload = seen["payload"]
        assert payload["forge_escalated_tier"] == 2
        assert "tier_processed" not in payload, "escalation must leave the PR visible to the next authority"
        assert seen["pr"] == 2533

    def test_completion_still_writes_the_skip_flag(self, monkeypatch):
        seen = self._capture(monkeypatch)
        prs._mark_tier_processed(2533, 2)
        payload = seen["payload"]
        assert payload["tier_processed"] == 2
        assert "forge_escalated_tier" not in payload

    def test_the_two_markers_are_distinct_keys(self):
        """A single field cannot mean both 'handed on' and 'finished'."""
        import inspect

        esc = inspect.getsource(prs._mark_forge_escalated)
        done = inspect.getsource(prs._mark_tier_processed)
        assert "forge_escalated_tier" in esc and "tier_processed" not in esc.split('"""')[2]
        assert "tier_processed" in done


class TestGetPrStatusExposesMerged:
    def test_merged_is_distinguishable_from_closed(self, monkeypatch):
        """`state` is only open|closed — the executor needs the real answer."""
        import tools.repair_bay.services.github_service as gs

        payload = {"state": "closed", "merged": True, "merged_at": "2026-07-28T00:29:40Z", "title": "t"}

        def fake_get(path, params=None, timeout=15):
            if path.endswith("/pulls/2522"):
                return True, payload
            return True, []

        monkeypatch.setattr(gs, "_api_get", fake_get)
        out = gs.get_pr_status(2522)
        assert out["state"] == "closed"
        assert out["merged"] is True
        assert out["merged_at"] == "2026-07-28T00:29:40Z"

    def test_open_pr_reports_not_merged(self, monkeypatch):
        import tools.repair_bay.services.github_service as gs

        monkeypatch.setattr(
            gs,
            "_api_get",
            lambda p, params=None, timeout=15: (
                (True, {"state": "open"})
                if "/pulls/1" in p and "reviews" not in p and "comments" not in p
                else (True, [])
            ),
        )
        assert gs.get_pr_status(1)["merged"] is False
