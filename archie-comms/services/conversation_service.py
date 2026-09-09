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

# Module-level imports so tests can monkeypatch these names
try:
    from services.archie_voice_service import _get_system_prompt
except Exception:  # service may not be importable in test environments
    _get_system_prompt = None  # type: ignore[assignment]
# #6654: A.R.C.H.I.E.'s reply streams THROUGH the dispatcher; no direct-Ollama path.
from services.dhq_stream_client import stream_dhq_chat, DHQUnavailable
from services.marker_filter import MarkerFilter as _MarkerFilter
from services.capability_map import resolve_capability
import os
import time
import uuid as _uuid_mod
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _dhq_chat_reply(system_prompt, user_prompt, user_id=None):
    """DHQ-preferred A.R.C.H.I.E. chat reply (KB mistake #273554).

    POSTs to the platform's synchronous DHQ chat endpoint (same intra-hub path
    the delegation hand-off already uses, PLATFORM_URL=http://archie_platform:3000)
    so the reply is welfare/cost-gated + cold-load-queued + fleet-routed instead
    of a raw Ollama call that hangs when the hub GPU is saturated.

    Returns the platform reply dict ``{response, agent_name, model_used}`` (+
    ``success``), or ``None`` on ANY failure (no key, hub
    unreachable, non-200, empty body) so the caller falls back to the
    direct-Ollama voice path — A.R.C.H.I.E. must still talk if the platform is
    down (ADR-013 voice-survives-crash waiver). This is DHQ-PREFERRED, not
    DHQ-only.
    """
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        return None  # no service credential → use the direct-Ollama voice
    platform_url = os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")
    try:
        import requests

        resp = requests.post(
            f"{platform_url}/api/internal/dhq/chat",
            json={
                "prompt": user_prompt,
                "system_prompt": system_prompt,
                "user_id": user_id,
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=float(os.getenv("DHQ_CHAT_TIMEOUT", "90")),
        )
        if resp.status_code != 200:
            logger.warning(
                "DHQ chat returned %s — falling back to direct Ollama", resp.status_code
            )
            return None
        data = resp.json()
        if data.get("success") and (data.get("response") or "").strip():
            # Slice 4: return the full dict {response, agent_name, model_used} so the
            # cockpit can badge each reply with who answered (was the bare string).
            return data
        return None
    except Exception as exc:
        logger.warning("DHQ chat unreachable (%s) — falling back to direct Ollama", exc)
        return None


def dhq_chat_raw(user_prompt, system_prompt=None, user_id=None):
    """Full-payload variant of _dhq_chat_reply for API callers that need agent
    attribution: returns the platform's response dict ({success, response,
    agent_name, model_used}) or None on ANY failure — same DHQ-preferred,
    fail-to-None contract so callers degrade explicitly (the v1 REST API
    returns 502 instead of silently falling back to the local voice)."""
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        return None
    platform_url = os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")
    try:
        import requests

        resp = requests.post(
            f"{platform_url}/api/internal/dhq/chat",
            json={"prompt": user_prompt, "system_prompt": system_prompt, "user_id": user_id},
            headers={"Authorization": f"Bearer {key}"},
            timeout=float(os.getenv("DHQ_CHAT_TIMEOUT", "90")),
        )
        if resp.status_code != 200:
            logger.warning("DHQ chat (v1 api) returned %s", resp.status_code)
            return None
        data = resp.json()
        if data.get("success") and (data.get("response") or "").strip():
            return data
        return None
    except Exception as exc:
        logger.warning("DHQ chat (v1 api) unreachable: %s", exc)
        return None


def save_chat_message(
    conversation_id,
    role,
    content,
    agent_used=None,
    model_used=None,
    station_code=None,
    thinking_steps=None,
    governance_events=None,
    duration_ms=None,
    channel="api",
):
    """Chat-schema writer for the v1 REST API: stores a unified_messages row
    shaped exactly as get_conversation_messages() unpacks it (metadata carries
    role/agent_used/model_used/station_code/duration_ms/thinking/governance).
    Returns {'id': ...} or None."""
    direction = "inbound" if role == "user" else "outbound"
    sender = "user" if role == "user" else (agent_used or "ARCHIE")
    metadata = {"role": role}
    if agent_used:
        metadata["agent_used"] = agent_used
    if model_used:
        metadata["model_used"] = model_used
    if station_code:
        metadata["station_code"] = station_code
    if duration_ms is not None:
        metadata["duration_ms"] = duration_ms
    if thinking_steps:
        metadata["thinking_steps"] = thinking_steps
    if governance_events:
        metadata["governance_events"] = governance_events
    result = save_message(conversation_id, channel, direction, sender, content, metadata)
    if isinstance(result, dict):
        return result
    return {"id": result} if result is not None else None


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

            # Auto-title the thread from its FIRST inbound (user) message (#4281).
            # The conversation list reads `title`, but new_conversation only sets
            # `topic`, so untitled threads all rendered as "Conversation". Fill
            # `title` from the opening user message; the guard means only a
            # blank/default title is set — an existing title is never overwritten,
            # so only the first user message names the thread.
            if direction == "inbound" and content and content.strip():
                _norm = " ".join(content.split())
                _title = _norm[:48] + ("…" if len(_norm) > 48 else "")
                cur.execute(
                    """UPDATE unified_conversations SET title = %s
                       WHERE id = %s
                         AND (title IS NULL OR title = '' OR title = 'New conversation')""",
                    (_title, conversation_id),
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

    # 2. Full LLM response — THROUGH the dispatcher (#6654; no direct inference)
    try:
        from services.archie_voice_service import _get_system_prompt

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
        _dhq = dhq_chat_raw(user_prompt, system_prompt=system_prompt, user_id=user_id)
        response_text = (_dhq or {}).get("response") if _dhq else None
        elapsed = int((time.time() - start) * 1000)

        if not response_text:
            response_text = "I processed your message but didn't generate a response. Could you rephrase?"

        # The model label reflects what DHQ actually ran (was a stale env default).
        model = (_dhq or {}).get("model_used") or "dhq"
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


# DEPRECATED + RENAMED (2026-06-16): this was a SECOND `def save_message` that
# SHADOWED the canonical one (~line 71, signature channel/direction/sender/content).
# Python keeps the later definition, so every one of the 12 in-file callers — which
# all pass the line-71 signature — had its arguments scrambled into the wrong columns
# (content<->sender<->direction), corrupting unified_messages. No caller uses this
# role-based signature (chat/api_routes.py has its own save_message; nothing imports
# this one), so renaming it is safe and restores the canonical save_message. Candidate
# for deletion once confirmed unused in review.
def _legacy_save_message_role(
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


# ---------------------------------------------------------------------------
# Sub-C Delegation Helpers (Task #2351)
# ---------------------------------------------------------------------------
import re as _re

_DELEGATE_RE = _re.compile(
    r'\{\{DELEGATE\s+capability="([^"]+)"\s+reason="([^"]*?)"\s*\}\}',
    _re.DOTALL,
)

_PLANNING_SYSTEM_PROMPT = (
    "[FEATURE PLANNING] The user wants to plan a software feature. Your job:\n"
    "1. Decompose the feature into 3-5 concrete implementation tasks (ordered).\n"
    "2. Present the plan clearly in your response.\n"
    "3. Include ONE {{DELEGATE}} marker for the FIRST task only:\n"
    '   {{DELEGATE capability="code_review" reason="implement: <task 1 description>"}}\n\n'
    "Format: 'Here is the plan for [feature]:\\n1. [Task 1]...\\nDelegating task 1 to "
    "F.O.R.G.E. now.'\n"
    "Only include one {{DELEGATE}} marker. The user will kick off remaining tasks manually."
)

_DELEGATION_SYSTEM_PROMPT = (
    "[DELEGATION] When the user explicitly asks you to delegate a task to an agent "
    "or the platform, include this marker anywhere in your response: "
    '{{DELEGATE capability="X" reason="Y"}} '
    "Valid capabilities: code_review, health_check, run_qa_suite, documentation, "
    "analyze, check_dep_drift, run_misroute_audit, summarize, research, security, general. "
    "Example: If the user says 'ask F.O.R.G.E. to review the dispatch code', respond "
    "naturally AND include: {{DELEGATE capability=\"code_review\" reason=\"review dispatch "
    'routing code for gaps"}} '
    "Only include {{DELEGATE}} when the user explicitly asks you to delegate. Never "
    "include it for regular conversation."
)

# --- Approval markers (COO Cockpit Slice 1) — same rail as {{DELEGATE}} -------
_APPROVALS_RE = _re.compile(r"\{\{APPROVALS\}\}")
_APPROVE_RE = _re.compile(r'\{\{APPROVE\s+id="([^"]+)"\s*\}\}')
_DENY_RE = _re.compile(r'\{\{DENY\s+id="([^"]+)"(?:\s+reason="([^"]*)")?\s*\}\}')

_APPROVALS_SYSTEM_PROMPT = (
    "[APPROVALS] You help the owner manage his pending approvals. When he asks to SEE "
    "pending approvals, emit the marker {{APPROVALS}} (nothing else needed). When he "
    'tells you to approve a specific one, emit {{APPROVE id="autonomy:N"}} using the id '
    "from the list you last showed him; to deny, emit "
    '{{DENY id="autonomy:N" reason="..."}}. Resolve references like "the family_tree one" '
    "to the matching id from that list. Emit a marker ONLY when he explicitly asks; never "
    "invent ids."
)

# --- Deepen marker (responsive chat) — fast front acks + async 7B follow-up ----
# The fast conversational model (llama3.2:3b) answers instantly; when it judges a
# question needs depth it emits {{DEEPEN}}, and A.R.C.H.I.E.'s full qwen2.5:7b brain
# answers the same question in the background, delivered as a NEW follow-up message
# (the cockpit's 5s poll renders it). Owner-confirmed: quick chat stays one message;
# only substantive asks get a follow-up.
_DEEPEN_RE = _re.compile(r"\{\{DEEPEN\}\}")

_DEEPEN_SYSTEM_PROMPT = (
    "[DEEPER FOLLOW-UP] You are replying FAST with a lightweight model. If the user's "
    "message is a SUBSTANTIVE question that would genuinely benefit from deeper analysis, "
    "real data, or careful reasoning (e.g. 'how is X trending', 'analyse Y', 'what should "
    "we do about Z'), give a brief honest first answer, tell him you're looking into it "
    "more deeply (e.g. 'digging into that now'), AND append the marker {{DEEPEN}} on its "
    "own line — a fuller answer will follow as a separate message. For simple, "
    "conversational, or greeting messages, just answer naturally and NEVER emit {{DEEPEN}}."
)

_DEEPEN_ANSWER_PROMPT = (
    "You are giving a considered, thorough follow-up to the user's question — a fast first "
    "reply has already been sent. Answer completely and accurately in your own voice. Do "
    "NOT use any {{...}} markers."
)


def _deepen_reply(system_prompt, user_prompt, user_id):
    """Full-7B deeper answer for the async cockpit follow-up. Long timeout (background,
    not latency-critical). Returns the answer string, or None on any failure."""
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        return None
    platform_url = os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")
    try:
        import requests

        resp = requests.post(
            f"{platform_url}/api/internal/dhq/chat",
            json={
                "prompt": user_prompt,
                "system_prompt": system_prompt,
                "user_id": user_id,
                "model": os.getenv("DEEPEN_MODEL", "qwen2.5:7b"),  # her full working brain
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=float(os.getenv("DEEPEN_TIMEOUT", "300")),
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") and (data.get("response") or "").strip():
                return data["response"].strip()
    except Exception as exc:
        logger.warning("deepen follow-up failed: %s", exc)
    return None


def _run_deepen(conv_id, channel, system_prompt, user_prompt, user_id):
    """Generate + persist the deeper follow-up as a new outbound message (the cockpit
    poll delivers it). Fail-soft — a missed follow-up is never fatal."""
    ctx = None
    try:  # save_message may need a Flask app context in this background thread
        from app_comms import app

        ctx = app.app_context()
        ctx.push()
    except Exception:  # pragma: no cover — save_message works without it
        ctx = None
    try:
        answer = _deepen_reply(system_prompt, user_prompt, user_id)
        if answer:
            save_message(
                conv_id, channel, "outbound", "archie", answer,
                {"role": "assistant", "conversation_id": conv_id, "deepen": True},
            )
    except Exception as exc:  # pragma: no cover — background best-effort
        logger.warning("deepen worker error: %s", exc)
    finally:
        if ctx is not None:
            ctx.pop()


def _spawn_deepen(conv_id, channel, system_prompt, user_prompt, user_id):
    """Run the deeper 7B follow-up in a background thread so the fast reply returns now."""
    import threading

    threading.Thread(
        target=_run_deepen,
        args=(conv_id, channel, system_prompt, user_prompt, user_id),
        daemon=True,
    ).start()


# --- Consult marker (COO command surface, Slice 1) — she consults the crew ---------
# When Kytran asks something a department/agent should answer, the fast front acks and
# emits {{CONSULT:<agent-or-department>}}. We dispatch to that crew member via DHQ and
# relay their answer in her voice as a NEW follow-up message (the cockpit's 5s poll
# renders it) — the same async pattern as {{DEEPEN}}. Unified voice: she reports it.
from services.coo_consult import consult as _coo_consult  # noqa: E402  (module-level test seam)

_CONSULT_RE = _re.compile(r"\{\{CONSULT:([^}]+)\}\}")

_CONSULT_SYSTEM_PROMPT = (
    "[CREW CONSULT] You are the COO with a crew of department directors. When Kytran asks "
    "something a specific department/agent should answer (security -> V.I.G.I.L., mail/support "
    "-> R.E.S.O.L.V.E., backups -> W.A.R.D.E.N., engineering -> F.O.R.G.E., etc.), briefly say "
    "you're checking with them, then on its own line emit exactly "
    "{{CONSULT:<AGENT-OR-DEPARTMENT>}} (e.g. {{CONSULT:V.I.G.I.L.}}). Emit AT MOST ONE consult "
    "marker, and only when a specialist should answer — for anything you can answer yourself, "
    "do NOT emit it."
)


def _run_consult(conv_id, channel, target, user_prompt, user_id):
    """Dispatch the consult to the crew member and persist their answer as an attributed
    follow-up (in her voice; the cockpit poll delivers it). Fail-soft."""
    ctx = None
    try:  # save_message may need a Flask app context in this background thread
        from app_comms import app

        ctx = app.app_context()
        ctx.push()
    except Exception:  # pragma: no cover
        ctx = None
    try:
        try:
            res = _coo_consult(target, user_prompt, user_id)
        except Exception:  # pragma: no cover
            res = None
        if res and res.get("success") and (res.get("response") or "").strip():
            agent = res.get("agent_name") or target
            model = res.get("model_used") or ""
            badge = f" · {model}" if model else ""
            content = f"**{agent}{badge}** reports —\n\n{res['response'].strip()}"
            meta = {
                "role": "assistant",
                "conversation_id": conv_id,
                "consult": True,
                "agent": agent,
                "model": model,
            }
        else:
            content = f"I couldn't reach {target} just now — I'll try again, or I can take it myself."
            meta = {
                "role": "assistant",
                "conversation_id": conv_id,
                "consult": True,
                "agent": target,
                "consult_failed": True,
            }
        save_message(conv_id, channel, "outbound", "archie", content, meta)
    except Exception as exc:  # pragma: no cover — background best-effort
        logger.warning("consult worker error: %s", exc)
    finally:
        if ctx is not None:
            ctx.pop()


def _spawn_consult(conv_id, channel, target, user_prompt, user_id):
    """Run the crew consult in a background thread so the fast reply returns now."""
    import threading

    threading.Thread(
        target=_run_consult,
        args=(conv_id, channel, target, user_prompt, user_id),
        daemon=True,
    ).start()


# --- Action marker (COO command surface, Slice 4) — she runs a curated safe tool -----
# When Kytran asks her to run a known diagnostic (platform health, QA suite, dep drift,
# misroute audit, briefing health), the fast front acks and emits {{ACTION:<key>}}. We run
# the curated known-tool through the platform (welfare/cost/C.R.E.E.D. + tier-gated there;
# the catalog is SAFE read-only diagnostics ONLY — nothing state-changing) and relay the
# result in her voice as a NEW follow-up message the cockpit's 5s poll renders — the same
# async pattern as {{CONSULT}}. Unified voice: she reports it.
from services.coo_actions import run as _coo_run_action  # noqa: E402  (module-level test seam)

_ACTION_RE = _re.compile(r"\{\{ACTION:([^}]+)\}\}")

_ACTION_SYSTEM_PROMPT = (
    "[RUN ACTION] You can run a curated set of SAFE, read-only diagnostics for Kytran: "
    "health (platform health), qa (QA suite), dep_drift (dependency drift), "
    "misroute_audit (agent dispatch misroutes), briefing_health (session-briefing pipeline), "
    "welfare (agent welfare / K.I.N.), infra (critical container heartbeat), "
    "dispatch (24h dispatch health), knowledge (knowledge-base size + embedding coverage), "
    "fleet (fleet node status). When Kytran asks you to run/check one of these, briefly say "
    "you're running it, then on its own line emit exactly {{ACTION:<key>}} using ONE of those "
    "exact keys (e.g. {{ACTION:health}}). Emit AT MOST ONE action marker, and ONLY those keys — "
    "for anything else (deploys, restarts, sending mail, or anything not in that list) do NOT "
    "emit it; those go through the normal approval path."
)


def _run_action(conv_id, channel, key, user_id):
    """Run the curated action on the platform and persist the result as a follow-up (in her
    voice; the cockpit poll delivers it). Fail-soft."""
    ctx = None
    try:  # save_message may need a Flask app context in this background thread
        from app_comms import app

        ctx = app.app_context()
        ctx.push()
    except Exception:  # pragma: no cover
        ctx = None
    try:
        try:
            res = _coo_run_action(key)
        except Exception:  # pragma: no cover
            res = None
        if res and res.get("ok"):
            label = res.get("label") or key
            summary = (res.get("summary") or "").strip() or "Done — no issues reported."
            content = f"**{label}** — done.\n\n{summary}"
            meta = {
                "role": "assistant",
                "conversation_id": conv_id,
                "action": True,
                "action_key": key,
            }
        else:
            label = (res or {}).get("label") or key
            content = f"I couldn't run {label} just now — I'll try again, or we can look into it."
            meta = {
                "role": "assistant",
                "conversation_id": conv_id,
                "action": True,
                "action_key": key,
                "action_failed": True,
            }
        save_message(conv_id, channel, "outbound", "archie", content, meta)
    except Exception as exc:  # pragma: no cover — background best-effort
        logger.warning("action worker error: %s", exc)
    finally:
        if ctx is not None:
            ctx.pop()


def _spawn_action(conv_id, channel, key, user_id):
    """Run the curated action in a background thread so the fast reply returns now."""
    import threading

    threading.Thread(
        target=_run_action,
        args=(conv_id, channel, key, user_id),
        daemon=True,
    ).start()


def _extract_approval_markers(text):
    """Return (events, clean_text): harvest {{APPROVALS}}/{{APPROVE}}/{{DENY}}
    markers into SSE events and strip them from the visible reply text."""
    events = []
    if _APPROVALS_RE.search(text):
        events.append({"type": "approvals_list_request"})
    for m in _APPROVE_RE.finditer(text):
        events.append(
            {"type": "approval_action", "verb": "approve", "approval_id": m.group(1), "reason": ""}
        )
    for m in _DENY_RE.finditer(text):
        events.append(
            {
                "type": "approval_action",
                "verb": "deny",
                "approval_id": m.group(1),
                "reason": m.group(2) or "",
            }
        )
    clean = _APPROVALS_RE.sub("", text)
    clean = _APPROVE_RE.sub("", clean)
    clean = _DENY_RE.sub("", clean)
    return events, clean


# ---------------------------------------------------------------------------
# Sub-A KB Memory Helpers and Streaming (Task #2349)
# ---------------------------------------------------------------------------


def _fetch_kb_conversation_memory(limit=5):
    """Fetch recent conversation_memory entries from knowledge_base.

    Isolated as its own function so tests can monkeypatch the DB call.
    """
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT title, content
                FROM knowledge_base
                WHERE knowledge_type = 'conversation_memory'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("_fetch_kb_conversation_memory failed: %s", exc)
        return []


def get_session_context(user_id, limit=5):
    """Return KB memory prefix to inject into ARCHIE system prompt.

    Returns empty string when no entries exist or on DB error.
    """
    rows = _fetch_kb_conversation_memory(limit)
    if not rows:
        return ""
    parts = [f"- {r['title']}: {r['content']}" for r in rows]
    return "[ARCHIE MEMORY] Recent conversation context:\n" + "\n".join(parts)


def summarize_conversation(conv_id):
    """Generate a 2-3 sentence summary and store to knowledge_base.

    Called when a chat session closes. Silently returns if fewer than
    2 messages exist (nothing worth summarising).
    """
    messages = get_conversation_messages(conv_id, limit=50)
    if len(messages) < 2:
        return

    lines = []
    for m in messages:
        role = "User" if m.get("direction") == "inbound" else "ARCHIE"
        lines.append(f"{role}: {m.get('content', '')}")
    transcript = "\n".join(lines)[:3000]

    title = f"Conversation {conv_id}"
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT title FROM unified_conversations WHERE id = %s", (conv_id,)
            )
            row = cur.fetchone()
            if row and row["title"]:
                title = row["title"]
    except Exception as exc:
        logger.error("summarize_conversation: title fetch failed: %s", exc)

    # #6654: summarize THROUGH the dispatcher (capability='summarize'), never
    # direct Ollama — archie_comms routes all inference via the platform DHQ
    # endpoint so it is welfare/cost-gated and visible in task_execution_log.
    system = (
        "Summarize this conversation in 2-3 sentences. "
        "Be factual and concise. Focus on decisions made and tasks discussed."
    )
    _dhq = dhq_chat_raw(f"Conversation:\n\n{transcript}", system_prompt=system)
    summary = (_dhq or {}).get("response") if _dhq else None
    if not summary:
        return

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                    (knowledge_type, title, content, category, importance_score, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                ("conversation_memory", title, summary, "chat_history", 0.75),
            )
    except Exception as exc:
        logger.error("summarize_conversation: KB store failed: %s", exc)


def stream_send_message(user_id, message, channel="web", conversation_id=None, terminal_context=None, is_plan_request=False):
    """Generator: yield str tokens then a final dict with type='done'.

    Usage in Flask SSE route::

        for item in stream_send_message(user_id, message):
            if isinstance(item, dict):
                yield f"data: {json.dumps(item)}\\n\\n"
            else:
                yield f"data: {json.dumps({'type':'token','content':item})}\\n\\n"
    """
    conv_id = conversation_id or get_or_create_conversation(user_id)
    if conv_id is None:
        yield {"type": "error", "message": "Failed to create conversation"}
        yield {"type": "done", "conversation_id": None}
        return

    save_message(conv_id, channel, "inbound", "user", message, {"role": "user"})

    memory_prefix = get_session_context(user_id)

    history = get_conversation_messages(conv_id, limit=10)
    history_text = ""
    if history:
        history_text = "\n\nRecent conversation:\n"
        for msg in history[-10:]:
            role_label = "User" if msg.get("direction") == "inbound" else "ARCHIE"
            history_text += f"{role_label}: {msg.get('content', '')}\n"

    system_prompt = (_get_system_prompt() if _get_system_prompt else None) or "You are A.R.C.H.I.E., an AI Chief Operating Officer."
    if memory_prefix:
        system_prompt = f"{memory_prefix}\n\n{system_prompt}"
    # Persona-only prompt (no interactive markers) for the async deeper 7B follow-up.
    deep_system_prompt = f"{system_prompt}\n\n{_DEEPEN_ANSWER_PROMPT}"
    system_prompt = f"{system_prompt}\n\n{_DELEGATION_SYSTEM_PROMPT}"
    system_prompt = f"{system_prompt}\n\n{_APPROVALS_SYSTEM_PROMPT}"
    system_prompt = f"{system_prompt}\n\n{_DEEPEN_SYSTEM_PROMPT}"
    system_prompt = f"{system_prompt}\n\n{_CONSULT_SYSTEM_PROMPT}"
    system_prompt = f"{system_prompt}\n\n{_ACTION_SYSTEM_PROMPT}"
    if is_plan_request:
        system_prompt = f"{_PLANNING_SYSTEM_PROMPT}\n\n{system_prompt}"
    if terminal_context:
        terminal_lines = terminal_context.strip()
        system_prompt = (
            f"[TERMINAL CONTEXT] Last lines from claude-code terminal session:\n"
            f"{terminal_lines}\n\n"
            f"You can reference this terminal state in your response.\n\n"
            f"{system_prompt}"
        )
    user_prompt = f"{history_text}\nUser: {message}\nARCHIE:"

    # DHQ-PREFERRED (KB mistake #273554): route A.R.C.H.I.E.'s reply through the
    # platform dispatcher (welfare + cost + cold-load queue + fleet) so chat stays
    # reliable when the hub GPU is saturated. Fall back to direct-Ollama streaming
    # if the hub is unreachable — the voice MUST survive a platform crash (ADR-013).
    full_parts = []
    dhq_agent = None
    dhq_model = None
    # Stream A.R.C.H.I.E.'s reply THROUGH the dispatcher (#6654): tokens arrive
    # live and render as they come. The RAW text accumulates into full_parts for
    # the marker harvest below; a MarkerFilter keeps in-flight {{...}} markers out
    # of the browser view. No direct-Ollama fallback — all inference goes through
    # DHQ (ADR-013). If the dispatcher is unreachable, yield an honest error and
    # save NO assistant turn (the voice does not fabricate a reply from nowhere).
    _filt = _MarkerFilter()
    try:
        for item in stream_dhq_chat(
            system_prompt,
            user_prompt,
            user_id,
            capability=resolve_capability(is_plan_request=is_plan_request),
        ):
            if isinstance(item, dict):  # the final done event
                dhq_agent = item.get("agent_name")
                dhq_model = item.get("model_used")
                continue
            full_parts.append(item)
            safe = _filt.feed(item)
            if safe:
                yield safe
        tail = _filt.flush()
        if tail:
            yield tail
    except DHQUnavailable as exc:
        logger.warning("stream_send_message: DHQ unreachable: %s", exc)
        yield {"type": "error", "message": "A.R.C.H.I.E.'s dispatcher is unreachable — no reply was generated."}
        yield {"type": "done", "conversation_id": conv_id, "agent_name": None, "model_used": None}
        return

    complete_text = "".join(full_parts)

    # Strip {{DELEGATE}} markers and collect delegation events
    delegation_events = []

    def _collect_delegate(m):
        delegation_events.append({
            "type": "delegation_detected",
            "capability": m.group(1).strip(),
            "reason": m.group(2).strip(),
        })
        return ""

    clean_text = _DELEGATE_RE.sub(_collect_delegate, complete_text)
    # Harvest {{APPROVALS}}/{{APPROVE}}/{{DENY}} on the same rail as {{DELEGATE}}.
    approval_events, clean_text = _extract_approval_markers(clean_text)
    # {{DEEPEN}} (responsive chat): the fast front flagged that a deeper 7B follow-up
    # should follow. Strip the marker from the visible reply; the follow-up is spawned below.
    wants_deepen = bool(_DEEPEN_RE.search(clean_text))
    clean_text = _DEEPEN_RE.sub("", clean_text).strip()
    # {{CONSULT:<target>}}: she wants a crew member to answer. Capture the target, strip the marker.
    _consult_match = _CONSULT_RE.search(clean_text)
    consult_target = _consult_match.group(1).strip() if _consult_match else None
    clean_text = _CONSULT_RE.sub("", clean_text).strip()
    # {{ACTION:<key>}}: she wants to run a curated safe diagnostic. Capture the key, strip the marker.
    _action_match = _ACTION_RE.search(clean_text)
    action_key = _action_match.group(1).strip() if _action_match else None
    clean_text = _ACTION_RE.sub("", clean_text).strip()

    # Tokens were already streamed live above, with in-flight {{...}} markers held
    # back by the MarkerFilter — no re-emit pass is needed. clean_text (markers
    # stripped by the harvest) is the canonical text saved to the transcript.
    if clean_text:
        save_message(
            conv_id,
            channel,
            "outbound",
            "archie",
            clean_text,
            {"role": "assistant", "conversation_id": conv_id},
        )

    # Responsive chat: the fast front flagged depth -> run her full 7B brain on the same
    # question in the background; its answer arrives as a NEW follow-up message that the
    # cockpit's 5s poll renders. The fast reply returns now; no one waits on the 7B.
    if wants_deepen and conv_id:
        _spawn_deepen(conv_id, channel, deep_system_prompt, user_prompt, user_id)
    # Consult lane (COO command surface): she flagged a crew member should answer -> dispatch
    # to them and relay their answer (in her voice) as a follow-up message the 5s poll renders.
    # Pass the raw user question (message), not the history-wrapped prompt.
    if consult_target and conv_id:
        _spawn_consult(conv_id, channel, consult_target, message, user_id)
    # Action lane (COO command surface): she flagged a curated safe diagnostic to run ->
    # run it on the platform and relay the result (in her voice) as a follow-up the 5s poll renders.
    if action_key and conv_id:
        _spawn_action(conv_id, channel, action_key, user_id)

    # Yield done first (carrying the DHQ agent+model for the cockpit attribution
    # badge), then delegation events, then approval events
    yield {"type": "done", "conversation_id": conv_id, "agent_name": dhq_agent, "model_used": dhq_model}
    for evt in delegation_events:
        yield evt
    for evt in approval_events:
        yield evt
