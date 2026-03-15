"""Sends Telegram notifications for deployments and updates."""

import logging

logger = logging.getLogger(__name__)


def notify_deployment(module_name, change_type, details=""):
    """Send deployment notification via Telegram."""
    try:
        from database import get_db_cursor

        message = f"*{change_type}*: {module_name}\n{details}"

        # Insert into system_notifications for Telegram daemon to pick up
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO system_notifications (type, title, message, priority, created_at)
                VALUES ('info', %s, %s, 'normal', NOW())
                """,
                (f"{change_type}: {module_name}", message),
            )

        logger.info(f"[Deploy Notify] {change_type}: {module_name}")
    except Exception as e:
        logger.warning(f"[Deploy Notify] Failed: {e}")


def notify_test_results(module_name, passed, failed, details=""):
    """Notify about test results."""
    status = "PASSED" if failed == 0 else "FAILED"
    notify_deployment(
        module_name,
        f"Test Results {status}",
        f"Passed: {passed}, Failed: {failed}\n{details}",
    )


def notify_scan_results(file_path, issues_found, critical_count=0):
    """Notify about code scan results."""
    if critical_count > 0:
        notify_deployment(
            file_path,
            "Critical Issues Found",
            f"Total: {issues_found}, Critical: {critical_count}",
        )
