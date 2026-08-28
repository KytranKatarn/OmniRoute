"""
tests/test_skill_failure_alerts.py — Unit tests for skill_failure_alerts.py

3 cases:
  1. success=True  → no alert
  2. executed=True, no error → no alert
  3. success=False with error → alert fired
"""

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub out telegram_service so the module can be imported without the full
# platform stack.
# ---------------------------------------------------------------------------
# Deliberately NOT a sys.modules stub. The previous version installed a bare
# types.ModuleType carrying a fabricated `send_warning`, which production does not and
# never did define — so this suite asserted against its own invention while the real alert
# path was dead (see services/skill_failure_alerts.py). Patch the REAL module instead: an
# attribute that disappears from production now breaks the test, which is the point.

# Now import the module under test
from services.skill_failure_alerts import alert_on_skill_failure  # noqa: E402


class TestAlertOnSkillFailure(unittest.TestCase):

    def setUp(self):
        # Patch the REAL telegram_service attribute. If production stops exporting
        # send_system, patch() raises AttributeError here and this suite fails loudly —
        # which is exactly what the old fabricated-stub version could never do.
        self._patcher = patch("services.telegram_service.send_system", MagicMock(return_value={"sent": True}))
        self._send_system = self._patcher.start()
        self.addCleanup(self._patcher.stop)

    # ------------------------------------------------------------------
    # Case 1 — success=True → no Telegram call
    # ------------------------------------------------------------------
    def test_no_alert_on_success_true(self):
        alert_on_skill_failure(
            approval_id=1,
            skill_name="linkedin_post",
            execution_result={"success": True, "url": "https://linkedin.com/feed/update/123"},
        )
        self._send_system.assert_not_called()

    # ------------------------------------------------------------------
    # Case 2 — executed=True, no error → no Telegram call
    # ------------------------------------------------------------------
    def test_no_alert_on_executed_true_no_error(self):
        alert_on_skill_failure(
            approval_id=2,
            skill_name="linkedin_company_post",
            execution_result={"executed": True, "post_id": "urn:li:share:999"},
        )
        self._send_system.assert_not_called()

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
        self._send_system.assert_called_once()
        call_kwargs = self._send_system.call_args
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
        self._send_system.assert_called_once()
        call_kwargs = self._send_system.call_args
        if call_kwargs.kwargs:
            title = call_kwargs.kwargs.get("title", "")
        else:
            title = call_kwargs.args[0]
        self.assertIn("❌", title)


if __name__ == "__main__":
    unittest.main()
