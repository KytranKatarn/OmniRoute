"""Agent chat routes — internal messaging with agents via Bridge dispatch.

Moved from tools/directory/ (Decision #431). Auth-required endpoints
for real-time agent conversations with history and rate limiting.
"""

import logging
from flask import jsonify, request
from flask_login import current_user
from functools import wraps
from database import get_db_cursor
from services.agent_service import get_agent

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple in-memory rate limiter for chat endpoints."""

    import time

    def __init__(self, per_user_limit=10, global_limit=50, window=60):
        self.per_user_limit = per_user_limit
        self.global_limit = global_limit
        self.window = window
        self.user_counts = {}
        self.global_count = 0
        self.global_window_start = self.time.time()

    def check(self, user_id):
        """Check if request is allowed. Returns (allowed, error_message)."""
        now = self.time.time()
        if now - self.global_window_start > self.window:
            self.global_count = 0
            self.global_window_start = now
        user_data = self.user_counts.get(user_id, (0, now))
        if now - user_data[1] > self.window:
            user_data = (0, now)
        if self.global_count >= self.global_limit:
            return False, "Chat system is busy. Please wait a moment."
        if user_data[0] >= self.per_user_limit:
            return False, "Please wait before sending another message."
        self.global_count += 1
        self.user_counts[user_id] = (user_data[0] + 1, user_data[1])
        return True, None


chat_rate_limiter = RateLimiter()


def _login_required_api(f):
    """API auth decorator — returns 401 JSON instead of redirect."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated


