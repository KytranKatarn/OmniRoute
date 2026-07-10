"""Tests for the Chronicle People-hub backend API (/api/people, /api/people/<id>).

Self-cleaning integration test against the real archie DB (mailbox_imports / mailbox_emails /
mailbox_entities / mailbox_email_entities / chronicle_entity / chronicle_entity_link /
chronicle_entity_story are live tables). Sentinel owner_id=-778 keeps this test data
unambiguous and easy to find/clean if a run is interrupted; cleanup runs in a `finally` block.
"""

from datetime import datetime

from psycopg2.extras import Json

from tools.mailbox_story.routes import _list_people, _person_detail

OWNER = -778


def test_list_people_and_person_detail():
    from database import get_db_cursor

    imp = ce = None
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO mailbox_imports (owner_id, filename, stored_path, status, email_count, source_kind) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (OWNER, "t", "t", "extracted", 1, "gmail"),
            )
            imp = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO mailbox_emails (import_id, message_id, from_addr, subject, body_text, "
                "sent_at, has_attachments) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (imp, "pm-1", "a@b.c", "Hello", "body text here", datetime(2026, 1, 2), False),
            )
            em = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO mailbox_entities (import_id, name, entity_type, normalized_name, mention_count) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (imp, "Test Person", "person", "test person", 2),
            )
            me = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO mailbox_email_entities (email_id, entity_id) VALUES (%s,%s)",
                (em, me),
            )

            cur.execute(
                "INSERT INTO chronicle_entity (owner_id, canonical_name, entity_type, aliases) "
                "VALUES (%s,%s,%s,%s) RETURNING id",
                (OWNER, "Test Person", "person", Json(["Test Person"])),
            )
            ce = cur.fetchone()["id"]

            cur.execute(
                "INSERT INTO chronicle_entity_link (chronicle_entity_id, mailbox_entity_id) VALUES (%s,%s)",
                (ce, me),
            )

        people = _list_people(OWNER)
        row = next(p for p in people if p["id"] == ce)
        assert row["canonical_name"] == "Test Person" and row["entity_type"] == "person"
        assert row["item_count"] == 1 and row["sources"] == ["gmail"]
        assert row["has_story"] is False and row["has_voice"] is False

        d = _person_detail(ce)
        assert d["entity"]["id"] == ce and d["story"] is None and d["voice"] is None
        assert d["sources"] == ["gmail"] and len(d["timeline"]) == 1
        assert d["timeline"][0]["subject"] == "Hello" and d["timeline"][0]["source_kind"] == "gmail"

        # add a story row -> has_story flips, detail.story populated
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO chronicle_entity_story (chronicle_entity_id, narrative, source_kinds, email_count) "
                "VALUES (%s,%s,%s,%s)",
                (ce, "arc", Json(["gmail"]), 1),
            )
        assert next(p for p in _list_people(OWNER) if p["id"] == ce)["has_story"] is True
        assert _person_detail(ce)["story"]["narrative"] == "arc"

        # not-found:
        assert _person_detail(-999999) is None
    finally:
        from database import get_db_cursor as _get_db_cursor

        with _get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM chronicle_entity WHERE owner_id=%s", (OWNER,))
            if imp is not None:
                cur.execute("DELETE FROM mailbox_imports WHERE id=%s", (imp,))
