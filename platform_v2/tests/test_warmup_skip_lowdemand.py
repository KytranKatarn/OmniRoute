"""WARMUP_SKIP keeps single-agent, near-zero-demand models out of the startup warm-up (#6106).

Measured 2026-10-19: the startup warm-up (app._warmup_ollama_models, run by every worker of
every process that imports app) preloaded phi3.5:latest (1 agent, 0 runs/7d) and
qwen2.5-coder:7b (1 agent, 16 runs/7d). Their VRAM left the 7B (21,988 runs/7d) without a card
and the router demoted it to CPU.

`app` runs the warm-up at import time, so it is NOT imported here: the set is read from the
source with `ast`, which also proves the set is the one `_get_agent_models` actually applies.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"


def _warmup_skip() -> set:
    tree = ast.parse(APP.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_get_agent_models")
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "WARMUP_SKIP" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError("WARMUP_SKIP assignment not found inside _get_agent_models")


def test_low_demand_single_agent_models_are_skipped():
    skip = _warmup_skip()
    assert "phi3.5:latest" in skip
    assert "qwen2.5-coder:7b" in skip


def test_the_original_exclusions_are_kept():
    skip = _warmup_skip()
    assert {"qwen2.5vl:7b", "dolphin3:latest"} <= skip


def test_hot_models_are_never_skipped():
    """Guard against over-reach: the demand leaders must keep their warm-up slot."""
    skip = _warmup_skip()
    for hot in ("qwen2.5:7b", "mistral:7b", "qwen2.5:1.5b", "qwen25-classify", "arctic-embed-cpu"):
        assert hot not in skip, f"{hot} is high-demand; skipping it would cold-load the busiest path"


def test_skip_is_applied_to_the_agent_model_loop():
    src = APP.read_text()
    body = src.split("def _get_agent_models", 1)[1].split("def _warmup_ollama_models", 1)[0]
    assert "m not in WARMUP_SKIP" in body
