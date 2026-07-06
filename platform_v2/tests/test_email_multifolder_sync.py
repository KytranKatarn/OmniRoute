"""Tests for Email HQ multi-folder IMAP sync (#4519)."""

import email as email_lib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.email_manager import sync_jobs


class _FakeCur:
    def __init__(self, rows=None, value=None):
        self._rows = rows or []
        self._value = value
        self.rowcount = 1
        self.last_sql = None
        self.last_params = None

    def execute(self, sql, params=None):
        self.last_sql = sql
        self.last_params = params

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return {"value": self._value} if self._value is not None else None


class _FakeCtx:
    """Mimics get_db_cursor() context manager yielding (conn, cur)."""

    def __init__(self, cur):
        self._cur = cur

    def __enter__(self):
        return (None, self._cur)

    def __exit__(self, *a):
        return False


def test_sync_folders_default(monkeypatch):
    cur = _FakeCur(value=None)  # no mailhq:sync:folders row → default
    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _FakeCtx(cur))
    assert sync_jobs._sync_folders() == ["INBOX", "Junk Mail"]


def test_sync_folders_custom_inbox_first_and_deduped(monkeypatch):
    cur = _FakeCur(value="Junk, Archive ,INBOX, Junk")
    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _FakeCtx(cur))
    # INBOX forced first, whitespace trimmed, duplicates removed, order preserved.
    assert sync_jobs._sync_folders() == ["INBOX", "Junk", "Archive"]


def test_sync_folders_failsafe_on_db_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.get_db_cursor", _boom)
    assert sync_jobs._sync_folders() == ["INBOX", "Junk Mail"]


def test_get_synced_uids_is_folder_scoped():
    # UIDs are per-folder — the skip-set must be scoped to (mailbox_id, folder).
    cur = _FakeCur(rows=[{"imap_uid": 1}, {"imap_uid": 2}])
    result = sync_jobs.get_synced_uids(cur, mailbox_id=7, folder="Junk")
    assert result == {1, 2}
    assert "folder = %s" in cur.last_sql
    assert cur.last_params == (7, "Junk")


def test_insert_email_message_stores_folder(monkeypatch):
    monkeypatch.setattr("tools.email_manager.thread_service.resolve_thread", lambda *a, **k: None)
    raw = (
        b"Message-ID: <abc@x>\r\nSubject: hi\r\nFrom: a@b.c\r\nTo: d@e.f\r\n"
        b"Date: Mon, 06 Jul 2026 10:00:00 -0400\r\n\r\nbody"
    )
    msg = email_lib.message_from_bytes(raw)
    cur = _FakeCur()
    sync_jobs.insert_email_message(cur, mailbox_id=7, imap_uid=5, msg=msg, raw=raw, folder="Junk")
    # INSERT tuple order: (mailbox_id, folder, imap_uid, message_id, ...)
    assert cur.last_params[0] == 7
    assert cur.last_params[1] == "Junk"
    assert cur.last_params[2] == 5
    assert "folder" in cur.last_sql
