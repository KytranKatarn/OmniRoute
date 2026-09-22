"""#6800 — a pass that answers in PROSE must be re-asked, never silently blocked or approved.

THE SHAPE. A multi-pass review folds each pass's `VERDICT:` line and `- [SEV]` findings. When a
pass answers in prose instead, `parse_verdict` returns "REVIEWED" (rank 1, blocking),
`_merge_chunk_summaries` finds no finding to carry, and the pass becomes a synthetic
"blocked without a parseable finding" WARNING that holds the PR — while NOTHING retries it,
because the #5287 retry is gated on `_is_degraded_blocking`, which is FALSE for prose.

MEASURED on archie-code PR #71, pass 2: "SUMMARY This PR introduces provider selection
functionality … The implementation is well-documented and includes tests." A review, in prose.
It held the PR at NEEDS REVIEW with no route forward but a re-roll.

⚠️ THE SAFETY PROPERTY IS THAT THIS NEVER INFERS A VERDICT. Reading approval out of friendly
prose is the #2458 shape — "a lost pass must never read as an approval". The salvage asks the
model again; if the second answer is also unreadable, the original fail-closed behaviour stands
byte-identical. `_is_unparseable_pass` is therefore deliberately blind to SENTIMENT: it only
answers "can the merge read this?".
"""

from __future__ import annotations

from tools.repair_bay.services.pr_diff_analyzer import (
    _is_unparseable_pass,
    _merge_chunk_summaries,
)

# VERBATIM shape of archie-code #71 pass 2.
PROSE = (
    "SUMMARY This PR introduces provider selection functionality, allowing the inference engine "
    'to switch between "fleet" and "omniroute" providers. The implementation is well-documented '
    "and includes tests."
)


class TestThePredicate:
    def test_prose_with_no_verdict_and_no_findings_is_unparseable(self):
        assert _is_unparseable_pass(PROSE) is True

    def test_a_verdict_line_makes_it_parseable_whatever_it_says(self):
        assert _is_unparseable_pass("VERDICT: APPROVE\nlooks fine") is False
        assert _is_unparseable_pass("VERDICT: REQUEST CHANGES\nsomething is wrong") is False

    def test_parseable_findings_make_it_parseable(self):
        """Real findings are real content — the synthetic-marker path already states the reason."""
        assert _is_unparseable_pass("- [WARNING] leak — the connection is never closed") is False

    def test_an_empty_summary_is_a_LOST_pass_not_an_unparseable_one(self):
        """⚠️ These must not be conflated. `lost` fails the whole review closed and MUST keep
        doing so; re-asking an empty pass is a different (unimplemented) question."""
        for empty in ("", "   ", None):
            assert _is_unparseable_pass(empty) is False

    def test_it_is_blind_to_sentiment(self):
        """It answers 'can the merge read this?', never 'did this sound happy?'. Praise-shaped
        prose and complaint-shaped prose are equally unparseable."""
        assert _is_unparseable_pass("This is excellent work, no problems at all.") is True
        assert _is_unparseable_pass("This looks dangerous and I am concerned about it.") is True


class TestTheFailClosedBehaviourIsUnchanged:
    """What the merge does with an unsalvaged prose pass must not change: the salvage happens
    BEFORE the merge, and when it fails the merge sees exactly what it saw before."""

    def test_an_unsalvaged_prose_pass_still_blocks(self):
        ok = "VERDICT: APPROVE\n- [INFO] nit\n[review-meta] structured=json chunks=1"
        out = _merge_chunk_summaries([ok, PROSE], {"shown_pct": 100})
        verdict = next((l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("VERDICT:")), None)
        assert verdict != "APPROVE", "prose must never fold into an approval"
        assert "blocked without a parseable finding" in out

    def test_a_lost_pass_still_fails_the_review_closed(self):
        ok = "VERDICT: APPROVE\n- [INFO] nit\n[review-meta] structured=json chunks=1"
        out = _merge_chunk_summaries(["", ok], {"shown_pct": 100})
        assert "failing closed" in out


class TestTheSalvageIsWiredAndBounded:
    """A predicate nobody calls is not a salvage — and an unbounded retry is a cost bug."""

    import pathlib

    SRC = pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pr_diff_analyzer.py"

    def test_the_chunk_loop_calls_the_predicate(self):
        src = self.SRC.read_text()
        assert "if summary and not _salvage_used and _is_unparseable_pass(summary):" in src

    def test_the_budget_is_one_per_review_and_separate_from_the_5287_retry(self):
        src = self.SRC.read_text()
        assert "_salvage_used = False" in src
        assert "_salvage_used = True" in src
        # the two budgets must be distinct variables, or one path steals the other's retry
        assert "_retry_used = False" in src

    def test_a_failed_salvage_keeps_the_original_summary(self):
        """The `else` branch must not assign — an unreadable salvage leaves `summary` alone."""
        src = self.SRC.read_text()
        i = src.index("if summary and not _salvage_used and _is_unparseable_pass(summary):")
        body = src[i : i + 1500]
        assert "if _salvaged and not _is_unparseable_pass(_salvaged):" in body
        assert "failing closed as before" in body
