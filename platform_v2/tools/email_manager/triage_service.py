"""Email HQ — AI triage service.

Dispatches email messages to DHQ agents for priority classification.
  business mailboxes    → classify capability (action / review / info)
  owner inbox           → summarize capability (summary + priority)
  human_agent mailboxes → classify capability, but ONLY while the collaborator
                          feature is enabled (see _collaborator_triage_enabled)
  ai_agent mailboxes    → skipped (agents handle their own)

Non-blocking: triage_message_async() runs in a background thread so the
IMAP sync job does not stall on LLM inference.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_VALID_PRIORITIES = {"action", "review", "info"}

# The COLLABORATOR marker — mirrors draft_proposal_service._COLLAB_MAILBOX_TYPE
# (kept local so triage does not import the draft module at module scope).
_COLLAB_MAILBOX_TYPE = "human_agent"


def _collaborator_triage_enabled() -> bool:
    """Is collaborator (`human_agent`) mail triaged?

    Gated on the SAME `platform_settings` flag as the collaborator draft job
    (`mailhq:draft:collaborators`, default OFF) — reused, not re-implemented, so
    one switch turns the whole collaborator feature on. Triaging the 21
    collaborator mailboxes only earns its LLM cost once those drafts can fire;
    while the flag is off they are skipped exactly as before.

    Fail-safe: any lookup error keeps the pre-existing skip behaviour.
    """
    try:
        from .draft_proposal_service import _collaborators_enabled

        return _collaborators_enabled()
    except Exception as exc:
        logger.debug("[email_triage] collaborator gate lookup failed: %s", exc)
        return False


def triage_message(message_id: int) -> dict:
    """Triage one email_messages row via DHQ dispatch.

    Returns {priority, suggestion, agent_id} on success, or {error}/{skipped}.
    Updates the email_messages row with ai_priority / ai_suggestion in-place.
    """
    from database import get_db_cursor

    from .fleet_dispatch import queued_dispatch_text

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.id, m.subject, m.from_address, m.body_preview,
                      mb.mailbox_type
               FROM email_messages m
               JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE m.id = %s""",
            (message_id,),
        )
        row = cur.fetchone()

    if not row:
        return {"error": f"email_messages.id={message_id} not found"}

    mailbox_type = row["mailbox_type"]

    if mailbox_type == "owner":
        capability = "summarize"
        prompt = (
            "Summarize this email and classify its priority.\n\n"
            f"From: {row['from_address']}\n"
            f"Subject: {row['subject']}\n"
            f"Preview: {row['body_preview']}\n\n"
            'Respond as JSON: {"priority": "action|review|info", "suggestion": "<one sentence>"}'
        )
    elif mailbox_type == "business":
        capability = "classify"
        prompt = (
            "Classify the priority of this business email.\n\n"
            f"From: {row['from_address']}\n"
            f"Subject: {row['subject']}\n"
            f"Preview: {row['body_preview']}\n\n"
            'Respond as JSON: {"priority": "action|review|info", "suggestion": "<one sentence>"}'
        )
    elif mailbox_type == _COLLAB_MAILBOX_TYPE and _collaborator_triage_enabled():
        # Collaborator mail (task #4956). Without an ai_priority the collaborator
        # persona draft job can never fire — it selects on ai_priority='action'.
        # Same classify path/priorities as business mail; gated OFF by default so
        # the 21 collaborator boxes cost nothing until the feature is enabled.
        capability = "classify"
        prompt = (
            "Classify the priority of this email sent to a team member.\n\n"
            f"From: {row['from_address']}\n"
            f"Subject: {row['subject']}\n"
            f"Preview: {row['body_preview']}\n\n"
            'Respond as JSON: {"priority": "action|review|info", "suggestion": "<one sentence>"}'
        )
    else:
        return {"skipped": True, "reason": f"mailbox_type={mailbox_type} not triaged"}

    # Queue-aware dispatch: waits for a free agent (cold-load queue) instead of
    # failing synchronously, so triage actually completes on a busy/small cluster.
    response_text = queued_dispatch_text(capability=capability, prompt=prompt, json_mode=True)
    if response_text is None:
        return {"error": "dispatch failed (or queued-poll timeout)"}

    parsed = _parse_triage_json(response_text)
    if parsed is None:
        return {"error": f"unparseable triage response: {response_text[:200]}"}

    priority = parsed.get("priority", "").lower()
    if priority not in _VALID_PRIORITIES:
        priority = "info"
    suggestion = str(parsed.get("suggestion", ""))[:500]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE email_messages
               SET ai_priority = %s, ai_suggestion = %s, ai_triaged_at = %s
               WHERE id = %s""",
            (priority, suggestion, datetime.now(timezone.utc), message_id),
        )

    logger.info("[email_triage] msg=%d priority=%s", message_id, priority)
    return {"priority": priority, "suggestion": suggestion}


def triage_message_async(message_id: int) -> None:
    """Fire-and-forget triage — runs in a daemon thread."""

    def _run():
        try:
            triage_message(message_id)
        except Exception as exc:
            logger.error("[email_triage] async error for msg=%d: %s", message_id, exc)

    threading.Thread(target=_run, daemon=True).start()


def _parse_triage_json(text: str) -> dict | None:
    """Try to extract a JSON object from the LLM response."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{[^}]+\}", text)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# Triage-health alert (task #4518)
