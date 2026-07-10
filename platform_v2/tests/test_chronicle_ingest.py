"""Tests for the Chronicle ingest seam (slice 04).

One pure unit test for the value-mapping helper, plus self-cleaning integration
tests against the real archie DB (mailbox_imports / mailbox_emails / mailbox_attachments
are live tables). Every integration test deletes its throwaway import in a `finally`
block; FK CASCADE removes the associated emails/attachments. Sentinel
source_account_id values (-987654, -987655, -987656) keep this test data
unambiguous and easy to find/clean if a run is interrupted.
"""

from services import chronicle_ingest
from services.chronicle_ingest import ingest_source, upsert_attachment


def test_email_values_maps_item():
    item = {
        "message_id": "m-1",
        "folder": "INBOX",
        "from_addr": "a@b.c",
        "to_addrs": "d@e.f",
        "cc_addrs": "g@h.i",
        "in_reply_to": "m-0",
        "sent_at": None,
        "subject": "hello",
        "body_text": "hi there",
        "body_html": "<p>hi there</p>",
    }
    values = chronicle_ingest._email_values(42, item)
    assert values == (
        42,
        "m-1",
        "INBOX",
        "a@b.c",
        "d@e.f",
        "g@h.i",
        "m-0",
        None,
        "hello",
        "hi there",
        "<p>hi there</p>",
        False,
    )

    # has_attachments True when attachments list present, even without the flag set
    with_atts = chronicle_ingest._email_values(1, {"attachments": [{"filename": "x.pdf"}]})
    assert with_atts[-1] is True

    # has_attachments True when the flag is explicitly set, even with no list
    with_flag = chronicle_ingest._email_values(1, {"has_attachments": True})
    assert with_flag[-1] is True

    # has_attachments False when neither is present
    with_neither = chronicle_ingest._email_values(1, {})
    assert with_neither[-1] is False


def _delete_import(import_id):
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM mailbox_imports WHERE id=%s", (import_id,))


def test_ingest_source_inserts_and_is_idempotent():
    items = [
        {"message_id": "m-1", "subject": "a", "body_text": "hi", "from_addr": "x@y.z", "sent_at": None},
        {"message_id": "m-2", "subject": "b", "body_text": "ho", "from_addr": "x@y.z", "sent_at": None},
    ]
    r1 = ingest_source("gmail", -987654, items, is_live=True)
    try:
        assert r1["inserted"] == 2
        assert r1["skipped"] == 0

        r2 = ingest_source("gmail", -987654, items, is_live=True)  # same items again
        assert r2["import_id"] == r1["import_id"]  # live import REUSED
        assert r2["inserted"] == 0
        assert r2["skipped"] == 2  # in-code dedup by message_id

        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT status, email_count, is_live_source, source_kind FROM mailbox_imports WHERE id=%s",
                (r1["import_id"],),
            )
            row = cur.fetchone()
            status = row["status"] if isinstance(row, dict) else row[0]
            email_count = row["email_count"] if isinstance(row, dict) else row[1]
            is_live_source = row["is_live_source"] if isinstance(row, dict) else row[2]
            source_kind = row["source_kind"] if isinstance(row, dict) else row[3]
            assert status == "extracted"
            assert email_count == 2
            assert is_live_source is True
            assert source_kind == "gmail"

            cur.execute(
                "SELECT enrich_status FROM mailbox_emails WHERE import_id=%s",
                (r1["import_id"],),
            )
            rows = cur.fetchall()
            assert len(rows) == 2
            for r in rows:
                enrich_status = r["enrich_status"] if isinstance(r, dict) else r[0]
                assert enrich_status == "pending"
    finally:
        _delete_import(r1["import_id"])


def test_ingest_source_dedupes_within_batch():
    items = [
        {"message_id": "dup-1", "subject": "a", "body_text": "hi", "sent_at": None},
        {"message_id": "dup-1", "subject": "a again", "body_text": "hi again", "sent_at": None},
    ]
    r = ingest_source("gmail", -987654, items, is_live=True)
    try:
        assert r["inserted"] == 1
        assert r["skipped"] == 1
    finally:
        _delete_import(r["import_id"])


def test_ingest_source_fresh_import_when_not_live():
    items = [{"message_id": "u-1", "subject": "upload", "body_text": "x", "sent_at": None}]
    r1 = ingest_source("upload", -987655, items, is_live=False)
    r2 = None
    try:
        r2 = ingest_source("upload", -987655, items, is_live=False)
        assert r1["import_id"] != r2["import_id"]  # NOT reused — fresh import each call
    finally:
        _delete_import(r1["import_id"])
        if r2 is not None:
            _delete_import(r2["import_id"])


def test_upsert_attachment_idempotent():
    items = [{"message_id": "a-1", "subject": "att", "body_text": "x", "sent_at": None}]
    r = ingest_source("gmail", -987656, items, is_live=True)
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM mailbox_emails WHERE import_id=%s AND message_id=%s",
                (r["import_id"], "a-1"),
            )
            row = cur.fetchone()
            email_id = row["id"] if isinstance(row, dict) else row[0]

        first = upsert_attachment(email_id, "x.pdf", "application/pdf", 123, "sha-SENTINEL", "/tmp/x.pdf")
        assert first[1] is True

        second = upsert_attachment(email_id, "x.pdf", "application/pdf", 123, "sha-SENTINEL", "/tmp/x.pdf")
        assert second[0] == first[0]
        assert second[1] is False
    finally:
        _delete_import(r["import_id"])
