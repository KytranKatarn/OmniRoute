"""The pinned reserve must never drive the unpinned budget to zero (#6749).

PINNED_RESERVED_SLICE (#3804) protects fleet warm-keeps from a sustained unpinned
queue. It was a flat subtraction from free_slots, so on a 6-thread pool the UNPINNED
side hit zero first and stayed there — the opposite starvation.

Measured 2026-09-13 over 24 consecutive cycles: budget exactly 0 in 15 of them
(free_slots 1-2, inflight 4-5), unpinned claims 0, while a lane sat 133 minutes
unclaimed. A reserve that silently becomes a total block is a cliff, not a gradient.

The counter-requirement is absolute and is why the floor is conditional: a row
claimed with no free thread rots as 'running' until the 900s reaper (#5699).
Forward progress never justifies claiming into a full pool.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.model_dispatch_service import (  # noqa: E402
    MAX_TASKS_PER_CYCLE,
    PINNED_RESERVED_SLICE,
    UNPINNED_MIN_SLICE,
    _unpinned_budget,
)


class TestFullPoolIsNeverClaimedInto:
    """The invariant that outranks fairness. If this breaks, rows rot until the reaper."""

    def test_zero_free_slots_yields_zero_budget(self):
        assert _unpinned_budget(0) == 0

    def test_negative_is_clamped_not_floored(self):
        """Defensive: a bad reading must not become a claim."""
        assert _unpinned_budget(-3) == 0


class TestTheCliff:
    """The measured production case: reserve >= free_slots meant a budget of 0."""

    def test_free_slots_equal_to_reserve_still_makes_progress(self):
        # free=2, reserve=2 -> old: max(0, 0) = 0 (the cliff). New: 1.
        assert _unpinned_budget(PINNED_RESERVED_SLICE) == UNPINNED_MIN_SLICE

    def test_free_slots_below_reserve_still_makes_progress(self):
        # free=1, reserve=2 -> old: max(0, -1) = 0. New: 1.
        assert _unpinned_budget(1) == UNPINNED_MIN_SLICE

    def test_the_old_formula_would_have_returned_zero_here(self):
        """Pins the regression itself: these are exactly the readings that produced 0."""
        for free in (1, 2):
            old = min(MAX_TASKS_PER_CYCLE, max(0, free - PINNED_RESERVED_SLICE))
            assert old == 0, "test premise wrong — the old formula did not stall at free=%d" % free
            assert _unpinned_budget(free) > 0


class TestReserveStillHonouredWhenThereIsRoom:
    """The floor is a floor, not a removal — #3804's guarantee must survive."""

    def test_ample_slots_subtract_the_full_reserve(self):
        assert _unpinned_budget(6) == 6 - PINNED_RESERVED_SLICE

    def test_reserve_is_not_bypassed_above_the_cliff(self):
        # free=5 -> 3, exactly as before. The floor must not inflate a healthy budget.
        assert _unpinned_budget(5) == 5 - PINNED_RESERVED_SLICE

    def test_budget_never_exceeds_the_cycle_cap(self):
        assert _unpinned_budget(10_000) == MAX_TASKS_PER_CYCLE

    def test_budget_never_exceeds_free_slots(self):
        """Claiming more than the pool can start is the #5699 defect."""
        for free in range(0, 12):
            assert _unpinned_budget(free) <= max(0, free)


class TestMonotonic:
    def test_more_free_slots_never_reduces_the_budget(self):
        budgets = [_unpinned_budget(f) for f in range(0, 12)]
        assert budgets == sorted(budgets), budgets
