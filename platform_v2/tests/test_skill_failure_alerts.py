"""
tests/test_skill_failure_alerts.py — Unit tests for skill_failure_alerts.py

3 cases:
  1. success=True  → no alert
  2. executed=True, no error → no alert
  3. success=False with error → alert fired
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub out telegram_service so the module can be imported without the full
# platform stack.
# ---------------------------------------------------------------------------
telegram_stub = types.ModuleType("services.telegram_service")
telegram_stub.send_warning = MagicMock()
sys.modules.setdefault("services.telegram_service", telegram_stub)

# Now import the module under test
from services.skill_failure_alerts import alert_on_skill_failure  # noqa: E402


class TestAlertOnSkillFailure(unittest.TestCase):

    def setUp(self):
        telegram_stub.send_warning.reset_mock()

    # ------------------------------------------------------------------
    # Case 1 — success=True → no Telegram call
    # ------------------------------------------------------------------
    def test_no_alert_on_success_true(self):
        alert_on_skill_failure(
            approval_id=1,
            skill_name="linkedin_post",
            execution_result={"success": True, "url": "https://linkedin.com/feed/update/123"},
        )
        telegram_stub.send_warning.assert_not_called()

    # ------------------------------------------------------------------
    # Case 2 — executed=True, no error → no Telegram call
    # ------------------------------------------------------------------
    def test_no_alert_on_executed_true_no_error(self):
        alert_on_skill_failure(
            approval_id=2,
            skill_name="linkedin_company_post",
            execution_result={"executed": True, "post_id": "urn:li:share:999"},
        )
        telegram_stub.send_warning.assert_not_called()

    # ------------------------------------------------------------------
    # Case 3 — success=False + error present → alert fires
    # ------------------------------------------------------------------
    def test_alert_fires_on_failure(self):
        alert_on_skill_failure(
            approval_id=42,
            skill_name="linkedin_company_post",
            execution_result={
                "success": False,
                "error": "LinkedIn API returned 401 Unauthorized",
                "_status": "failed",
            },
        )
        telegram_stub.send_warning.assert_called_once()
        call_kwargs = telegram_stub.send_warning.call_args
        # Accept both positional and keyword invocations
        if call_kwargs.kwargs:
            title = call_kwargs.kwargs.get("title", "")
            message = call_kwargs.kwargs.get("message", "")
        else:
            title, message = call_kwargs.args[0], call_kwargs.args[1]

        self.assertIn("linkedin_company_post", title)
        self.assertIn("42", message)
        self.assertIn("401 Unauthorized", message)

    # ------------------------------------------------------------------
    # Case 4 (bonus) — exception path dict → alert fires
    # ------------------------------------------------------------------
    def test_alert_fires_on_exception_dict(self):
        alert_on_skill_failure(
            approval_id=99,
            skill_name="send_email",
            execution_result={"success": False, "error": "Connection refused", "_status": "exception"},
        )
        telegram_stub.send_warning.assert_called_once()
        call_kwargs = telegram_stub.send_warning.call_args
        if call_kwargs.kwargs:
            title = call_kwargs.kwargs.get("title", "")
        else:
            title = call_kwargs.args[0]
        self.assertIn("❌", title)


if __name__ == "__main__":
    unittest.main()
