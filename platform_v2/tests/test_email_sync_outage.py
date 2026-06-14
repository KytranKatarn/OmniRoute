"""Unit tests for email IMAP sync OUTAGE observability.

Follow-up to the NUL-byte false-green fix (#1686). The OUTER IMAP auth/connection
except blocks in sync_single_mailbox_full used to `return 0`, which is
indistinguishable from "synced OK, 0 new messages". A real Stalwart outage
(every mailbox's connection fails) therefore reported `success` every 5 minutes
because:
  1. sync_single_mailbox_full swallowed the error and returned 0, and
  2. job_service.run_job records ("success", 1, 0) unless the func RAISES.

The hardening: sync_single_mailbox_full raises a typed MailboxSyncError on
auth/connection/unknown failure (per-message isolation is unchanged), and
run_email_imap_sync raises EmailSyncOutageError when every mailbox fails so the
job goes red in autonomy_loop_log. Partial failures log loudly + surface in the
return dict but do NOT redden the whole job (a single bad-credential mailbox is
a config issue, not a sync-system outage).

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_email_sync_outage.py -v
"""

import imaplib
from contextlib import contextmanager
from unittest import mock

import pytest

from tools.email_manager import sync_jobs
from tools.email_manager.sync_jobs import (
    EmailSyncOutageError,
    MailboxSyncError,
    run_email_imap_sync,
    sync_single_mailbox_full,
)


def _fake_get_db_cursor(mailboxes):
    """Return a get_db_cursor replacement whose cursor.fetchall() yields mailboxes."""

    @contextmanager
    def _cm(*args, **kwargs):
        cur = mock.MagicMock()
        cur.fetchall.return_value = mailboxes
        yield (mock.MagicMock(), cur)

    return _cm


def _mailboxes(n):
    return [{"id": i, "address": f"box{i}@kytranempowerment.com", "imap_password": "pw"} for i in range(1, n + 1)]


# --- sync_single_mailbox_full: outer except must RAISE, not return 0 -----------


def test_connection_error_raises_mailbox_sync_error():
    """Stalwart down → IMAP4_SSL constructor raises OSError → connection category."""
    with mock.patch.object(sync_jobs.imaplib, "IMAP4_SSL", side_effect=OSError("connection refused")):
        with pytest.raises(MailboxSyncError) as exc_info:
            sync_single_mailbox_full(1, "box1@kytranempowerment.com", "pw")
    assert exc_info.value.category == "connection"
    assert exc_info.value.address == "box1@kytranempowerment.com"


def test_auth_error_raises_mailbox_sync_error():
    """Bad credentials → imap.login raises imaplib.IMAP4.error → auth category."""
    fake_imap = mock.MagicMock()
    fake_imap.login.side_effect = imaplib.IMAP4.error("authentication failed")
    cm = mock.MagicMock()
    cm.__enter__.return_value = fake_imap
    cm.__exit__.return_value = False
    with mock.patch.object(sync_jobs.imaplib, "IMAP4_SSL", return_value=cm):
        with pytest.raises(MailboxSyncError) as exc_info:
            sync_single_mailbox_full(1, "box1@kytranempowerment.com", "pw")
    assert exc_info.value.category == "auth"


# --- run_email_imap_sync: outage raises, partial does not ---------------------


def test_full_outage_raises():
    """Every mailbox fails → EmailSyncOutageError so JobService records status=error."""
    boxes = _mailboxes(3)
    with mock.patch("database.get_db_cursor", _fake_get_db_cursor(boxes)), mock.patch.object(
        sync_jobs,
        "sync_single_mailbox_full",
        side_effect=MailboxSyncError("box@x.com", "connection", OSError("down")),
    ):
        with pytest.raises(EmailSyncOutageError):
            run_email_imap_sync()


def test_partial_failure_does_not_raise():
    """Some mailboxes fail, others succeed → no raise, accurate counts."""
    boxes = _mailboxes(3)

    def _side_effect(mailbox_id, address, password):
        if address == "box2@kytranempowerment.com":
            raise MailboxSyncError(address, "auth", imaplib.IMAP4.error("bad creds"))
        return 3

    with mock.patch("database.get_db_cursor", _fake_get_db_cursor(boxes)), mock.patch.object(
        sync_jobs, "sync_single_mailbox_full", side_effect=_side_effect
    ):
        result = run_email_imap_sync()

    assert result["errors"] == 1
    assert result["synced"] == 2
    assert result["new_messages"] == 6  # two healthy boxes × 3
    assert result["mailboxes"] == 3


def test_all_healthy_no_errors():
    """All mailboxes sync OK → errors=0, no raise."""
    boxes = _mailboxes(2)
    with mock.patch("database.get_db_cursor", _fake_get_db_cursor(boxes)), mock.patch.object(
        sync_jobs, "sync_single_mailbox_full", return_value=0
    ):
        result = run_email_imap_sync()
    assert result["errors"] == 0
    assert result["synced"] == 2


def test_empty_mailbox_list_does_not_raise():
    """No provisioned mailboxes → no outage (guard against total==0 false positive)."""
    with mock.patch("database.get_db_cursor", _fake_get_db_cursor([])), mock.patch.object(
        sync_jobs, "sync_single_mailbox_full", return_value=0
    ):
        result = run_email_imap_sync()
    assert result["errors"] == 0
    assert result["mailboxes"] == 0
