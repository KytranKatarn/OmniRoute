"""Guards for the node-aware A/B run and fleet-wide model list (#383, revives #825).

Before this, `ab_test_models()` enumerated `OLLAMA_LOCAL_HOST` — the hub and only
the hub — and `/api/ab-test/run` had no node parameter. The route's own comment
said it plainly: *"model_override pins to the hub: fine for a controlled A/B
(both sides same node = fair)."* Fair, and it made the fleet's most important
question unaskable.

These are source-level guards. The route needs a Flask context and a live
dispatcher, so what is pinned here is the CONTRACT: the node is optional, it is
passed as a hint, and what gets RECORDED is what actually ran.
"""

from __future__ import annotations

import re
from pathlib import Path

ROUTES = (Path(__file__).resolve().parents[1] / "tools" / "agent_academy" / "benchmark_routes.py").read_text()


# --------------------------------------------------------------------------
# The node axis exists and is optional
# --------------------------------------------------------------------------


def test_run_endpoint_accepts_a_node_per_side():
    assert 'data.get("node_a")' in ROUTES
    assert 'data.get("node_b")' in ROUTES


def test_absent_node_is_None_not_empty_string():
    """'' is falsy but still reads as 'a node was specified' to a key check."""
    assert re.search(r'node_a\s*=\s*\(data\.get\("node_a"\)\s*or\s*""\)\.strip\(\)\s*or\s*None', ROUTES)


def test_preferred_node_is_passed_ONLY_when_a_node_is_named():
    """Omitted => byte-identical to the pre-#383 behaviour. Passing
    preferred_node=None unconditionally would change routing for every existing
    caller, which is exactly what an additive change must not do."""
    assert '_kw = {"preferred_node": [node_name]} if node_name else {}' in ROUTES
    assert "**_kw," in ROUTES


def test_node_is_threaded_through_the_per_side_loop():
    assert '[("a", model_a, node_a), ("b", model_b, node_b)]' in ROUTES


# --------------------------------------------------------------------------
# Requested vs actual — the distinction that keeps a placement finding honest
# --------------------------------------------------------------------------


def test_result_records_BOTH_requested_and_used_node():
    """`preferred_node` is a HINT; the dispatcher may place elsewhere on
    capacity/presence/welfare grounds. Recording only the request would make a
    silent re-placement invisible and turn a placement finding into fiction."""
    assert '"node_requested"' in ROUTES
    assert '"node_used"' in ROUTES


def test_node_used_is_read_from_the_RESULT_not_the_request():
    m = re.search(r'"node_used":\s*(.+)', ROUTES)
    assert m and "result" in m.group(1), "node_used must come from the dispatch result"
    assert "node_name" not in m.group(1).split("result")[0]


# --------------------------------------------------------------------------
# A placement result must not be readable as a model verdict
# --------------------------------------------------------------------------


def test_comparison_kind_is_computed_and_persisted():
    """gemma3:12b is 35% on the hub and 95% on USS-246 over 2,918 runs. Storing
    a run without saying WHICH variable moved is how that became one 56%
    fleet-wide 'model verdict' and seeded a blocklist that was reversed the same
    day."""
    assert "run_kind = comparison_kind(sel_a, sel_b)" in ROUTES
    assert '"comparison_kind": run_kind' in ROUTES


def test_stored_config_carries_the_node_axis():
    for key in ('"node_a"', '"node_b"', '"side_a"', '"side_b"', '"node_a_used"', '"node_b_used"'):
        assert key in ROUTES, key


def test_normalize_side_is_used_so_a_cloud_side_drops_its_node():
    """A provider's hardware is not ours to choose; keeping a node on a cloud
    side would later read as a placement claim never made."""
    assert "normalize_side(model_a, node_a)" in ROUTES
    assert "normalize_side(model_b, node_b)" in ROUTES


# --------------------------------------------------------------------------
# Fleet-wide model list
# --------------------------------------------------------------------------


def test_model_list_is_fleet_wide_not_hub_only():
    assert "node_ollama_models" in ROUTES
    assert "JOIN remote_nodes" in ROUTES


def test_fleet_list_is_additive_and_fails_open():
    """`local`/`cloud` keep their exact shape, and a failed enumeration must
    degrade to the hub-only list rather than break the dropdown."""
    assert '"local": local, "cloud": cloud, "fleet": fleet' in ROUTES
    assert "ab_test_models: fleet enumeration failed" in ROUTES


def test_fleet_list_uses_the_platforms_own_presence_records():
    """Not a per-node Ollama probe: that would be both a second source of truth
    and an inference-path call the dispatcher should own (ADR-013)."""
    assert "is_available" in ROUTES
    assert "r.status = 'online'" in ROUTES
