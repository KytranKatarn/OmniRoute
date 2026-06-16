"""Unit tests for Mailbox Story Extractor Phase 2 enrichment (no DB, no LLM).

`_coerce` is pure. `enrich_one` is exercised with dispatch_json + the DB cursor stubbed,
so these run anywhere and assert the local-only contract + the validate/clamp/write logic.
"""

from contextlib import contextmanager

import services.mailbox_enrich_service as svc


# ---------- _coerce (pure validate/clamp) ----------


def test_coerce_full_valid():
    out = svc._coerce(
        {
            "summary": "Jane sent the signed deliverable.",
            "topic": "contract 24-0098",
            "category": "Procurement",
            "sensitivity": "secret",
            "sentiment": "neutral",
            "event": {"date": "2026-06-03", "title": "deliverable 3 signed"},
            "entities": [
                {"name": "Jane Auditor", "type": "person", "role": "sender"},
                {"name": "TBS", "type": "org", "role": "mentioned"},
            ],
        }
    )
    assert out["category"] == "procurement"  # lowercased
    assert out["sensitivity"] == "secret"
    assert out["sentiment"] == "neutral"
    assert out["event_date"] == "2026-06-03"
    assert out["event_title"] == "deliverable 3 signed"
    assert {e["type"] for e in out["entities"]} == {"person", "org"}


def test_coerce_defaults_and_drops_invalid():
    out = svc._coerce(
        {
            "summary": "x",
            "sensitivity": "ultra-mega-secret",  # invalid → normal
            "sentiment": "spicy",  # invalid → None
            "event": {"date": "June 3rd", "title": "t"},  # bad date → None
            "entities": [
                {"name": "A", "type": "alien"},  # invalid type → dropped
                {"name": "Bob", "type": "person"},
                {"name": "bob", "type": "person"},  # dedup (normalized) → one
            ],
        }
    )
    assert out["sensitivity"] == "normal"
    assert out["sentiment"] is None
    assert out["event_date"] is None
    assert [e["name"] for e in out["entities"]] == ["Bob"]


def test_coerce_non_dict_is_none():
    assert svc._coerce(None) is None
    assert svc._coerce("not json") is None


# ---------- enrich_one (stub dispatch + DB) ----------


class _FakeCur:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchone(self):
        return {"id": 42}  # entity RETURNING id


def _patch_db(monkeypatch):
    store = []

    @contextmanager
    def _fake_db(commit=True):
        yield (None, _FakeCur(store))

    monkeypatch.setattr(svc, "get_db_cursor", _fake_db)
    return store


_ROW = {
    "id": 7,
    "import_id": 3,
    "from_addr": "a@b.gc.ca",
    "to_addrs": "c@d.com",
    "cc_addrs": None,
    "sent_at": None,
    "subject": "hi",
    "body_text": "body",
}


class _Result:
    def __init__(self, success, response, model="qwen2.5:7b"):
        self.success = success
        self.response = response
        self.model = model


def test_enrich_one_local_only_and_persists(monkeypatch):
    store = _patch_db(monkeypatch)
    captured = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return _Result(
            True,
            {
                "summary": "a summary",
                "category": "hr",
                "sensitivity": "gov",
                "entities": [{"name": "Jane", "type": "person", "role": "sender"}],
            },
        )

    monkeypatch.setattr(svc, "dispatch", fake_dispatch)
    assert svc.enrich_one(dict(_ROW)) is True
    # HARD privacy contract: the dispatch MUST be local_only.
    assert captured.get("local_only") is True
    assert captured.get("capability") == "analyze"
    sqls = " ".join(s for s, _ in store)
    assert "INSERT INTO mailbox_email_facts" in sqls
    assert "INSERT INTO mailbox_entities" in sqls
    assert "INSERT INTO mailbox_email_entities" in sqls
    assert "enrich_status='done'" in sqls


def test_enrich_one_defers_when_model_cold(monkeypatch):
    # A failed dispatch (model cold/queued) must NOT burn the email — leave it 'pending'.
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "dispatch", lambda **k: _Result(False, None))
    assert svc.enrich_one(dict(_ROW)) is None
    assert not any("error" in (p or ()) for _, p in store)  # no 'error' status written


def test_enrich_one_errors_on_unparseable(monkeypatch):
    # A successful dispatch with garbage output is a genuine error.
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "dispatch", lambda **k: _Result(True, "not json at all"))
    assert svc.enrich_one(dict(_ROW)) is False
    assert any(p and "error" in p for _, p in store)
