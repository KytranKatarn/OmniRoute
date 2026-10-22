"""Pin the pricing rules that decide what the platform reports as SPEND.

The problem this exists to prevent, measured 2026-10-21:
``task_execution_log.cost`` was 0 on every one of its 2,127,111 rows, so
every view that summed it (the smart router's cost comparison, the
consciousness cost view, the dispatch history, the admin MCP tools, the media
studio, the DS9 tab) reported a confident ``$0.00`` for real spend.

The rules these hold:

    known price      -> the computed cost
    known-FREE price -> 0.00, which is a real price of zero
    NO published price -> NULL / None, NEVER 0 and never an estimate

The last one is the one that matters. The gateway's own ``getModelPricing``
ends with an ESTIMATE for unknown models (it needs a number to rank models by
cost). That is right for routing and wrong for accounting: an invented number
in a ledger reads as a fact. So the platform reproduces the gateway's
resolution ORDER but not its estimate.

Run from platform_v2/:
    python3 -m pytest tests/test_model_pricing.py -v
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import model_pricing_service as mps  # noqa: E402


# A miniature of the gateway's pricing table, in its real shape.
FAKE_TABLE = {
    "openai": {
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    },
    "anthropic": {
        "claude-fable-5-1": {"input": 10.0, "output": 50.0},
        "claude-haiku-4-5": {"input": 0.8, "output": 4.0},
    },
    "deepseek": {
        "deepseek-v4-flash": {"input": 0.22, "output": 0.66},
    },
    "groq": {
        "llama-3.3-70b-versatile": {"input": 0.0, "output": 0.0},
    },
    "kiro": {
        "minimax-m2.5": {"input": 0.27, "output": 0.95},
    },
}


class _PricingTestBase(unittest.TestCase):
    """Install a fake pricing table and a clean cache around each test."""

    def setUp(self):
        mps._cache = {}
        mps._cache_fetched_at = 0.0
        mps._cache_source = "test"
        mps._model_index = {}
        mps._reindex()
        with mock.patch.object(mps, "_fetch_ds9_pricing", return_value=None):
            with mock.patch.object(mps, "_load_db_pricing", return_value={}):
                mps._cache = {k: {m: dict(v) for m, v in mm.items()} for k, mm in FAKE_TABLE.items()}
                mps._cache_fetched_at = 10**9  # far in the future: never expires
                mps._cache_source = "test"
                mps._reindex()

    def tearDown(self):
        mps._cache = {}
        mps._model_index = {}
        mps._cache_fetched_at = 0.0
        mps._cache_source = "empty"


class TestModelCandidates(_PricingTestBase):
    """The platform's ledger records the ids the gateway DISPATCHED, which are
    often a little more specific than the ids the pricing table is keyed by."""

    def test_a_namespaced_id_keeps_only_its_last_segment(self):
        self.assertEqual(mps.model_candidates("cfp/zai-org/glm-5.2"), ["glm-5.2"])

    def test_an_ollama_variant_tag_is_stripped(self):
        self.assertEqual(
            mps.model_candidates("minimax-m2.5:cloud"),
            ["minimax-m2.5:cloud", "minimax-m2.5"],
        )

    def test_a_snapshot_suffix_is_stripped(self):
        self.assertEqual(
            mps.model_candidates("deepseek-v4-flash-0731"),
            ["deepseek-v4-flash-0731", "deepseek-v4-flash"],
        )

    def test_a_single_digit_suffix_is_NOT_stripped(self):
        # claude-haiku-5-5 must not become claude-haiku-5 — that is a different
        # model, and the table has no price for either.
        self.assertEqual(mps.model_candidates("claude-haiku-5-5"), ["claude-haiku-5-5"])

    def test_an_empty_model_yields_no_candidates(self):
        self.assertEqual(mps.model_candidates(None), [])
        self.assertEqual(mps.model_candidates(""), [])


class TestResolvePrice(_PricingTestBase):
    def test_a_known_model_resolves_at_its_published_price(self):
        p = mps.resolve_price("openai", "gpt-4o")
        self.assertIsNotNone(p)
        self.assertEqual(p["input_per_1m"], 2.5)
        self.assertEqual(p["output_per_1m"], 10.0)
        self.assertFalse(p["is_free"])

    def test_a_model_reached_through_another_provider_still_prices(self):
        """The gateway dispatches minimax models under its own provider ids,
        but prices the MODEL. The platform must agree."""
        p = mps.resolve_price("ollama_cloud", "minimax-m2.5:cloud")
        self.assertIsNotNone(p)
        self.assertEqual(p["input_per_1m"], 0.27)

    def test_a_free_channel_is_a_known_price_of_zero(self):
        p = mps.resolve_price("cloudflare-playground", "zai-org/glm-5.2")
        self.assertIsNotNone(p)
        self.assertEqual(p["input_per_1m"], 0.0)
        self.assertEqual(p["output_per_1m"], 0.0)
        self.assertTrue(p["is_free"])

    def test_a_local_fleet_node_is_a_known_price_of_zero(self):
        p = mps.resolve_price("fleet_node", "gemma2:9b")
        self.assertIsNotNone(p)
        self.assertTrue(p["is_free"])

    def test_a_zero_zero_table_entry_is_free_not_unknown(self):
        p = mps.resolve_price("groq", "llama-3.3-70b-versatile")
        self.assertIsNotNone(p)
        self.assertTrue(p["is_free"])
        self.assertEqual(p["input_per_1m"], 0.0)

    def test_an_unknown_model_is_NOT_TRACKED(self):
        """Never a fabricated 0.0 — an unknown price is not a price of zero."""
        self.assertIsNone(mps.resolve_price("some-provider", "totally-unknown-model"))

    def test_no_model_is_not_tracked(self):
        self.assertIsNone(mps.resolve_price("openai", None))
        self.assertIsNone(mps.resolve_price(None, None))

    def test_the_gateway_table_wins_over_the_offline_floor(self):
        """The gateway is the source of truth. groq is 0/0 in its table (a free
        tier) while a hand-written map once said $0.59/$0.79."""
        p = mps.resolve_price("groq", "llama-3.3-70b-versatile")
        self.assertEqual(p["source"], "ds9")
        self.assertTrue(p["is_free"])


class TestComputeCost(_PricingTestBase):
    def test_the_arithmetic_is_per_million_tokens(self):
        cost = mps.compute_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 12.5)

    def test_a_fraction_of_a_million_costs_proportionally(self):
        cost = mps.compute_cost("openai", "gpt-4o", 500_000, 250_000)
        self.assertAlmostEqual(cost, 1.25 + 2.5)

    def test_a_free_model_costs_zero(self):
        self.assertEqual(mps.compute_cost("groq", "llama-3.3-70b-versatile", 1000, 1000), 0.0)

    def test_an_unknown_model_costs_None_not_zero(self):
        self.assertIsNone(mps.compute_cost("nobody", "nothing", 1000, 1000))

    def test_missing_token_counts_are_treated_as_zero(self):
        cost = mps.compute_cost("openai", "gpt-4o", None, None)
        self.assertEqual(cost, 0.0)

    def test_negative_token_counts_are_refused(self):
        self.assertIsNone(mps.compute_cost("openai", "gpt-4o", -5, 0))


class TestCostForGroups(_PricingTestBase):
    """The ledger is priced per GROUP of rows, because a price is per-token
    and linear: summing a group's tokens against one price is exact."""

    def test_a_fully_priced_window_is_complete(self):
        # gpt-4o: 1M prompt x $2.50 = $2.50
        # claude-fable-5-1: 1M completion x $50.00 = $50.00
        res = mps.cost_for_groups(
            [
                ("openai", "gpt-4o", 1_000_000, 0),
                ("anthropic", "claude-fable-5-1", 0, 1_000_000),
            ]
        )
        self.assertAlmostEqual(res["cost"], 52.5)
        self.assertEqual(res["unpriced_tokens"], 0)
        self.assertEqual(res["unpriced_calls"], 0)

    def test_an_unpriced_group_is_reported_not_zeroed(self):
        res = mps.cost_for_groups(
            [
                ("openai", "gpt-4o", 1_000_000, 0),
                ("nobody", "nothing", 2_000_000, 0),
            ]
        )
        self.assertAlmostEqual(res["cost"], 2.5)
        self.assertEqual(res["unpriced_tokens"], 2_000_000)
        self.assertEqual(res["unpriced_calls"], 1)
        self.assertIn("nobody/nothing", res["unpriced_models"])

    def test_malformed_groups_are_skipped_not_fatal(self):
        res = mps.cost_for_groups([("openai", "gpt-4o"), ("openai", "gpt-4o", 1, 2)])
        self.assertEqual(res["priced_calls"], 1)
        self.assertEqual(res["unpriced_calls"], 0)


