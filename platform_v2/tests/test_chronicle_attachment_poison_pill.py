"""Poison-pill fix for the Chronicle attachment downloader.

An email whose Gmail message was DELETED returns HTTP 404 on get_email. Before the fix it
never got a mailbox_attachments row, so it stayed a _candidate_emails candidate forever and
run_attachment_download re-attempted it every cycle (infinite spin). The fix marks such an
email attachment_fetch_status='unavailable' (leaving has_attachments TRUE) so it is excluded
from candidacy while a transient error is left retryable.

Self-cleaning integration test against the real archie DB. Uses a sentinel email in gmail
import 16 (account 7) with a fake message_id; get_email is monkeypatched to raise a
404-shaped HttpError so no real Gmail call is made. Requires migration 454
(mailbox_emails.attachment_fetch_status).
"""

import services.chronicle_gmail_attachments as mod

SENTINEL_MSG = "__poison_pill_test__"
# chronicle_import["import_id"] used to be 16 — a REAL production gmail import. archie_test has never held it,
# so the INSERT below hit mailbox_emails_import_id_fkey. The `chronicle_import` fixture
# (tests/conftest.py) creates its own import + email and cleans up after.


class _Resp:
    status = 404


class _FakeHttpError(Exception):
    resp = _Resp()


def test_deleted_message_marked_unavailable_and_excluded(chronicle_import):
    from database import get_db_cursor

    email_id = None
    orig_get_email = mod.gmail_service.get_email
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO mailbox_emails (import_id, message_id, has_attachments, subject) "
                "VALUES (%s, %s, TRUE, 'poison pill test') RETURNING id",
                (chronicle_import["import_id"], SENTINEL_MSG),
            )
            email_id = cur.fetchone()["id"]

        # It is a candidate before the run.
        before = [e[0] for e in mod._candidate_emails(chronicle_import["import_id"], 100000)]
        assert email_id in before, "sentinel should start as an attachment candidate"

        # get_email 404s for the sentinel (message gone); real ids pass through untouched.
        def _fake_get_email(account_id, gmail_id):
            if gmail_id == SENTINEL_MSG:
                raise _FakeHttpError()
            return orig_get_email(account_id, gmail_id)

        mod.gmail_service.get_email = _fake_get_email
        mod.run_attachment_download(chronicle_import["import_id"], limit=100000)

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT attachment_fetch_status, has_attachments FROM mailbox_emails WHERE id=%s",
                (email_id,),
            )
            row = cur.fetchone()

        assert (
            row["attachment_fetch_status"] == "unavailable"
        ), f"404 email should be marked unavailable, got {row['attachment_fetch_status']!r}"
        # has_attachments must be preserved (the reader displays it; it WAS true).
        assert row["has_attachments"] is True, "has_attachments must not be flipped"

        # It is no longer a candidate → no more spinning.
        after = [e[0] for e in mod._candidate_emails(chronicle_import["import_id"], 100000)]
        assert email_id not in after, "marked email must drop out of candidacy"
    finally:
        mod.gmail_service.get_email = orig_get_email
        if email_id is not None:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM mailbox_emails WHERE message_id=%s", (SENTINEL_MSG,))


def test_http_status_helper():
    assert mod._http_status(_FakeHttpError()) == 404
    assert mod._http_status(ValueError("nope")) is None
