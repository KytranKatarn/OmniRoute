"""Mail HQ Smart Inbox — Slice 2: A.R.C.H.I.E. → Telegram advisory on new important mail.

Called from sync_single_mailbox_full after new messages are inserted. Sends ONE
coalesced advisory per mailbox per sync burst (so a flurry of mail = one ping, not
many), only for watched mailbox types, and only for recently-arrived mail (so a
first-time backfill of old messages can't trigger a notification storm).

A.R.C.H.I.E. is the single voice to the owner (services.telegram_service.send with
source_agent="A.R.C.H.I.E." is privileged). Tunable mailbox set / thresholds land in
Slice 5 (platform_settings mailhq:notify:*); v1 uses sensible hardcoded defaults.
"""

from __future__ import annotations

import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

# Slice 5: the watched mailbox types + enabled/quiet-hours come from mailhq_settings
# (platform_settings). These two stay as code constants (display/guard tuning).
_RECENCY_HOURS = 2  # ignore mail older than this (guards against first-sync backfill)
_MAX_LISTED = 3  # in a coalesced advisory, list at most this many subjects


def notify_new_mail(mailbox_id: int, address: str, new_msgs: list[dict]) -> None:
    """Advise the owner (via A.R.C.H.I.E. on Telegram) about newly-arrived important mail.

    new_msgs: list of {"from": str, "subject": str, "received_at": datetime|None}.
    Best-effort + fully isolated — a notification failure must never break mail sync.
    """
    try:
        if not new_msgs:
            return

        from . import mailhq_settings

        # Slice 5 tunables: advisory on/off + quiet hours. Mail suppressed by quiet
        # hours still surfaces in the daily digest, so nothing is lost.
        if not mailhq_settings.notify_enabled() or mailhq_settings.in_quiet_hours():
            return

        # Watched mailbox types only.
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT mailbox_type FROM email_mailboxes WHERE id = %s", (mailbox_id,))
            row = cur.fetchone()
        mtype = (row or {}).get("mailbox_type") or ""
        if mtype not in mailhq_settings.notify_mailbox_types():
            return

        # Recency guard — only mail that actually just arrived.
        recent = []
        try:
            from services.time_utils import now_utc

            cutoff = now_utc() - timedelta(hours=_RECENCY_HOURS)
            for m in new_msgs:
                ra = m.get("received_at")
                if ra is None or ra >= cutoff:
                    recent.append(m)
        except Exception:
            recent = list(new_msgs)  # if tz math is unavailable, don't drop mail
        if not recent:
            return

        # Build a coalesced message.
        n = len(recent)
        if n == 1:
            m = recent[0]
            title = f"New email · {address}"
            body = f"From: {(m.get('from') or '?').strip()[:120]}\nSubject: {(m.get('subject') or '(no subject)').strip()[:160]}"
        else:
            title = f"{n} new emails · {address}"
            lines = []
            for m in recent[:_MAX_LISTED]:
                frm = (m.get("from") or "?").strip()[:48]
                subj = (m.get("subject") or "(no subject)").strip()[:80]
                lines.append(f"• {frm} — {subj}")
            if n > _MAX_LISTED:
                lines.append(f"…and {n - _MAX_LISTED} more")
            body = "\n".join(lines)

        import threading

        def _deliver() -> None:
            try:
                from services.telegram_service import send

                r = send(
                    category="info",
                    title=title,
                    message=body,
                    source_agent="A.R.C.H.I.E.",
                    source_department="Customer Success & Support",
                    source_module="email_manager.notify_service",
                    force=True,  # coalesced already → safe to bypass the per-category throttle
                    voice=False,  # fast template, NO LLM dispatch — must never block mail sync
                )
                if not r.get("sent"):
                    logger.debug("[mailhq-notify] advisory not sent (%s) for %s", r.get("reason"), address)
            except Exception as exc:
                logger.debug("[mailhq-notify] advisory send failed for %s: %s", address, exc)

        # Fire-and-forget: the IDLE/sync thread must not wait on Telegram delivery.
        threading.Thread(target=_deliver, daemon=True, name=f"mailhq-notify-{mailbox_id}").start()
    except Exception as exc:
        logger.debug("[mailhq-notify] advisory failed for mailbox %s (%s): %s", mailbox_id, address, exc)
