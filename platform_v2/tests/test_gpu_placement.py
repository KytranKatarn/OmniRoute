"""Pin the per-card placement contract.

The value of this change rests on ONE claim: it is a strict generalisation of
the old scalar rule, so it can only convert a CPU demotion into a GPU placement
on a multi-card box, never the reverse. That claim is not asserted here, it is
PROVEN -- ``_old_scalar_rule`` below is the rule being replaced, and the
equivalence tests compare the two directly over a swept input space.

This matters because the module sits on the dispatch path, whose last
regression (#5623) forced 7B work onto a pre-AVX2 CPU and produced an
89%-failure hour.
"""

from __future__ import annotations

import itertools
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.gpu_placement import (  # noqa: E402
    cards_free_gb_from_state,
    plan_gpu_placement,
)


def _old_scalar_rule(cards_free_gb, needed, reserve):
    """The rule this module replaces: one number for the whole box."""
    if not cards_free_gb:
        return False
    budget = max(cards_free_gb)
    return (budget - reserve) >= needed


class TestTheMeasuredRegression(unittest.TestCase):
    """The live hub case: 127 CPU demotions in 24h."""

    def test_second_card_absorbs_the_model_the_scalar_rule_refused(self):
        # freest card 7.9 GB (as logged), other card holds 6.5 GB free.
        cards = [7.9, 6.5]
        needed, reserve = 5.6, 6.0

        # Old rule: 7.9 - 6.0 = 1.9 < 5.6  -> CPU.
        self.assertFalse(_old_scalar_rule(cards, needed, reserve))

        # New rule: put it on the 6.5 GB card? 6.5-5.6=0.9, but the 7.9 card
        # still covers the reserve -> GPU.
        p = plan_gpu_placement(cards, needed, reserve)
        self.assertTrue(p.on_gpu, p)
        self.assertEqual(p.reason, "fits_reserve_elsewhere")
        self.assertEqual(p.card_index, 1)  # best-fit = smallest that fits

    def test_it_still_refuses_when_the_reserve_genuinely_cannot_be_kept(self):
        """Not a rubber stamp: one card, and placing would eat the reserve."""
        cards = [7.9, 2.0]
        p = plan_gpu_placement(cards, needed_gb=5.6, reserve_gb=6.0)
        self.assertFalse(p.on_gpu, p)
        self.assertEqual(p.reason, "reserve_hold")
        self.assertFalse(_old_scalar_rule(cards, 5.6, 6.0))  # old rule agrees


class TestStrictGeneralisation(unittest.TestCase):
    """The safety argument, swept rather than asserted."""

    def test_single_card_is_algebraically_the_old_rule(self):
        for free in (0.0, 1.0, 4.0, 5.6, 8.0, 11.8, 12.0, 24.0):
            for needed in (0.5, 4.0, 5.6, 8.0, 12.0):
                for reserve in (0.0, 1.0, 6.0, 12.0):
                    old = _old_scalar_rule([free], needed, reserve)
                    new = plan_gpu_placement([free], needed, reserve).on_gpu
                    self.assertEqual(old, new, f"1-card divergence free={free} n={needed} r={reserve}")

    def test_zero_reserve_is_the_old_rule_on_any_card_count(self):
        for cards in itertools.product((0.0, 2.0, 6.0, 12.0), repeat=3):
            for needed in (0.5, 4.0, 5.6, 12.0):
                old = _old_scalar_rule(list(cards), needed, 0.0)
                new = plan_gpu_placement(list(cards), needed, 0.0).on_gpu
                self.assertEqual(old, new, f"r=0 divergence cards={cards} n={needed}")

    def test_never_refuses_where_the_old_rule_placed(self):
        """The one-directional guarantee. A regression here is a real regression."""
        swept = downgrades = upgrades = 0
        for cards in itertools.product((0.0, 1.5, 3.0, 6.5, 7.9, 11.8), repeat=2):
            for needed in (0.5, 2.0, 5.6, 8.0):
                for reserve in (0.0, 2.0, 6.0):
                    swept += 1
                    old = _old_scalar_rule(list(cards), needed, reserve)
                    new = plan_gpu_placement(list(cards), needed, reserve).on_gpu
                    if old and not new:
                        downgrades += 1
                    if new and not old:
                        upgrades += 1
        self.assertEqual(downgrades, 0, "the new rule refused a placement the old rule made")
        # Non-vacuity: the sweep must actually contain cases that CHANGE, or
        # "no downgrades" would be trivially true for an identical function.
        self.assertGreater(upgrades, 0, "sweep found no improvement — test is vacuous")
        self.assertGreater(swept, 100)


