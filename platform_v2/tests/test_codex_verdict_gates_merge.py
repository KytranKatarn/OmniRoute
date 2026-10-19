"""A fresh whole-diff CODEX REQUEST_CHANGES now refuses a merge.

REVERSAL (2026-10-19). `codex_verdicts` shipped the verdict ADVISORY (#3627) and a test
over there pinned it that way. That test was right about the risk and wrong about the
cost: on 2026-10-18 F.O.R.G.E. approved #3921, #3927 and #3930, CODEX's whole-diff review
refused exactly those three on real defects (each confirmed by reading the file), and
`merge_state` — the only thing the UI renders a Merge button from — could not see it.

So the tests here pin the REVERSAL, and they pin the shape of it rather than just the
outcome:

  * only `REQUEST_CHANGES` blocks (an APPROVE changes nothing);
  * only a FRESH one blocks (`stale` means it described a commit that is no longer the
    tip, and refusing there would outlive the fix) — which only holds because the verdict
    stores the commit the review COVERED, not the poll's branch tip;
  * it is read BEFORE the F.O.R.G.E. verdict, so it overrides an APPROVE — but a missing
    summary is still `awaiting_review`, because reasoning about CODEX on a PR nothing has
    reviewed would be the tail wagging the dog;
  * BOTH attended merge routes refuse, not just the renderer. #5834 was a route that
    showed the refusal and merged anyway; the assertion is order — the check must run
    BEFORE `merge_pr`;
  * the verdict is the NEWEST CODEX review, sorted rather than trusting GitHub's response
    order — the ingest kept the first one, so an early COMMENT outlived a later APPROVE.

Not asserted: that CODEX can refuse an unattended/automated merge. The gate here is the
same one #5194 already governs, and `human_override` still clears AUTHORITY, never the
fact that a reviewer objected.
"""

import ast
import inspect
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services.pr_review_service import (  # noqa: E402
    _stored_codex,
    codex_merge_refusal,
    merge_state,
)

_ROUTES_PY = _ROOT / "tools" / "repair_bay" / "github_routes.py"

_APPROVED = "VERDICT: APPROVE\n\nSUMMARY\nNo issues found."
_CHANGES = "VERDICT: REQUEST CHANGES\n- [high] a.py:1 - the button does nothing"

#: What `codex_verdicts.record_verdict` actually writes into metadata.
_FRESH_BLOCK = {"verdict": "REQUEST_CHANGES", "stale": False, "finding_count": 2, "head_sha": "a" * 40}
_STALE_BLOCK = dict(_FRESH_BLOCK, stale=True)
_FRESH_APPROVE = {"verdict": "APPROVE", "stale": False, "finding_count": 0, "head_sha": "a" * 40}


class TestCodexMergeRefusal(unittest.TestCase):
    """The decision table, pure — no DB, no GitHub, no Flask."""

    def test_fresh_request_changes_refuses(self):
        why = codex_merge_refusal(_FRESH_BLOCK)
        self.assertIsNotNone(why)
        self.assertIn("REQUEST_CHANGES", why.upper().replace(" ", "_"))

    def test_the_refusal_names_the_reviewer_that_blocked(self):
        """The row shows a Merge button and a F.O.R.G.E. badge; the hint must say which
        reviewer objected, or the operator reads it as F.O.R.G.E. contradicting itself."""
        self.assertIn("CODEX", codex_merge_refusal(_FRESH_BLOCK))

    def test_counts_the_findings(self):
        self.assertIn("2 finding", codex_merge_refusal(_FRESH_BLOCK))

    def test_missing_finding_count_still_refuses(self):
        why = codex_merge_refusal({"verdict": "REQUEST_CHANGES", "stale": False})
        self.assertIsNotNone(why)

    def test_stale_never_refuses(self):
        """An old REQUEST_CHANGES is a statement about code that has been replaced. Reading
        it as current is the exact class of defect #3627 exists to surface the OTHER way."""
        self.assertIsNone(codex_merge_refusal(_STALE_BLOCK))

    def test_approve_does_not_refuse(self):
        self.assertIsNone(codex_merge_refusal(_FRESH_APPROVE))

    def test_absent_verdict_changes_nothing(self):
        for codex in (None, {}, {"finding_count": 3}, "APPROVE", ["REQUEST_CHANGES"]):
            with self.subTest(codex=codex):
                self.assertIsNone(codex_merge_refusal(codex))

    def test_verdict_case_and_space_are_normalised(self):
        self.assertIsNotNone(codex_merge_refusal({"verdict": " request_changes ", "stale": False}))

    def test_unnamed_verdict_is_not_blocking(self):
        self.assertIsNone(codex_merge_refusal({"verdict": "NEEDS REVIEW", "stale": False}))


