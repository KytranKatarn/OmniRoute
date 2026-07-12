"""Cockpit chat routing — fast conversational front on a fleet GPU node.

The interactive cockpit chat (A.R.C.H.I.E., no caller-pinned model) routes to
Starship-246's GPU with a fast GPU-resident model (llama3.2:3b) + hub fallback,
keeping its high-priority lane. Service callers that pin a model/agent (e.g. the
engine plan step) are untouched. A.R.C.H.I.E. the working agent stays qwen2.5:7b.
"""


class _Result:
    success = True
    response = "ok"
    agent_name = "A.R.C.H.I.E."
    model_used = "llama3.2:3b"


def _patch_dispatch(monkeypatch):
    seen = {}
    import tools.department_hq.services.department_dispatcher as dd

    def fake_dispatch(**kwargs):
        seen.update(kwargs)
        return _Result()

    monkeypatch.setattr(dd, "dispatch", fake_dispatch)
    return seen


def test_cockpit_chat_routes_to_node_gpu(client, monkeypatch):
    seen = _patch_dispatch(monkeypatch)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post("/api/internal/dhq/chat", json={"prompt": "hi"}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    assert seen["model_override"] == "llama3.2:3b"
    assert seen["preferred_node"] == ["starship_76583490e36955ab", "archie-starbase"]
    assert seen["priority"] == "high"
    assert seen["prefer_agent"] == "A.R.C.H.I.E."


def test_service_caller_untouched(client, monkeypatch):
    seen = _patch_dispatch(monkeypatch)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    # Engine plan step pins its own model + agent -> must NOT be node/model-rerouted.
    r = client.post(
        "/api/internal/dhq/chat",
        json={"prompt": "code this", "prefer_agent": "F.O.R.G.E.", "model": "qwen2.5-coder:7b", "capability": "code"},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    assert seen["model_override"] == "qwen2.5-coder:7b"
    assert seen["preferred_node"] is None
    assert seen["priority"] == "normal"


def test_deepen_follow_up_7b_routes_to_node(client, monkeypatch):
    # The {{DEEPEN}} follow-up: A.R.C.H.I.E. conversation pinned to qwen2.5:7b -> the node
    # GPU (hub fallback) at NORMAL priority (async, not the interactive fast lane).
    seen = _patch_dispatch(monkeypatch)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    r = client.post(
        "/api/internal/dhq/chat",
        json={"prompt": "deep q", "prefer_agent": "A.R.C.H.I.E.", "model": "qwen2.5:7b", "capability": "conversation"},
        headers={"Authorization": "Bearer k"},
    )
    assert r.status_code == 200
    assert seen["model_override"] == "qwen2.5:7b"
    assert seen["preferred_node"] == ["starship_76583490e36955ab", "archie-starbase"]
    assert seen["priority"] == "normal"


def test_cockpit_chat_model_is_env_tunable(client, monkeypatch):
    seen = _patch_dispatch(monkeypatch)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("COCKPIT_CHAT_MODEL", "qwen2.5:1.5b")
    r = client.post("/api/internal/dhq/chat", json={"prompt": "hi"}, headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    assert seen["model_override"] == "qwen2.5:1.5b"
    assert seen["preferred_node"] == ["starship_76583490e36955ab", "archie-starbase"]
