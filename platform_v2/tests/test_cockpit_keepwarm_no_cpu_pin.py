"""The cockpit keep-warm must not CPU-pin a model the cluster keep-warm owns (#7352)."""

from __future__ import annotations

from pathlib import Path

from services.keepwarm_policy import CLUSTER_WARMED_HUB_MODELS, cockpit_cpu_pin_allowed


def _agent_loop() -> str:
    for base in (Path(__file__).resolve().parents[2], Path("/mnt/archie_brain")):
        p = base / "ai_bridge" / "agent_loop.py"
        if p.exists():
            return p.read_text()
    raise FileNotFoundError("ai_bridge/agent_loop.py")


SRC = _agent_loop()
COCKPIT = SRC.split("def _keep_cockpit_model_warm", 1)[1].split("def _keep_forge_review_model_warm", 1)[0]
CLUSTER = SRC.split("def _keep_cluster_models_warm", 1)[1].split("\n    def ", 1)[0]


def test_the_hub_7bs_are_never_cpu_pinned_by_the_cockpit_job():
    assert cockpit_cpu_pin_allowed("qwen2.5:7b") is False  # A.R.C.H.I.E.'s model: the 20:38 EDT stranding
    assert cockpit_cpu_pin_allowed("mistral:7b") is False
    assert cockpit_cpu_pin_allowed("qwen2.5:7b:latest") is False


def test_other_cockpit_models_keep_the_legacy_behaviour():
    assert cockpit_cpu_pin_allowed("llama3.2:3b") is True
    assert cockpit_cpu_pin_allowed("") is True and cockpit_cpu_pin_allowed(None) is True


def test_the_cockpit_job_returns_before_it_builds_the_num_gpu_0_request():
    guard = COCKPIT.index("cockpit_cpu_pin_allowed(model)")
    assert guard < COCKPIT.index('"num_gpu": 0') and guard < COCKPIT.index("req.post(")
    assert "return" in COCKPIT[guard : COCKPIT.index("req.post(")]


def test_every_model_the_policy_protects_really_is_in_the_cluster_keepwarm_registry():
    """The policy constant must not drift from the registry that actually owns these models."""
    for model in CLUSTER_WARMED_HUB_MODELS:
        assert f'"{model}"' in CLUSTER, f"{model} is not warmed by _keep_cluster_models_warm"


# ---- behaviour: run the real method with a stubbed DB and HTTP layer -----------------------------
import contextlib
import importlib
import sys
import types

import pytest


def _run_cockpit_job(monkeypatch, model):
    """Execute AgentLoop._keep_cockpit_model_warm and return the POST bodies it tried to send."""
    posts = []

    class Cur:
        def execute(self, *_a):
            pass

        def fetchone(self):
            return {"model": model}

    @contextlib.contextmanager
    def get_db_cursor(commit=False):
        yield (None, Cur())

    class Resp:
        status_code = 200

    def post(url, json=None, timeout=None):
        posts.append(json)
        return Resp()

    monkeypatch.setitem(sys.modules, "database", types.SimpleNamespace(get_db_cursor=get_db_cursor))
    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(post=post))
    # Use the FIRST layout that has ai_bridge (this checkout, else the container mount): inserting both put the
    # other copy's old code in front. ai_bridge modules import siblings as `from db import ...`.
    base = next(
        b for b in (Path(__file__).resolve().parents[2], Path("/mnt/archie_brain")) if (b / "ai_bridge").exists()
    )
    for entry in (base / "ai_bridge", base):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    for stale in [m for m in sys.modules if m == "ai_bridge" or m.startswith("ai_bridge.")]:
        del sys.modules[stale]  # never reuse a previously imported copy
    try:
        mod = importlib.import_module("ai_bridge.agent_loop")
    except Exception as exc:  # the module needs the platform's runtime deps/DB at import
        pytest.skip(f"ai_bridge.agent_loop is not importable in this environment: {exc}")
    cls = next((getattr(mod, n) for n in dir(mod) if hasattr(getattr(mod, n), "_keep_cockpit_model_warm")), None)
    if cls is None:
        pytest.skip("could not find the class that owns _keep_cockpit_model_warm")
    cls._keep_cockpit_model_warm(object.__new__(cls))
    return posts


def test_behaviour_the_7b_is_not_posted_with_num_gpu_0(monkeypatch):
    assert _run_cockpit_job(monkeypatch, "qwen2.5:7b") == []  # nothing sent: placement stays with the cluster job


def test_behaviour_another_cockpit_model_is_still_cpu_pinned(monkeypatch):
    posts = _run_cockpit_job(monkeypatch, "llama3.2:3b")
    assert len(posts) == 1 and posts[0]["options"]["num_gpu"] == 0
