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


class TestEveryPassGetsOneSalvage:
    """Exercise the real chunk loop, not a source-text imitation of the budget."""

    def run_review(self, monkeypatch, salvage):
        from tools.repair_bay.services import pr_diff_analyzer as analyzer

        calls = {}
        chunks = []
        full = "".join(
            f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n" "@@ -1 +1 @@\n-old\n+new\n"
            for i in range(3)
        )

        def review(_review, chunk, *args, ground_diff=None, **kwargs):
            assert ground_diff == full
            calls[chunk] = calls.get(chunk, 0) + 1
            chunks.append(chunk)
            assert calls[chunk] <= 2, "salvage must never recurse or loop"
            return PROSE if calls[chunk] == 1 else salvage

        monkeypatch.setattr(analyzer, "_get_setting", lambda *a, **k: None)
        monkeypatch.setattr(analyzer, "_tier3_is_reachable", lambda: False)
        monkeypatch.setattr(analyzer, "_structured_review", review)
        monkeypatch.setattr(analyzer, "mark_review_progress", lambda *a, **k: None)
        monkeypatch.setattr(analyzer, "_publish_file_progress", lambda *a, **k: None)
        with analyzer.review_scope_override(plan="per_file", max_files=3):
            out = analyzer._obtain_review_summary({"title": "test"}, full, 1, "test/repo")
        assert len(calls) == 3
        assert list(calls.values()) == [2, 2, 2]
        return out

    def test_later_malformed_passes_receive_their_own_retry(self, monkeypatch):
        out = self.run_review(monkeypatch, "VERDICT: APPROVE")
        assert "VERDICT: APPROVE" in out
        assert "blocked without a parseable finding" not in out

    def test_repeated_prose_still_blocks_without_more_retries(self, monkeypatch):
        out = self.run_review(monkeypatch, PROSE)
        assert "VERDICT: NEEDS REVIEW" in out
        assert "blocked without a parseable finding" in out

    def test_unavailable_salvage_keeps_original_prose_and_blocks(self, monkeypatch):
        out = self.run_review(monkeypatch, None)
        assert "VERDICT: NEEDS REVIEW" in out
        assert "blocked without a parseable finding" in out

    def test_salvaged_defect_is_not_discarded(self, monkeypatch):
        out = self.run_review(
            monkeypatch,
            "- [CRITICAL] Regression — new breaks execution — Evidence: new\n" "VERDICT: REQUEST CHANGES",
        )
        assert "VERDICT: REQUEST CHANGES" in out
        assert "Regression" in out
