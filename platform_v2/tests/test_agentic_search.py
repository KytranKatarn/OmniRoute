"""Unit tests for ai_bridge.agentic_search.run_tool_loop (#3534 Phases 1-2).

run_tool_loop is the agentic-retrieval execution primitive invoked by
tools.department_hq.services.department_dispatcher.request_work(). These tests
stub the HTTP layer and services.rag_service so the bounded multi-tool loop is
verified without a live model or DB.
"""

import os
import sys
import types

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


def _patch_rag(monkeypatch, results, record=None):
    """Inject a fake services.rag_service so _execute_kb_tool resolves here.

    Avoids importing the real module. `record` (if a list) captures the
    knowledge_types each tool call passes, to assert routing.
    """

    def fake_search(query, limit=10, knowledge_types=None, min_importance=0.0):
        if record is not None:
            record.append(knowledge_types)
        return results

    fake = types.ModuleType("services.rag_service")
    fake.search_knowledge = fake_search
    monkeypatch.setitem(sys.modules, "services.rag_service", fake)


def _hit(id=1, title="t", content="c", ktype="vault_note", similarity=0.8):
    return {"id": id, "title": title, "content": content, "knowledge_type": ktype, "similarity": similarity}


def _tool_msg(name, query, limit=None):
    args = {"query": query}
    if limit is not None:
        args["limit"] = limit
    return FakeResp(
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}
    )


def test_tool_call_then_answer(monkeypatch):
    """Model issues a search_knowledge call, reads results, then answers."""
    _patch_rag(monkeypatch, [_hit(263641, "Cluster Architecture", "Hub mesh IP 100.64.0.4", "vault_note", 0.91)])
    responses = [
        _tool_msg("search_knowledge", "cluster architecture", 3),
        FakeResp({"role": "assistant", "content": "The hub uses mesh IP 100.64.0.4."}),
    ]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "what is the cluster architecture?", agent_name="D.A.R.W.I.N.")
    assert out["success"] is True
    assert out["used_tools"] is True
    assert out["tool_calls"] == 1
    assert out["tool_queries"] == [{"tool": "search_knowledge", "query": "cluster architecture"}]
    assert "100.64.0.4" in out["response"]


def test_search_mistakes_routes_to_mistake_type(monkeypatch):
    """search_mistakes filters knowledge_types to mistake_learned."""
    record = []
    _patch_rag(monkeypatch, [_hit(ktype="mistake_learned")], record=record)
    responses = [_tool_msg("search_mistakes", "deploy errors"), FakeResp({"role": "assistant", "content": "ok"})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "q", agent_name="D.A.R.W.I.N.")
    assert out["tool_queries"] == [{"tool": "search_mistakes", "query": "deploy errors"}]
    assert record == [["mistake_learned"]]


def test_recall_context_routes_to_vault_and_memory(monkeypatch):
    """recall_context filters knowledge_types to vault_note + conversation_memory."""
    record = []
    _patch_rag(monkeypatch, [_hit(ktype="vault_note")], record=record)
    responses = [_tool_msg("recall_context", "prior decisions"), FakeResp({"role": "assistant", "content": "ok"})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "q", agent_name="S.P.E.C.T.R.A.")
    assert out["tool_queries"] == [{"tool": "recall_context", "query": "prior decisions"}]
    assert record == [["vault_note", "conversation_memory"]]


def test_no_tool_call_signals_fallback(monkeypatch):
    """Model answers directly without a tool call -> used_tools False (caller falls back to RAG)."""
    _patch_rag(monkeypatch, [])
    responses = [FakeResp({"role": "assistant", "content": "I already know this."})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "trivial question", agent_name="D.A.R.W.I.N.")
    assert out["used_tools"] is False
    assert out["tool_calls"] == 0


def test_http_error_returns_fallback(monkeypatch):
    """An HTTP error returns success=False so the caller falls back, never raises."""
    _patch_rag(monkeypatch, [])
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence([FakeResp({}, status_ok=False)]))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "anything", agent_name="D.A.R.W.I.N.")
    assert out["success"] is False
    assert out["used_tools"] is False
    assert out["error"]


def test_iteration_cap_forces_final_answer(monkeypatch):
    """If the model keeps tool-calling, the loop caps iterations then forces an answer."""
    _patch_rag(monkeypatch, [_hit()])
    tool_resp = _tool_msg("search_knowledge", "more")
    responses = [tool_resp, tool_resp, tool_resp, FakeResp({"role": "assistant", "content": "final synthesis"})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "deep q", agent_name="D.A.R.W.I.N.", max_iterations=3)
    assert out["used_tools"] is True
    assert out["tool_calls"] == 3
    assert out["response"] == "final synthesis"


def test_unknown_tool_name_falls_back_to_search_knowledge(monkeypatch):
    """A tool name outside the registry is treated as search_knowledge (all types)."""
    record = []
    _patch_rag(monkeypatch, [_hit()], record=record)
    responses = [_tool_msg("some_bogus_tool", "q"), FakeResp({"role": "assistant", "content": "ok"})]
    monkeypatch.setattr(ag.requests, "post", _fake_post_sequence(responses))

    out = ag.run_tool_loop("qwen2.5:7b", "sys", "q", agent_name="D.A.R.W.I.N.")
    assert out["tool_queries"] == [{"tool": "search_knowledge", "query": "q"}]
    assert record == [None]  # search_knowledge -> knowledge_types None (all types)


def test_is_tool_capable_model():
    assert ag.is_tool_capable_model("qwen2.5:7b") is True
    assert ag.is_tool_capable_model("mistral:7b") is True
    assert ag.is_tool_capable_model("qwen2.5:1.5b") is False
    assert ag.is_tool_capable_model("llama3.2:3b") is False
    assert ag.is_tool_capable_model(None) is False


def test_string_arguments_parsed(monkeypatch):
    """Some models return tool arguments as a JSON string -> still parsed."""
    _patch_rag(monkeypatch, [_hit()])
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
    assert out["tool_queries"] == [{"tool": "search_knowledge", "query": "json-encoded args"}]
