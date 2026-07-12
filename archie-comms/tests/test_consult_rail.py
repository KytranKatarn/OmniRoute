"""COO consult — the {{CONSULT}} rail (Slice 1). The fast front emits {{CONSULT:<target>}};
it's stripped from the visible reply and the crew member's answer is dispatched via DHQ and
saved as an attributed follow-up (the cockpit's 5s poll renders it) — in her voice."""
import services.conversation_service as cs


def test_consult_marker_regex():
    assert cs._CONSULT_RE.search("On it.\n{{CONSULT:V.I.G.I.L.}}").group(1) == "V.I.G.I.L."
    assert cs._CONSULT_RE.sub("", "Checking.\n{{CONSULT:V.I.G.I.L.}}").strip() == "Checking."
    assert cs._CONSULT_RE.search("plain reply") is None


def test_consult_system_prompt_mentions_marker():
    assert "{{CONSULT:" in cs._CONSULT_SYSTEM_PROMPT


def test_run_consult_saves_attributed_followup(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        cs,
        "_coo_consult",
        lambda target, prompt, user_id: {
            "success": True,
            "response": "Firewall is clean.",
            "agent_name": "V.I.G.I.L.",
            "model_used": "qwen2.5:7b",
        },
    )
    monkeypatch.setattr(
        cs,
        "save_message",
        lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content, meta=meta or {}),
    )
    cs._run_consult(42, "web", "V.I.G.I.L.", "firewall?", 4)
    assert "V.I.G.I.L." in saved["content"] and "Firewall is clean." in saved["content"]
    assert saved["meta"].get("consult") is True and saved["meta"].get("agent") == "V.I.G.I.L."


def test_run_consult_failsoft(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_coo_consult", lambda *a, **k: None)
    monkeypatch.setattr(
        cs, "save_message", lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content)
    )
    cs._run_consult(42, "web", "V.I.G.I.L.", "q", 4)
    assert "couldn" in saved["content"].lower() or "reach" in saved["content"].lower()
