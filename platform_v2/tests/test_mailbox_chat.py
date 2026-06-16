"""Unit tests for mailbox_chat_service (chat -> Mailbox Story ingestion). DB stubbed."""

import json
from contextlib import contextmanager

import pytest

import services.mailbox_chat_service as svc


def test_to_dt():
    assert svc._to_dt(1696000000).year == 2023  # epoch float
    assert svc._to_dt("2026-01-05T10:00:00Z").year == 2026  # ISO
    assert svc._to_dt("2026-01-05").month == 1
    assert svc._to_dt(None) is None
    assert svc._to_dt("garbage") is None


def test_chatgpt_messages_sorted_no_system():
    conv = {
        "mapping": {
            "a": {"message": {"author": {"role": "user"}, "content": {"parts": ["hi"]}, "create_time": 2}},
            "b": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["hello"]}, "create_time": 3}},
            "s": {"message": {"author": {"role": "system"}, "content": {"parts": ["sys"]}, "create_time": 1}},
        }
    }
    msgs = svc._chatgpt_messages(conv)
    assert [r for r, _, _ in msgs] == ["user", "assistant"]  # system dropped, sorted by time


def test_claude_messages_and_attachments():
    conv = {
        "chat_messages": [
            {"sender": "human", "text": "q", "created_at": "2026-01-05T10:00:00Z"},
            {"sender": "assistant", "text": "a", "attachments": [{"file_name": "x.pdf"}]},
        ]
    }
    msgs = svc._claude_messages(conv)
    assert msgs[0][0] == "user"
    assert "x.pdf" in msgs[1][1]


class _FakeCur:
    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        self.store.append((sql, params))

    def fetchone(self):
        return {"id": 99}


def _patch_db(monkeypatch):
    store = []

    @contextmanager
    def _fake_db(commit=True):
        yield (None, _FakeCur(store))

    monkeypatch.setattr(svc, "get_db_cursor", _fake_db)
    return store


def test_ingest_chat_inserts_import_and_messages(monkeypatch):
    store = _patch_db(monkeypatch)
    from datetime import datetime, timezone

    msgs = [("user", "Hello there", datetime(2026, 1, 5, tzinfo=timezone.utc)), ("assistant", "Hi!\nsecond line", None)]
    iid = svc.ingest_chat("Termination thread", msgs, owner_id=1)
    assert iid == 99
    sqls = " ".join(s for s, _ in store)
    assert "INSERT INTO mailbox_imports" in sqls
    assert sqls.count("INSERT INTO mailbox_emails") == 2  # one row per message


def test_ingest_export_file_bad_path():
    with pytest.raises(ValueError):
        svc.ingest_export_file("/no/such/file.json")


def test_ingest_export_file_parses_and_ingests(tmp_path, monkeypatch):
    _patch_db(monkeypatch)
    calls = []
    monkeypatch.setattr(svc, "ingest_chat", lambda title, msgs, owner_id=None: (calls.append((title, len(msgs))) or 1))
    p = tmp_path / "conversations.json"
    p.write_text(
        json.dumps(
            [
                {
                    "title": "Chat A",
                    "mapping": {
                        "a": {"message": {"author": {"role": "user"}, "content": {"parts": ["x"]}, "create_time": 1}}
                    },
                },
                {"name": "Chat B", "chat_messages": [{"sender": "human", "text": "y"}]},
            ]
        )
    )
    res = svc.ingest_export_file(str(p))
    assert len(res) == 2 and len(calls) == 2
    # title filter
    calls.clear()
    res2 = svc.ingest_export_file(str(p), title_filter="chat a")
    assert len(res2) == 1