class TestStoredCodex(unittest.TestCase):
    """The gate's input is the RAW blob, not the UI projection.

    `codex_verdicts.verdict_for_row` drops keys (it is a display projection). If
    `merge_state` were handed the projection, a projection change would silently change
    what blocks a merge — the exact class of split this file exists to prevent.
    """

    def test_reads_metadata(self):
        self.assertEqual(_stored_codex({"codex": _FRESH_BLOCK}), _FRESH_BLOCK)

    def test_absent_and_malformed_yield_empty(self):
        for meta in (None, {}, {"codex": None}, {"codex": "REQUEST_CHANGES"}, {"codex": []}, "nope", 3):
            self.assertEqual(_stored_codex(meta), {})


class TestMergeStateReadsIt(unittest.TestCase):
    def test_fresh_block_overrides_an_approved_summary(self):
        ms = merge_state("reviewed", _APPROVED, codex=_FRESH_BLOCK)
        self.assertFalse(ms["mergeable"])
        self.assertNotEqual(ms["state"], "approved")

    def test_the_row_says_who_blocked(self):
        ms = merge_state("reviewed", _APPROVED, codex=_FRESH_BLOCK)
        self.assertIn("CODEX", ms["label"])
        self.assertIn("CODEX", ms["hint"])

    def test_a_stale_block_leaves_the_approval_alone(self):
        ms = merge_state("reviewed", _APPROVED, codex=_STALE_BLOCK)
        self.assertEqual(ms["state"], "approved")
        self.assertTrue(ms["mergeable"])

    def test_an_approve_leaves_the_approval_alone(self):
        ms = merge_state("reviewed", _APPROVED, codex=_FRESH_APPROVE)
        self.assertEqual(ms["state"], "approved")
        self.assertTrue(ms["mergeable"])

    def test_absent_codex_is_byte_identical(self):
        """Every pre-2026-10-19 caller must be unaffected — omit the kwarg or pass None."""
        base = merge_state("reviewed", _APPROVED)
        self.assertEqual(base, merge_state("reviewed", _APPROVED, codex=None))
        self.assertEqual(merge_state("reviewed", _CHANGES), merge_state("reviewed", _CHANGES, codex=None))

    def test_codex_does_not_dress_up_a_missing_verdict(self):
        """No F.O.R.G.E. summary -> `awaiting_review` whatever CODEX says. Nothing has
        reviewed the PR, and that is the louder fact."""
        for state in ("draft", "open", None):
            ms = merge_state("pending", "", pr_state=state, codex=_FRESH_BLOCK)
            self.assertEqual(ms["state"], "awaiting_review")

    def test_a_closed_pr_is_still_closed(self):
        """pr_state is checked FIRST for the same reason it was added in #6792."""
        ms = merge_state("reviewed", _APPROVED, pr_state="closed", codex=_FRESH_BLOCK)
        self.assertFalse(ms["mergeable"])
        self.assertEqual(ms["state"], "closed")

    def test_an_in_progress_review_is_still_in_progress(self):
        ms = merge_state("in_progress", _APPROVED, codex=_FRESH_BLOCK)
        self.assertEqual(ms["state"], "reviewing")

    def test_a_stacked_pr_still_names_its_target(self):
        """Refusing must not lose the #5853 information that the merge would not ship."""
        ms = merge_state("reviewed", _APPROVED, base_branch="feat/parent", codex=_FRESH_BLOCK)
        self.assertEqual(ms["base_branch"], "feat/parent")


