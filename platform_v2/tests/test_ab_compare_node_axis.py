"""The NODE axis of Agent Academy A/B runs (#383 slice 1, revives #825).

These guard the distinction the calibration program is built on: a run that
changes the MODEL and a run that changes the HARDWARE answer different
questions, and conflating them is how `gemma3:12b` (hub 35% / USS-246 95% over
2,918 runs) got reported as one 56% fleet-wide model verdict and blocklisted,
then reversed the same day.
"""

from __future__ import annotations

from tools.agent_academy.ab_compare import (
    comparison_kind,
    normalize_side,
    parse_model_selection,
    side_label,
)


# --------------------------------------------------------------------------
# normalize_side
# --------------------------------------------------------------------------


def test_local_side_keeps_its_node():
    s = normalize_side("qwen2.5:7b", "USS-246")
    assert s["kind"] == "local" and s["model"] == "qwen2.5:7b" and s["node"] == "USS-246"


def test_local_side_without_a_node_is_none_not_empty_string():
    """None means 'let the dispatcher choose'. '' would be a falsy node that
    still reads as 'a node was specified' to anything doing a key check."""
    assert normalize_side("qwen2.5:7b")["node"] is None
    assert normalize_side("qwen2.5:7b", "   ")["node"] is None


def test_cloud_side_DROPS_a_node():
    """A provider's hardware is not ours to choose. Keeping the node would let a
    cloud result later read as a placement claim we never made."""
    s = normalize_side("provider:openai:gpt-4o-mini", "USS-246")
    assert s["kind"] == "cloud" and s["node"] is None


def test_parse_model_selection_is_unchanged():
    """normalize_side adds `node`; the underlying parser must not — an existing
    test asserts exact dict equality on it."""
    assert parse_model_selection("qwen2.5:7b") == {"kind": "local", "provider": None, "model": "qwen2.5:7b"}


# --------------------------------------------------------------------------
# side_label
# --------------------------------------------------------------------------


def test_label_shows_where_a_local_model_ran():
    assert side_label(normalize_side("qwen2.5:7b", "USS-246")) == "qwen2.5:7b @ USS-246"


def test_label_omits_the_at_clause_when_no_node():
    assert side_label(normalize_side("qwen2.5:7b")) == "qwen2.5:7b"


def test_label_for_cloud_names_the_provider():
    assert side_label(normalize_side("provider:openai:gpt-4o-mini")) == "openai:gpt-4o-mini"


# --------------------------------------------------------------------------
# comparison_kind — the load-bearing one
# --------------------------------------------------------------------------


def test_same_model_different_node_is_a_PLACEMENT_question():
    k = comparison_kind(
        normalize_side("gemma3:12b", "archie-starbase"),
        normalize_side("gemma3:12b", "USS-246"),
    )
    assert k == "placement"


def test_different_model_same_node_is_a_MODEL_question():
    k = comparison_kind(
        normalize_side("qwen2.5:7b", "USS-246"),
        normalize_side("qwen3:8b", "USS-246"),
    )
    assert k == "model"


def test_two_variables_at_once_is_MIXED_not_silently_a_model_verdict():
    """The dangerous case. Changing model AND node yields a clean conclusion
    about NEITHER, so it must not be labelled 'model' — that is precisely the
    mislabel that produced the blocklist reversal."""
    k = comparison_kind(
        normalize_side("qwen2.5:7b", "archie-starbase"),
        normalize_side("qwen3:8b", "USS-246"),
    )
    assert k == "mixed"


def test_same_model_same_node_is_IDENTICAL_a_repeatability_probe():
    """Legitimate to run (measures run-to-run noise), useless if mislabelled as
    a model or placement result."""
    k = comparison_kind(
        normalize_side("qwen2.5:7b", "USS-246"),
        normalize_side("qwen2.5:7b", "USS-246"),
    )
    assert k == "identical"


def test_both_nodes_unspecified_is_still_identical_for_the_same_model():
    k = comparison_kind(normalize_side("qwen2.5:7b"), normalize_side("qwen2.5:7b"))
    assert k == "identical"


def test_local_vs_cloud_same_name_is_not_treated_as_the_same_model():
    """A local 'gpt-4o-mini' tag and the cloud model are different things; kind
    must participate in sameness or a cross-tier run reads as 'placement'."""
    k = comparison_kind(
        normalize_side("gpt-4o-mini", "USS-246"),
        normalize_side("provider:openai:gpt-4o-mini"),
    )
    assert k != "placement"
