"""/api/internal/dhq/chat/stream — the SSE cockpit-streaming route (#6654).

The route must (a) require the dhq:chat scope like its blocking sibling and
(b) relay the dispatcher's token/done events as Server-Sent Events. The
dispatcher itself is faked here (its own guard/log behaviour is covered by
test_dispatcher_stream_work.py); this pins the HTTP contract.
"""

import json
import tools.department_hq.services.department_dispatcher as dd


def _fake_stream(**kwargs):
    yield {"type": "meta", "agent_name": "A.R.C.H.I.E.", "model": "llama3.2:3b", "provider": "fleet_node"}
    yield {"type": "token", "content": "Hel"}
    yield {"type": "token", "content": "lo"}
    yield {
        "type": "done",
        "model_used": "llama3.2:3b",
        "agent_name": "A.R.C.H.I.E.",
        "provider": "fleet_node",
        "completion_tokens": 2,
        "duration_ms": 40,
        "streamed": True,
    }


def _parse_sse(body):
    return [json.loads(ln[len("data: ") :]) for ln in body.splitlines() if ln.startswith("data: ")]


def test_stream_relays_tokens_and_done(client, monkeypatch):
    monkeypatch.setattr(dd, "stream_dispatch", _fake_stream)
    monkeypatch.setenv("INTERNAL_API_KEY_ARCHIE_COMMS", "comms-key")
    r = client.post(
        "/api/internal/dhq/chat/stream",
        json={"prompt": "hi"},
        headers={"Authorization": "Bearer comms-key"},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("Content-Type", "")
    events = _parse_sse(r.get_data(as_text=True))
    tokens = [e["content"] for e in events if e.get("type") == "token"]
    done = [e for e in events if e.get("type") == "done"]
    assert tokens == ["Hel", "lo"]
    assert done and done[0]["model_used"] == "llama3.2:3b" and done[0]["completion_tokens"] == 2


def test_stream_requires_dhq_chat_scope(client, monkeypatch):
    monkeypatch.setattr(dd, "stream_dispatch", _fake_stream)
    # browser caller has only the `sessions` scope — must be refused 403.
    monkeypatch.setenv("INTERNAL_API_KEY_BROWSER", "browser-key")
    r = client.post(
        "/api/internal/dhq/chat/stream",
        json={"prompt": "hi"},
        headers={"Authorization": "Bearer browser-key"},
    )
    assert r.status_code == 403
    assert r.get_json().get("required") == "dhq:chat"


def test_stream_no_key_is_401(client):
    r = client.post("/api/internal/dhq/chat/stream", json={"prompt": "hi"})
    assert r.status_code == 401


def test_stream_empty_prompt_is_400(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY_ARCHIE_COMMS", "comms-key")
    r = client.post(
        "/api/internal/dhq/chat/stream",
        json={"prompt": "  "},
        headers={"Authorization": "Bearer comms-key"},
    )
    assert r.status_code == 400