class TestTheSurfacesAgree(unittest.TestCase):
    """`merge_state` is read from three places; all three must hand it the verdict."""

    def _src(self) -> str:
        import tools.repair_bay.services.pr_review_service as m

        return inspect.getsource(m)

    def test_list_reviews_passes_it(self):
        body = self._src().split("def list_reviews(")[1].split("\ndef ")[0]
        # (?s): the call is wrapped across lines, so `.` must cross newlines.
        self.assertRegex(body, r"(?s)merge_state\(.*?codex=")

    def test_stamp_merge_states_passes_it(self):
        body = self._src().split("def stamp_merge_states(")[1].split("\ndef ")[0]
        self.assertRegex(body, r"(?s)merge_state\(.*?codex=")

    def test_the_route_that_re_renders_after_a_dismissal_passes_it(self):
        routes = _ROUTES_PY.read_text(encoding="utf-8")
        body = routes.split("def forge_dismiss_finding(")[1].split("\n    @bp.route")[0]
        self.assertRegex(body, r"(?s)merge_state\(.*?codex=")


class TestBothMergeRoutesRefuse(unittest.TestCase):
    """A renderer that blocks and a route that merges is how #2458 reached main.

    The property is ORDER: the refusal must be computed (and returned) before `merge_pr`.
    """

    ROUTES = _ROUTES_PY

    def _body(self, name: str) -> str:
        src = self.ROUTES.read_text(encoding="utf-8")
        return src.split(f"def {name}(")[1].split("\n    @bp.route")[0]

    def test_prs_merge_route_checks_codex_before_merging(self):
        body = self._body("forge_merge_pr")
        self.assertIn("codex_merge_refusal", body)
        self.assertLess(body.index("codex_merge_refusal"), body.index("merge_pr("))

    def test_pr_review_merge_route_checks_codex_before_merging(self):
        body = self._body("forge_pr_review_merge")
        self.assertIn("codex_merge_refusal", body)
        self.assertLess(body.index("codex_merge_refusal"), body.index("merge_pr("))

    def test_the_check_is_after_the_human_verdict_rule(self):
        """Ordering, not priority: the human's own rule is read first so its message wins
        where both apply. CODEX is the second, narrower answer."""
        body = self._body("forge_merge_pr")
        self.assertLess(body.index("verdict_refusal("), body.index("codex_merge_refusal("))

    def test_human_override_is_untouched(self):
        for name in ("forge_merge_pr", "forge_pr_review_merge"):
            self.assertIn("human_override=True", self._body(name))


class TestNoASTTrickeryInMechanism(unittest.TestCase):
    def test_merge_state_gained_a_keyword_only_field(self):
        params = inspect.signature(merge_state).parameters
        self.assertIn("codex", params)
        # Appended, so every positional caller in the tree keeps its meaning.
        self.assertEqual(list(params)[-1], "codex")

    def test_the_gate_is_not_reimplemented(self):
        """ONE definition: the routes and the list must call `codex_merge_refusal`, not
        re-derive "is this verdict blocking" from a dict."""
        routes = _ROUTES_PY.read_text(encoding="utf-8")
        self.assertEqual(routes.count("codex_merge_refusal("), 2)
        self.assertNotIn('== "REQUEST_CHANGES"', routes)


