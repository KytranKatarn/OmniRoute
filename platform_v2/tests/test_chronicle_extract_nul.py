"""Extraction poison-pill fix: text with NUL (0x00) bytes must not leave a row stuck 'new'.

OCR/PDF extraction routinely emits NUL bytes, which Postgres TEXT rejects. Before the fix the
success-path UPDATE raised, extract_attachment propagated, and the row stayed extract_status
='new' — so run_attachment_extraction re-selected and re-failed it every cycle (spin). The fix
strips NUL (recovering the text as 'done') and wraps the store so any failure persists 'error'.

Self-cleaning integration test against the real archie DB. Creates a temp file + a
mailbox_attachments row on a real email, monkeypatches extract_text_from_file to return
NUL-containing text, and asserts the row lands 'done' with the NUL stripped.
"""

import os
import services.chronicle_attachment_service as svc

SENTINEL_SHA = "__nul_poison_pill_test__"


def test_nul_text_stores_done_not_stuck_new(chronicle_import):
    from database import get_db_cursor

    att_id = None
    tmp_path = "/tmp/__nul_extract_test__.bin"
    orig_extract = svc.extract_text_from_file
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(b"dummy")  # only needs to exist; extract_text_from_file is monkeypatched

        with get_db_cursor(commit=True) as (conn, cur):
            # Was `WHERE import_id=16` — Terry's LIVE Gmail import in PRODUCTION. In
            # archie_test that SELECT returns None, and None["id"] raises
            # "TypeError: 'NoneType' object is not subscriptable" — a message that says
            # nothing about the real cause. The fixture supplies its own row.
            email_id = chronicle_import["email_id"]
            cur.execute(
                "INSERT INTO mailbox_attachments "
                "(email_id, filename, mime_type, size_bytes, sha256, stored_path, extract_status) "
                "VALUES (%s,'nul.pdf','application/pdf',5,%s,%s,'new') RETURNING id",
                (email_id, SENTINEL_SHA, tmp_path),
            )
            att_id = cur.fetchone()["id"]

        svc.extract_text_from_file = lambda path, mime=None: ("hello\x00world\x00", True)

        status = svc.extract_attachment(att_id)

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT extract_status, extracted_text FROM mailbox_attachments WHERE id=%s",
                (att_id,),
            )
            row = cur.fetchone()

        assert status == "done", f"expected done, got {status!r}"
        assert row["extract_status"] == "done", f"row should be done, got {row['extract_status']!r}"
        assert "\x00" not in (row["extracted_text"] or ""), "NUL bytes must be stripped"
        assert row["extracted_text"] == "helloworld", f"unexpected text {row['extracted_text']!r}"
    finally:
        svc.extract_text_from_file = orig_extract
        if att_id is not None:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM mailbox_attachments WHERE sha256=%s", (SENTINEL_SHA,))
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
