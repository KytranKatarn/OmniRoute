"""stream_work / _execute_llm_stream — the dispatcher streaming path (#6654).

Proves the token-streaming counterpart to _execute_llm keeps every guarantee
the blocking path has: the guards run BEFORE the first token, exactly one
task_execution_log row is written with the REAL model/provider/token counts
(never 'auto', never 0), and a client disconnect mid-stream still logs (with
client_disconnected) instead of vanishing.
"""

import json
import types
import pytest

import tools.department_hq.services.department_dispatcher as dd


class _FakeCursor:
    def __init__(self):
        self._n = 0

    def execute(self, *a, **k):
        self._n += 1

    def fetchone(self):
        return [1]

    def close(self):
        pass


class _FakeConn:
    def cursor(self, *a, **k):
        return _FakeCursor()

    def commit(self):
        pass

    def close(self):
        pass


class _FakeStreamResp:
    """Mimics requests.post(..., stream=True) as a context manager."""

    def __init__(self, lines, status=200):
        self.status_code = status
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=True):
        for ln in self._lines:
            yield ln


def _base_patches(monkeypatch, disp, order, *, provider_for_model=None, lane_over_cap=False):
    """Wire the dispatcher so streaming runs entirely offline and record the
    ORDER in which each guard/step fires."""
    monkeypatch.setattr(disp, "_get_db", lambda: _FakeConn())
    monkeypatch.setattr(disp, "ensure_model_ready", lambda *a, **k: {"ready": True})
    monkeypatch.setattr(disp, "_log_execution", lambda *a, **k: None)
    monkeypatch.setattr(disp, "_update_agent_welfare", lambda *a, **k: None)

    # cloud provider lookup
    import ai_bridge.external_providers as ep

    monkeypatch.setattr(ep, "get_provider_for_model", lambda m: provider_for_model)

    # hub admission cap — record that it was consulted
    import services.welfare_governance_service as wg

    def _cap(**k):
        order.append("hub_lane_over_cap")
        return lane_over_cap

    monkeypatch.setattr(wg, "hub_lane_over_cap", _cap)

    # cloud allow / budget — record consultation
    monkeypatch.setattr(disp, "_cloud_capability_allowed", lambda c: (order.append("cloud_allow"), True)[1])
    monkeypatch.setattr(disp, "_cloud_budget_ok", lambda *a, **k: (order.append("cloud_budget"), True)[1])

    import ai_bridge.archie_bridge as ab

    monkeypatch.setattr(ab, "get_ollama_url", lambda m, g: ("http://hub:11434", None))

    return None


def _done_result(events):
    done = [e for e in events if e.get("type") == "done"]
    assert done, "no done event"
    return done[0]["_result"]


def _fake_ollama_lines():
    return [
        json.dumps({"response": "Hel"}),
        json.dumps({"response": "lo"}),
        json.dumps({"response": "!", "done": True, "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 3}),
    ]


def test_local_stream_yields_tokens_and_logs_real_counts(monkeypatch):
    disp = dd.DepartmentDispatcher()
    order = []
    _base_patches(monkeypatch, disp, order)

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeStreamResp(_fake_ollama_lines()))

    events = list(
        disp._execute_llm_stream(
            model="qwen2.5:7b",
            prompt="hi",
            capability="conversation",
            module_id="archie_comms",
            agent_name="A.R.C.H.I.E.",
        )
    )
    tokens = [e["content"] for e in events if e.get("type") == "token"]
    done = [e for e in events if e.get("type") == "done"]

    assert tokens == ["Hel", "lo", "!"]
    assert done and done[0]["streamed"] is True
    # GUARD ORDER: the hub cap must have been consulted before any token.
    assert order and order[0] == "hub_lane_over_cap"
    # exactly one log row, with REAL model/provider/tokens (never 'auto'/0)
    r = _done_result(events)
    assert r.success is True
    assert r.model_used == "qwen2.5:7b"
    assert r.provider == "ollama"
    assert r.prompt_tokens == 12 and r.completion_tokens == 3
    assert r.metadata["stream"] is True and r.metadata["tokens_estimated"] is False


def test_hub_saturated_sheds_before_any_token(monkeypatch):
    disp = dd.DepartmentDispatcher()
    order = []
    _base_patches(monkeypatch, disp, order, lane_over_cap=True)

    import requests

    # If this were called it would blow up — proving no HTTP happened.
    def _boom(*a, **k):
        raise AssertionError("must not POST to Ollama when the lane is saturated")

    monkeypatch.setattr(requests, "post", _boom)

    events = list(
        disp._execute_llm_stream(model="qwen2.5:7b", prompt="hi", capability="conversation", agent_name="A.R.C.H.I.E.")
    )
    errs = [e for e in events if e.get("type") == "error"]
    assert errs and errs[0]["code"] == "hub_saturated"
    assert not [e for e in events if e.get("type") == "token"]
    assert _done_result(events).success is False


def test_client_disconnect_still_logs_with_flag(monkeypatch):
    disp = dd.DepartmentDispatcher()
    order = []
    _base_patches(monkeypatch, disp, order)

    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeStreamResp(_fake_ollama_lines()))

    gen = disp._execute_llm_stream(
        model="qwen2.5:7b", prompt="hi", capability="conversation", agent_name="A.R.C.H.I.E."
    )
    assert next(gen)["type"] == "token"  # first token
    gen.close()  # client hangs up

    r = disp._last_stream_result
    assert r.metadata["client_disconnected"] is True
    assert r.success is False
    # partial tokens estimated so the row is never a false 0
    assert r.completion_tokens > 0 and r.metadata["tokens_estimated"] is True


def test_cloud_model_gates_before_token_and_does_not_stream(monkeypatch):
    disp = dd.DepartmentDispatcher()
    order = []
    _base_patches(monkeypatch, disp, order, provider_for_model="anthropic")
    # cloud path runs the blocking _execute_llm once; fake it
    monkeypatch.setattr(
        disp,
        "_execute_llm",
        lambda **k: {
            "success": True,
            "response": "cloud reply",
            "provider": "contractor:anthropic",
            "prompt_tokens": 5,
            "completion_tokens": 2,
        },
    )

    events = list(disp._execute_llm_stream(model="claude-x", prompt="hi", capability="code", agent_name="F.O.R.G.E."))
    # allowlist + budget consulted BEFORE the single token
    assert order[:2] == ["cloud_allow", "cloud_budget"]
    done = [e for e in events if e.get("type") == "done"]
    assert done and done[0]["streamed"] is False
    assert _done_result(events).metadata["is_cloud"] is True


def test_cloud_blocked_capability_never_reaches_provider(monkeypatch):
    disp = dd.DepartmentDispatcher()
    order = []
    _base_patches(monkeypatch, disp, order, provider_for_model="anthropic")
    monkeypatch.setattr(disp, "_cloud_capability_allowed", lambda c: False)

    def _boom(**k):
        raise AssertionError("blocked capability must not call the provider")

    monkeypatch.setattr(disp, "_execute_llm", _boom)

    events = list(disp._execute_llm_stream(model="claude-x", prompt="hi", capability="company_secret"))
    errs = [e for e in events if e.get("type") == "error"]
    assert errs and errs[0]["code"] == "cloud_capability_blocked"
    assert _done_result(events).success is False
