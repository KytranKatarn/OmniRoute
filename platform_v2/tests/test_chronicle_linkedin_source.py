"""Hermetic tests for the Chronicle LinkedIn source adapter (slice 07).

No DB, no external API — pure helpers/mappers are tested with canned dict rows, and
run_linkedin_ingest is tested by monkeypatching the 5 _fetch_* functions + ingest_source.
"""

import services.chronicle_linkedin_source as L


def test_helpers():
    assert L._norm_key("  Hello   World  ") == "hello world"
    assert L._with_link("hi", "http://x", "On") == "hi\n\nOn: http://x"
    assert L._with_link("hi", None) == "hi"
    assert len(L._subject("a" * 200, "fb")) == 80
    assert L._subject("", "fb") == "fb"


def test_map_post():
    row = {"id": 5, "content": "My post", "sent_at": None}
    item = L._map_post(row, "post:log", "http://p")
    assert item["message_id"] == "li:post:log:5"
    assert item["from_addr"] == "Terry Caetano"
    assert item["folder"] == "linkedin/posts"
    assert "My post" in item["body_text"]
    assert "LinkedIn: http://p" in item["body_text"]
    assert item["has_attachments"] is False


def test_map_inbound_comment():
    row = {
        "id": 9,
        "author": "Ann",
        "body": "nice",
        "comment_url": "http://c",
        "first_seen_at": None,
    }
    item = L._map_inbound_comment(row)
    assert item["from_addr"] == "Ann"
    assert item["message_id"] == "li:comment:in:9"
    assert "nice" in item["body_text"]
    assert "On: http://c" in item["body_text"]


def test_map_reply():
    row = {
        "id": 12,
        "draft_reply": "thanks",
        "comment_urn": "urn:1",
        "comment_url": "http://c",
        "last_seen_at": None,
        "first_seen_at": None,
    }
    item = L._map_reply(row)
    assert item["from_addr"] == "Terry Caetano"
    assert item["in_reply_to"] == "urn:1"
    assert item["message_id"] == "li:comment:reply:12"


def test_map_engagement():
    row = {"id": 3, "comment_text": "great point", "url": "http://o", "sent_at": None}
    item = L._map_engagement(row)
    assert item["from_addr"] == "Terry Caetano"
    assert item["message_id"] == "li:engage:3"
    assert "great point" in item["body_text"]
    assert "On: http://o" in item["body_text"]


def test_run_dedups_posts_across_tables(monkeypatch):
    monkeypatch.setattr(
        L,
        "_fetch_post_log",
        lambda k: [{"id": 1, "content": "Same Post", "post_url": "http://p", "sent_at": None}],
    )
    monkeypatch.setattr(
        L,
        "_fetch_calendar",
        lambda k: [{"id": 2, "content": "same post", "sent_at": None}],
    )
    monkeypatch.setattr(L, "_fetch_drafts", lambda k: [])
    monkeypatch.setattr(L, "_fetch_comments", lambda k: [])
    monkeypatch.setattr(L, "_fetch_engagement", lambda a: [])

    calls = {}

    def fake_ingest_source(source_kind, source_account_id, items, owner_id=None, is_live=None, title=None):
        calls["args"] = (source_kind, source_account_id, items)
        calls["owner_id"] = owner_id
        calls["is_live"] = is_live
        return {"import_id": 50, "inserted": 1, "skipped": 0}

    monkeypatch.setattr(L, "ingest_source", fake_ingest_source)

    result = L.run_linkedin_ingest()

    source_kind, source_account_id, items = calls["args"]
    assert source_kind == "linkedin"
    assert source_account_id == 2
    assert len(items) == 1
    assert calls["owner_id"] == 4
    assert calls["is_live"] is True
    assert result["items"] == 1


def test_run_comment_makes_two_items(monkeypatch):
    monkeypatch.setattr(L, "_fetch_post_log", lambda k: [])
    monkeypatch.setattr(L, "_fetch_calendar", lambda k: [])
    monkeypatch.setattr(L, "_fetch_drafts", lambda k: [])
    monkeypatch.setattr(
        L,
        "_fetch_comments",
        lambda k: [
            {
                "id": 7,
                "author": "Ann",
                "body": "x",
                "draft_reply": "y",
                "comment_url": "http://c",
                "comment_urn": "urn:7",
                "first_seen_at": None,
                "last_seen_at": None,
            }
        ],
    )
    monkeypatch.setattr(L, "_fetch_engagement", lambda a: [])

    calls = {}

    def fake_ingest_source(source_kind, source_account_id, items, owner_id=None, is_live=None, title=None):
        calls["items"] = items
        return {"import_id": 51, "inserted": 2, "skipped": 0}

    monkeypatch.setattr(L, "ingest_source", fake_ingest_source)

    result = L.run_linkedin_ingest()

    assert len(calls["items"]) == 2
    assert result["items"] == 2


def test_run_no_items_no_call(monkeypatch):
    monkeypatch.setattr(L, "_fetch_post_log", lambda k: [])
    monkeypatch.setattr(L, "_fetch_calendar", lambda k: [])
    monkeypatch.setattr(L, "_fetch_drafts", lambda k: [])
    monkeypatch.setattr(L, "_fetch_comments", lambda k: [])
    monkeypatch.setattr(L, "_fetch_engagement", lambda a: [])

    called = {"n": 0}

    def fake_ingest_source(*args, **kwargs):
        called["n"] += 1
        return {"import_id": None, "inserted": 0, "skipped": 0}

    monkeypatch.setattr(L, "ingest_source", fake_ingest_source)

    result = L.run_linkedin_ingest()

    assert called["n"] == 0
    assert result["items"] == 0
    assert result["import_id"] is None
