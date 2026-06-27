"""Email HQ — AI triage service.

Dispatches email messages to DHQ agents for priority classification.
  business mailboxes → classify capability (action / review / info)
  owner inbox        → summarize capability (summary + priority)
  ai_agent mailboxes → skipped (agents handle their own)

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
