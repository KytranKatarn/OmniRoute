"""Hermetic tests for chronicle_gmail_source (slice 05).

No live Gmail, no DB — everything the module talks to (gmail_service, ingest_source,
_seen_message_ids, _owner_id_for_account) is monkeypatched in-process.
"""

from datetime import datetime

import services.chronicle_gmail_source as g


def _canned_email(sender="a@b.c", recipients=None, subject="Hi", attachments=None):
    return {
        "subject": subject,
        "sender": sender,
        "recipients": recipients if recipients is not None else ["x@y.z"],
        "date": "Wed, 09 Jul 2026 10:00:00 -0400",
        "body_plain": "body",
        "body_html": "<p>body</p>",
        "attachments": attachments if attachments is not None else [],
    }


def test_to_item_maps_fields():
    item = g._to_item(
        "m1",
        {
            "sender": "a@b.c",
            "recipients": ["x@y.z", "w@y.z"],
            "subject": "Hi",
            "body_plain": "body",
            "body_html": "<p>body</p>",
            "date": "Wed, 09 Jul 2026 10:00:00 -0400",
            "attachments": [{"filename": "a.pdf"}],
        },
    )
    assert item["message_id"] == "m1"
    assert item["from_addr"] == "a@b.c"
    assert item["to_addrs"] == "x@y.z, w@y.z"
    assert item["subject"] == "Hi"
    assert item["body_text"] == "body"
    assert item["body_html"] == "<p>body</p>"
    assert item["has_attachments"] is True
    assert isinstance(item["sent_at"], datetime)
    assert item["sent_at"].year == 2026

    # body_text falls back to "" when body_plain is missing
    item2 = g._to_item("m2", {"sender": "a@b.c"})
    assert item2["body_text"] == ""


def test_parse_date_bad_returns_none():
    assert g._parse_date("not a date") is None
    assert g._parse_date("") is None
    dt = g._parse_date("Wed, 09 Jul 2026 10:00:00 -0400")
    assert isinstance(dt, datetime)


def test_run_ingest_maps_and_calls_ingest_source(monkeypatch):
    monkeypatch.setattr(g, "_owner_id_for_account", lambda account_id: 4)
    monkeypatch.setattr(g, "_seen_message_ids", lambda account_id: set())
    monkeypatch.setattr(
        g.gmail_service,
        "list_all_message_ids",
        lambda account_id, page_token=None, max_per_page=500, query="": (
            [{"id": "m1"}, {"id": "m2"}],
            None,
        ),
    )

    canned = {
        "m1": _canned_email(sender="a@b.c"),
        "m2": _canned_email(sender="d@e.f"),
    }
    monkeypatch.setattr(g.gmail_service, "get_email", lambda account_id, gid: canned[gid])

    calls = []

    def recorder(source_kind, source_account_id, items, owner_id=None, is_live=None, title=None):
        calls.append((source_kind, source_account_id, items, owner_id, is_live, title))
        return {"import_id": 99, "inserted": 2, "skipped": 0}

    monkeypatch.setattr(g, "ingest_source", recorder)

    result = g.run_gmail_ingest(7, limit=50)

    assert len(calls) == 1
    source_kind, source_account_id, items, owner_id, is_live, title = calls[0]
    assert source_kind == "gmail"
    assert source_account_id == 7
    assert len(items) == 2
    assert owner_id == 4
    assert is_live is True

    assert result["fetched"] == 2
    assert result["errors"] == 0
    assert result["import_id"] == 99
    assert result["inserted"] == 2


def test_run_ingest_dedups_seen(monkeypatch):
    monkeypatch.setattr(g, "_owner_id_for_account", lambda account_id: 4)
    monkeypatch.setattr(g, "_seen_message_ids", lambda account_id: {"m1"})
    monkeypatch.setattr(
        g.gmail_service,
        "list_all_message_ids",
        lambda account_id, page_token=None, max_per_page=500, query="": (
            [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
            None,
        ),
    )

    fetched_ids = []

    def get_email(account_id, gid):
        fetched_ids.append(gid)
        return _canned_email()

    monkeypatch.setattr(g.gmail_service, "get_email", get_email)

    calls = []
    monkeypatch.setattr(
        g,
        "ingest_source",
        lambda *a, **kw: calls.append((a, kw)) or {"import_id": 1, "inserted": 2, "skipped": 0},
    )

    result = g.run_gmail_ingest(7, limit=50)

    assert "m1" not in fetched_ids
    assert set(fetched_ids) == {"m2", "m3"}
    assert result["fetched"] == 2


def test_limit_honored(monkeypatch):
    monkeypatch.setattr(g, "_owner_id_for_account", lambda account_id: 4)
    monkeypatch.setattr(g, "_seen_message_ids", lambda account_id: set())
    monkeypatch.setattr(
        g.gmail_service,
        "list_all_message_ids",
        lambda account_id, page_token=None, max_per_page=500, query="": (
            [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}, {"id": "m4"}, {"id": "m5"}],
            None,
        ),
    )
    monkeypatch.setattr(g.gmail_service, "get_email", lambda account_id, gid: _canned_email())

    calls = []

    def recorder(source_kind, source_account_id, items, owner_id=None, is_live=None, title=None):
        calls.append(items)
        return {"import_id": 1, "inserted": len(items), "skipped": 0}

    monkeypatch.setattr(g, "ingest_source", recorder)

    result = g.run_gmail_ingest(7, limit=2)

    assert result["fetched"] == 2
    assert len(calls) == 1
    assert len(calls[0]) == 2


def test_get_email_error_isolated(monkeypatch):
    monkeypatch.setattr(g, "_owner_id_for_account", lambda account_id: 4)
    monkeypatch.setattr(g, "_seen_message_ids", lambda account_id: set())
    monkeypatch.setattr(
        g.gmail_service,
        "list_all_message_ids",
        lambda account_id, page_token=None, max_per_page=500, query="": (
            [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}],
            None,
        ),
    )

    def get_email(account_id, gid):
        if gid == "m2":
            raise RuntimeError("boom")
        return _canned_email()

    monkeypatch.setattr(g.gmail_service, "get_email", get_email)

    calls = []

    def recorder(source_kind, source_account_id, items, owner_id=None, is_live=None, title=None):
        calls.append(items)
        return {"import_id": 1, "inserted": len(items), "skipped": 0}

    monkeypatch.setattr(g, "ingest_source", recorder)

    result = g.run_gmail_ingest(7, limit=50)

    assert result["errors"] == 1
    assert result["fetched"] == 2
    assert len(calls) == 1
    assert len(calls[0]) == 2


def test_no_items_no_ingest_call(monkeypatch):
    monkeypatch.setattr(g, "_owner_id_for_account", lambda account_id: 4)
    monkeypatch.setattr(g, "_seen_message_ids", lambda account_id: set())
    monkeypatch.setattr(
        g.gmail_service,
        "list_all_message_ids",
        lambda account_id, page_token=None, max_per_page=500, query="": ([], None),
    )
    monkeypatch.setattr(g.gmail_service, "get_email", lambda account_id, gid: _canned_email())

    calls = []
    monkeypatch.setattr(
        g,
        "ingest_source",
        lambda *a, **kw: calls.append((a, kw)) or {"import_id": 1, "inserted": 0, "skipped": 0},
    )

    result = g.run_gmail_ingest(7, limit=50)

    assert calls == []
    assert result["fetched"] == 0
    assert result["import_id"] is None
