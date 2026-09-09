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


def test_hub_stream_posts_to_generate_endpoint_not_bare_base(monkeypatch):
    """Regression for the #6654 streaming 405.

    ``get_ollama_url`` returns a BASE url with no path; the blocking
    ``call_ollama`` appends the generate endpoint itself, so the hub
    streaming branch must too. A bare-base POST hits Ollama's root and
    comes back HTTP 405 (0 tokens). The node branch already includes the
    path — this pins the hub branch. The pre-fix tests mocked the POST
    without ever asserting the URL, which is why the bug shipped.
    """
    disp = dd.DepartmentDispatcher()
    order = []
    _base_patches(monkeypatch, disp, order)  # get_ollama_url -> base, no path

    captured = {}
    import requests

    def _cap(url, *a, **k):
        captured["url"] = url
        return _FakeStreamResp(_fake_ollama_lines())

    monkeypatch.setattr(requests, "post", _cap)

    events = list(
        disp._execute_llm_stream(
            model="qwen2.5:7b",
            prompt="hi",
            capability="conversation",
            module_id="archie_comms",
        )
    )
    assert [e for e in events if e.get("type") == "token"], "hub path yielded no tokens"
    assert "url" in captured, "hub path never POSTed to Ollama"
    _endpoint = "/api/" + "generate"
    assert captured["url"].endswith(_endpoint), f"hub POST must target the generate endpoint, got {captured['url']!r}"
    assert captured["url"] != "http://hub:11434", "hub POST went to the bare base (the 405 bug)"


# ---------------------------------------------------------------------------
# stream_work mid-stream hub fallback (#6660) — a preferred node that errors
# BEFORE the first token falls back to the hub (when the caller named it),
# instead of stranding the stream. Once a token streams we never fall back.
# ---------------------------------------------------------------------------


class _R:
    def __init__(self, success=True, provider="ollama", model="qwen2.5:7b"):
        self.success = success
        self.provider = provider
        self.model_used = model
        self.department = None
        self.agent_id = None
        self.duration_ms = 1000
        self.prompt_tokens = 1
        self.completion_tokens = 1
        self.metadata = {"stream": True}


class _StubCoord:
    def resolve_department(self, capability):
        return "Engineering & Technology"

    def select_agent(self, capability, department):
        return None  # no cache in the test -> default model path


def _wire_stream_work(monkeypatch, disp, *, node_fail_pretoken):
    """Script _execute_llm_stream per target + mock node resolution + logging."""
    monkeypatch.setattr(dd, "get_dept_coordinator", lambda: _StubCoord())
    monkeypatch.setattr(disp, "_get_db", lambda: _FakeConn())  # node row resolves
    monkeypatch.setattr(
        disp,
        "_get_fleet_node_for_dispatch",
        lambda *a, **k: {
            "node_hostname": "100.64.0.3",
            "node_port": 11434,
            "node_id": "starship_x",
            "node_name": "Starship - Defiant",
            "agent_name": "R.E.S.O.L.V.E.",
            "model": "qwen2.5:7b",
        },
    )
    logged = []
    monkeypatch.setattr(disp, "_log_execution", lambda res, *a, **k: logged.append(res))
    monkeypatch.setattr(disp, "_update_agent_welfare", lambda *a, **k: None)

    def _exec(**kw):
        if kw.get("node_url"):
            disp._last_stream_result = _R(success=False, provider="fleet_node")
            if node_fail_pretoken:
                yield {"type": "error", "code": "dispatch_failed", "message": "timeout"}
                return
            yield {"type": "token", "content": "N"}
            yield {"type": "done", "_result": _R(True, "fleet_node"), "streamed": True}
        else:
            disp._last_stream_result = _R(success=True, provider="ollama")
            yield {"type": "token", "content": "H"}
            yield {"type": "done", "_result": _R(True, "ollama"), "streamed": True}

    monkeypatch.setattr(disp, "_execute_llm_stream", _exec)
    return logged


def _run_stream_work(disp, preferred_node):
    return list(
        disp.stream_work(
            capability="conversation",
            prompt="hi",
            module_id="archie_comms",
            prefer_agent=None,
            preferred_node=preferred_node,
        )
    )


def test_stream_work_falls_back_to_hub_when_node_errors_pretoken(monkeypatch):
    disp = dd.DepartmentDispatcher()
    logged = _wire_stream_work(monkeypatch, disp, node_fail_pretoken=True)
    evts = _run_stream_work(disp, ["starship_x", "archie-starbase"])
    metas = [e for e in evts if e.get("type") == "meta"]
    toks = "".join(e.get("content", "") for e in evts if e.get("type") == "token")
    errs = [e for e in evts if e.get("type") == "error"]
    assert len(metas) == 2, "expected node meta then hub meta"
    assert metas[0]["provider"] == "fleet_node" and metas[1]["provider"] == "ollama"
    assert toks == "H", "hub tokens should reach the client; the failed node's do not"
    assert not errs, "fallback is transparent — no error surfaced to the client"
    assert len(logged) == 1 and logged[0].success is True and logged[0].provider == "ollama"


def test_stream_work_commits_to_node_once_a_token_streams(monkeypatch):
    disp = dd.DepartmentDispatcher()
    logged = _wire_stream_work(monkeypatch, disp, node_fail_pretoken=False)
    evts = _run_stream_work(disp, ["starship_x", "archie-starbase"])
    metas = [e for e in evts if e.get("type") == "meta"]
    toks = "".join(e.get("content", "") for e in evts if e.get("type") == "token")
    assert len(metas) == 1 and metas[0]["provider"] == "fleet_node", "no fallback once streaming"
    assert toks == "N"
    assert len(logged) == 1 and logged[0].provider == "fleet_node"


def test_stream_work_surfaces_error_when_no_hub_fallback_named(monkeypatch):
    disp = dd.DepartmentDispatcher()
    logged = _wire_stream_work(monkeypatch, disp, node_fail_pretoken=True)
    evts = _run_stream_work(disp, ["starship_x"])  # hub NOT named -> no fallback
    metas = [e for e in evts if e.get("type") == "meta"]
    errs = [e for e in evts if e.get("type") == "error"]
    assert len(metas) == 1, "only the node target; caller did not name the hub"
    assert errs, "the node error must be surfaced when there is no fallback"
    assert len(logged) == 1 and logged[0].success is False
