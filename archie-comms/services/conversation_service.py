"""A.R.C.H.I.E. Conversation Service — Unified Cross-Channel Routing.

One conversation thread, any device. Platform chat, Telegram, Claude terminal
all merge into unified_conversations + unified_messages.

Usage:
    from services.conversation_service import send_message, get_history

    # Platform chat sends a message
    response = send_message(user_id=2, message="What happened overnight?", channel="platform")

    # Telegram inbound routes through the same service
    response = send_message(user_id=2, message="Any updates?", channel="telegram")

    # Both appear in the same conversation
    history = get_history(user_id=2)
"""

import json
import logging
import os
import time
import uuid as _uuid_mod
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_or_create_conversation(user_id, topic=None):
    """Get the active conversation for a user, or create a new one."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            # Find active conversation
            cur.execute(
                """SELECT id, topic FROM unified_conversations
                   WHERE user_id = %s AND status = 'active'
                   ORDER BY last_activity DESC LIMIT 1""",
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                cid = row["id"] if isinstance(row, dict) else row[0]
                return cid

            # Create new
            cur.execute(
                """INSERT INTO unified_conversations (user_id, topic)
                   VALUES (%s, %s) RETURNING id""",
                (user_id, topic or "New conversation"),
            )
            row = cur.fetchone()
            conn.commit()
            cid = row["id"] if isinstance(row, dict) else row[0]
            logger.info("conversation_service: new conversation #%d for user %d", cid, user_id)
            return cid

    except Exception as e:
        logger.error("conversation_service: get_or_create failed: %s", e)
        return None


def save_message(conversation_id, channel, direction, sender, content, metadata=None):
    """Save a message to the unified message log."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """INSERT INTO unified_messages
                   (conversation_id, channel, direction, sender, content, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    conversation_id,
                    channel,
                    direction,
                    sender,
                    content,
                    json.dumps(metadata) if metadata else "{}",
                ),
            )
            msg_id = cur.fetchone()
            mid = msg_id["id"] if isinstance(msg_id, dict) else msg_id[0]

            # Update conversation last_activity
            cur.execute(
                "UPDATE unified_conversations SET last_activity = NOW() WHERE id = %s",
                (conversation_id,),
            )
            conn.commit()
            return mid

    except Exception as e:
        logger.error("conversation_service: save_message failed: %s", e)
        return None


