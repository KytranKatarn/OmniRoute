"""Mail HQ Smart Inbox — Slices 3 + 4: agent-drafted, approve-to-send proposals.

Slice 3 (background job `run_mailhq_draft_proposals`): for newly-triaged
**action-priority** owner/business mail with no existing proposal, dispatch
R.E.S.O.L.V.E. (DHQ `capability='support'`, local fleet) to draft a reply, then
persist the proposal as an `autonomy_approval_queue` row (`action_type='email_reply'`)
and ping the owner via A.R.C.H.I.E. on Telegram with Approve / Cancel buttons.

Slice 4 executor (`execute_email_reply`): sends the drafted reply via the shared
`send_service.send_email_via_stalwart`. Called from BOTH the Telegram approve button
(`telegram_gateway._email_callback` action `replysend`) and the DHQ web Approvals tab
(`approvals_routes._approve_autonomy`). Idempotent — a double-tap cannot double-send.

Guardrails (mailhq-smart-inbox-design.md): nothing sends without the owner's tap; all
inference via DHQ dispatch (local fleet); A.R.C.H.I.E. is the sole outbound voice; the
draft job is gated OFF by default (`platform_settings mailhq:draft:enabled`) until the
send executor has been safety-tested.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DRAFT_FLAG_KEY = "mailhq:draft:enabled"  # platform_settings; absent/false => job is a no-op
_MAX_PER_RUN = 5  # cap fleet dispatches per run (welfare-safe)
_RECENCY_HOURS = 24  # only draft for mail that arrived within this window
_DRAFT_MAILBOX_TYPES = ("owner", "business")  # never auto-draft for the 38 agent mailboxes
_DRAFT_PREVIEW_CHARS = 600  # how much of the draft to show in the Telegram advisory

# #4527 — draft-proposal retry cap / cooldown. A message whose draft dispatch keeps
# failing (a "poison" message on a busy/cold cluster, or an un-draftable body) must not
# be re-dispatched every run forever — it would burn fleet dispatch indefinitely because
# a failed attempt inserts no proposal row, so the candidate query keeps selecting it.
# Per-message attempt state lives in a self-pruning platform_settings JSON map (no
# migration; the draft job is single-instance so there is no concurrent writer).
_ATTEMPTS_KEY = "mailhq:draft:attempts"  # JSON {message_id: {"n": int, "last": iso}}
_MAX_ATTEMPTS_KEY = "mailhq:draft:max_attempts"  # tunable; default below
_COOLDOWN_MIN_KEY = "mailhq:draft:cooldown_min"  # tunable; default below
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_COOLDOWN_MIN = 60


def _setting(key: str, default: str | None = None) -> str | None:
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
    except Exception as exc:
        logger.debug("[mailhq-draft] setting lookup failed for %s: %s", key, exc)
        return default
    if not row:
        return default
    return row["value"] if isinstance(row, dict) else row[0]


def _draft_enabled() -> bool:
    return str(_setting(DRAFT_FLAG_KEY, "false") or "false").strip().lower() in ("1", "true", "on", "yes")


def _set_setting(key: str, value: str) -> None:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO platform_settings (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
            (key, value),
        )


def _int_setting(key: str, default: int) -> int:
    try:
        return int(str(_setting(key, default)).strip())
    except (ValueError, TypeError):
        return default


def _load_attempts() -> dict:
    """Load the per-message draft-attempt map from platform_settings (best-effort)."""
    raw = _setting(_ATTEMPTS_KEY, "") or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save_attempts(attempts: dict) -> None:
    try:
        _set_setting(_ATTEMPTS_KEY, json.dumps(attempts))
    except Exception as exc:  # never let bookkeeping break the job
        logger.debug("[mailhq-draft] could not persist attempts map: %s", exc)


def _parse_iso(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Slice 3 — background draft-proposal job
# --------------------------------------------------------------------------- #
def run_mailhq_draft_proposals() -> dict:
    """Scheduled job: create approve-to-send proposals for new action-priority mail.

    Returns a small summary dict for the job log. Fully isolated per message — one
    bad dispatch never aborts the batch.
    """
    if not _draft_enabled():
        return {"skipped": True, "reason": f"{DRAFT_FLAG_KEY} is off"}

    from database import get_db_cursor
    from services.time_utils import now_utc

    cutoff = now_utc() - timedelta(hours=_RECENCY_HOURS)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.id, m.subject, m.from_address, m.body_text, m.body_preview,
                      m.mailbox_id, m.thread_id, m.message_id AS rfc_message_id,
                      mb.address AS mailbox_address, mb.mailbox_type,
                      mb.display_name AS mailbox_name
                 FROM email_messages m
                 JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                WHERE m.ai_priority = 'action'
                  AND mb.mailbox_type = ANY(%s)
                  AND m.received_at >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM autonomy_approval_queue q
                       WHERE q.action_type = 'email_reply'
                         AND q.action_data->>'message_id' = m.id::text
                  )
                  -- Never auto-draft a reply to one of OUR OWN mailboxes: replying to
                  -- self re-syncs as new action mail → another proposal → reply loop.
                  AND lower(m.from_address) NOT IN (
                      SELECT lower(address) FROM email_mailboxes WHERE provisioned = TRUE
                  )
                  -- Skip no-reply / automated senders — a drafted reply is pointless.
                  AND lower(coalesce(m.from_address, '')) !~ '(no-?reply|do-?not-?reply|mailer-daemon|postmaster)@'
                ORDER BY m.received_at DESC
                LIMIT %s""",
            (list(_DRAFT_MAILBOX_TYPES), cutoff, _MAX_PER_RUN),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    # #4527 — retry cap / cooldown: skip messages that have already failed too many
    # times (poison) or that failed recently (cooldown), so one bad message can't burn
    # fleet dispatch on every run.
    attempts = _load_attempts()
    max_attempts = _int_setting(_MAX_ATTEMPTS_KEY, _DEFAULT_MAX_ATTEMPTS)
    cooldown = timedelta(minutes=_int_setting(_COOLDOWN_MIN_KEY, _DEFAULT_COOLDOWN_MIN))
    now = now_utc()

    created = 0
    capped = 0
    cooling = 0
    for c in candidates:
        mid = str(c.get("id"))
        rec = attempts.get(mid)
        if rec:
            if int(rec.get("n", 0)) >= max_attempts:
                capped += 1
                continue  # given up on this poison message until it ages out of the window
            last = _parse_iso(rec.get("last"))
            if last and (now - last) < cooldown:
                cooling += 1
                continue  # still cooling down from the last failed attempt
        try:
            ok = _create_proposal(c)
        except Exception as exc:
            logger.error("[mailhq-draft] proposal failed for msg=%s: %s", c.get("id"), exc)
            ok = False
        if ok:
            created += 1
            attempts.pop(mid, None)  # clear attempt history on success
        else:
            attempts[mid] = {"n": int((rec or {}).get("n", 0)) + 1, "last": now.isoformat()}

    # Prune entries past the recency window — those messages are no longer candidates,
    # so the attempts map can never grow unbounded.
    horizon = now - timedelta(hours=_RECENCY_HOURS)
    attempts = {k: v for k, v in attempts.items() if (_parse_iso(v.get("last")) or now) >= horizon}
    _save_attempts(attempts)

    if candidates or capped or cooling:
        logger.info(
            "[mailhq-draft] %d candidate(s) -> %d created, %d capped, %d cooling",
            len(candidates),
            created,
            capped,
            cooling,
        )
    return {"candidates": len(candidates), "created": created, "capped": capped, "cooling": cooling}


