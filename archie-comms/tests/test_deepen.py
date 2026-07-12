"""Responsive-chat {{DEEPEN}} follow-up (piece 2).

The fast front emits {{DEEPEN}} for substantive asks; it's stripped from the visible
reply and A.R.C.H.I.E.'s full 7B answers the same question in the background, saved as a
new follow-up message (the cockpit's 5s poll renders it)."""

import services.conversation_service as cs


def test_deepen_marker_stripped():
    assert cs._DEEPEN_RE.sub("", "Digging into that now.\n{{DEEPEN}}").strip() == "Digging into that now."
    assert bool(cs._DEEPEN_RE.search("plain conversational reply")) is False
    assert bool(cs._DEEPEN_RE.search("On it — one moment.\n{{DEEPEN}}")) is True


def test_deepen_prompts():
    # the fast front is told to emit the marker; the deep-answer prompt forbids markers
    assert "{{DEEPEN}}" in cs._DEEPEN_SYSTEM_PROMPT
    assert "NOT use any" in cs._DEEPEN_ANSWER_PROMPT


def test_deepen_reply_uses_full_7b(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"success": True, "response": "Here is the deep answer.", "model_used": "qwen2.5:7b"}

    import requests as _rq

    monkeypatch.setattr(
        _rq, "post", lambda url, json=None, headers=None, timeout=None: seen.update(json=json) or _R()
    )
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = cs._deepen_reply("sys", "question", 4)
    assert out == "Here is the deep answer."
    assert seen["json"]["model"] == "qwen2.5:7b"  # her full working brain, not the fast front


def test_deepen_reply_none_on_failure(monkeypatch):
    import requests as _rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(_rq, "post", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert cs._deepen_reply("sys", "q", 4) is None


def test_run_deepen_saves_followup(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_deepen_reply", lambda s, u, uid: "The deeper answer.")
    monkeypatch.setattr(
        cs, "save_message",
        lambda conv, ch, direction, sender, content, meta=None: saved.update(
            content=content, meta=meta or {}, direction=direction
        ),
    )
    cs._run_deepen(42, "web", "sys", "q", 4)
    assert saved["content"] == "The deeper answer."
    assert saved["direction"] == "outbound" and saved["meta"].get("deepen") is True


def test_run_deepen_no_save_when_no_answer(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_deepen_reply", lambda s, u, uid: None)
    monkeypatch.setattr(cs, "save_message", lambda *a, **k: saved.update(called=True))
    cs._run_deepen(42, "web", "sys", "q", 4)
    assert "called" not in saved
