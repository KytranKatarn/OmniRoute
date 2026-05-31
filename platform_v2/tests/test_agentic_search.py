"""Unit tests for ai_bridge.agentic_search.run_tool_loop (#3534 Phase 1).

run_tool_loop is the agentic-retrieval execution primitive invoked by
tools.department_hq.services.department_dispatcher.request_work(). These tests
stub the HTTP layer and semantic_search so the bounded tool-calling loop is
verified without a live model or DB.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root for ai_bridge
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ai_bridge.agentic_search as ag


class FakeResp:
    def __init__(self, message, status_ok=True):
        self._message = message
        self._ok = status_ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP 500")

    def json(self):
        return {"message": self._message}


def _fake_post_sequence(responses):
    """Return a stub that yields the given responses in order."""
    seq = list(responses)

    def _post(url, json=None, timeout=None):
        return seq.pop(0)

    return _post


def _patch_search(monkeypatch, results):
    # Inject a fake module so run_tool_loop's lazy
    # `from ai_bridge.semantic_search import search` resolves here — avoids
    # importing the real module (which eagerly does `from db import get_db`).
    import types

    fake = types.ModuleType("ai_bridge.semantic_search")
    fake.search = lambda q, limit=5: results
    monkeypatch.setitem(sys.modules, "ai_bridge.semantic_search", fake)


class _R:
    def __init__(self, id, title, content, score):
        self.id, self.title, self.content, self.score = id, title, content, score


def test_tool_call_then_answer(monkeypatch):
    """Model issues a search call, reads results, then answers."""
    _patch_search(monkeypatch, [_R(263641, "Cluster Architecture", "Hub mesh IP 100.64.0.4", 0.91)])
    responses = [
        FakeResp(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_knowledge",
                            "arguments": {"query": "cluster architecture", "limit": 3},
                        }
                    }
                ],
            }
        ),
        FakeResp({"role": "assistant", "content": "The hub uses mesh IP 100.64.0.4."}),
    ]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "what is the cluster architecture?", agent_name="D.A.R.W.I.N.")
    assert out["success"] is True
    assert out["used_tools"] is True
    assert out["tool_calls"] == 1
    assert out["tool_queries"] == ["cluster architecture"]
    assert "100.64.0.4" in out["response"]


def test_no_tool_call_signals_fallback(monkeypatch):
    """Model answers directly without a tool call -> used_tools False (caller falls back to RAG)."""
    _patch_search(monkeypatch, [])
    responses = [FakeResp({"role": "assistant", "content": "I already know this."})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "trivial question", agent_name="D.A.R.W.I.N.")
    assert out["used_tools"] is False
    assert out["tool_calls"] == 0


def test_http_error_returns_fallback(monkeypatch):
    """An HTTP error returns success=False so the caller falls back, never raises."""
    _patch_search(monkeypatch, [])
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence([FakeResp({}, status_ok=False)]))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "anything", agent_name="D.A.R.W.I.N.")
    assert out["success"] is False
    assert out["used_tools"] is False
    assert out["error"]


def test_iteration_cap_forces_final_answer(monkeypatch):
    """If the model keeps tool-calling, the loop caps iterations then forces an answer."""
    _patch_search(monkeypatch, [_R(1, "t", "c", 0.8)])
    tool_resp = FakeResp(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "search_knowledge", "arguments": {"query": "more"}}}],
        }
    )
    responses = [tool_resp, tool_resp, tool_resp, FakeResp({"role": "assistant", "content": "final synthesis"})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "deep q", agent_name="D.A.R.W.I.N.", max_iterations=3)
    assert out["used_tools"] is True
    assert out["tool_calls"] == 3
    assert out["response"] == "final synthesis"


def test_is_tool_capable_model():
    assert ag.is_tool_capable_model("qwen2.5:7b") is True
    assert ag.is_tool_capable_model("mistral:7b") is True
    assert ag.is_tool_capable_model("qwen2.5:1.5b") is False
    assert ag.is_tool_capable_model("llama3.2:3b") is False
    assert ag.is_tool_capable_model(None) is False


def test_string_arguments_parsed(monkeypatch):
    """Some models return tool arguments as a JSON string -> still parsed."""
    _patch_search(monkeypatch, [_R(1, "t", "c", 0.8)])
    responses = [
        FakeResp(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "search_knowledge", "arguments": '{"query": "json-encoded args"}'}}
                ],
            }
        ),
        FakeResp({"role": "assistant", "content": "done"}),
    ]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "q", agent_name="D.A.R.W.I.N.")
    assert out["tool_queries"] == ["json-encoded args"]
