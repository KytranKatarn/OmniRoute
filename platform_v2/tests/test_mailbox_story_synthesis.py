"""Unit tests for Mailbox Story Extractor Phase 3 synthesis (no DB, no LLM).

build_stories is exercised with _clusters / _cluster_emails / dispatch / the DB cursor stubbed,
asserting the local-only contract, the deferred-on-cold-model behavior, and the write path.
"""

from contextlib import contextmanager

import services.mailbox_story_service as svc


class _FakeCur:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store.append((sql, params))


def _patch_db(monkeypatch):
    store = []

    @contextmanager
    def _fake_db(commit=True):
        yield (None, _FakeCur(store))

    monkeypatch.setattr(svc, "get_db_cursor", _fake_db)
    return store


class _Result:
    def __init__(self, success, response, model="qwen2.5:7b"):
        self.success = success
        self.response = response
        self.model = model


_CLUSTER = {"id": 1, "name": "Northstar", "entity_type": "project", "mention_count": 3, "email_count": 2}
_EMAILS = [
    {"id": 1, "subject": "kickoff", "sent_at": None, "summary": "kickoff scheduled"},
    {"id": 2, "subject": "update", "sent_at": None, "summary": "milestone reached"},
]


def test_build_stories_local_only_and_writes(monkeypatch):
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "_clusters", lambda iid: [dict(_CLUSTER)])
    monkeypatch.setattr(svc, "_cluster_emails", lambda eid: list(_EMAILS))
    captured = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return _Result(True, "Northstar kicked off then hit a milestone.")

    monkeypatch.setattr(svc, "dispatch", fake_dispatch)
    res = svc.build_stories(7)
    assert res == {"stories": 1, "deferred": False}
    assert captured.get("local_only") is True  # HARD privacy contract
    assert any("INSERT INTO mailbox_stories" in s for s, _ in store)


def test_build_stories_defers_when_model_cold(monkeypatch):
    _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "_clusters", lambda iid: [dict(_CLUSTER)])
    monkeypatch.setattr(svc, "_cluster_emails", lambda eid: list(_EMAILS))
    monkeypatch.setattr(svc, "dispatch", lambda **k: _Result(False, None))
    res = svc.build_stories(7)
    assert res["deferred"] is True and res["stories"] == 0


def test_build_stories_no_clusters(monkeypatch):
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "_clusters", lambda iid: [])
    res = svc.build_stories(7)
    assert res == {"stories": 0, "deferred": False}
    assert any("DELETE FROM mailbox_stories" in s for s, _ in store)


def test_build_import_story_does_not_stamp_when_deferred(monkeypatch):
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "build_timeline", lambda iid: 3)
    monkeypatch.setattr(svc, "build_stories", lambda iid: {"stories": 0, "deferred": True})
    res = svc.build_import_story(7)
    assert res["stamped"] is False
    # story_built_at must NOT be set when synthesis deferred (so it retries)
    assert not any("story_built_at=now()" in s for s, _ in store)


def test_build_import_story_stamps_when_complete(monkeypatch):
    store = _patch_db(monkeypatch)
    monkeypatch.setattr(svc, "build_timeline", lambda iid: 3)
    monkeypatch.setattr(svc, "build_stories", lambda iid: {"stories": 2, "deferred": False})
    res = svc.build_import_story(7)
    assert res["stamped"] is True
    assert any("story_built_at=now()" in s for s, _ in store)
