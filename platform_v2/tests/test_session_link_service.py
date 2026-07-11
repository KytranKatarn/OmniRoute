"""Engine-session <-> comms-conversation link store (Track B, CLI collaboration)."""

import services.session_link_service as sls


class _FakeCursor:
    def __init__(self, store):
        self._store = store
        self._selected = None

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("INSERT"):
            self._store[params[0]] = params[1]
        else:
            self._selected = self._store.get(params[0])

    def fetchone(self):
        return {"value": self._selected} if self._selected is not None else None


class _FakeCtx:
    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return (None, _FakeCursor(self._store))

    def __exit__(self, *a):
        return False


def test_record_and_get_link(monkeypatch):
    store = {}
    monkeypatch.setattr(sls, "get_db_cursor", lambda commit=False: _FakeCtx(store))

    assert sls.record_link("sess-abc", "conv-uuid-9") is True
    assert store == {"session_link:sess-abc": "conv-uuid-9"}
    assert sls.get_link("sess-abc") == "conv-uuid-9"
    assert sls.get_link("nope") is None


def test_record_link_rejects_empty():
    assert sls.record_link("", "c") is False
    assert sls.record_link("s", "") is False
