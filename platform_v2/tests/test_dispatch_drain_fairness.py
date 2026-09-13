"""Drain fairness + warm-tag matching + per-lane starvation detection (#6749).

Three defects, measured live on 2026-09-12/13, all in the queue drain:

  1. `next_model not in all_warm_by_model` compared a BARE queue name against a
     TAGGED inventory key, so it was ALWAYS true for qwen25-classify. Every cycle
     the drain declared the model cold and fired a blocking cold-load for a model
     that was resident and serving 91/91 successfully.
  2. The claim loop walked the warm inventory in dict INSERTION order against a
     per-cycle budget of 3, so the first backlogged model took every slot. A model
     at position 13 was never reached: its head aged by exactly the wall-clock
     elapsed for over two hours.
  3. The monitor's stall check used ONE GLOBAL MAX(claimed_at), which sits near
     zero whenever any model drains — precisely when a starved lane is invisible.

These target the PURE helpers plus the CALL SITES. The call-site tests matter:
an earlier fix in this repo was reverted at the call site while helper-only tests
stayed green, so a helper test alone proves nothing about the running drain.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.dispatch_drain_monitor import starved_lanes  # noqa: E402
from services.model_dispatch_service import (  # noqa: E402
    _canonical_model_name,
    _drain_order,
    _model_is_warm,
)

_SERVICE_SRC = os.path.join(os.path.dirname(__file__), "..", "services", "model_dispatch_service.py")


# ---------------------------------------------------------------------------
# 1. warm matching across bare <-> :latest
# ---------------------------------------------------------------------------


class TestModelIsWarm:
    def test_bare_queue_name_matches_tagged_inventory_key(self):
        """THE BUG: this returned False for a resident, actively-serving model."""
        warm = {"qwen25-classify:latest": [None], "mistral:7b": [None]}
        assert _model_is_warm("qwen25-classify", warm) is True

    def test_tagged_queue_name_matches_bare_inventory_key(self):
        """The mismatch runs both ways — the inventory is not always the tagged side."""
        assert _model_is_warm("arctic-embed-cpu:latest", {"arctic-embed-cpu": [None]}) is True

    def test_exact_match_still_works(self):
        assert _model_is_warm("mistral:7b", {"mistral:7b": [None]}) is True

    def test_absent_model_is_not_warm(self):
        assert _model_is_warm("gemma3:12b", {"mistral:7b": [None]}) is False

    def test_different_tags_must_not_cross_match(self):
        """Only bare<->:latest may be equated. Sizes are different models."""
        assert _model_is_warm("qwen2.5:7b", {"qwen2.5:1.5b": [None]}) is False
        assert _model_is_warm("qwen2.5:1.5b", {"qwen2.5:7b": [None]}) is False

    def test_empty_inputs_are_not_warm(self):
        assert _model_is_warm("", {"mistral:7b": [None]}) is False
        assert _model_is_warm(None, {"mistral:7b": [None]}) is False
        assert _model_is_warm("mistral:7b", {}) is False


# ---------------------------------------------------------------------------
# 2. drain ordering by queue pressure
# ---------------------------------------------------------------------------


class TestDrainOrder:
    def test_oldest_head_drains_first(self):
        warm = {"a:latest": [None], "b:latest": [None], "c:latest": [None]}
        ages = {"a:latest": 60.0, "b:latest": 7800.0, "c:latest": 300.0}
        assert [m for m, _ in _drain_order(warm, ages)] == ["b:latest", "c:latest", "a:latest"]

    def test_models_with_no_queued_work_sort_last(self):
        """An idle model must never displace a starving one — it costs an empty query."""
        warm = {"idle:latest": [None], "starving:latest": [None]}
        order = [m for m, _ in _drain_order(warm, {"starving:latest": 5000.0})]
        assert order == ["starving:latest", "idle:latest"]

    def test_the_production_starvation_case(self):
        """Measured: classify (pos 1, big backlog) starved qwen2.5:1.5b (pos 13).

        Insertion order put classify first. By head age the starved lane goes first.
        """
        warm = {}
        warm["qwen25-classify:latest"] = [None]  # inserted FIRST, as in production
        for filler in range(11):
            warm["filler%d:latest" % filler] = [None]
        warm["qwen2.5:1.5b"] = [None]  # inserted LAST — never reached before
        ages = {"qwen25-classify:latest": 1080.0, "qwen2.5:1.5b": 7980.0}
        assert [m for m, _ in _drain_order(warm, ages)][0] == "qwen2.5:1.5b"

    def test_canonical_keys_match_bare_inventory_names(self):
        """head_ages is keyed canonically; a bare inventory key must still match."""
        order = [
            m
            for m, _ in _drain_order(
                {"mistral:7b": [None], "arctic-embed-cpu": [None]}, {_canonical_model_name("arctic-embed-cpu"): 900.0}
            )
        ]
        assert order[0] == "arctic-embed-cpu"

    def test_empty_head_ages_does_not_crash_or_drop_models(self):
        """Fail-safe: a failed probe degrades to 'no ordering hint', never to no drain."""
        warm = {"a:latest": [None], "b:latest": [None]}
        assert sorted(m for m, _ in _drain_order(warm, {})) == ["a:latest", "b:latest"]


# ---------------------------------------------------------------------------
# 3. per-lane starvation (what one global MAX(claimed_at) cannot see)
# ---------------------------------------------------------------------------


def _lane(module, model, rows, head, claim):
    return {
        "module_id": module,
        "model_needed": model,
        "queued_rows": rows,
        "head_age_min": head,
        "lane_claim_age_min": claim,
    }


class TestStarvedLanes:
    def test_old_rows_never_claimed_is_starved(self):
        lanes = [_lane("wtf_hub_quick", "qwen2.5:1.5b", 258, 133.0, None)]
        assert [l["module_id"] for l in starved_lanes(lanes, 45.0)] == ["wtf_hub_quick"]

    def test_old_rows_with_recent_claim_is_busy_not_starved(self):
        """Backlog under load is normal; it is only starvation if THIS lane stopped."""
        lanes = [_lane("quality_scorer", "qwen25-classify", 183, 120.0, 0.2)]
        assert starved_lanes(lanes, 45.0) == []

    def test_young_rows_are_never_starved(self):
        assert starved_lanes([_lane("m", "x", 500, 5.0, None)], 45.0) == []

    def test_the_case_check_two_misses(self):
        """The exact production shape: one lane draining hard, another frozen.

        The global MAX(claimed_at) is ~0 because classify is claimed every cycle,
        so check 2 reports healthy. Per lane, the frozen one is unmistakable.
        """
        lanes = [
            _lane("quality_scorer", "qwen25-classify", 183, 120.0, 0.1),  # draining
            _lane("wtf_hub_quick", "qwen2.5:1.5b", 258, 133.0, None),  # frozen
            _lane("wtf_hub", "mistral:7b", 5, 121.0, 118.0),  # frozen
        ]
        got = sorted(l["model_needed"] for l in starved_lanes(lanes, 45.0))
        assert got == ["mistral:7b", "qwen2.5:1.5b"]

    def test_empty_and_none_inputs_are_safe(self):
        assert starved_lanes([], 45.0) == []
        assert starved_lanes(None, 45.0) == []


# ---------------------------------------------------------------------------
# 4. CALL SITES — a helper nobody calls fixes nothing
# ---------------------------------------------------------------------------


class TestCallSites:
    def _src(self):
        with open(_SERVICE_SRC) as fh:
            return fh.read()

    def test_warm_check_call_site_uses_the_matcher(self):
        src = self._src()
        assert "_model_is_warm(next_model, all_warm_by_model)" in src
        assert not re.search(
            r"next_model\s+not\s+in\s+all_warm_by_model", src
        ), "the raw membership test is back — bare vs :latest will always miss"

    def test_claim_loop_call_site_uses_drain_order(self):
        src = self._src()
        assert "_drain_order(all_warm_by_model" in src
        assert not re.search(
            r"for model_name, node_ids in all_warm_by_model\.items\(\)", src
        ), "the claim loop is back on dict insertion order — lanes can starve again"
