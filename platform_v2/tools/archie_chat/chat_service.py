"""
ARCHIE Chat — Core Business Logic Service

Conversation CRUD, message storage, tier-gating, and history retrieval.
All DB access uses get_db_cursor context manager with RealDictCursor.

Phase 4 (#2176): SQL re-pointed from chat_conversations + chat_messages to
unified_conversations + unified_messages. Function signatures unchanged —
routes.py and api_routes.py callers require no modification.

Metadata that has no direct unified_messages column (role, agent_used,
model_used, station_code, governance_events, duration_ms, token_count,
thinking_steps) is packed into the unified_messages.metadata JSONB field
and unpacked on read so callers continue to see the original column shape.
"""

import json
import uuid
from datetime import datetime, timezone

from database import get_db_cursor


# Tiers that grant chat access
def check_chat_access(user_id):
    """Check if user has admin access to chat.

    Only admin users are allowed. Non-admins are denied regardless of tier.

    Returns:
        dict: {"allowed": bool, "tier": str or None, "reason": str}
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (user_id,))
        user_row = cur.fetchone()
        if user_row and user_row["is_admin"]:
            return {"allowed": True, "tier": "admin", "reason": "Admin access"}

    return {"allowed": False, "tier": None, "reason": "Admin access required"}


def get_user_team_id(user_id):
    """Returns team_id=1 for admin users (shared conversation space), None otherwise."""
    access = check_chat_access(user_id)
    if access["allowed"]:
        return 1
    return None


def find_team_channel(team_id, agent_target, module_key):
    """Return the oldest non-archived team conversation for a module channel.

    Returns the first-created conversation so all admins always land in the same
    thread regardless of who created it.
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT id, conversation_uuid, title, agent_target, created_at, updated_at
            FROM unified_conversations
            WHERE team_id = %s
              AND agent_target = %s
              AND is_archived = FALSE
              AND title ILIKE %s
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (team_id, agent_target, f"%{module_key}%"),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def create_conversation(user_id, team_id=None, title=None, agent_target=None):
    """Create a new conversation thread.

    Args:
        user_id: Owner of the conversation.
        team_id: If set, conversation is shared with the team.
        title: Optional title (auto-generated later if None).
        agent_target: Optional target agent name for routing.

    Returns:
        dict with conversation details including conversation_uuid.
    """
    conversation_uuid = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    topic = title or "New conversation"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO unified_conversations
                (user_id, topic, status, created_at, last_activity, updated_at,
                 title, agent_target, team_id, is_archived, conversation_uuid)
            VALUES (%s, %s, 'active', %s, %s, %s, %s, %s, %s, FALSE, %s)
            RETURNING id, conversation_uuid, user_id, team_id, title,
                      agent_target, created_at, updated_at, is_archived
            """,
            (user_id, topic, now, now, now, title, agent_target, team_id, conversation_uuid),
        )
        row = cur.fetchone()

    return dict(row)


def get_conversations(user_id, team_id=None, page=1, limit=20, archived=False):
    """List conversations for a user or team.

    If team_id is provided, returns shared team conversations.
    Otherwise returns only the user's own conversations.

    Args:
        user_id: The requesting user.
        team_id: If set, show team-shared conversations.
        page: Page number (1-indexed).
        limit: Results per page (max 100).
        archived: If True, show archived conversations.

    Returns:
        dict: {"conversations": list, "total": int, "page": int, "limit": int}
    """
    limit = min(max(limit, 1), 100)
    offset = (max(page, 1) - 1) * limit

    with get_db_cursor(commit=False) as (conn, cur):
        if team_id is not None:
            where = "team_id = %s AND is_archived = %s"
            params = (team_id, archived)
        else:
            where = "user_id = %s AND team_id IS NULL AND is_archived = %s"
            params = (user_id, archived)

        # Count total
        cur.execute(f"SELECT COUNT(*) as cnt FROM unified_conversations WHERE {where}", params)
        total = cur.fetchone()["cnt"]

        # Fetch page
        cur.execute(
            f"""
            SELECT id, conversation_uuid, user_id, team_id, title,
                   agent_target, created_at, updated_at, is_archived
            FROM unified_conversations
            WHERE {where}
            ORDER BY updated_at DESC
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


def get_conversation_by_uuid(conversation_uuid, user_id, team_id=None):
    """Load a conversation by UUID, enforcing ownership.

    Access is granted if:
    - The user owns the conversation, OR
    - The conversation belongs to the user's team.

    Returns:
        dict or None if not found / not authorized.
    """
    with get_db_cursor(commit=False) as (conn, cur):
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

    # Ownership check: user owns it, or it belongs to their team
    if conv["user_id"] == user_id:
        return conv
    if team_id is not None and conv["team_id"] == team_id:
        return conv

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
    extra_metadata=None,
):
    """Save a chat message and update the conversation timestamp.

    Args:
        conversation_id: FK to unified_conversations.id
        role: 'user', 'assistant', or 'system'
        content: Message text content.
        thinking_steps: Optional list of reasoning steps (packed into metadata).
        agent_used: Name of the agent that handled the message.
        model_used: LLM model identifier.
        station_code: Station that handled the request.
        governance_events: Optional list of C.R.E.E.D. events (packed into metadata).
        duration_ms: Response generation time in milliseconds.
        token_count: Number of tokens used.

    Returns:
        dict with the saved message (includes backfilled role/agent_used/model_used).

    Phase 4: Writes to unified_messages. role→direction/sender mapped:
      user      → inbound,  sender='user'
      assistant → outbound, sender=agent_used or 'assistant'
      system    → outbound, sender='system'
    All chat_messages-specific columns packed into metadata JSONB.
    """
    now = datetime.now(timezone.utc)

    channel = "web"
    direction = "inbound" if role == "user" else "outbound"
    sender = "user" if role == "user" else (agent_used or role)

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
    if extra_metadata:
        metadata.update(extra_metadata)

    with get_db_cursor(commit=True) as (conn, cur):
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

    # Return a dict that mimics chat_messages shape so callers don't break
    row = dict(msg)
    row.setdefault("role", role)
    row.setdefault("agent_used", agent_used)
    row.setdefault("model_used", model_used)
    row.setdefault("station_code", station_code)
    row.setdefault("duration_ms", duration_ms)
    row.setdefault("token_count", token_count)
    return row


