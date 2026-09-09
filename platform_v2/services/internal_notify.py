"""The ONE internal-notify implementation (#6657).

Two ``/api/internal/notify`` handlers existed: app.py's (platform notification +
Telegram in A.R.C.H.I.E.'s voice for high/urgent) and account_center's (a
different env var, X-Internal-Key only, FAILED OPEN when unset, Telegram always,
KBS-only wording). Both routes stay — KBS depends on the account-center path —
but they now share this body.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def send_internal_notify(data: dict, *, default_source: str = "media_hub", default_title: str = "Notification") -> dict:
    """Create a platform notification; speak it on Telegram when asked or urgent.

    Body: {title, message, priority?(low|normal|high|urgent), source?, telegram?(bool)}.
    Never raises — a notify path must not turn a caller's alert into a 500.
    """
    data = data or {}
    title = (data.get("title") or default_title).strip()
    message = (data.get("message") or "").strip()
    priority = (data.get("priority") or "normal").strip().lower()
    source = (data.get("source") or default_source).strip()
    want_tg = bool(data.get("telegram")) or priority in ("high", "urgent")
    if not message:
        return {"ok": False, "error": "message is required"}
    try:
        from services.notification_service import create_notification

        create_notification(
            notification_type="warning" if priority in ("high", "urgent") else "info",
            title=title,
            message=message,
            source=source,
            priority=priority,
            visibility="all",
        )
    except Exception as exc:  # noqa: BLE001 - a broken notification store must not lose the Telegram leg
        logger.error("internal notify: create_notification failed: %s", exc)
    tg = False
    if want_tg:
        try:
            from services import telegram_service

            # Always A.R.C.H.I.E.'s voice — she is the single outbound channel for
            # every agent and product (feedback_archie-as-unified-voice).
            telegram_service.send_info(title, message, priority=priority)
            tg = True
        except Exception as exc:  # noqa: BLE001
            logger.error("internal notify: telegram send failed: %s", exc)
    return {"ok": True, "telegram": tg}