def register_chat_routes(bp, admin_required):
    """Register agent chat routes on Department HQ blueprint."""

    @bp.route("/api/chat", methods=["POST"])
    @_login_required_api
    def send_chat_message():
        """Send a message to an agent via Bridge dispatch."""
        user_id = current_user.id

        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        message = (data.get("message") or "").strip()

        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400
        if not message:
            return jsonify({"error": "message is required"}), 400
        if len(message) > 2000:
            return jsonify({"error": "Message too long (max 2000 chars)"}), 400

        allowed, error_msg = chat_rate_limiter.check(user_id)
        if not allowed:
            return jsonify({"error": error_msg}), 429

        # Check agent is online via crew manifest
        try:
            from tools.department_hq.services.bridge_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            manifest = dispatcher.get_crew_manifest()
        except Exception:
            manifest = []

        agent_manifest = None
        for member in manifest:
            mid = member.get("agent_id") or member.get("id")
            if mid == agent_id:
                agent_manifest = member
                break

        if not agent_manifest:
            return jsonify({"error": "Agent not found in roster"}), 404

        shift_state = agent_manifest.get("shift_state", "off_duty")
        if shift_state not in ("active", "deployed"):
            return jsonify({"error": f"Agent is currently {shift_state}. Try again later."}), 503

        # Get agent info via agent_service
        agent = get_agent(agent_id)
        if not agent:
            return jsonify({"error": "Agent not found"}), 404

        agent_code_name = agent["name"]
        agent_display = agent.get("display_name") or agent_code_name
        agent_title = agent.get("title") or "Team Member"
        agent_bio = agent.get("bio") or ""
        agent_department = agent.get("department") or ""
        agent_capabilities = agent.get("capabilities") or ""

        # Get or create conversation
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO directory_conversations (agent_id, user_id)
                       VALUES (%s, %s)
                       ON CONFLICT (agent_id, user_id) DO UPDATE
                       SET updated_at = now()
                       RETURNING id""",
                    (agent_id, user_id),
                )
                conversation_id = cur.fetchone()[0]
        except Exception:
            return jsonify({"error": "Failed to create conversation"}), 500

        # Store user message
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO directory_messages
                       (conversation_id, sender_type, message)
                       VALUES (%s, 'user', %s)""",
                    (conversation_id, message),
                )
        except Exception:
            return jsonify({"error": "Failed to store message"}), 500

        # Load context: last 10 messages
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT sender_type, message, timestamp
                       FROM directory_messages
                       WHERE conversation_id = %s
                       ORDER BY timestamp DESC
                       LIMIT 10""",
                    (conversation_id,),
                )
                recent_rows = cur.fetchall()
        except Exception:
            recent_rows = []

        conversation_lines = []
        for row in reversed(recent_rows):
            sender = "User" if row[0] == "user" else agent_display
            conversation_lines.append(f"{sender}: {row[1]}")
        conversation_text = "\n".join(conversation_lines)

        # Build system prompt
        system_prompt = f"You are {agent_display}, {agent_title} at Kytran Empowerment."
        if agent_bio:
            system_prompt += f" {agent_bio}"
        if agent_department:
            system_prompt += f"\nDepartment: {agent_department}"
        if agent_capabilities:
            system_prompt += f"\nCapabilities: {agent_capabilities}"
        system_prompt += (
            "\n\nYou are having a friendly, professional conversation with a team "
            "member. Be helpful, stay in character, and keep responses concise "
            "(2-3 sentences unless more detail is needed)."
        )
        if conversation_text:
            system_prompt += f"\n\n## Current conversation:\n{conversation_text}"

        # Dispatch to Bridge
        try:
            dispatcher = get_dispatcher()
            result = dispatcher.dispatch(
                prompt=message,
                system_prompt=system_prompt,
                agent_name=agent_code_name,
                user_id=user_id,
            )
            response_text = result.get("response", "Sorry, I had trouble processing that.")
        except Exception:
            response_text = "Sorry, I'm having trouble responding right now."

        # Store agent response
        resp_timestamp = None
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO directory_messages
                       (conversation_id, sender_type, message)
                       VALUES (%s, 'agent', %s)
                       RETURNING timestamp""",
                    (conversation_id, response_text),
                )
                resp_timestamp = cur.fetchone()[0]

                cur.execute(
                    """UPDATE directory_conversations
                       SET message_count = message_count + 2,
                           last_message_at = now(),
                           updated_at = now()
                       WHERE id = %s""",
                    (conversation_id,),
                )
        except Exception:
            pass

        return jsonify(
            {
                "response": response_text,
                "timestamp": resp_timestamp.isoformat() if resp_timestamp else None,
                "conversation_id": conversation_id,
            }
        )

    @bp.route("/api/chat/<int:agent_id>")
    @_login_required_api
    def get_chat_history(agent_id):
        """Return conversation history with an agent."""
        user_id = current_user.id
        offset = request.args.get("offset", 0, type=int)
        limit = request.args.get("limit", 50, type=int)
        limit = min(limit, 100)

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, last_message_at, message_count
                       FROM directory_conversations
                       WHERE agent_id = %s AND user_id = %s""",
                    (agent_id, user_id),
                )
                conv = cur.fetchone()

                if not conv:
                    return jsonify(
                        {
                            "messages": [],
                            "has_more": False,
                            "total": 0,
                            "last_message_at": None,
                            "pinned_memories": [],
                        }
                    )

                conv_id = conv[0]
                last_msg_at = conv[1]
                total = conv[2] or 0

                cur.execute(
                    """SELECT id, sender_type, message, timestamp, is_pinned
                       FROM directory_messages
                       WHERE conversation_id = %s
                       ORDER BY timestamp ASC
                       LIMIT %s OFFSET %s""",
                    (conv_id, limit, offset),
                )
                messages = [
                    {
                        "id": row[0],
                        "sender_type": row[1],
                        "message": row[2],
                        "timestamp": row[3].isoformat() if row[3] else None,
                        "is_pinned": row[4],
                    }
                    for row in cur.fetchall()
                ]

                cur.execute(
                    """SELECT message, timestamp
                       FROM directory_messages
                       WHERE conversation_id = %s AND is_pinned = true
                       ORDER BY timestamp DESC
                       LIMIT 10""",
                    (conv_id,),
                )
                pinned = [
                    {
                        "text": r[0],
                        "timestamp": r[1].isoformat() if r[1] else None,
                    }
                    for r in cur.fetchall()
                ]

                return jsonify(
                    {
                        "messages": messages,
                        "has_more": (offset + limit) < total,
                        "total": total,
                        "last_message_at": last_msg_at.isoformat() if last_msg_at else None,
                        "pinned_memories": pinned,
                    }
                )
        except Exception:
            return jsonify({"error": "Failed to load chat history"}), 500
