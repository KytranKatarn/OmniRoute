"""mailbox_chat_service.py — ingest AI chat conversations (ChatGPT/Claude) into the
Mailbox Story Extractor, so they ride the SAME pipeline as emails: each chat message becomes
a mailbox_emails row, then the existing enrichment + story workers process them via the DHQ
dispatcher (capability='analyze', local_only=True — welfare-gated). No new dispatch path.

Two entry points:
  * ingest_chat(title, messages, owner_id) — messages = [(role, text, datetime|None), ...]
  * ingest_export_file(path, owner_id, title_filter) — parse a ChatGPT/Claude data export
    (conversations.json or .zip) and ingest each conversation. The COMPLETE history.

This is the platform-side counterpart of the `chat-capture` skill: the skill renders/parses,
this service lands the result in the product where A.R.C.H.I.E.'s agents enrich it.
"""

import json
import logging
import os
import zipfile
from datetime import datetime, timezone

from database import get_db_cursor

logger = logging.getLogger(__name__)

_BODY_CAP = 100_000


def _to_dt(v):
    """Normalize ChatGPT epoch float / Claude ISO string -> aware UTC datetime, else None."""
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        s = str(v).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _parts_text(content):
    if not isinstance(content, dict):
        return ""
    out = []
    for p in content.get("parts") or []:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            out.append(p.get("text") or f"[{p.get('content_type', 'attachment')}]")
    return "\n".join(x for x in out if x).strip()


def _chatgpt_messages(conv):
    msgs = []
    for node in (conv.get("mapping") or {}).values():
        m = (node or {}).get("message")
        if not m:
            continue
        role = ((m.get("author") or {}).get("role")) or "unknown"
        if role == "system":
            continue
        text = _parts_text(m.get("content"))
        if text:
            msgs.append((m.get("create_time") or 0, role, text))
    msgs.sort(key=lambda x: x[0] or 0)
    return [(r, t, _to_dt(ct)) for ct, r, t in msgs]


def _claude_messages(conv):
    out = []
    for m in conv.get("chat_messages") or []:
        role = "user" if m.get("sender") == "human" else (m.get("sender") or "assistant")
        text = m.get("text") or ""
        if not text and m.get("content"):
            text = "\n".join(c.get("text", "") for c in m["content"] if isinstance(c, dict))
        for a in m.get("attachments") or []:
            text += f"\n[attachment: {a.get('file_name', 'file')}]"
        if text.strip():
            out.append((role, text.strip(), _to_dt(m.get("created_at"))))
    return out


def ingest_chat(title, messages, owner_id=None):
    """Insert one chat conversation as a mailbox import + per-message rows. Returns import_id.
    `messages` = list of (role, text, datetime|None). Status 'extracted' so the enrichment
    worker (DHQ local-only) picks it up exactly like extracted email."""
    title = (title or "chat").strip()
    if not messages:
        return None
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """INSERT INTO mailbox_imports (owner_id, filename, stored_path, status, email_count)
               VALUES (%s, %s, %s, 'extracted', %s) RETURNING id""",
            (owner_id, f"chat: {title}"[:255], "chat", len(messages)),
        )
        import_id = cur.fetchone()["id"]
        for role, text, ts in messages:
            subj = (text or "").strip().splitlines()[0][:120] if (text or "").strip() else "(empty)"
            cur.execute(
                """INSERT INTO mailbox_emails
                       (import_id, folder, from_addr, to_addrs, sent_at, subject, body_text, has_attachments)
                   VALUES (%s, %s, %s, NULL, %s, %s, %s, false)""",
                (import_id, title[:200], role, ts, subj, (text or "")[:_BODY_CAP]),
            )
    logger.info("mailbox chat ingest: import %s '%s' (%d messages)", import_id, title, len(messages))
    return import_id


def ingest_export_file(path, owner_id=None, title_filter=None):
    """Parse a ChatGPT/Claude export (conversations.json or .zip) and ingest each conversation.
    Returns a list of (import_id, title, n_messages). Raises ValueError on a bad file."""
    if not os.path.exists(path):
        raise ValueError(f"file not found: {path}")
    try:
        if path.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
                if not name:
                    raise ValueError("no conversations.json inside the zip")
                data = json.loads(z.read(name))
        else:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
    except (json.JSONDecodeError, zipfile.BadZipFile, OSError, UnicodeDecodeError) as e:
        raise ValueError(f"could not read export ({type(e).__name__}): {e}")

    convs = data if isinstance(data, list) else [data]
    out = []
    tf = (title_filter or "").lower()
    for conv in convs:
        if not isinstance(conv, dict):
            continue
        title = conv.get("title") or conv.get("name") or "conversation"
        if tf and tf not in title.lower():
            continue
        if "mapping" in conv:
            msgs = _chatgpt_messages(conv)
        elif "chat_messages" in conv:
            msgs = _claude_messages(conv)
        else:
            continue
        iid = ingest_chat(title, msgs, owner_id=owner_id)
        if iid:
            out.append((iid, title, len(msgs)))
    return out