class TestBackfillContract(unittest.TestCase):
    """The backfill's two rules, checked against the source rather than a live
    database: a KNOWN price is written as the computed cost, and an UNKNOWN
    price is written as NULL — never as 0, which would mean "free"."""

    def test_the_backfill_writes_null_for_an_unpriced_model(self):
        src = mps.backfill_ledger_cost.__doc__ or ""
        self.assertIn("NULL", src)
        self.assertIn("lower bound", src.lower())

    def test_the_backfill_window_reaches_the_update_not_only_the_discovery(self):
        """An unbounded UPDATE re-scans the 2.1M-row table every night (439s
        measured). The window must be in the UPDATE."""
        import inspect

        src = inspect.getsource(mps.backfill_ledger_cost)
        self.assertIn("update_window", src)
        self.assertIn("null_window", src)
        # The window is applied in the UPDATE statements, not only the SELECT:
        # one assignment each, plus their use inside the UPDATE SQL.
        self.assertGreaterEqual(src.count("update_window"), 2)
        self.assertGreaterEqual(src.count("null_window"), 2)
        self.assertIn("tel.created_at >= NOW()", src)


class TestOfflineFloor(_PricingTestBase):
    def test_a_model_the_gateway_does_not_price_falls_back_to_the_floor(self):
        p = mps.resolve_price("cohere", "command-a-03-2025")
        self.assertIsNotNone(p)
        self.assertEqual(p["source"], "builtin")
        self.assertEqual(p["input_per_1m"], 2.5)


if __name__ == "__main__":
    unittest.main()