def get_conversation_messages(conversation_id, include_thinking=False, limit=50, before_id=None):
    """Retrieve messages for a conversation in chronological order.

    Args:
        conversation_id: The conversation to load messages for.
        include_thinking: If True, include thinking_steps in results.
        limit: Max messages to return (for pagination).
        before_id: If set, return messages with id < before_id (cursor pagination).

    Returns:
        list of message dicts. Metadata is unpacked so callers see
        role/agent_used/model_used/station_code/duration_ms/token_count
        as top-level keys (same shape as the old chat_messages columns).
    """
    limit = min(max(limit, 1), 200)

    with get_db_cursor(commit=False) as (conn, cur):
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
        # Unpack metadata so callers can access chat_messages-shaped fields
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


def archive_conversation(conversation_id, user_id):
    """Soft-delete a conversation (set is_archived = TRUE, status = 'archived').

    Only the owner can archive a conversation.

    Returns:
        bool: True if archived, False if not found or not authorized.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE unified_conversations
            SET is_archived = TRUE, status = 'archived', updated_at = %s
            WHERE id = %s AND user_id = %s AND is_archived = FALSE
            """,
            (datetime.now(timezone.utc), conversation_id, user_id),
        )
        return cur.rowcount > 0


def search_conversations(user_id, query, team_id=None, limit=20):
    """Search conversations by title/topic or message content (ILIKE).

    Args:
        user_id: The requesting user.
        query: Search text.
        team_id: If set, search team conversations instead of personal.
        limit: Max results (default 20).

    Returns:
        list of dicts with conversation_uuid, title, updated_at.
    """
    safe_query = query.replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{safe_query}%"
    limit = min(max(limit, 1), 100)

    with get_db_cursor(commit=False) as (conn, cur):
        if team_id:
            cur.execute(
                """SELECT DISTINCT c.id, c.conversation_uuid, c.title, c.updated_at
                   FROM unified_conversations c
                   LEFT JOIN unified_messages m ON m.conversation_id = c.id
                   WHERE c.team_id = %s AND c.is_archived = FALSE
                     AND (c.title ILIKE %s OR c.topic ILIKE %s OR m.content ILIKE %s)
                   ORDER BY c.updated_at DESC LIMIT %s""",
                (team_id, pattern, pattern, pattern, limit),
            )
        else:
            cur.execute(
                """SELECT DISTINCT c.id, c.conversation_uuid, c.title, c.updated_at
                   FROM unified_conversations c
                   LEFT JOIN unified_messages m ON m.conversation_id = c.id
                   WHERE c.user_id = %s AND c.team_id IS NULL AND c.is_archived = FALSE
                     AND (c.title ILIKE %s OR c.topic ILIKE %s OR m.content ILIKE %s)
                   ORDER BY c.updated_at DESC LIMIT %s""",
                (user_id, pattern, pattern, pattern, limit),
            )
        rows = cur.fetchall()

    return [
        {
            "conversation_uuid": str(r["conversation_uuid"]),
            "title": r["title"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


def get_conversation_context(conversation_id, max_messages=20, max_chars=4000):
    """Build conversation history context for AI dispatch.

    Fetches the last N messages, formats them oldest-first, and truncates
    from the oldest end when the character budget is exceeded.

    Returns a formatted string ready to prepend to the system prompt,
    or empty string if there are no prior messages.
    """
    messages = get_conversation_messages(conversation_id, limit=max_messages)

    # Exclude the very last message (the user turn just saved — already in prompt)
    # and build from oldest to newest within the char budget.
    context_parts = []
    total_chars = 0
    for msg in messages[:-1]:  # skip the message just saved
        role = msg.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        entry = f"{role}: {content}"
        if total_chars + len(entry) > max_chars:
            break
        context_parts.append(entry)
        total_chars += len(entry)

    if not context_parts:
        return ""

    return "Previous conversation:\n" + "\n".join(context_parts) + "\n\n"


def auto_title_conversation(conversation_id, first_message):
    """Auto-generate a conversation title from the first message.

    Truncates to 100 characters with ellipsis if needed.

    Args:
        conversation_id: The conversation to title.
        first_message: The user's first message text.

    Returns:
        str: The generated title.
    """
    if not first_message:
        title = "New conversation"
    elif len(first_message) <= 100:
        title = first_message.strip()
    else:
        title = first_message[:97].strip() + "..."

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE unified_conversations
            SET title = %s, topic = %s, updated_at = %s
            WHERE id = %s
            """,
            (title, title, datetime.now(timezone.utc), conversation_id),
        )

    return title