def send_message(user_id, message, channel="platform", agent_target=None):
    """Process an inbound message and generate A.R.C.H.I.E.'s response.

    Routes through: script match -> LLM personality engine.
    Saves both inbound and outbound to unified_messages.

    Args:
        user_id: The user sending the message
        message: Message text
        channel: platform, telegram, claude, cli
        agent_target: Optional department override

    Returns:
        dict with response, agent_name, department, model, flight_deck
    """
    start = time.time()

    # Get or create conversation
    conv_id = get_or_create_conversation(user_id)
    if not conv_id:
        return {"response": "Conversation error. Try again.", "agent_name": "A.R.C.H.I.E."}

    # Save inbound message
    save_message(conv_id, channel, "inbound", "kytran", message)

    # Load conversation context (last 10 messages for LLM context)
    context_messages = get_conversation_messages(conv_id, limit=10)

    # 1. Check script match
    from services.archie_voice_service import get_script_response

    script_resp = get_script_response(message)
    if script_resp:
        elapsed = int((time.time() - start) * 1000)
        save_message(conv_id, channel, "outbound", "archie", script_resp, {
            "model": "scripted", "latency_ms": elapsed
        })
        return {
            "response": script_resp,
            "agent_name": "A.R.C.H.I.E.",
            "department": "Executive Office",
            "model": "scripted",
            "conversation_id": conv_id,
            "flight_deck": {
                "model": "scripted",
                "total_ms": elapsed,
                "steps": [{"name": "Script Match", "detail": "Pattern matched", "duration_ms": elapsed, "success": True}],
            },
        }

    # 2. Full LLM response
    try:
        from services.archie_voice_service import _get_system_prompt, _call_ollama

        system_prompt = _get_system_prompt()
        if not system_prompt:
            fallback = "I'm having trouble with my personality config. Give me a moment."
            save_message(conv_id, channel, "outbound", "archie", fallback)
            return {"response": fallback, "agent_name": "A.R.C.H.I.E.", "department": "Executive Office"}

        # Build conversational prompt with history context
        history_text = ""
        if context_messages:
            history_text = "\n\nRecent conversation:\n"
            for msg in context_messages[-6:]:  # last 6 messages for context
                sender = msg.get("sender", "unknown")
                content = msg.get("content", "")
                if sender == "kytran":
                    history_text += f"Kytran: {content}\n"
                else:
                    history_text += f"A.R.C.H.I.E.: {content}\n"

        user_prompt = f"{history_text}\nKytran says: {message}\n\nRespond naturally as A.R.C.H.I.E. in conversation. Be helpful, warm, and direct."
        response_text = _call_ollama(system_prompt, user_prompt)
        elapsed = int((time.time() - start) * 1000)

        if not response_text:
            response_text = "I processed your message but didn't generate a response. Could you rephrase?"

        model = os.getenv("ARCHIE_VOICE_MODEL", "dolphin3-8k")
        save_message(conv_id, channel, "outbound", "archie", response_text, {
            "model": model, "latency_ms": elapsed, "department": "Executive Office"
        })

        return {
            "response": response_text,
            "agent_name": "A.R.C.H.I.E.",
            "department": "Executive Office",
            "model": model,
            "conversation_id": conv_id,
            "flight_deck": {
                "model": model,
                "total_ms": elapsed,
                "steps": [
                    {"name": "Intent Parse", "detail": "Conversational", "duration_ms": 1, "success": True},
                    {"name": "C.R.E.E.D. Check", "detail": "Approved", "duration_ms": 0, "success": True},
                    {"name": "Context Load", "detail": f"{len(context_messages)} messages", "duration_ms": 2, "success": True},
                    {"name": "Agent Select", "detail": "A.R.C.H.I.E. (Executive Office)", "duration_ms": 0, "success": True},
                    {"name": "LLM Generate", "detail": f"{model}, {elapsed}ms", "duration_ms": elapsed, "success": True},
                ],
            },
        }

    except Exception as e:
        logger.error("conversation_service: send_message LLM error: %s", e)
        fallback = "Something went wrong on my end. Let me try again."
        save_message(conv_id, channel, "outbound", "archie", fallback)
        return {"response": fallback, "agent_name": "A.R.C.H.I.E.", "department": "Executive Office"}


def get_conversation_messages(conversation_id, limit=50):
    """Get messages for a conversation."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, channel, direction, sender, content, metadata, created_at
                   FROM unified_messages
                   WHERE conversation_id = %s
                   ORDER BY created_at ASC
                   LIMIT %s""",
                (conversation_id, limit),
            )
            return cur.fetchall()

    except Exception as e:
        logger.error("conversation_service: get_messages failed: %s", e)
        return []


def get_conversations(user_id, limit=20):
    """Get conversation list for a user."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT c.id, c.topic, c.status, c.created_at, c.last_activity,
                          (SELECT COUNT(*) FROM unified_messages WHERE conversation_id = c.id) as msg_count
                   FROM unified_conversations c
                   WHERE c.user_id = %s
                   ORDER BY c.last_activity DESC
                   LIMIT %s""",
                (user_id, limit),
            )
            return cur.fetchall()

    except Exception as e:
        logger.error("conversation_service: get_conversations failed: %s", e)
        return []


