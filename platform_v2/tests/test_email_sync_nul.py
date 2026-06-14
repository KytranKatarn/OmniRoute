"""Unit test for the email IMAP sync NUL-byte fix.

A message containing a NUL byte (0x00) — common in spam / bounce-back / DSN mail —
made the email_messages INSERT raise "A string literal cannot contain NUL (0x00)
characters", which sync_single_mailbox_full swallowed as `return 0` (reported as
success). The bad message sat at the front of the unsynced queue and re-failed
every cycle, freezing ALL mail sync since 2026-06-11. _strip_nul removes NUL so
the insert never aborts; per-message try/except keeps one bad message from
killing the whole mailbox.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_email_sync_nul.py -v
"""

from tools.email_manager.sync_jobs import _strip_nul


def test_strips_nul_from_string():
    assert _strip_nul("hello\x00world") == "helloworld"


def test_strips_multiple_nuls():
    assert _strip_nul("\x00a\x00b\x00") == "ab"


def test_clean_string_unchanged():
    assert _strip_nul("normal subject line") == "normal subject line"


def test_none_passes_through():
    assert _strip_nul(None) is None


def test_non_string_passes_through():
    assert _strip_nul(12345) == 12345


def test_empty_string_unchanged():
    assert _strip_nul("") == ""
