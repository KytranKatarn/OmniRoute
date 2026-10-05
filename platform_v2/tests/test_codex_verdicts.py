"""CODEX (CLI) verdict ingestion and projection — unit tests.

No browser and no network: `parse_codex_review` and `verdict_for_row` are the two pieces
that decide what gets believed, and both are pure.

The behaviour these pin down came from a real miss. On 2026-10-05 #3627 rendered a green
F.O.R.G.E. APPROVED row while CODEX held an open REQUEST_CHANGES with a `[high]` finding,
because nothing imported CODEX at all. A second miss shipped inside this module: severities
came back as `["h","m","m"]` because `findall` with one group returns strings and the code
took `f[0]` — the first CHARACTER. Only reading real ingest output caught that one.
"""

import unittest

from tools.repair_bay.services.codex_verdicts import (
    parse_codex_review,
    probe_for_row,
    verdict_for_row,
)
from tools.repair_bay.services.pr_review_service import GATE_REVIEWERS


class TestParseCodexReview(unittest.TestCase):
    def test_reads_the_verdict(self):
        r = parse_codex_review("VERDICT: REQUEST_CHANGES\nThe pane can lie.")
        self.assertEqual(r["verdict"], "REQUEST_CHANGES")

    def test_reads_full_severity_words_not_first_letters(self):
        """Regression: `findall` with one group yields strings, so `f[0]` returned "h"."""
        body = (
            "VERDICT: REQUEST_CHANGES\n"
            "- [high] a.py:1 - one\n"
            "- [medium] b.py:2 - two\n"
            "- [low] c.py:3 - three\n"
            "- [critical] d.py:4 - four\n"
        )
        r = parse_codex_review(body)
        self.assertEqual(r["findings"], ["high", "medium", "low", "critical"])
        self.assertEqual(r["finding_count"], 4)

    def test_clean_approve_is_still_a_verdict(self):
        """A clean CODEX run posts APPROVE with no findings. Dropping those would hide
        half the signal, which is what an earlier draft of this parser would have done."""
        r = parse_codex_review("VERDICT: APPROVE\n\nSUMMARY\nNo issues found.")
        self.assertEqual(r["verdict"], "APPROVE")
        self.assertEqual(r["finding_count"], 0)
        self.assertEqual(r["findings"], [])

    def test_banner_is_not_required(self):
        """The banner is echoed to the operator's terminal and never posted, so matching
        it found nothing at all — the original reason no CODEX review ever displayed."""
        self.assertIsNotNone(parse_codex_review("VERDICT: APPROVE"))

    def test_body_without_a_verdict_is_not_a_model_verdict(self):
        self.assertIsNone(parse_codex_review("Looks good to me, nice refactor."))
        self.assertIsNone(parse_codex_review(""))
        self.assertIsNone(parse_codex_review(None))

    def test_verdict_may_appear_after_a_leading_blank_line(self):
        self.assertIsNotNone(parse_codex_review("\n\nVERDICT: APPROVE\n"))

    def test_summary_is_bounded(self):
        r = parse_codex_review("VERDICT: REQUEST_CHANGES\n" + ("x" * 5000))
        self.assertLessEqual(len(r["summary"]), 600)

    def test_finding_list_is_capped(self):
        body = "VERDICT: REQUEST_CHANGES\n" + "".join(f"- [low] f.py:{i} - x\n" for i in range(50))
        r = parse_codex_review(body)
        self.assertLessEqual(len(r["findings"]), 12)
        self.assertEqual(r["finding_count"], 50, "the true count must not be capped")


class TestVerdictForRow(unittest.TestCase):
    def test_absent_metadata_yields_nothing(self):
        """`{}` so the UI renders no badge at all, rather than an empty one."""
        self.assertEqual(verdict_for_row(None), {})
        self.assertEqual(verdict_for_row({}), {})
        self.assertEqual(verdict_for_row({"codex": None}), {})
        self.assertEqual(verdict_for_row({"codex": {"finding_count": 3}}), {})

    def test_projects_a_stored_verdict(self):
        meta = {
            "codex": {
                "verdict": "REQUEST_CHANGES",
                "finding_count": 6,
                "findings": ["high", "medium"],
                "reviewed_at": "2026-10-05T00:47:11Z",
                "head_sha": "abc123",
                "stale": False,
            }
        }
        out = verdict_for_row(meta)
        self.assertEqual(out["verdict"], "REQUEST_CHANGES")
        self.assertEqual(out["finding_count"], 6)
        self.assertEqual(out["findings"], ["high", "medium"])
        self.assertFalse(out["stale"])

    def test_stale_flag_is_surfaced(self):
        out = verdict_for_row({"codex": {"verdict": "APPROVE", "stale": True}})
        self.assertTrue(out["stale"])

    def test_missing_stale_key_reads_as_current(self):
        out = verdict_for_row({"codex": {"verdict": "APPROVE"}})
        self.assertFalse(out["stale"])

    def test_a_non_dict_codex_value_is_survivable(self):
        """metadata is operator- and code-written JSONB; a stray string must not 500 the
        whole PR list."""
        self.assertEqual(verdict_for_row({"codex": "REQUEST_CHANGES"}), {})


