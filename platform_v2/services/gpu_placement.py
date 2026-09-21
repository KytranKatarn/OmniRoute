"""Decide WHICH card a model goes on, instead of collapsing the box to one number.

THE PROBLEM THIS SOLVES
-----------------------
Placement asked a single scalar question::

    budget = max(free_gb per card)        # the freest card
    place_on_gpu = (budget - reserve) >= needed

The reserve (``ARCHIE_VRAM_GPU_RESERVE_GB``, live at 6 GB) exists so an
on-demand 7B finds GPU room without evicting the warm set. But because the
budget is ONE number, the reserve and the candidate model compete for the SAME
card -- so on a two-card box the second card cannot absorb a small model while
the first holds the reserve.

Measured on the hub, 24h: ``qwen25-classify`` (needs 5.6 GB, CPU-viable, so it
pays the reserve) was demoted to CPU **127 times** with lines like::

    placement qwen25-classify -> cpu (budget 7.9 - reserve 6.0 < needed 5.6 GB; reserve_hold)

7.9 GB free on the freest card, 6 GB held back, so 1.9 GB offered to a 5.6 GB
model. Whether the OTHER card could have taken it was never asked.

THE RIGHT QUESTION
------------------
The reserve's purpose is that a 7B finds room *somewhere*, not on one specific
card. So::

    is there a card that fits `needed`, such that AFTER placing it,
    some card still has `reserve` free?

Placement prefers the SMALLEST card that fits (best-fit). On this hub that puts
small models on the 8 GB Quadro and keeps the 12 GB TITAN clear for 7B work --
the placement the reserve was trying to approximate with one number.

WHY THIS IS SAFE
----------------
It is a strict generalisation, not a new policy:

* ONE card      -- ``free >= needed and (free - needed) >= reserve`` is
                   algebraically ``free - reserve >= needed``: the old rule.
* ``reserve=0``  -- reduces to ``max(free) >= needed``: the old rule.
* no per-card data -- the caller keeps its existing scalar path untouched.

So it can only turn a CPU demotion into a GPU placement on a multi-card box,
never the reverse. That direction matters: this module sits on the dispatch
path, whose last regression (#5623) forced 7B work onto a pre-AVX2 CPU and
produced an 89%-failure hour.
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional, Sequence


class GpuPlacement(NamedTuple):
    """Where a model should go, and why (the reason is telemetry, not decoration)."""

    on_gpu: bool
    card_index: Optional[int]
    reason: str


def plan_gpu_placement(
    cards_free_gb: Sequence[float],
    needed_gb: float,
    reserve_gb: float = 0.0,
) -> GpuPlacement:
    """Pick a card for ``needed_gb``, keeping ``reserve_gb`` free somewhere.

    ``cards_free_gb`` is free VRAM per card, in GB, in card order (so
    ``card_index`` indexes back into the caller's own card list).

    Reasons returned:
      ``fits_reserve_elsewhere`` -- placed; another card still holds the reserve
      ``fits_reserve_intact``    -- placed; the chosen card itself still holds it
      ``no_cards``               -- nothing to place on
      ``too_large``              -- no single card fits the model at all
      ``reserve_hold``           -- a card fits, but placing would leave the
                                    reserve unsatisfiable anywhere
    """
    free = [max(0.0, float(f or 0.0)) for f in cards_free_gb]
    if not free:
        return GpuPlacement(False, None, "no_cards")

    reserve = max(0.0, float(reserve_gb or 0.0))
    needed = max(0.0, float(needed_gb or 0.0))

    fitting = [i for i, f in enumerate(free) if f >= needed]
    if not fitting:
        return GpuPlacement(False, None, "too_large")

    # Best-fit: the SMALLEST card that fits. Leaves the largest card free for
    # the big-model work the reserve exists to protect. Ties break on the lower
    # index so the choice is deterministic (a flapping choice would make the
    # placement log unreadable).
    fitting.sort(key=lambda i: (free[i], i))

    for i in fitting:
        if reserve <= 0:
            return GpuPlacement(True, i, "fits_reserve_intact")
        remaining = list(free)
        remaining[i] -= needed
        if max(remaining) >= reserve:
            # Distinguish "this card still covers the reserve by itself" from
            # "another card is covering it" -- the second is the case the old
            # scalar rule could not see, and the one worth watching in telemetry.
            reason = "fits_reserve_intact" if remaining[i] >= reserve else "fits_reserve_elsewhere"
            return GpuPlacement(True, i, reason)

    return GpuPlacement(False, None, "reserve_hold")


def cards_free_gb_from_state(state: Optional[dict]) -> Optional[List[float]]:
    """Free GB per card from the host exporter payload, or None if untrustworthy.

    None means "no per-card data" and the caller must keep its scalar fallback --
    never an empty list, which would read as "a box with no GPUs" and silently
    force CPU. Same unknown-is-not-empty rule as ADR-017.
    """
    if not state:
        return None
    cards = state.get("cards") or []
    if not cards:
        return None
    out: List[float] = []
    for c in cards:
        mb = c.get("mem_free_mb")
        if mb is None:
            return None  # a partial reading is not a reading
        try:
            out.append(float(mb) / 1024.0)
        except (TypeError, ValueError):
            return None
    return out or None
