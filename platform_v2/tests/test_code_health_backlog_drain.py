"""Tests for the Code Health backlog-drain job (#4942).

The job is welfare-gated (default OFF), fix-generation only (deploy stays
human-gated), and drains the STANDING code_health proposal backlog every few
hours regardless of new-issue discovery. Batch size + interval are
platform_settings-tunable (no deploy).
"""

from unittest.mock import MagicMock, patch

from tools.department_hq import jobs


def test_drain_disabled_does_not_dispatch():
    """DEFAULT OFF: when the work-control toggle is off, no fleet dispatch happens."""
    with patch("services.work_control_service.is_enabled", return_value=False), patch(
        "services.audit_pipeline.dispatch_audit_proposals"
    ) as m_disp:
        jobs.code_health_backlog_drain_job()
    m_disp.assert_not_called()


def test_drain_enabled_dispatches_with_tunable_limit():
    """When enabled, dispatches up to the tunable max_fixes and logs the outcome."""
    with patch("services.work_control_service.is_enabled", return_value=True), patch(
        "tools.department_hq.jobs._drain_int_setting", return_value=15
    ) as m_set, patch(
        "services.audit_pipeline.dispatch_audit_proposals",
        return_value={"dispatched": 3, "failed": 0, "skipped": 0},
    ) as m_disp, patch(
        "tools.department_hq.jobs._log_cycle"
    ) as m_log:
        jobs.code_health_backlog_drain_job()
    m_disp.assert_called_once_with(limit=15)
    m_set.assert_called_with("work:code_health_backlog_drain:max_fixes", 15)
    args = m_log.call_args[0]
    assert args[0] == "code_health_backlog_drain"
    assert args[1] == 3  # items_processed == dispatched count


def test_drain_int_setting_default_when_missing():
    """A missing platform_settings key falls back to the default (read-only, real DB)."""
    assert jobs._drain_int_setting("work:code_health_backlog_drain:__no_such_key__", 15) == 15


def test_drain_int_setting_reads_and_parses():
    """A present setting value is read and parsed to an int, floored at 1."""
    fake_cur = MagicMock()
    fake_cur.fetchone.return_value = {"value": "7"}

    class _FakeCtx:
        def __enter__(self):
            return (MagicMock(), fake_cur)

        def __exit__(self, *a):
            return False

    with patch("database.get_db_cursor", return_value=_FakeCtx()):
        assert jobs._drain_int_setting("any:key", 15) == 7