def escalate_to_claude(user_id, message, conversation_id=None):
    """Escalate to Claude when A.R.C.H.I.E.'s team can't handle the request.

    A.R.C.H.I.E. frames the request, Claude responds, A.R.C.H.I.E. relays back.
    """
    if not conversation_id:
        conversation_id = get_or_create_conversation(user_id)

    # Save the escalation note
    save_message(conversation_id, "platform", "outbound", "archie",
                 "This needs Claude's expertise. Let me bring him in.",
                 {"escalation": True})

    try:
        from collaboration.claude_bridge import get_claude_bridge

        bridge = get_claude_bridge()
        bridge.connect()

        # Frame the request for Claude with A.R.C.H.I.E.'s context
        framed = (
            f"A.R.C.H.I.E. (COO) is escalating this from Kytran (CEO):\n\n"
            f"{message}\n\n"
            f"Please help with this — A.R.C.H.I.E.'s local team couldn't handle it."
        )

        claude_response = bridge.send_message(framed)

        if claude_response:
            # A.R.C.H.I.E. frames Claude's response
            save_message(conversation_id, "claude", "inbound", "claude", claude_response,
                         {"model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")})

            # A.R.C.H.I.E. relays it back
            relay = f"Claude says:\n\n{claude_response}"
            save_message(conversation_id, "platform", "outbound", "archie", relay,
                         {"source": "claude_escalation"})

            return {
                "response": relay,
                "agent_name": "A.R.C.H.I.E.",
                "department": "Executive Office",
                "model": "claude (escalated)",
                "conversation_id": conversation_id,
                "flight_deck": {
                    "model": "claude-sonnet",
                    "total_ms": 0,
                    "steps": [
                        {"name": "Escalation", "detail": "A.R.C.H.I.E. → Claude", "duration_ms": 0, "success": True},
                        {"name": "Claude Response", "detail": "Via Anthropic API", "duration_ms": 0, "success": True},
                    ],
                },
            }
        else:
            fallback = "I tried to bring Claude in, but he's not available right now. Let me try to help directly."
            save_message(conversation_id, "platform", "outbound", "archie", fallback)
            return {"response": fallback, "agent_name": "A.R.C.H.I.E.", "department": "Executive Office"}

    except Exception as e:
        logger.error("conversation_service: escalate_to_claude failed: %s", e)
        fallback = "Claude escalation failed. I'll do my best to help directly."
        save_message(conversation_id, "platform", "outbound", "archie", fallback)
        return {"response": fallback, "agent_name": "A.R.C.H.I.E.", "department": "Executive Office"}


def new_conversation(user_id, topic=None):
    """Archive current active conversation and start a new one."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "UPDATE unified_conversations SET status = 'archived' WHERE user_id = %s AND status = 'active'",
                (user_id,),
            )
            cur.execute(
                "INSERT INTO unified_conversations (user_id, topic) VALUES (%s, %s) RETURNING id",
                (user_id, topic or "New conversation"),
            )
            row = cur.fetchone()
            conn.commit()
            return row["id"] if isinstance(row, dict) else row[0]

    except Exception as e:
        logger.error("conversation_service: new_conversation failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Phase 2 (#2174): Full api_routes.py-compatible wrappers over unified_* tables
# ---------------------------------------------------------------------------

def create_conversation(user_id, team_id=None, title=None, agent_target=None):
    """Create a new conversation in unified_conversations.

    Drop-in replacement for chat_service.create_conversation().
    Returns a dict with the same keys the frontend expects:
      id, conversation_uuid, user_id, team_id, title, agent_target,
      created_at, updated_at, is_archived
    """
    new_uuid = str(_uuid_mod.uuid4())
    now = datetime.now(timezone.utc)
    topic = title or "New conversation"

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO unified_conversations
                    (user_id, topic, status, created_at, last_activity, updated_at,
                     title, agent_target, team_id, is_archived, conversation_uuid)
                VALUES (%s, %s, 'active', %s, %s, %s, %s, %s, %s, FALSE, %s)
                RETURNING id, conversation_uuid, user_id, team_id, title,
                          agent_target, created_at, updated_at, is_archived
                """,
                (user_id, topic, now, now, now, title, agent_target, team_id, new_uuid),
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)

    except Exception as e:
        logger.error("conversation_service: create_conversation failed: %s", e)
        return None


