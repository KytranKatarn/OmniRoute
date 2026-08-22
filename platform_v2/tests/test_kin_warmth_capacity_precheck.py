"""#5947 — kin_warmth must not QUEUE a pin the drain will only reject.

`kin_warmth` raw-INSERTs into `dispatch_pending_queue` with a model + a pinned
node, never calling `dispatch()`. The drain (model_dispatch_service) then gates it
and fails it, burning a claim and a 30s cycle. A producer-side pre-check avoids
that -- but it is an OPTIMISATION, never a replacement for the drain gate (#5809).
"""

import inspect
import pathlib
import re

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "services" / "fleet_jobs.py"


def _src() -> str:
    return _SRC.read_text(encoding="utf-8")


def test_node_query_selects_what_the_predicate_reads():
    """THE BUG THIS ALMOST SHIPPED WITH. `can_node_run_model` reads gpu_available /
    gpu_vram_gb / ram_gb / extra_capabilities. The kin_warmth node query selected
    none of them, so the predicate would have seen gpu 0 + ram 0 + no cap, computed
    `cap = 0.0`, and returned False for EVERY model -- silently killing all fleet
    warm-up. Verified against live data after the fix: outposts admit qwen2.5:1.5b,
    Citadel adds llama3.2:3b, USS-246 admits gemma3:12b, Beacon admits nothing."""
    src = _src()
    head = src[: src.index("array_agg(nom.model_name)")]
    tail = head[head.rindex("SELECT rn.id") :]
    for col in ("gpu_available", "gpu_vram_gb", "ram_gb", "extra_capabilities", "ollama_available"):
        assert f"rn.{col}" in tail, f"kin_warmth node query must select rn.{col}"


def test_precheck_fails_OPEN():
    """A broken import must never starve keep-warm. The drain is authoritative; this
    check is advisory, so any doubt has to resolve to 'queue it anyway'."""
    import sys

    sys.path.insert(0, "/app")
    fj = pytest.importorskip("services.fleet_jobs")
    body = inspect.getsource(fj._node_can_hold)
    assert "return True" in body.split("except")[1], "the except branch must return True"


def test_the_skip_is_counted_and_logged_not_silent():
    """Before this change a bad pin surfaced as a visible queue failure. Skipping it
    silently would HIDE a cap set too low for a node's documented warm set -- the
    cap-4 vs llama3.2:3b (5.0 GB) trap in .claude/rules/fleet.md."""
    src = _src()
    assert "skipped += 1" in src
    assert "queued = rested = skipped = 0" in src
    assert "%d skipped (capacity)" in src


def test_it_continues_rather_than_breaking():
    """`break` would abandon the node's remaining warm targets because ONE model did
    not fit. The pre-existing dedup legitimately breaks; this must not."""
    src = _src()
    seg = src[src.index("if not _node_can_hold(n, model):") :][:900]
    assert "continue" in seg and not re.search(r"\bbreak\b", seg.split("continue")[0])


def test_the_drain_gate_is_still_the_authority():
    """#5809's whole resolution rests on the drain being the choke point. A future
    edit must not 'move' the check here and drop it there."""
    mds = _SRC.parent / "model_dispatch_service.py"
    body = mds.read_text(encoding="utf-8")
    assert "can_node_run_model(node_row, model)" in body
    assert "node_has_model(node_row, model)" in body