class TestBestFit(unittest.TestCase):
    def test_prefers_the_smallest_card_that_fits(self):
        """Keeps the big card clear for the 7B work the reserve protects."""
        p = plan_gpu_placement([11.8, 6.5, 2.0], needed_gb=5.0, reserve_gb=0.0)
        self.assertEqual(p.card_index, 1)

    def test_best_fit_still_wins_when_the_other_card_covers_the_reserve(self):
        """Best-fit picks the 6.2 GB card; the 6.5 GB card then holds the reserve.

        Placing on 6.2 leaves [0.6, 6.5], and 6.5 >= 6.0, so the reserve is
        satisfied *elsewhere* -- which is the whole point of the change.
        """
        p = plan_gpu_placement([6.2, 6.5], needed_gb=5.6, reserve_gb=6.0)
        self.assertTrue(p.on_gpu)
        self.assertEqual(p.card_index, 0)
        self.assertEqual(p.reason, "fits_reserve_elsewhere")

    def test_best_fit_is_OPTIMAL_for_reserve_satisfaction(self):
        """Best-fit never costs a placement — brute-forced, not argued.

        Using the smallest fitting card leaves the LARGEST card untouched, so it
        gives the reserve the best possible chance. This asserts the property
        directly: whenever *some* card assignment keeps the reserve, the choice
        made here also keeps it. (An earlier version of this test tried to build
        a case where best-fit had to be skipped in favour of a bigger card. No
        such case exists, which is exactly what this proves.)
        """
        checked = feasible = 0
        for cards in itertools.product((0.0, 2.0, 5.9, 6.0, 8.0, 12.0), repeat=3):
            for needed in (1.0, 5.6, 8.0):
                for reserve in (0.0, 6.0):
                    checked += 1
                    # brute force: does ANY single-card assignment work?
                    any_ok = False
                    for i, f in enumerate(cards):
                        if f < needed:
                            continue
                        rem = list(cards)
                        rem[i] -= needed
                        if reserve <= 0 or max(rem) >= reserve:
                            any_ok = True
                            break
                    got = plan_gpu_placement(list(cards), needed, reserve)
                    self.assertEqual(
                        any_ok,
                        got.on_gpu,
                        f"best-fit suboptimal: cards={cards} n={needed} r={reserve} -> {got}",
                    )
                    feasible += 1 if any_ok else 0
        self.assertGreater(checked, 200)
        self.assertGreater(feasible, 0)  # non-vacuity: some cases DO place

    def test_ties_break_deterministically_on_the_lower_index(self):
        a = plan_gpu_placement([6.0, 6.0], needed_gb=1.0, reserve_gb=0.0)
        b = plan_gpu_placement([6.0, 6.0], needed_gb=1.0, reserve_gb=0.0)
        self.assertEqual(a.card_index, 0)
        self.assertEqual(a, b)


class TestDegenerateInputs(unittest.TestCase):
    def test_no_cards_is_refused_not_crashed(self):
        p = plan_gpu_placement([], needed_gb=1.0, reserve_gb=0.0)
        self.assertFalse(p.on_gpu)
        self.assertEqual(p.reason, "no_cards")

    def test_model_larger_than_every_card(self):
        p = plan_gpu_placement([8.0, 12.0], needed_gb=24.0, reserve_gb=0.0)
        self.assertFalse(p.on_gpu)
        self.assertEqual(p.reason, "too_large")

    def test_none_and_negative_free_are_treated_as_zero(self):
        p = plan_gpu_placement([None, -3.0, 9.0], needed_gb=5.0, reserve_gb=0.0)
        self.assertTrue(p.on_gpu)
        self.assertEqual(p.card_index, 2)


class TestStateParsing(unittest.TestCase):
    def test_reads_free_mb_per_card(self):
        state = {"ts": 1, "cards": [{"mem_free_mb": 2804}, {"mem_free_mb": 12048}]}
        got = cards_free_gb_from_state(state)
        self.assertEqual([round(g, 1) for g in got], [2.7, 11.8])

    def test_missing_state_is_None_not_empty(self):
        """Empty would read as 'a box with no GPUs' and silently force CPU."""
        self.assertIsNone(cards_free_gb_from_state(None))
        self.assertIsNone(cards_free_gb_from_state({}))
        self.assertIsNone(cards_free_gb_from_state({"ts": 1, "cards": []}))

    def test_a_partial_reading_is_no_reading(self):
        state = {"ts": 1, "cards": [{"mem_free_mb": 2804}, {"name": "no free field"}]}
        self.assertIsNone(cards_free_gb_from_state(state))

    def test_unparseable_free_is_no_reading(self):
        state = {"ts": 1, "cards": [{"mem_free_mb": "lots"}]}
        self.assertIsNone(cards_free_gb_from_state(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