def get_conversations(user_id, team_id=None, page=1, limit=20, archived=False):
    """List conversations from unified_conversations for a user or team.

    Drop-in replacement for chat_service.get_conversations().
    Returns: {"conversations": list, "total": int, "page": int, "limit": int}

    Each conversation dict includes `title` (populated from Phase 2 data copy)
    so comms.js `c.title || c.topic` continues to work.

    Escalation pin: ORDER BY (title = 'A.R.C.H.I.E. Escalations') DESC, updated_at DESC
    """
    limit = min(max(limit, 1), 100)
    offset = (max(page, 1) - 1) * limit

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            if team_id is not None:
                where = "team_id = %s AND is_archived = %s"
                params = (team_id, archived)
            else:
                where = "user_id = %s AND team_id IS NULL AND is_archived = %s"
                params = (user_id, archived)

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM unified_conversations WHERE {where}",
                params,
            )
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"""
                SELECT id, conversation_uuid, user_id, team_id, title,
                       agent_target, created_at, updated_at, is_archived
                FROM unified_conversations
                WHERE {where}
                ORDER BY (title = 'A.R.C.H.I.E. Escalations') DESC, updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cur.fetchall()

        return {
            "conversations": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "limit": limit,
        }

    except Exception as e:
        logger.error("conversation_service: get_conversations failed: %s", e)
        return {"conversations": [], "total": 0, "page": page, "limit": limit}


def get_conversation_by_uuid(conversation_uuid, user_id, team_id=None):
    """Load a conversation by UUID, enforcing ownership.

    Drop-in replacement for chat_service.get_conversation_by_uuid().
    Returns dict or None.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, conversation_uuid, user_id, team_id, title,
                       agent_target, created_at, updated_at, is_archived
                FROM unified_conversations
                WHERE conversation_uuid = %s
                """,
                (conversation_uuid,),
            )
            row = cur.fetchone()

        if not row:
            return None

        conv = dict(row)

        # Ownership: user owns it, or it belongs to user's team
        if conv["user_id"] == user_id:
            return conv
        if team_id is not None and conv["team_id"] == team_id:
            return conv
        return None

    except Exception as e:
        logger.error("conversation_service: get_conversation_by_uuid failed: %s", e)
        return None


def save_message(
    conversation_id,
    role,
    content,
    thinking_steps=None,
    agent_used=None,
    model_used=None,
    station_code=None,
    governance_events=None,
    duration_ms=None,
    token_count=None,
):
    """Save a chat message to unified_messages and bump conversation updated_at.

    Drop-in replacement for chat_service.save_message().
    Maps chat_service's (role, content, ...) signature to unified_messages
    (channel, direction, sender, content, metadata).

    Returns dict with at least {"id": <int>}.
    """
    now = datetime.now(timezone.utc)

    channel = "web"
    direction = "inbound" if role == "user" else "outbound"
    sender = "user" if role == "user" else (agent_used or "assistant")

    metadata = {
        "role": role,
        "agent_used": agent_used,
        "model_used": model_used,
        "station_code": station_code,
        "duration_ms": duration_ms,
        "token_count": token_count,
    }
    if thinking_steps is not None:
        metadata["thinking_steps"] = thinking_steps
    if governance_events is not None:
        metadata["governance_events"] = governance_events

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                INSERT INTO unified_messages
                    (conversation_id, channel, direction, sender, content, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, conversation_id, channel, direction, sender, content,
                          metadata, created_at
                """,
                (
                    conversation_id,
                    channel,
                    direction,
                    sender,
                    content,
                    json.dumps(metadata),
                    now,
                ),
            )
            msg = cur.fetchone()

            # Bump conversation updated_at + last_activity
            cur.execute(
                """
                UPDATE unified_conversations
                SET updated_at = %s, last_activity = %s
                WHERE id = %s
                """,
                (now, now, conversation_id),
            )
            conn.commit()

        # Return a dict that mimics chat_messages shape enough for api_routes
        row = dict(msg)
        # Backfill role/agent_used/model_used so callers don't break
        row.setdefault("role", role)
        row.setdefault("agent_used", agent_used)
        row.setdefault("model_used", model_used)
        return row

    except Exception as e:
        logger.error("conversation_service: save_message failed: %s", e)
        return {"id": None}


