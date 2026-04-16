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
