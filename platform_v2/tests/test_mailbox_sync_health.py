"""#5849 — per-mailbox sync-health indicator (migration 481).

The owner mailbox failed IMAP auth for 9 days (2026-08-19 -> 08-28) while
rendering identically to a healthy mailbox, because sync outcomes lived only in
scheduler log lines. These tests pin the whole visibility chain: the pure
predicate, the sync-loop stamping, the API payload, and the JS renderer —
the K.I.N.-tab lesson (#5157) is that any ONE missing link makes it invisible.
"""

import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.email_manager.mailbox_routes import _sync_broken

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


class TestSyncBrokenPredicate:
    def test_error_newer_than_success_is_broken(self):
        assert _sync_broken(_NOW - timedelta(hours=1), _NOW) is True

    def test_success_newer_than_error_is_healthy(self):
        assert _sync_broken(_NOW, _NOW - timedelta(hours=1)) is False

    def test_error_with_no_success_ever_is_broken(self):
        assert _sync_broken(None, _NOW) is True

    def test_no_stamps_at_all_is_fail_safe_healthy(self):
        # fresh deploy / stamping disabled must NOT page as broken
        assert _sync_broken(None, None) is False
        assert _sync_broken(_NOW, None) is False


class TestVisibilityChainWiring:
    def test_sync_loop_stamps_success_and_failure(self):
        from tools.email_manager import sync_jobs

        src = inspect.getsource(sync_jobs)
        assert "last_sync_ok_at = NOW()" in src, "success stamp missing"
        assert "last_sync_error = %s, last_sync_error_at = NOW()" in src, "failure stamp missing"
        # success must CLEAR the error, else a healed mailbox stays flagged forever
        assert "last_sync_error = NULL, last_sync_error_at = NULL" in src

    def test_list_endpoint_selects_and_derives(self):
        from tools.email_manager import mailbox_routes

        src = inspect.getsource(mailbox_routes)
        assert "m.last_sync_ok_at, m.last_sync_error, m.last_sync_error_at" in src
        assert 'r["sync_broken"] = _sync_broken(' in src
        # derive BEFORE isoformat conversion — datetime compare, never string compare
        assert src.index('r["sync_broken"]') < src.index("r[k] = r[k].isoformat()")

    def test_renderer_reads_the_flag(self):
        js = Path(__file__).resolve().parents[1] / "static" / "js" / "email-manager.js"
        src = js.read_text()
        assert "m.sync_broken" in src, "UI must consume the flag"
        assert "SYNC BROKEN" in src

    def test_migration_exists_and_is_idempotent(self):
        import pytest

        mig = Path(__file__).resolve().parents[2] / "database" / "migrations" / "481_email_mailbox_sync_health.sql"
        if not mig.exists():
            # in-container /app mounts platform_v2 only; the migrations tree lives
            # at the repo root and is visible on host runs
            pytest.skip("migrations tree not mounted in this environment")
        src = mig.read_text()
        assert src.count("ADD COLUMN IF NOT EXISTS") == 3
