"""AUX POWER families must cover the modules that actually generate queue traffic.

`queue_row_gets_priority` biases drain order only for rows it can CLASSIFY. A
module whose `module_source` matches no family's keywords is invisible to AUX
POWER: it is neither promoted nor demoted, so it keeps cycling on equal footing
with whatever the operator focused.

Measured 2026-10-02 on the live queue, newest-first:

    fact_check    src=wtf_hub      <- busiest source, NO family matched
    code_review   src=repair_bay
    warmup        src=kin_warmth   <- deliberately never boosted
    bias_analysis src=bias_sampler

with fleet_dispatch_focus='repair_bay'. AUX was correctly promoting repair_bay
and still could not outrun wtf_hub traffic, because wtf_hub was not something
the taxonomy knew about.

`is_family_queue_row` is a substring match, so the fix is coverage: name the
module sources that are actually busy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.fleet_dispatch_profile import (  # noqa: E402
    MODULE_FAMILIES,
    NEVER_BOOST_MODULES,
    is_family_queue_row,
    queue_row_gets_priority,
)


class TestWtfIsClassifiable:
    def test_wtf_hub_matches_a_family(self):
        hits = [f for f in MODULE_FAMILIES if is_family_queue_row("wtf_hub", f)]
        assert hits, "wtf_hub matches no family — AUX POWER cannot reason about it"
        assert (
            len(hits) == 1
        ), f"wtf_hub matches several families ({hits}); boost becomes ambiguous"

    def test_wtf_ingest_and_what_the_fact_also_match(self):
        for mod in ("wtf-ingest", "what_the_fact"):
            assert any(
                is_family_queue_row(mod, f) for f in MODULE_FAMILIES
            ), f"{mod} unclassified"

    def test_existing_families_still_resolve(self):
        for mod, family in (
            ("repair_bay", "repair_bay"),
            ("consciousness", "consciousness"),
            ("email_manager", "email"),
            ("linkedin", "social"),
            ("chronicle", "chronicle"),
        ):
            assert is_family_queue_row(mod, family), f"{mod} -> {family} regressed"


class TestNoCrossFamilyBleed:
    def test_wtf_hub_is_not_a_repair_bay_row(self):
        """Otherwise focusing repair_bay would silently drag wtf traffic forward."""
        assert is_family_queue_row("wtf_hub", "repair_bay") is False

    def test_repair_bay_is_not_a_wtf_row(self):
        assert is_family_queue_row("repair_bay", "wtf") is False

    def test_never_boost_modules_stay_never_boosted(self):
        """kin_warmth/fleet_warmup are excluded for every family, including the new one."""
        for mod in NEVER_BOOST_MODULES:
            for fam in MODULE_FAMILIES:
                assert is_family_queue_row(mod, fam) is False, f"{mod} boosted by {fam}"


class TestPromotionStillWorksUnderFocus:
    def test_focusing_wtf_promotes_only_wtf(self):
        for mod in ("wtf_hub", "wtf-ingest"):
            assert (
                queue_row_gets_priority("fact_check", mod, "platform", "wtf") is True
            ), mod
        assert (
            queue_row_gets_priority("code_review", "repair_bay", "platform", "wtf")
            is False
        )

    def test_focusing_repair_bay_still_ignores_wtf(self):
        assert (
            queue_row_gets_priority(
                "code_review", "repair_bay", "platform", "repair_bay"
            )
            is True
        )
        assert (
            queue_row_gets_priority("fact_check", "wtf_hub", "platform", "repair_bay")
            is False
        )

    def test_auto_mode_is_unbiased(self):
        """The stable-split contract: auto must never promote anything."""
        for mod in ("wtf_hub", "repair_bay"):
            assert queue_row_gets_priority("fact_check", mod, "auto", "wtf") is False

    def test_every_family_is_selectable_and_nonempty(self):
        for fam, keywords in MODULE_FAMILIES.items():
            assert keywords, f"family {fam} has no keywords — unselectable"