class TestAttemptRecording(unittest.TestCase):
    """`forge_reviews` is the corpus; it needs the reviewer that finds things."""

    def test_record_review_attempt_takes_source_and_dedup(self):
        from tools.repair_bay.services.pr_review_service import record_review_attempt

        params = inspect.signature(record_review_attempt).parameters
        self.assertIn("review_source", params)
        self.assertEqual(params["review_source"].default, "forge")
        self.assertIn("dedup_key", params)
        self.assertIsNone(params["dedup_key"].default)

    def test_review_source_is_bound_not_literal(self):
        from tools.repair_bay.services import pr_review_service as m

        src = inspect.getsource(m.record_review_attempt)
        self.assertNotIn("'forge'::", src)
        self.assertIn("review_source", src)

    def test_the_source_goes_in_the_payload(self):
        from tools.repair_bay.services import pr_review_service as m

        self.assertIn('"review_source": review_source', inspect.getsource(m.record_review_attempt))

    def test_codex_ingest_appends_an_attempt(self):
        from tools.repair_bay.services import codex_verdicts as m

        src = inspect.getsource(m)
        self.assertIn("record_review_attempt", src)
        self.assertIn('review_source="codex"', src)
        self.assertIn("dedup_key", src)

    def test_the_dedup_key_is_the_github_review_id(self):
        """Any other key re-appends on every poll; `ingest_for_open_prs` runs per tick."""
        from tools.repair_bay.services import codex_verdicts as m

        src = inspect.getsource(m._record_attempt)
        self.assertIn("github-review:", src)
        self.assertIn("rev", src)

    def test_the_codex_error_path_is_swallowed(self):
        """Bookkeeping must never break the sync that produced the verdict."""
        from tools.repair_bay.services import codex_verdicts as m

        tree = ast.parse(inspect.getsource(m))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_record_attempt")
        handlers = [h for n in ast.walk(fn) for h in getattr(n, "handlers", [])]
        self.assertTrue(handlers, "_record_attempt must catch its own failures")


class TestTheRefusalCannotOutliveTheFix(unittest.TestCase):
    """The `stale` carve-out is only worth having if it is TRUE.

    A gate that refuses on a verdict describing a replaced commit blocks the fix. The flag
    is decided in `codex_verdicts.verdict_staleness`, and it is only meaningful because the
    verdict stores the commit the review covers — not the branch tip the poll just wrote to
    `metadata->>'head_sha'`.
    """

    def _fn(self):
        from tools.repair_bay.services.codex_verdicts import verdict_staleness

        return verdict_staleness

    def test_a_review_of_the_tip_is_current(self):
        sha, stale = self._fn()({"commit_id": "a" * 40}, "a" * 40)
        self.assertEqual(sha, "a" * 40)
        self.assertFalse(stale)

    def test_a_review_of_an_older_commit_is_stale(self):
        sha, stale = self._fn()({"commit_id": "b" * 40}, "a" * 40)
        self.assertEqual(sha, "b" * 40)
        self.assertTrue(stale)

    def test_the_stored_sha_is_the_reviewed_commit_not_the_tip(self):
        """The whole defect: storing the tip made tip-vs-tip always equal, so the verdict
        read as current after every push and `stale` oscillated True→False in one tick."""
        sha, _ = self._fn()({"commit_id": "b" * 40}, "a" * 40)
        self.assertNotEqual(sha, "a" * 40)

    def test_unprovable_is_not_stale(self):
        """Matches the gate's rule for a missing `reviewed_head_sha`: an unproven sha is
        allowed, so a GitHub payload that omits `commit_id` cannot invalidate every verdict
        at once."""
        cases = (({}, "a" * 40), ({"commit_id": ""}, "a" * 40), ({"commit_id": "b" * 40}, ""), ({}, None))
        for rev, tip in cases:
            with self.subTest(rev=rev, tip=tip):
                _sha, stale = self._fn()(rev, tip)
                self.assertFalse(stale)

    def test_the_ingest_records_it(self):
        from tools.repair_bay.services import codex_verdicts as m

        src = inspect.getsource(m.ingest_for_open_prs)
        self.assertIn("verdict_staleness(rev, head_sha)", src)
        # `head_sha=` must carry the covered commit, not the tip.
        self.assertIn("head_sha=covered_sha", src)

    def test_the_flag_the_gate_reads_is_recomputed_every_tick(self):
        """The ingest must not short-circuit on the stored verdict: `record_verdict` runs
        on every tick, and that rewrite is what lets a push clear the refusal."""
        src = inspect.getsource(
            __import__("tools.repair_bay.services.codex_verdicts", fromlist=["x"]).ingest_for_open_prs
        )
        self.assertNotIn("if stored", src)
        self.assertIn("record_verdict(", src)


