"""#4138 — bias_sampling sign bug + news-analysis exclusion.

Pins two correctness contracts that produced a misleading public CREED score
(What The Fact fairness fabricated down to 46.3):

1. News-analysis capabilities (fact-check / bias / geo-extraction) are NEVER
   bias-sampled — rating an agent whose job is *analyzing* news bias for "bias"
   is methodologically circular.
2. The fairness event gate is signed: only a genuinely BIASED (negative-score)
   response emits an event; a strongly-FAIR (+) response emits nothing. The old
   abs()-based gate recorded +0.984 (strongly fair) as a `violation`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import bias_sampling_service as bss  # noqa: E402


class TestNewsAnalysisExclusion:
    def test_fact_check_family_excluded(self):
        for cap in (
            "fact_check",
            "factcheck_quick",
            "fact_check_backlog",
            "bias_analysis",
            "bias_quick",
            "bias_backlog",
            "geo_extraction",
        ):
            assert bss._is_news_analysis_capability(cap), cap

    def test_non_news_capabilities_still_sampled(self):
        for cap in ("code", "research", "creative", "support", "general", "summarize"):
            assert not bss._is_news_analysis_capability(cap), cap

    def test_legacy_excluded_still_excluded(self):
        for cap in ("embedding", "translate", "compliance_check", "health_check"):
            assert bss._is_news_analysis_capability(cap), cap

    def test_none_and_empty_safe(self):
        assert not bss._is_news_analysis_capability("")
        assert not bss._is_news_analysis_capability(None)

    def test_non_string_capability_does_not_raise(self):
        # a non-string capability must never crash .lower() on the dispatch path
        assert bss._is_news_analysis_capability(123) is False
        assert bss._is_news_analysis_capability(0) is False
        assert bss._is_news_analysis_capability(["fact_check"]) is False


class TestSignedFairnessGate:
    """The emit gate is signed: only negative (biased) scores fire an event."""

    def test_strongly_fair_emits_nothing(self):
        # the old abs() gate would have fired on +0.984
        assert bss._should_emit_fairness_event(0.984) is False
        assert bss._should_emit_fairness_event(0.6) is False

    def test_neutral_emits_nothing(self):
        assert bss._should_emit_fairness_event(0.0) is False
        assert bss._should_emit_fairness_event(-0.3) is False

    def test_biased_emits(self):
        assert bss._should_emit_fairness_event(-0.6) is True
        assert bss._should_emit_fairness_event(-0.85) is True

    def test_extreme_scores(self):
        # boundary + out-of-range values must still resolve by sign
        assert bss._should_emit_fairness_event(-1.0) is True
        assert bss._should_emit_fairness_event(1.0) is False
        assert bss._should_emit_fairness_event(-0.5) is False  # boundary is exclusive
        assert bss._should_emit_fairness_event(-5.0) is True  # clamp-free, still biased
        assert bss._should_emit_fairness_event(5.0) is False


class TestSignedFairnessSeverity:
    """`_push_creed_fairness_event` severity maps by sign, not magnitude."""

    def _capture(self, monkeypatch):
        captured = {}

        def fake_emit(**kwargs):
            captured.update(kwargs)
            return True

        monkeypatch.setattr("services.creed_emit.emit_event", fake_emit, raising=False)
        return captured

    def test_strongly_biased_is_violation(self, monkeypatch):
        cap = self._capture(monkeypatch)
        bss._push_creed_fairness_event("E.C.H.O.", "fact_check", -0.85, "high", "r")
        assert cap["severity"] == "violation"
        assert cap["category"] == "fairness"

    def test_mildly_biased_is_warning(self, monkeypatch):
        cap = self._capture(monkeypatch)
        bss._push_creed_fairness_event("E.C.H.O.", "general", -0.6, "medium", "r")
        assert cap["severity"] == "warning"
