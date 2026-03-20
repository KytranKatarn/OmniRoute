"""Directory chat routes — auth-required endpoints for status and messaging."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "ai_bridge"))

from flask import jsonify, request
from flask_login import current_user, login_required
from functools import wraps
from .helpers import chat_rate_limiter


def login_required_api(f):
    """API auth decorator — returns 401 JSON instead of redirect."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)

    return decorated


def register_chat_routes(bp, admin_required):
    """Register auth-gated directory routes."""

    @bp.route("/api/directory/status")
    @login_required_api
    def get_agent_status():
        """Get live roster status for all agents."""
        try:
            from bridge_dispatcher import get_crew_manifest

            manifest = get_crew_manifest()
        except Exception:
            manifest = []

        status_map = {}
        for member in manifest:
            agent_id = member.get("agent_id") or member.get("id")
            if agent_id:
                model_loaded = member.get("model_loaded", False)
                shift_state = member.get("shift_state", "off_duty")
                is_online = shift_state == "active" and model_loaded
                status_map[str(agent_id)] = {
                    "is_online": is_online,
                    "status": "Online" if is_online else "Off Duty",
                    "chat_available": is_online,
                    "shift_state": shift_state,
                }

        return jsonify({"status": status_map})

    @bp.route("/api/directory/chat", methods=["POST"])
    @login_required_api
    def send_chat_message():
        """Send a message to an agent via Bridge dispatch."""
        from database import get_db_cursor

        user_id = current_user.id

        # --- Validate input ---
        data = request.get_json(silent=True) or {}
        agent_id = data.get("agent_id")
        message = (data.get("message") or "").strip()

        if not agent_id:
            return jsonify({"error": "agent_id is required"}), 400
        if not message:
            return jsonify({"error": "message is required"}), 400
        if len(message) > 2000:
            return jsonify({"error": "Message too long (max 2000 chars)"}), 400

        # --- Rate limit ---
        allowed, error_msg = chat_rate_limiter.check(user_id)
        if not allowed:
            return jsonify({"error": error_msg}), 429

        # --- Check agent is online via crew manifest ---
        try:
            from bridge_dispatcher import get_crew_manifest

            manifest = get_crew_manifest()
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
        model_loaded = agent_manifest.get("model_loaded", False)
        if not (shift_state == "active" and model_loaded):
            return (
                jsonify({"error": "Agent is currently offline. Try again later."}),
                503,
            )

        # --- Get agent info from DB ---
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, name, display_name, title, bio, capabilities,
                              department, station_code
                       FROM agents WHERE id = %s""",
                    (agent_id,),
                )
                agent_row = cur.fetchone()
        except Exception:
            return jsonify({"error": "Failed to look up agent"}), 500

        if not agent_row:
            return jsonify({"error": "Agent not found"}), 404

        agent_code_name = agent_row[1]  # agents.name — what Bridge expects
        agent_display = agent_row[2] or agent_code_name
        agent_title = agent_row[3] or "Team Member"
        agent_bio = agent_row[4] or ""
        agent_capabilities = agent_row[5] or ""
        agent_department = agent_row[6] or ""

        # --- Get or create conversation (UPSERT) ---
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

        # --- Store user message ---
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

        # --- Load context: last 10 messages ---
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

        # Build conversation history (oldest first)
        conversation_lines = []
        for row in reversed(recent_rows):
            sender = "User" if row[0] == "user" else agent_display
            conversation_lines.append(f"{sender}: {row[1]}")
        conversation_text = "\n".join(conversation_lines)

        # --- Build system prompt ---
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

        # --- Dispatch to Bridge ---
        try:
            from bridge_dispatcher import get_dispatcher

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

        # --- Store agent response ---
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

                # Update conversation counters
                cur.execute(
                    """UPDATE directory_conversations
                       SET message_count = message_count + 2,
                           last_message_at = now(),
                           updated_at = now()
                       WHERE id = %s""",
                    (conversation_id,),
                )
        except Exception:
            pass  # Response was generated, just counter update failed

        return jsonify(
            {
                "response": response_text,
                "timestamp": resp_timestamp.isoformat() if resp_timestamp else None,
                "conversation_id": conversation_id,
            }
        )

    @bp.route("/api/directory/chat/<int:agent_id>")
    @login_required_api
    def get_chat_history(agent_id):
        """Return conversation history with an agent."""
        from database import get_db_cursor

        user_id = current_user.id
        offset = request.args.get("offset", 0, type=int)
        limit = request.args.get("limit", 50, type=int)
        limit = min(limit, 100)  # Cap at 100

        try:
            with get_db_cursor() as (conn, cur):
                # Get conversation
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

                # Get messages
                cur.execute(
                    """SELECT id, sender_type, message, timestamp, is_pinned
                       FROM directory_messages
                       WHERE conversation_id = %s
                       ORDER BY timestamp ASC
                       LIMIT %s OFFSET %s""",
                    (conv_id, limit, offset),
                )
                rows = cur.fetchall()

                messages = []
                for row in rows:
                    messages.append(
                        {
                            "id": row[0],
                            "sender_type": row[1],
                            "message": row[2],
                            "timestamp": row[3].isoformat() if row[3] else None,
                            "is_pinned": row[4],
                        }
                    )

                # Get pinned messages as memories
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
