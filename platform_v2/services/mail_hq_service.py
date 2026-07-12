"""COO command surface — Mail HQ read + draft + queue-for-send (Slice 3). Reads the
owner/business inbox (email_messages), drafts via R.E.S.O.L.V.E., and queues a reply into the
EXISTING approve-to-send gate (autonomy_approval_queue, action_type='email_reply'). NEVER sends
directly — the Approvals panel / Telegram [Send/Cancel] + execute_email_reply do that."""

from __future__ import annotations

_OWNER_TYPES = ("owner", "business", "human_agent")


def _get_cursor():
    from database import get_db_cursor

    return get_db_cursor


def list_inbox(limit=40, mailbox_id=None):
    q = (
        "SELECT em.id, em.mailbox_id, mb.address AS mailbox_address, em.from_address, em.subject, "
        "em.body_preview, em.received_at, em.is_read, em.ai_priority "
        "FROM email_messages em JOIN email_mailboxes mb ON mb.id = em.mailbox_id "
        "WHERE mb.active = TRUE AND mb.mailbox_type = ANY(%s)"
    )
    params = [list(_OWNER_TYPES)]
    if mailbox_id:
        q += " AND em.mailbox_id = %s"
        params.append(int(mailbox_id))
    q += " ORDER BY em.received_at DESC LIMIT %s"
    params.append(int(limit))
    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(q, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("received_at") is not None:
            d["received_at"] = str(d["received_at"])
        out.append(d)
    return out


def read_message(message_id):
    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(
            "SELECT em.id, em.mailbox_id, mb.address AS mailbox_address, mb.mailbox_type, "
            "em.from_address, em.to_address, em.subject, em.body_text, em.body_html, "
            "em.received_at, em.ai_priority, em.ai_suggestion, em.message_id "
            "FROM email_messages em JOIN email_mailboxes mb ON mb.id = em.mailbox_id "
            "WHERE em.id = %s",
            (int(message_id),),
        )
        row = cur.fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("received_at") is not None:
        d["received_at"] = str(d["received_at"])
    return d


def draft_reply(message_id):
    """R.E.S.O.L.V.E. AI draft reply (DHQ dispatch, capability='support'). Returns {draft, agent} or None."""
    msg = read_message(message_id)
    if not msg:
        return None
    from tools.department_hq.services.department_dispatcher import dispatch

    prompt = (
        "You are R.E.S.O.L.V.E., Customer Success. Draft a concise, professional reply to this email "
        "in the owner's voice. Return only the reply body, no preamble.\n"
        f"From: {msg.get('from_address')}\nSubject: {msg.get('subject')}\n\n"
        f"{(msg.get('body_text') or msg.get('body_preview') or '')[:2000]}\n\nReply:"
    )
    try:
        res = dispatch(capability="support", prompt=prompt, prefer_agent="R.E.S.O.L.V.E.", local_only=True)
        if getattr(res, "success", False) and (res.response or "").strip():
            return {"draft": res.response.strip(), "agent": res.agent_name or "R.E.S.O.L.V.E."}
    except Exception:
        pass
    return None


def queue_reply(message_id, body):
    """Create a GATED email_reply approval (autonomy_approval_queue). Does NOT send — the existing
    approve-to-send gate (Telegram / Slice-1 Approvals panel) executes it. Returns {queued, approval_id}."""
    body = (body or "").strip()
    if not body:
        return None
    from psycopg2.extras import Json

    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT em.mailbox_id, em.from_address, em.subject, em.message_id, em.thread_id, "
            "mb.address AS our_address FROM email_messages em "
            "JOIN email_mailboxes mb ON mb.id = em.mailbox_id WHERE em.id = %s",
            (int(message_id),),
        )
        m = cur.fetchone()
        if not m:
            return None
        m = dict(m)
        subject = m.get("subject") or ""
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        action_data = {
            "message_id": int(message_id),
            "mailbox_id": m.get("mailbox_id"),
            "from_address": m.get("our_address"),
            "to_address": m.get("from_address"),
            "subject": subject,
            "in_reply_to": m.get("message_id"),
            "thread_id": m.get("thread_id"),
            "draft_reply": body,
            "agent": "R.E.S.O.L.V.E.",
            "original_subject": m.get("subject"),
        }
        cur.execute(
            "INSERT INTO autonomy_approval_queue (action_type, action_data, tier, status, priority, "
            "requested_by, reason) VALUES ('email_reply', %s, 2, 'pending', 5, 'cockpit', %s) RETURNING id",
            (Json(action_data), f"Cockpit Mail HQ reply to {m.get('from_address')}"),
        )
        approval_id = cur.fetchone()["id"]
    return {"queued": True, "approval_id": approval_id}
