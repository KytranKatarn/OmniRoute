"""Hermetic tests for chronicle_story_service (slice 09). No DB, no real dispatch."""

from datetime import datetime

import services.chronicle_story_service as S


class R:
    """Fake dispatch result."""

    def __init__(self, success, response="", model=None):
        self.success = success
        self.response = response
        self.model = model


def test_build_prompt():
    prompt = S._build_prompt("Terry", "person", ["[2026-01-01] hi — body"])
    assert "Terry (person)" in prompt
    assert "[2026-01-01] hi — body" in prompt


def test_run_writes_story(monkeypatch):
    monkeypatch.setattr(
        S, "_fetch_candidates", lambda o, l: [{"id": 9, "canonical_name": "Terry", "entity_type": "person"}]
    )
    monkeypatch.setattr(
        S,
        "_fetch_entity_emails",
        lambda i: [
            {"sent_at": datetime(2026, 1, 1), "subject": "a", "body_text": "x", "source_kind": "gmail"},
            {"sent_at": datetime(2026, 2, 1), "subject": "b", "body_text": "y", "source_kind": "linkedin"},
        ],
    )

    dispatch_calls = []

    def fake_dispatch(**kw):
        dispatch_calls.append(kw)
        return R(True, "the arc", "qwen2.5:7b")

    monkeypatch.setattr(S, "_dispatch_fn", lambda: fake_dispatch)

    write_calls = []
    monkeypatch.setattr(
        S,
        "_write_story",
        lambda *args: write_calls.append(args),
    )

    result = S.run_entity_stories(4)

    assert result == {"stories": 1, "deferred": False}
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0]["capability"] == "summarize"
    assert dispatch_calls[0]["local_only"] is True
    assert "Terry" in dispatch_calls[0]["prompt"]

    assert len(write_calls) == 1
    entity_id, narrative, span_start, span_end, source_kinds, email_count, model_used = write_calls[0]
    assert entity_id == 9
    assert narrative == "the arc"
    assert source_kinds == {"gmail", "linkedin"}
    assert email_count == 2
    assert model_used == "qwen2.5:7b"
    assert span_start == datetime(2026, 1, 1)
    assert span_end == datetime(2026, 2, 1)


def test_run_defers_on_cold(monkeypatch):
    monkeypatch.setattr(
        S, "_fetch_candidates", lambda o, l: [{"id": 9, "canonical_name": "Terry", "entity_type": "person"}]
    )
    monkeypatch.setattr(
        S,
        "_fetch_entity_emails",
        lambda i: [
            {"sent_at": datetime(2026, 1, 1), "subject": "a", "body_text": "x", "source_kind": "gmail"},
            {"sent_at": datetime(2026, 2, 1), "subject": "b", "body_text": "y", "source_kind": "linkedin"},
        ],
    )
    monkeypatch.setattr(S, "_dispatch_fn", lambda: (lambda **kw: R(False)))

    write_calls = []
    monkeypatch.setattr(S, "_write_story", lambda *args: write_calls.append(args))

    result = S.run_entity_stories(4)

    assert result == {"stories": 0, "deferred": True}
    assert write_calls == []


def test_run_defers_on_exception(monkeypatch):
    monkeypatch.setattr(
        S, "_fetch_candidates", lambda o, l: [{"id": 9, "canonical_name": "Terry", "entity_type": "person"}]
    )
    monkeypatch.setattr(
        S,
        "_fetch_entity_emails",
        lambda i: [
            {"sent_at": datetime(2026, 1, 1), "subject": "a", "body_text": "x", "source_kind": "gmail"},
            {"sent_at": datetime(2026, 2, 1), "subject": "b", "body_text": "y", "source_kind": "linkedin"},
        ],
    )

    def raiser(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(S, "_dispatch_fn", lambda: raiser)

    write_calls = []
    monkeypatch.setattr(S, "_write_story", lambda *args: write_calls.append(args))

    result = S.run_entity_stories(4)

    assert result == {"stories": 0, "deferred": True}
    assert write_calls == []


def test_run_skips_empty_narrative(monkeypatch):
    monkeypatch.setattr(
        S, "_fetch_candidates", lambda o, l: [{"id": 9, "canonical_name": "Terry", "entity_type": "person"}]
    )
    monkeypatch.setattr(
        S,
        "_fetch_entity_emails",
        lambda i: [
            {"sent_at": datetime(2026, 1, 1), "subject": "a", "body_text": "x", "source_kind": "gmail"},
            {"sent_at": datetime(2026, 2, 1), "subject": "b", "body_text": "y", "source_kind": "linkedin"},
        ],
    )
    monkeypatch.setattr(S, "_dispatch_fn", lambda: (lambda **kw: R(True, "   ")))

    write_calls = []
    monkeypatch.setattr(S, "_write_story", lambda *args: write_calls.append(args))

    result = S.run_entity_stories(4)

    assert result == {"stories": 0, "deferred": False}
    assert write_calls == []


def test_run_no_candidates(monkeypatch):
    monkeypatch.setattr(S, "_fetch_candidates", lambda o, l: [])

    dispatch_calls = []
    monkeypatch.setattr(S, "_dispatch_fn", lambda: (lambda **kw: dispatch_calls.append(kw) or R(True, "x")))

    result = S.run_entity_stories(4)

    assert result == {"stories": 0, "deferred": False}
    assert dispatch_calls == []