# --------------------------------------------------------------------------- #
# On 2026-06-27 triage had populated ai_priority on 0 of 121 messages EVER (the
# dispatch_json/queued masking bug, fixed PR #1948) and nothing alerted. This guards
# against that class of silent failure: if a large share of recent owner/business
# mail stays untriaged, ping the owner.
_ALERT_LAST_KEY = "mailhq:triage:alert_last"  # platform_settings — once-per-day de-dup
_HEALTH_MIN_COUNT = 5  # need at least this many recent messages to judge
_HEALTH_BAD_FRAC = 0.5  # alert when >= this fraction are untriaged
_HEALTH_GRACE_MIN = 30  # ignore mail newer than this (triage runs async, give it time)


def run_triage_health_check() -> dict:
    """Alert (at most once/day) if recent owner/business mail is largely untriaged.

    Returns a small summary for the job log. Best-effort — never raises.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT count(*) AS total,
                           count(*) FILTER (WHERE m.ai_priority IS NULL) AS untriaged
                      FROM email_messages m
                      JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                     WHERE mb.mailbox_type IN ('owner', 'business')
                       AND m.received_at >= NOW() - INTERVAL '24 hours'
                       AND m.received_at <= NOW() - INTERVAL '{_HEALTH_GRACE_MIN} minutes'"""
            )
            row = cur.fetchone() or {}
        total = int(row.get("total", 0))
        untriaged = int(row.get("untriaged", 0))
        if total < _HEALTH_MIN_COUNT:
            return {"ok": True, "total": total, "untriaged": untriaged, "alerted": False}

        frac = untriaged / total if total else 0.0
        if frac < _HEALTH_BAD_FRAC:
            return {"ok": True, "total": total, "untriaged": untriaged, "frac": round(frac, 2), "alerted": False}

        # Degraded — de-dup to once per local day.
        from services.time_utils import now_utc

        today = now_utc().strftime("%Y-%m-%d")
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (_ALERT_LAST_KEY,))
            last = cur.fetchone()
        last_val = (last["value"] if isinstance(last, dict) else last[0]) if last else None
        if last_val == today:
            return {"ok": False, "total": total, "untriaged": untriaged, "frac": round(frac, 2), "alerted": "deduped"}

        msg = (
            f"{untriaged} of {total} recent emails are untriaged (ai_priority not set). "
            "Triage dispatch may be failing — Smart Inbox priority gating, drafts and digest "
            "depend on it. Check the email triage job / DHQ dispatch."
        )
        try:
            from services.telegram_service import send

            send(
                category="warning",
                title="⚠️ Mail HQ triage degraded",
                message=msg,
                source_agent="A.R.C.H.I.E.",
                source_department="Documentation & Knowledge",
                source_module="email_manager.triage_health",
                force=True,
                voice=False,
            )
        except Exception as exc:
            logger.debug("[triage-health] telegram alert failed: %s", exc)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO system_notifications (type, title, message, created_at)
                       VALUES ('warning', %s, %s, NOW())""",
                    ("Mail HQ triage degraded", msg),
                )
                cur.execute(
                    """INSERT INTO platform_settings (key, value) VALUES (%s, %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                    (_ALERT_LAST_KEY, today),
                )
        except Exception as exc:
            logger.debug("[triage-health] notification/dedup write failed: %s", exc)

        logger.warning("[triage-health] ALERT: %d/%d recent emails untriaged (%.0f%%)", untriaged, total, frac * 100)
        return {"ok": False, "total": total, "untriaged": untriaged, "frac": round(frac, 2), "alerted": True}
    except Exception as exc:
        logger.error("[triage-health] check failed: %s", exc)
        return {"ok": True, "error": str(exc)}