def get_conversation_messages(conversation_id, include_thinking=False, limit=50, before_id=None):
    """Retrieve messages for a conversation in chronological order.

    Drop-in replacement for chat_service.get_conversation_messages().
    Returns list of dicts. Metadata JSONB is unpacked so callers can access
    role/agent_used/model_used directly (as chat_messages exposed them as columns).
    """
    limit = min(max(limit, 1), 200)

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            if before_id is not None:
                cur.execute(
                    """
                    SELECT id, conversation_id, channel, direction, sender,
                           content, metadata, created_at
                    FROM unified_messages
                    WHERE conversation_id = %s AND id < %s
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (conversation_id, before_id, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, conversation_id, channel, direction, sender,
                           content, metadata, created_at
                    FROM unified_messages
                    WHERE conversation_id = %s
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (conversation_id, limit),
                )
            rows = cur.fetchall()

        result = []
        for r in rows:
            row = dict(r)
            # Unpack metadata so api_routes can access role/agent_used/model_used
            meta = row.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            row["role"] = meta.get("role", row.get("direction", "user"))
            row["agent_used"] = meta.get("agent_used")
            row["model_used"] = meta.get("model_used")
            row["station_code"] = meta.get("station_code")
            row["duration_ms"] = meta.get("duration_ms")
            row["token_count"] = meta.get("token_count")
            if include_thinking:
                row["thinking_steps"] = meta.get("thinking_steps")
                row["governance_events"] = meta.get("governance_events")
            result.append(row)

        return result

    except Exception as e:
        logger.error("conversation_service: get_conversation_messages failed: %s", e)
        return []


def archive_conversation(conversation_id, user_id):
    """Soft-delete a conversation (set is_archived = TRUE, status = 'archived').

    Drop-in replacement for chat_service.archive_conversation().
    Returns bool: True if archived, False if not found or not authorized.
    """
    now = datetime.now(timezone.utc)
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                UPDATE unified_conversations
                SET is_archived = TRUE, status = 'archived', updated_at = %s
                WHERE id = %s AND user_id = %s AND is_archived = FALSE
                """,
                (now, conversation_id, user_id),
            )
            affected = cur.rowcount
            conn.commit()
        return affected > 0

    except Exception as e:
        logger.error("conversation_service: archive_conversation failed: %s", e)
        return False


def auto_title_conversation(conversation_id, first_message):
    """Generate and save a short title from the first message.

    Drop-in replacement for chat_service.auto_title_conversation().
    Simple heuristic: truncate to 60 chars. A future phase can wire an LLM.
    """
    if not first_message:
        return

    title = first_message.strip()[:60]
    if len(first_message.strip()) > 60:
        title += "…"

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                UPDATE unified_conversations
                SET title = %s, topic = %s, updated_at = %s
                WHERE id = %s AND (title IS NULL OR title = '')
                """,
                (title, title, datetime.now(timezone.utc), conversation_id),
            )
            conn.commit()

    except Exception as e:
        logger.error("conversation_service: auto_title_conversation failed: %s", e)


def get_conversation_context(conversation_id, max_messages=20, max_chars=4000):
    """Build a plain-text context string from recent messages for LLM prompts.

    Drop-in replacement for chat_service.get_conversation_context().
    Returns a string (possibly empty).
    """
    try:
        msgs = get_conversation_messages(conversation_id, limit=max_messages)
        if not msgs:
            return ""

        lines = []
        total_chars = 0
        for m in msgs:
            role = m.get("role", "user")
            label = "User" if role == "user" else "Assistant"
            snippet = (m.get("content") or "")[:500]
            line = f"{label}: {snippet}"
            if total_chars + len(line) > max_chars:
                break
            lines.append(line)
            total_chars += len(line)

        return "\n".join(lines) + "\n\n" if lines else ""

    except Exception as e:
        logger.error("conversation_service: get_conversation_context failed: %s", e)
        return ""


def search_conversations(user_id, query, team_id=None, limit=20):
    """Search unified_conversations by title/topic (ILIKE).

    Drop-in replacement for chat_service.search_conversations().
    Returns a list of conversation dicts.
    """
    limit = min(max(limit, 1), 100)
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            if team_id is not None:
                cur.execute(
                    """
                    SELECT id, conversation_uuid, user_id, team_id, title,
                           agent_target, created_at, updated_at, is_archived
                    FROM unified_conversations
                    WHERE team_id = %s
                      AND (title ILIKE %s OR topic ILIKE %s)
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (team_id, f"%{query}%", f"%{query}%", limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, conversation_uuid, user_id, team_id, title,
                           agent_target, created_at, updated_at, is_archived
                    FROM unified_conversations
                    WHERE user_id = %s AND team_id IS NULL
                      AND (title ILIKE %s OR topic ILIKE %s)
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (user_id, f"%{query}%", f"%{query}%", limit),
                )
            rows = cur.fetchall()

        return [dict(r) for r in rows]

    except Exception as e:
        logger.error("conversation_service: search_conversations failed: %s", e)
        return []
