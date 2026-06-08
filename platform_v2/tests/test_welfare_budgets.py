"""Per-LLM token budget tests (item C, 2026-06-08).

The C.R.E.E.D. welfare/capacity baseline: each model tier has a base daily token
budget, and recalibration clamps usage-derived budgets into [base*0.75, base*2] so
no agent balloons (the V.E.R.I.F.Y. 1.6M bug where p90-of-overwork inflated the
budget until the welfare 'at limit' check could never fire) or starves.
"""

from __future__ import annotations

import pytest

from services.welfare_load import (
    DEFAULT_TOKEN_LIMIT_PER_DAY,
    base_budget_for_model,
    clamp_budget_to_band,
)


class TestBaseBudgetForModel:
    def test_known_tiers(self):
        assert base_budget_for_model("qwen2.5:7b") == 120_000
        assert base_budget_for_model("gemma3:12b") == 90_000
        assert base_budget_for_model("qwen2.5:1.5b") == 75_000
        assert base_budget_for_model("arctic-embed-cpu:latest") == 50_000

    def test_unknown_model_falls_back_to_default(self):
        assert base_budget_for_model("some-new-model:99b") == DEFAULT_TOKEN_LIMIT_PER_DAY

    def test_none_or_blank_falls_back(self):
        assert base_budget_for_model(None) == DEFAULT_TOKEN_LIMIT_PER_DAY
        assert base_budget_for_model("") == DEFAULT_TOKEN_LIMIT_PER_DAY

    def test_whitespace_tolerant(self):
        assert base_budget_for_model("  qwen2.5:7b  ") == 120_000


class TestClampBudgetToBand:
    def test_runaway_capped_at_base_times_2(self):
        # The V.E.R.I.F.Y. case: p90-of-overwork would inflate to 1.6M — must cap at 240k.
        assert clamp_budget_to_band(1_600_000, "qwen2.5:7b") == 240_000

    def test_starvation_floored_at_base_times_075(self):
        assert clamp_budget_to_band(10_000, "qwen2.5:7b") == 90_000

    def test_in_band_passes_through(self):
        assert clamp_budget_to_band(120_000, "mistral:7b") == 120_000
        assert clamp_budget_to_band(150_000, "qwen2.5:7b") == 150_000  # within [90k,240k]

    def test_unknown_model_uses_default_band(self):
        # default base 150k -> band [112.5k, 300k]
        assert clamp_budget_to_band(1_000_000, "mystery") == 300_000
        assert clamp_budget_to_band(1_000, "mystery") == 112_500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
