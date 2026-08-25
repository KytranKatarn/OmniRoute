import pytest
from unittest.mock import patch, MagicMock


def _make_mock_cursor():
    """Return a mock get_backup_db_cursor context manager."""
    from datetime import datetime, timezone

    class MockCur:
        def __init__(self):
            self._q = 0

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            self._q += 1
            if self._q == 1:  # Latest backup query
                return {
                    "file_path": "/backups/test",
                    "created_at": datetime(2026, 5, 8, 6, 0, tzinfo=timezone.utc),
                    "size_bytes": 1024 * 1024,
                }
            if self._q == 2:  # Total count
                return {"cnt": 5}
            if self._q == 4:  # Failures in 24h
                return {"cnt": 0}
            return None

        def fetchall(self):
            self._q += 1
            if self._q == 3:  # Standalones
                return []
            return []

    class MockCtx:
        def __enter__(self):
            return (None, MockCur())

        def __exit__(self, *a):
            pass

    return MockCtx()


def test_briefing_contains_required_sections():
    from tools.archie_chat.warden_briefing import _build_warden_briefing

    with patch("tools.backup_manager._shared.get_backup_db_cursor") as mock_db, patch(
        "os.path.exists", return_value=False
    ), patch("tools.backup_manager._shared.get_backup_retention_status", return_value={"delete_count": 0}):
        mock_db.return_value = _make_mock_cursor()
        result = _build_warden_briefing()

    assert "DEPARTMENT BRIEFING" in result
    assert "Latest backup" in result
    assert "Retention" in result
    assert "Backup lock" in result
    assert "End briefing" in result


def test_briefing_marks_partial_standalones():
    from tools.archie_chat.warden_briefing import _build_warden_briefing
    from datetime import datetime, timezone

    standalone_rows = [
        {
            "standalone_name": "gov_watch",
            "status": "success",
            "created_at": datetime(2026, 5, 8, 6, 0, tzinfo=timezone.utc),
        },
        {"standalone_name": "kso", "status": "partial", "created_at": datetime(2026, 5, 8, 5, 0, tzinfo=timezone.utc)},
    ]

    class FakeCur:
        def __init__(self):
            self._q = 0

        def execute(self, *a):
            pass

        def fetchone(self):
            self._q += 1
            if self._q == 1:
                return {
                    "file_path": "/backups/test",
                    "created_at": datetime(2026, 5, 8, 6, 0, tzinfo=timezone.utc),
                    "size_bytes": 1024 * 1024,
                }
            if self._q == 2:
                return {"cnt": 5}
            if self._q == 4:
                return {"cnt": 0}
            return None

        def fetchall(self):
            self._q += 1
            if self._q == 3:
                return standalone_rows
            return []

    class FakeCtx:
        def __enter__(self):
            return (None, FakeCur())

        def __exit__(self, *a):
            pass

    # NOTE: get_backup_retention_status is no longer patched — production does not call it.
    # #2438 deleted that call deliberately; warden_briefing.py says why, in its own words:
    # the delete_count was "a RETIRED single-triple pruner's projection for a policy the
    # system does not enforce". The real engine is scripts/backup/retention_prune.py,
    # per-component and per-tier. Patching a function nobody calls only hides that.
    with patch("tools.backup_manager._shared.get_backup_db_cursor", return_value=FakeCtx()), patch(
        "os.path.exists", return_value=False
    ):
        result = _build_warden_briefing()

    assert "⚠️" in result
    assert "kso" in result
    assert "✅" in result
    assert "gov_watch" in result

    # The briefing reports the CANONICAL engine and the last real prune.
    assert "Retention: automatic" in result

    # ANTI-REGRESSION: this test used to assert "2 backup(s) eligible for pruning" — a
    # projection from the retired pruner. Asserting its ABSENCE is what stops the fiction
    # coming back; restoring that line would mean surfacing a number nothing enforces.
    assert "eligible for pruning" not in result
