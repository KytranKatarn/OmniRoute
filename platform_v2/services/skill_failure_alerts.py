"""
skill_failure_alerts.py — Layer A Phase 1

Fires a Telegram alert when an autonomy approval queue item executes
but returns a failure result (logical failure) or raises an exception
(hard failure).

This closes the silent-failure gap where skills like linkedin_company_post
could return {"success": False, "error": "..."} into the 'executed' DB
status without any operator notification.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _send_telegram(title: str, message: str) -> None:
    """Best-effort Telegram send via telegram_service. Never raises."""
    try:
        # send_system, NOT send_warning: telegram_service has never defined send_warning
        # (its senders are send/send_agent/send_forge/send_info/send_security/send_sync/
        # send_system/send_with_buttons). The import raised ImportError on EVERY call and
        # the best-effort `except` below swallowed it, so skill-failure alerts were never
        # delivered — unmonitored while appearing monitored.
        #
        # The unit test did not catch it because it installed its own
        # types.ModuleType("services.telegram_service") stub carrying a fabricated
        # send_warning: the stub tested the mock, not the module.
        #
        # send_system takes the same (title, message) kwargs and routes through the
        # director_reports inbox — the sanctioned A.R.C.H.I.E.-voice path, so it also
        # clears the _PRIVILEGED_SOURCES guard that rejects raw send() callers.
        from services.telegram_service import send_system

        send_system(title=title, message=message)
    except Exception:
        logger.exception("[skill_failure_alerts] Telegram send failed")


def alert_on_skill_failure(
    approval_id: int,
    skill_name: str,
    execution_result: Dict[str, Any],
) -> None:
    """Fire alert if execution_result indicates failure. No-op on success.

    Success conditions (either is enough):
      - execution_result.get("success") is True
      - execution_result.get("executed") is True  AND  no "error" key present

    Everything else is treated as failure and triggers a Telegram alert.
    """
    if not execution_result:
        return

    # Treat as success if success=True
    if execution_result.get("success") is True:
        return

    # Treat as success if executed=True with no error field
    if execution_result.get("executed") is True and not execution_result.get("error"):
        return

    err = execution_result.get("error") or "(no error message)"
    status = execution_result.get("_status") or "failed"
    icon = "⏱" if status == "timeout" else "❌"

    title = f"{icon} Skill failed — {skill_name}"
    message = (
        f"Approval #{approval_id} executed but failed.\n\n"
        f"Skill: {skill_name}\n"
        f"Status: {status}\n"
        f"Error: {str(err)[:300]}\n\n"
        f"This is the silent-failure gap closed by Layer A. "
        f"Check screenshots in archie_browser:/tmp/browser_screenshots/."
    )
    _send_telegram(title=title, message=message)