class TestTheNewestReviewWins(unittest.TestCase):
    """GitHub returns `/pulls/{n}/reviews` in CHRONOLOGICAL order.

    The ingest used to keep the FIRST CODEX review, on a comment claiming the opposite, so
    the oldest review was pinned on a PR forever: #3926 was COMMENTed at 11:52:43 and
    APPROVEd at 11:55:56, and the stored verdict stayed the COMMENT. Nothing read it then;
    a merge gate reading it makes that a permanent false refusal.
    """

    def _fn(self):
        from tools.repair_bay.services.codex_verdicts import codex_reviews

        return codex_reviews

    @staticmethod
    def _rev(verdict, when, rid):
        return {"id": rid, "submitted_at": when, "body": f"VERDICT: {verdict}\n\nSUMMARY\nx"}

    def test_the_last_entry_is_the_current_verdict(self):
        reviews = [
            self._rev("COMMENT", "2026-10-19T11:52:43Z", 1),
            self._rev("APPROVE", "2026-10-19T11:55:56Z", 2),
        ]
        found = self._fn()(reviews)
        self.assertEqual([p["verdict"] for p, _ in found], ["COMMENT", "APPROVE"])
        self.assertEqual(found[-1][0]["verdict"], "APPROVE")

    def test_order_is_derived_not_assumed(self):
        """A newest-first payload must give the same answer as a chronological one."""
        chronological = [
            self._rev("REQUEST_CHANGES", "2026-10-19T11:00:00Z", 1),
            self._rev("APPROVE", "2026-10-19T12:00:00Z", 2),
        ]
        self.assertEqual(self._fn()(list(reversed(chronological))), self._fn()(chronological))

    def test_the_id_breaks_a_tie_on_the_timestamp(self):
        found = self._fn()(
            [
                self._rev("APPROVE", "2026-10-19T11:00:00Z", 9),
                self._rev("REQUEST_CHANGES", "2026-10-19T11:00:00Z", 10),
            ]
        )
        self.assertEqual(found[-1][0]["verdict"], "REQUEST_CHANGES")

    def test_human_and_malformed_reviews_are_dropped(self):
        found = self._fn()(
            [
                {"id": 1, "body": "looks good to me"},
                {"id": 2, "body": ""},
                "not a dict",
                {"id": 3, "body": None},
                None,
                self._rev("APPROVE", "2026-10-19T11:00:00Z", 4),
            ]
        )
        self.assertEqual(len(found), 1)

    def test_no_reviews_at_all(self):
        for reviews in (None, [], [{"body": "no verdict here"}]):
            with self.subTest(reviews=reviews):
                self.assertEqual(self._fn()(reviews), [])

    def test_the_ingest_takes_the_last_and_records_all(self):
        """`found[-1]` is the verdict; every review is appended to the corpus."""
        from tools.repair_bay.services import codex_verdicts as m

        src = inspect.getsource(m.ingest_for_open_prs)
        self.assertIn("parsed, rev = found[-1]", src)
        self.assertNotIn("found[0]", src)
        self.assertIn("for _parsed, _rev in found:", src)


class TestRepairBayWay(unittest.TestCase):
    """The surviving advisory-pin in test_codex_verdicts must not be read as the gate."""

    def test_the_advisory_test_still_exists_and_is_findable(self):
        """Kept deliberately: it documents the decision that was reversed, and a future
        reader who greps for the advisory will find both halves."""
        blob = (_ROOT / "tests" / "test_codex_verdicts.py").read_text(encoding="utf-8")
        self.assertIn("ADVISORY", blob.upper())

    def test_the_rule_stays_server_side(self):
        """The UI renders `merge_state`; it must not re-derive the rule, and a copy of
        "which verdicts block" in JS is the split #2722 collapsed."""
        js = ""
        p = _ROOT / "static" / "js" / "repair-bay-main.js"
        if p.exists():
            js = p.read_text(encoding="utf-8")
        self.assertNotIn("REQUEST_CHANGES", js)
        self.assertNotRegex(js, re.compile(r"codex", re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
