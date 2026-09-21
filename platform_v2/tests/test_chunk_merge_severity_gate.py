"""The severity gates must bind the MERGED review, not just each pass (#6822 follow-up).

MEASURED 2026-09-21: `_merge_chunk_summaries` copies "- [" finding lines VERBATIM and folds
the verdict from each chunk's own VERDICT line. Every severity gate — the non-blocking
categories, `_asserts_no_defect`, #6029's prose-evidence check, and GATE 6's hedge detector —
ran per pass and was then discarded. With `forge:review_plan=per_file` live, EVERY production
review is multi-pass, so the gates bound NOTHING in production.

Consequence on PR #3401: five attempts held REQUEST CHANGES on findings the gates classify as
non-blocking — one of them ("_nodes_for_model does not log") provably false against the
`logger.warning(...)` it cited as its own evidence.

⚠️ THE HALF OF THIS FILE THAT MATTERS IS THE FAIL-CLOSED HALF. The gate only ever RELAXES, so
the risk of wiring it here is converting "we could not read this" into "this is fine" — the
#2458 shape. Two such paths exist and each has a test below: a LOST pass, and a pass that
blocked without producing a parseable finding.
"""

from __future__ import annotations

from tools.repair_bay.services.pr_diff_analyzer import (
    _UNPARSEABLE_BLOCK_MARK,
    _demote_nonblocking_lines,
    _merge_chunk_summaries,
)

COV = {"shown_pct": 100}

# A pure hedge: GATE 6 demotes it — it names no definite fault.
HEDGED = "The function catches all exceptions and logs a warning, which could hide unexpected issues."
# A real defect claim: no gate may touch this.
REAL = "the connection is never closed — this leaks a handle per request"


def _chunk(verdict: str, *findings: str) -> str:
    body = "\n".join(findings)
    return f"VERDICT: {verdict}\n{body}\n[review-meta] structured=json chunks=1"


def _verdict_of(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("VERDICT:"):
            return line.split(":", 1)[1].strip()
    return "<none>"


class TestTheGateNowBindsTheMergedReview:
    def test_a_hedged_finding_is_demoted_in_the_merged_output(self):
        out = _merge_chunk_summaries([_chunk("REQUEST CHANGES", f"- [WARNING] sanity — {HEDGED}")], COV)
        assert "[WARNING]" not in out
        assert "- [INFO] sanity" in out

    def test_a_block_resting_only_on_hedges_is_relaxed(self):
        out = _merge_chunk_summaries(
            [_chunk("REQUEST CHANGES", f"- [WARNING] sanity — {HEDGED}"), _chunk("APPROVE", "- [INFO] nit — naming")],
            COV,
        )
        assert _verdict_of(out) == "APPROVE"
        assert "[severity-gate]" in out, "the relaxation must leave an audit note"


class TestTheAsymmetryIsPreserved:
    """The gate relaxes, never tightens — and never relaxes a real defect away."""

    def test_a_real_defect_still_blocks(self):
        out = _merge_chunk_summaries([_chunk("REQUEST CHANGES", f"- [WARNING] leak — {REAL}")], COV)
        assert "[WARNING] leak" in out
        assert _verdict_of(out) == "REQUEST CHANGES"

    def test_one_real_defect_among_hedges_still_blocks(self):
        out = _merge_chunk_summaries(
            [
                _chunk("REQUEST CHANGES", f"- [WARNING] sanity — {HEDGED}"),
                _chunk("REQUEST CHANGES", f"- [WARNING] leak — {REAL}"),
            ],
            COV,
        )
        assert _verdict_of(out) == "REQUEST CHANGES"


class TestFailClosedPathsSurvive:
    """⚠️ The dangerous direction. Each of these would be a #2458-shape regression."""

    def test_a_lost_pass_is_never_relaxed(self):
        # An empty summary = a pass that produced nothing. Its block has no findings to
        # inspect, so relaxing it would turn "unreadable" into "fine".
        out = _merge_chunk_summaries(["", _chunk("REQUEST CHANGES", f"- [WARNING] sanity — {HEDGED}")], COV)
        assert _verdict_of(out) != "APPROVE"
        assert "failing closed" in out

    def test_an_unparseable_block_marker_is_never_demoted(self):
        # A blocking pass with no parseable finding gets a synthetic WARNING whose prose is
        # the pass's OWN text — which can itself read as a hedge. Its severity IS the block.
        hedgy_prose = "VERDICT: REQUEST CHANGES\nthis could possibly be a problem, it may not be safe"
        out = _merge_chunk_summaries([hedgy_prose], COV)
        assert _UNPARSEABLE_BLOCK_MARK in out
        assert "[WARNING]" in out, "the fail-closed marker must keep its blocking severity"
        assert _verdict_of(out) == "REQUEST CHANGES"

    def test_a_bare_blocking_verdict_with_no_finding_is_never_relaxed(self):
        """THIRD fail-closed path, and the one I missed — caught by the existing
        test_chunk_once_per_pr::test_a_real_rejection_still_outranks_needs_review.

        The synthetic marker is only added when there is prose to quote (`if raw:`). A pass
        that is nothing but "VERDICT: REQUEST CHANGES" leaves NO finding and NO marker, so the
        merged text has no blocking severity for the gate to see. Relaxing there converts an
        unexplained block into an approval — the #2458 shape."""
        out = _merge_chunk_summaries(["VERDICT: NEEDS REVIEW", "VERDICT: REQUEST CHANGES"], COV)
        assert _verdict_of(out) == "REQUEST CHANGES"

    def test_an_unexplained_block_is_not_relaxed_even_beside_a_demoted_hedge(self):
        """The dangerous mix: one pass blocks with nothing inspectable, another raises only a
        hedge. Demoting the hedge must not leave the merged review looking clean."""
        out = _merge_chunk_summaries(
            ["VERDICT: REQUEST CHANGES", _chunk("REQUEST CHANGES", f"- [WARNING] sanity — {HEDGED}")], COV
        )
        assert _verdict_of(out) == "REQUEST CHANGES"

    def test_the_demoter_itself_skips_the_marker(self):
        line = f"- [WARNING] {_UNPARSEABLE_BLOCK_MARK} (pass 2) — this may possibly be an issue"
        assert "[WARNING]" in _demote_nonblocking_lines(line)

    def test_the_demoter_still_demotes_an_ordinary_hedge(self):
        # Non-vacuity guard for the carve-out above: it must be narrow.
        assert "[INFO]" in _demote_nonblocking_lines(f"- [WARNING] sanity — {HEDGED}")
