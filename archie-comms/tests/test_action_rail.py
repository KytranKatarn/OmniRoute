"""COO action — the {{ACTION}} rail (Slice 4). The fast front emits {{ACTION:<key>}} for a
curated SAFE diagnostic; it's stripped from the visible reply and the tool is run on the
platform, its result saved as a follow-up (the cockpit's 5s poll renders it) — in her voice."""
import services.conversation_service as cs


def test_action_marker_regex():
    assert cs._ACTION_RE.search("Running it.\n{{ACTION:health}}").group(1) == "health"
    assert cs._ACTION_RE.sub("", "Running.\n{{ACTION:qa}}").strip() == "Running."
    assert cs._ACTION_RE.search("plain reply") is None


def test_action_system_prompt_mentions_marker_and_keys():
    assert "{{ACTION:" in cs._ACTION_SYSTEM_PROMPT
    # the curated safe keys must be named so the model only emits those
    for key in ("health", "qa", "dep_drift", "misroute_audit", "briefing_health"):
        assert key in cs._ACTION_SYSTEM_PROMPT


def test_run_action_saves_result_followup(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        cs,
        "_coo_run_action",
        lambda key: {"ok": True, "label": "Platform health", "summary": "All green.", "result": {"ok": 1}},
    )
    monkeypatch.setattr(
        cs,
        "save_message",
        lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content, meta=meta or {}),
    )
    cs._run_action(42, "web", "health", 4)
    assert "Platform health" in saved["content"] and "All green." in saved["content"]
    assert saved["meta"].get("action") is True and saved["meta"].get("action_key") == "health"


def test_run_action_failsoft(monkeypatch):
    saved = {}
    monkeypatch.setattr(cs, "_coo_run_action", lambda *a, **k: {"ok": False, "error": "unreachable"})
    monkeypatch.setattr(
        cs, "save_message", lambda conv, ch, direction, sender, content, meta=None: saved.update(content=content)
    )
    cs._run_action(42, "web", "health", 4)
    assert "couldn" in saved["content"].lower()
