"""A node may narrow one capability's fleet-leg budget, never widen it (#7349)."""

from __future__ import annotations

import json
from pathlib import Path

from services.node_ctx import narrowed_leg_timeout, node_leg_timeout_cap

ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = (ROOT / "tools/department_hq/services/department_dispatcher.py").read_text()
CAPS = {"fleet_leg_timeout": {"code_review": 120}}


def test_cap_applies_to_the_listed_capability_only():
    assert node_leg_timeout_cap(CAPS, "code_review") == 120
    assert node_leg_timeout_cap(CAPS, "fact_check") is None  # WTF legs legitimately run longer
    assert node_leg_timeout_cap(CAPS, "") is None


def test_no_entry_means_no_change():
    assert node_leg_timeout_cap({}, "code_review") is None
    assert node_leg_timeout_cap(None, "code_review") is None
    assert node_leg_timeout_cap({"fleet_leg_timeout": "oops"}, "code_review") is None


def test_json_string_extra_capabilities_are_accepted():
    assert node_leg_timeout_cap(json.dumps(CAPS), "code_review") == 120


def test_bad_or_out_of_range_values_are_ignored():
    for bad in ("fast", None, 5, 59, 601, 10**6, -1):
        assert node_leg_timeout_cap({"fleet_leg_timeout": {"code_review": bad}}, "code_review") is None
    assert node_leg_timeout_cap({"fleet_leg_timeout": {"code_review": 60}}, "code_review") == 60
    assert node_leg_timeout_cap({"fleet_leg_timeout": {"code_review": 600}}, "code_review") == 600


def test_a_cap_narrows_the_budget_and_never_widens_it():
    assert narrowed_leg_timeout(600, CAPS, "code_review") == 120  # Defiant review leg: 600 -> 120
    assert narrowed_leg_timeout(240, CAPS, "code_review") == 120
    assert narrowed_leg_timeout(90, CAPS, "code_review") == 90  # a cap above the granted budget is ignored
    assert narrowed_leg_timeout(120, CAPS, "code_review") == 120


def test_other_capabilities_and_unlisted_nodes_keep_their_budget():
    assert narrowed_leg_timeout(600, CAPS, "fact_check") == 600
    assert narrowed_leg_timeout(600, {}, "code_review") == 600
    assert narrowed_leg_timeout(600, None, "code_review") == 600


def test_dispatcher_uses_the_narrowed_budget_before_the_http_call():
    leaf = DISPATCHER.split("def _dispatch_to_node", 1)[1]
    call = leaf.index("narrowed_leg_timeout(")
    assert call < leaf.index("resp = requests.post(")
    assert "timeout = _capped" in leaf  # the narrowed value is what requests.post receives
    assert '(_nr or {}).get("extra_capabilities"), capability)' in leaf


def test_the_240_floor_is_untouched_for_nodes_without_an_entry():
    # the caller-side floor stays exactly as #5810 left it
    assert "timeout=max(timeout, 240)" in DISPATCHER