class TestAdvisoryContract(unittest.TestCase):
    def test_no_code_path_writes_a_merge_deciding_column(self):
        """The single most important property: CODEX must never gate a merge.

        Checked over the AST rather than the raw source, because the module's DOCSTRING
        necessarily names these columns in order to explain why it avoids them — a plain
        substring scan fails on the explanation. So: every string constant that is not a
        docstring is inspected, which is where an actual `SET review_status = ...` or
        `UPDATE ... ai_summary` would live.
        """
        import ast
        import inspect
        import textwrap

        import tools.repair_bay.services.codex_verdicts as m

        tree = ast.parse(textwrap.dedent(inspect.getsource(m)))

        # Collect docstring nodes so they can be excluded.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstrings.add(id(body[0].value))

        literals = [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
        ]
        blob = " ".join(literals)
        for forbidden in ("merge_state", "review_status", "ai_summary"):
            self.assertNotIn(
                forbidden,
                blob,
                f"codex_verdicts has a code path touching {forbidden}; it is advisory only",
            )

    def test_only_metadata_is_written(self):
        import inspect

        import tools.repair_bay.services.codex_verdicts as m

        src = inspect.getsource(m.record_verdict)
        self.assertIn("metadata", src)
        self.assertNotIn("review_status", src)
        self.assertNotIn("ai_summary", src)

    def test_module_doc_states_advisory(self):
        import inspect

        import tools.repair_bay.services.codex_verdicts as m

        doc = inspect.getdoc(m) or ""
        self.assertIn("ADVISORY", doc.upper())


class TestProbeVerdict(unittest.TestCase):
    """P.R.O.B.E. (QA) is a second opinion that must not become the merge gate's verdict."""

    def test_absent_probe_yields_nothing(self):
        self.assertEqual(probe_for_row(None), {})
        self.assertEqual(probe_for_row({}), {})
        self.assertEqual(probe_for_row({"probe": {"reviewer": "P.R.O.B.E."}}), {})

    def test_projects_a_stored_probe_verdict(self):
        out = probe_for_row(
            {
                "probe": {
                    "reviewer": "P.R.O.B.E.",
                    "verdict": "APPROVE",
                    "summary": "all green",
                    "at": "2026-10-05T02:20:00Z",
                }
            }
        )
        self.assertEqual(out["verdict"], "APPROVE")
        self.assertEqual(out["reviewer"], "P.R.O.B.E.")
        self.assertTrue(out["advisory"])

    def test_non_dict_probe_is_survivable(self):
        self.assertEqual(probe_for_row({"probe": "APPROVE"}), {})


class TestGateOwnership(unittest.TestCase):
    """Only F.O.R.G.E. owns `ai_summary`, which is what `merge_state` reads."""

    def test_only_forge_gates(self):
        self.assertEqual(GATE_REVIEWERS, ("F.O.R.G.E.",))

    def test_probe_is_not_a_gate_reviewer(self):
        self.assertNotIn("P.R.O.B.E.", GATE_REVIEWERS)

    def test_mark_review_done_accepts_a_reviewer(self):
        import inspect

        from tools.repair_bay.services.pr_review_service import mark_review_done

        self.assertIn("reviewer", inspect.signature(mark_review_done).parameters)

    def test_advisory_branch_never_writes_the_gate_field(self):
        """AST over mark_review_done: the advisory branch's SQL must not touch
        ai_summary / ai_review_at / reviewed_head_sha."""
        import ast
        import inspect
        import textwrap

        from tools.repair_bay.services.pr_review_service import mark_review_done

        tree = ast.parse(textwrap.dedent(inspect.getsource(mark_review_done)))
        # find the `else:` arm (the advisory path)
        advisory = None
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                body = ast.unparse(node.body)
                if "ai_summary=%s" in body:
                    advisory = node.orelse
                    break
        self.assertIsNotNone(advisory, "could not locate the gating branch")
        # `orelse` is a LIST of statements, and ast.walk needs a node, not a list.
        sql = " ".join(
            n.value
            for stmt in advisory
            for n in ast.walk(stmt)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        for forbidden in ("ai_summary", "ai_review_at", "reviewed_head_sha"):
            self.assertNotIn(
                forbidden,
                sql,
                f"the advisory (non-F.O.R.G.E.) branch must not write {forbidden}",
            )
        self.assertIn("probe", sql, "the advisory branch should record metadata->'probe'")


if __name__ == "__main__":
    unittest.main()
