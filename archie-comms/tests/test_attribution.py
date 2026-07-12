"""Attribution threading (COO Cockpit Slice 4) — the DHQ reply now carries
agent_name + model_used so stream_send_message can put them in the SSE done event
for the cockpit's per-reply ⟨agent · model⟩ badge."""

import services.conversation_service as cs


def test_dhq_reply_returns_agent_and_model(monkeypatch):
    class _R:
        status_code = 200
        content = b"x"

        def json(self):
            return {"success": True, "response": "hi", "agent_name": "A.R.C.H.I.E.", "model_used": "qwen2.5:7b"}

    import requests as _rq

    monkeypatch.setattr(_rq, "post", lambda *a, **k: _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = cs._dhq_chat_reply("sys", "hi", 2)
    assert out["response"] == "hi"
    assert out["agent_name"] == "A.R.C.H.I.E." and out["model_used"] == "qwen2.5:7b"


def test_dhq_reply_none_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    import requests as _rq

    monkeypatch.setattr(_rq, "post", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cs._dhq_chat_reply("sys", "hi", 2) is None
