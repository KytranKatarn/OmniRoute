"""Review legs fail fast and one node runs ONE num_ctx per model (#7349)."""

from __future__ import annotations

import json
from pathlib import Path

from services.node_ctx import apply_node_default_ctx, node_default_ctx
from services.review_leg_policy import DEFAULT_LEG_TIMEOUT, PATIENT_LEG_TIMEOUT, leg_timeout

ROOT = Path(__file__).resolve().parents[1]
ANALYZER = (ROOT / "tools/repair_bay/services/pr_diff_analyzer.py").read_text()
DISPATCHER = (ROOT / "tools/department_hq/services/department_dispatcher.py").read_text()
AGENT_LOOP = (ROOT.parent / "ai_bridge/agent_loop.py").read_text()

CAPS = {"num_ctx_default": {"qwen2.5:7b": 8192}}


# ---- per-leg timeout -------------------------------------------------------------------------
def test_default_leg_timeout_is_240_not_600():
    assert leg_timeout(None) == DEFAULT_LEG_TIMEOUT == 240


def test_setting_is_bounded_to_the_dispatcher_floor_and_the_old_cap():
    assert leg_timeout("100") == 240  # below the 240 fleet floor is meaningless (#5810/#266396)
    assert leg_timeout("300") == 300
    assert leg_timeout("9999") == 600
    assert leg_timeout("600") == 600  # setting 600 restores the old behaviour


def test_bad_setting_falls_back_to_the_default():
    assert leg_timeout("junk") == 240 and leg_timeout("") == 240 and leg_timeout({}) == 240


def test_patient_model_escalation_keeps_600():
    assert leg_timeout(None, patient=True) == PATIENT_LEG_TIMEOUT == 600
    assert leg_timeout("240", patient=True) == 600  # a 12B cold-load needs the headroom


def test_both_review_dispatches_use_the_leg_timeout():
    body = ANALYZER.split("def _dispatch_json_review", 1)[1]
    structured = body.split("result = dispatch(", 1)[1].split(")\n    except", 1)[0]
    assert "_review_leg_timeout(kw)" in structured  # patient detection sees the model override
    assert ANALYZER.count("_review_leg_timeout(") >= 3  # def + structured + freeform


def test_a_caller_supplied_timeout_still_wins():
    assert '**{"timeout": _review_leg_timeout(kw), **kw}' in ANALYZER  # kw is spread AFTER the default


# ---- one num_ctx per node + model ------------------------------------------------------------
def test_node_default_fills_a_caller_that_sent_none():
    assert apply_node_default_ctx(None, CAPS, "qwen2.5:7b") == {"num_ctx": 8192}
    assert apply_node_default_ctx({"temperature": 0.7}, CAPS, "qwen2.5:7b") == {"temperature": 0.7, "num_ctx": 8192}


def test_explicit_caller_num_ctx_always_wins():
    opts = {"num_ctx": 4096}
    assert apply_node_default_ctx(opts, CAPS, "qwen2.5:7b") is opts


def test_other_models_and_unmapped_nodes_are_untouched():
    assert apply_node_default_ctx({"a": 1}, CAPS, "llama3.2:3b") == {"a": 1}  # cockpit 3B keeps its own runner
    assert apply_node_default_ctx(None, {}, "qwen2.5:7b") is None
    assert apply_node_default_ctx(None, None, "qwen2.5:7b") is None


def test_json_string_and_latest_tag_are_handled():
    assert node_default_ctx(json.dumps(CAPS), "qwen2.5:7b") == 8192
    assert node_default_ctx({"num_ctx_default": {"qwen2.5:7b": 8192}}, "qwen2.5:7b:latest") == 8192


def test_bad_or_out_of_range_values_are_ignored():
    for bad in ("big", None, 100, 10**7, -1):
        assert node_default_ctx({"num_ctx_default": {"qwen2.5:7b": bad}}, "qwen2.5:7b") is None
    assert node_default_ctx({"num_ctx_default": "oops"}, "qwen2.5:7b") is None
    assert node_default_ctx("not json", "qwen2.5:7b") is None


def test_dispatcher_applies_the_node_default_before_building_the_payload():
    leaf = DISPATCHER.split("def _dispatch_to_node", 1)[1]
    assert leaf.index("apply_node_default_ctx(") < leaf.index("payload = {")
    assert '(_nr or {}).get("extra_capabilities")' in leaf


def test_keepwarm_reads_the_same_node_map():
    kw = AGENT_LOOP.split("def _keep_forge_review_model_warm", 1)[1].split("def _keep_cockpit_node_model_warm", 1)[0]
    assert "node_default_ctx(" in kw and "extra_capabilities" in kw