def _create_proposal(c: dict) -> bool:
    """Draft a reply for one message and enqueue an approve-to-send proposal."""
    from psycopg2.extras import Json

    from database import get_db_cursor

    from .fleet_dispatch import queued_dispatch_text

    body_snippet = (c.get("body_text") or c.get("body_preview") or "")[:1000]
    prompt = (
        "Draft a concise, professional email reply to the following message.\n\n"
        f"Mailbox: {c.get('mailbox_name')}\n"
        f"From: {c.get('from_address')}\n"
        f"Subject: {c.get('subject')}\n"
        f"Message:\n{body_snippet}\n\n"
        "Write only the reply body text — no subject line, no greeting header, "
        "no 'Here is a draft' preamble. Start directly with the reply content."
    )

    # Queue-aware dispatch: waits for a free R.E.S.O.L.V.E. agent (cold-load queue)
    # rather than failing synchronously on a busy/small cluster.
    draft = queued_dispatch_text(capability="support", prompt=prompt)
    if not draft:
        logger.warning("[mailhq-draft] draft dispatch failed/empty for msg=%s", c.get("id"))
        return False
    draft = draft.strip()
    agent = "R.E.S.O.L.V.E."  # capability='support' routes to R.E.S.O.L.V.E.

    subject = (c.get("subject") or "").strip() or "(no subject)"
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    action_data = {
        "message_id": c["id"],
        "mailbox_id": c["mailbox_id"],
        "from_address": c["mailbox_address"],  # reply FROM our mailbox
        "to_address": c["from_address"],  # TO the original sender
        "subject": reply_subject,
        "in_reply_to": c.get("rfc_message_id"),
        "thread_id": c.get("thread_id"),
        "draft_reply": draft,
        "agent": agent,
        "original_subject": subject,
    }

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO autonomy_approval_queue
                   (action_type, action_data, tier, status, priority, requested_by, reason)
               VALUES ('email_reply', %s, 2, 'pending', 5, 'mailhq', %s)
               RETURNING id""",
            (Json(action_data), f"Draft reply to {c['from_address']} re: {subject[:80]}"),
        )
        qrow = cur.fetchone()
    queue_id = qrow["id"] if isinstance(qrow, dict) else qrow[0]

    _send_proposal_buttons(queue_id, c, draft, agent)
    return True


def _send_proposal_buttons(queue_id: int, c: dict, draft: str, agent: str) -> None:
    """A.R.C.H.I.E. → Telegram: gist + draft preview + Approve/Cancel buttons.

    Single-token callback actions (`replysend` / `replycancel`) so the gateway's
    `data.split("_", 2)` parser stays correct (a 2-word action would break it).
    """
    try:
        from services.telegram_service import send_with_buttons

        preview = (draft or "").strip()[:_DRAFT_PREVIEW_CHARS]
        title = f"Reply ready · {c.get('mailbox_address')}"
        message = (
            f"From: {(c.get('from_address') or '?')[:120]}\n"
            f"Subject: {(c.get('subject') or '(no subject)')[:160]}\n\n"
            f"{agent} drafted:\n{preview}"
        )
        buttons = [
            {"text": "✅ Send", "callback_data": f"email_replysend_{queue_id}"},
            {"text": "❌ Cancel", "callback_data": f"email_replycancel_{queue_id}"},
        ]
        r = send_with_buttons(
            category="info",
            title=title,
            message=message,
            buttons=buttons,
            source_agent="A.R.C.H.I.E.",
            source_department="Customer Success & Support",
        )
        if not r.get("sent"):
            logger.warning("[mailhq-draft] button advisory not sent (%s) for q=%s", r.get("reason"), queue_id)
        # Store the Telegram message id so approving from the DHQ Approvals tab can
        # clear the phone's live buttons (_approve_autonomy echoes via this id). (#4521)
        mid = r.get("message_id")
        if mid:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE autonomy_approval_queue SET telegram_message_id = %s WHERE id = %s",
                    (mid, queue_id),
                )
    except Exception as exc:
        logger.error("[mailhq-draft] button advisory failed for q=%s: %s", queue_id, exc)


# --------------------------------------------------------------------------- #
# Slice 4 — approve-to-send executor (shared by Telegram + DHQ web)
# --------------------------------------------------------------------------- #
def execute_email_reply(queue_id: int, approved_by: int | None = None) -> dict:
    """Send the drafted reply for an `email_reply` proposal. Idempotent.

    Atomically claims the row by stamping `executed_at` (only when it is still NULL
    and the row is pending/approved) BEFORE sending, so a second approval tap finds
    nothing to claim and cannot double-send. Marks status `executed` or `failed`.
    Returns {"success": bool, ...}.
    """
    from psycopg2.extras import Json

    from database import get_db_cursor

    # Atomic claim — flip executed_at NULL -> NOW() and record who approved.
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET executed_at = NOW(), updated_at = NOW(),
                      status = 'approved',
                      approved_by = COALESCE(approved_by, %s),
                      approved_at = COALESCE(approved_at, NOW())
                WHERE id = %s
                  AND action_type = 'email_reply'
                  AND executed_at IS NULL
                  AND status IN ('pending', 'approved')
                RETURNING action_data""",
            (approved_by, queue_id),
        )
        claimed = cur.fetchone()

    if not claimed:
        # Already executing/executed, rejected/expired, missing, or wrong type.
        return {"success": False, "error": "not claimable (already handled, rejected, or missing)"}

    ad = claimed["action_data"] if isinstance(claimed, dict) else claimed[0]
    ad = ad if isinstance(ad, dict) else json.loads(ad or "{}")

    from .send_service import send_email_via_stalwart

    send_res = send_email_via_stalwart(
        from_address=ad.get("from_address"),
        to_address=ad.get("to_address"),
        subject=ad.get("subject"),
        body=ad.get("draft_reply") or "",
        in_reply_to=ad.get("in_reply_to"),
    )
    ok = bool(send_res.get("success"))

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET status = %s, execution_result = %s, updated_at = NOW()
                WHERE id = %s""",
            ("executed" if ok else "failed", Json(send_res), queue_id),
        )

    if ok:
        logger.info("[mailhq-draft] sent reply for q=%s -> %s", queue_id, ad.get("to_address"))
    else:
        logger.error("[mailhq-draft] send FAILED for q=%s: %s", queue_id, send_res.get("error"))
    return {"success": ok, "result": send_res, "to": ad.get("to_address")}


def reject_email_reply(queue_id: int, rejected_by: int | None = None) -> dict:
    """Cancel an `email_reply` proposal (owner tapped Cancel). Idempotent."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET status = 'rejected',
                      rejected_reason = 'Cancelled by owner',
                      approved_by = COALESCE(approved_by, %s),
                      updated_at = NOW()
                WHERE id = %s
                  AND action_type = 'email_reply'
                  AND status = 'pending'
                RETURNING id""",
            (rejected_by, queue_id),
        )
        row = cur.fetchone()
    return {"success": bool(row)}
