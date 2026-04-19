"""
ARCHIE Chat — REST API Endpoints

All chat endpoints: messaging, conversations, agents, stations, API keys.
Registered via register_routes(bp, admin_required) pattern (ADR-045).
"""

import logging
import time

from flask import request, jsonify

from .auth_middleware import (
    chat_auth_required,
    get_chat_user,
    generate_api_key,
    check_rate_limit,
)
from .chat_service import (
    check_chat_access,
    get_user_team_id,
)
from services.conversation_service import (
    create_conversation,
    get_conversations,
    get_conversation_by_uuid,
    save_message,
    get_conversation_messages,
    archive_conversation,
    auto_title_conversation,
    get_conversation_context,
)

log = logging.getLogger(__name__)

# Canonical 10 stations with colors and capabilities
STATIONS = [
    {
        "code": "COMMAND",
        "name": "Command",
        "color": "#00e5ff",
        "capabilities": ["orchestration", "oversight", "strategy"],
    },
    {
        "code": "ANALYTICS",
        "name": "Analytics",
        "color": "#8b5cf6",
        "capabilities": ["data_analysis", "reporting", "insights"],
    },
    {
        "code": "CREATIVE",
        "name": "Creative",
        "color": "#f472b6",
        "capabilities": ["content_creation", "design", "media"],
    },
    {
        "code": "ENGINEERING",
        "name": "Engineering",
        "color": "#fbbf24",
        "capabilities": ["code_generation", "debugging", "architecture"],
    },
    {
        "code": "COMMUNICATIONS",
        "name": "Communications",
        "color": "#22d3ee",
        "capabilities": ["messaging", "translation", "outreach"],
    },
    {
        "code": "RESEARCH",
        "name": "Research",
        "color": "#10b981",
        "capabilities": ["knowledge_retrieval", "summarization", "learning"],
    },
    {
        "code": "SECURITY",
        "name": "Security",
        "color": "#ef4444",
        "capabilities": ["threat_detection", "audit", "compliance"],
    },
    {
        "code": "LOGISTICS",
        "name": "Logistics",
        "color": "#f97316",
        "capabilities": ["scheduling", "resource_management", "planning"],
    },
    {
        "code": "DIPLOMATIC",
        "name": "Diplomatic",
        "color": "#818cf8",
        "capabilities": ["negotiation", "ethics", "governance"],
    },
    {
        "code": "OPERATIONS",
        "name": "Operations",
        "color": "#a3e635",
        "capabilities": ["system_ops", "monitoring", "automation"],
    },
]


def _error(code, message, status=400):
    """Return a standardised error JSON response."""
    return jsonify({"success": False, "error": {"code": code, "message": message}}), status


def _serialize_datetime(obj):
    """Convert datetime fields in a dict to ISO-8601 strings."""
    if obj is None:
        return None
    out = {}
    for k, v in obj.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def register_routes(bp, admin_required):
    """Register all chat API routes on the given blueprint."""

    # ------------------------------------------------------------------
    # 1. POST /api/v1/chat/message — Send message, get orchestrated response
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/message", methods=["POST"])
    @chat_auth_required
    def send_message():
        start = time.time()
        user = get_chat_user()
        user_id = user["id"]

        # Tier check
        access = check_chat_access(user_id)
        if not access["allowed"]:
            return _error("TIER_REQUIRED", access["reason"], 403)

        # Parse body
        body = request.get_json(silent=True) or {}
        message = (body.get("message") or "").strip()
        if not message:
            return _error("VALIDATION_ERROR", "Message cannot be empty", 400)

        conversation_id_param = body.get("conversation_id")  # UUID string or None
        agent_target = body.get("agent_target")
        include_thinking = bool(body.get("include_thinking", True))

        # Rate limit for API key users
        if user.get("auth_method") == "api_key":
            if not check_rate_limit(user_id, user.get("rate_limit", 30)):
                return _error("RATE_LIMITED", "Rate limit exceeded. Try again shortly.", 429)

        # Load or create conversation
        team_id = get_user_team_id(user_id)
        conv = None
        if conversation_id_param:
            conv = get_conversation_by_uuid(conversation_id_param, user_id, team_id)
            if not conv:
                return _error("NOT_FOUND", "Conversation not found or access denied", 404)
        else:
            conv = create_conversation(user_id, team_id=team_id, agent_target=agent_target)

        # Save user message
        user_msg = save_message(conv["id"], "user", message)

        # Auto-title from first message (only when conversation was just created)
        if not conversation_id_param:
            auto_title_conversation(conv["id"], message)

        # Default to ARCHIE when no agent targeted (she's primary on COMMAND)
        effective_target = agent_target if agent_target and agent_target != "auto" else "ARCHIE"

        # Build conversation context for multi-turn memory (up to 20 msgs / 4000 chars)
        conv_context = get_conversation_context(conv["id"], max_messages=20, max_chars=4000)

        # Build structured history list for orchestration engine (newest excluded — already in prompt)
        recent_messages = get_conversation_messages(conv["id"], include_thinking=False, limit=20)
        conversation_history = []
        for m in recent_messages[:-1]:  # exclude the user message just saved
            if m["role"] in ("user", "assistant") and m.get("content"):
                conversation_history.append({"role": m["role"], "content": m["content"][:500]})

        # Prepend conversation title + context to the message for the AI
        title_prefix = ""
        if conv.get("title") and conversation_id_param:
            title_prefix = f"[This conversation is about: {conv['title']}]\n\n"
        contextual_message = f"{title_prefix}{conv_context}{message}" if (title_prefix or conv_context) else message

        # Call orchestration engine
        # TODO: route through platform HTTP API (archie-comms standalone — no direct bridge access)
        try:
            raise NotImplementedError("archie-comms: orchestration not yet wired to platform API")
        except NotImplementedError as exc:
            log.exception("Orchestration failed: %s", exc)
            return _error("ORCHESTRATION_ERROR", "Failed to generate response", 500)

        # Look up agent display_name and station_code
        agent_display_name = None
        agent_station = None
        if result.agent_used:
            try:
                from database import get_db_cursor as _gc

                with _gc() as (conn, cur):
                    cur.execute(
                        """SELECT a.display_name, sa.station_code
                           FROM agents a
                           LEFT JOIN station_assignments sa
                               ON sa.agent_id = a.id AND sa.is_active = TRUE
                           WHERE a.name = %s LIMIT 1""",
                        (result.agent_used,),
                    )
                    row = cur.fetchone()
                    if row:
                        agent_display_name = row["display_name"]
                        agent_station = row["station_code"]
            except Exception:
                log.warning("Failed to look up agent display info for %s", result.agent_used)

        duration_ms = int((time.time() - start) * 1000)

        # Save assistant message
        governance_dicts = (
            [
                {"event_type": g.event_type, "timestamp": g.timestamp, "details": g.details}
                for g in result.governance_events
            ]
            if result.governance_events
            else None
        )
        thinking_dicts = (
            [
                {"step_type": s.step_type, "label": s.label, "duration_ms": s.duration_ms, "success": s.success}
                for s in result.thinking_steps
            ]
            if result.thinking_steps
            else None
        )

        assistant_msg = save_message(
            conv["id"],
            "assistant",
            result.response,
            thinking_steps=thinking_dicts,
            agent_used=result.agent_used,
            model_used=result.model_used,
            station_code=agent_station,
            governance_events=governance_dicts,
            duration_ms=duration_ms,
        )

        # Cross-session memory: ingest conversation for knowledge retrieval
        # TODO: route through platform HTTP API (archie-comms standalone)
        # from ai_bridge.conversation_ingest import ingest_conversation

        # Build response
        response_data = {
            "success": True,
            "conversation_id": str(conv["conversation_uuid"]),
            "message_id": assistant_msg["id"],
            "response": result.response,
            "agent": {
                "name": result.agent_used,
                "display_name": agent_display_name,
                "station": agent_station,
            },
            "model_used": result.model_used,
            "duration_ms": duration_ms,
        }

        if include_thinking and thinking_dicts:
            response_data["thinking_steps"] = thinking_dicts

        if governance_dicts:
            response_data["governance_events"] = governance_dicts

        # KB augmentation: attach knowledge sources used
        include_knowledge = bool(body.get("include_knowledge", False))
        if include_knowledge:
            # TODO: route through platform HTTP API (archie-comms standalone)
            # from ai_bridge.knowledge_retrieval import get_relevant_knowledge
            response_data["knowledge_used"] = []

        return jsonify(response_data), 200

    # ------------------------------------------------------------------
    # 2. GET /api/v1/chat/conversations — List conversations
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations", methods=["GET"])
    @chat_auth_required
    def list_conversations():
        user = get_chat_user()
        user_id = user["id"]

        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        archived = request.args.get("archived", "false").lower() == "true"

        team_id = get_user_team_id(user_id)
        result = get_conversations(user_id, team_id=team_id, page=page, limit=limit, archived=archived)

        return (
            jsonify(
                {
                    "success": True,
                    "conversations": [_serialize_datetime(c) for c in result["conversations"]],
                    "total": result["total"],
                    "page": result["page"],
                    "limit": result["limit"],
                }
            ),
            200,
        )

    # ------------------------------------------------------------------
    # 3. POST /api/v1/chat/conversations — Create new conversation
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations", methods=["POST"])
    @chat_auth_required
    def create_new_conversation():
        user = get_chat_user()
        user_id = user["id"]

        access = check_chat_access(user_id)
        if not access["allowed"]:
            return _error("TIER_REQUIRED", access["reason"], 403)

        body = request.get_json(silent=True) or {}
        title = (body.get("title") or "").strip() or None
        agent_target = body.get("agent_target")

        team_id = get_user_team_id(user_id)
        conv = create_conversation(user_id, team_id=team_id, title=title, agent_target=agent_target)

        return (
            jsonify(
                {
                    "success": True,
                    "conversation": _serialize_datetime(conv),
                }
            ),
            201,
        )

    # ------------------------------------------------------------------
    # 4. GET /api/v1/chat/conversations/<uuid>/messages — Get history
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations/<string:conv_uuid>/messages", methods=["GET"])
    @chat_auth_required
    def get_messages(conv_uuid):
        user = get_chat_user()
        user_id = user["id"]
        team_id = get_user_team_id(user_id)

        conv = get_conversation_by_uuid(conv_uuid, user_id, team_id)
        if not conv:
            return _error("NOT_FOUND", "Conversation not found or access denied", 404)

        include_thinking = request.args.get("include_thinking", "true").lower() != "false"
        limit = request.args.get("limit", 50, type=int)
        before_id = request.args.get("before", None, type=int)

        messages = get_conversation_messages(
            conv["id"],
            include_thinking=include_thinking,
            limit=limit,
            before_id=before_id,
        )

        return (
            jsonify(
                {
                    "success": True,
                    "conversation_id": str(conv["conversation_uuid"]),
                    "messages": [_serialize_datetime(m) for m in messages],
                }
            ),
            200,
        )

    # ------------------------------------------------------------------
    # 5. DELETE /api/v1/chat/conversations/<int:id> — Archive conversation
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations/<int:conv_id>", methods=["DELETE"])
    @chat_auth_required
    def delete_conversation(conv_id):
        user = get_chat_user()
        user_id = user["id"]

        success = archive_conversation(conv_id, user_id)
        if not success:
            return _error("NOT_FOUND", "Conversation not found or already archived", 404)

        return jsonify({"success": True, "message": "Conversation archived"}), 200

    # ------------------------------------------------------------------
    # 6. GET /api/v1/chat/agents — List available agents
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/agents", methods=["GET"])
    @chat_auth_required
    def list_agents():
        try:
            from database import get_db_cursor as _gc

            with _gc() as (conn, cur):
                cur.execute(
                    """
                    SELECT a.id, a.name, a.display_name,
                           a.shift_state, a.department, a.model
                    FROM agents a
                    WHERE a.shift_state IN ('active', 'deployed')
                    ORDER BY a.department, a.display_name
                    """
                )
                rows = cur.fetchall()

            agents = []
            for r in rows:
                agents.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "display_name": r["display_name"],
                        "department": r["department"],
                        "model": r["model"],
                        "shift_state": r["shift_state"],
                    }
                )

            return jsonify({"success": True, "agents": agents}), 200
        except Exception as exc:
            log.exception("Failed to list agents: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to retrieve agents", 500)

    # ------------------------------------------------------------------
    # 7. GET /api/v1/chat/stations — Return 10 stations
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/stations", methods=["GET"])
    @chat_auth_required
    def list_stations():
        return jsonify({"success": True, "stations": STATIONS}), 200

    # ------------------------------------------------------------------
    # 8. POST /api/v1/chat/keys — Generate API key (admin only)
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/keys", methods=["POST"])
    @chat_auth_required
    def create_api_key():
        user = get_chat_user()
        if not user.get("is_admin"):
            return _error("AUTH_FAILED", "Admin access required", 403)
        body = request.get_json(silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return _error("VALIDATION_ERROR", "Key name is required", 400)

        rate_limit = body.get("rate_limit", 30)
        if not isinstance(rate_limit, int) or rate_limit < 1 or rate_limit > 1000:
            rate_limit = 30

        try:
            result = generate_api_key(user["id"], name, rate_limit)
            return (
                jsonify(
                    {
                        "success": True,
                        "key": result["key"],
                        "key_id": result["key_id"],
                        "prefix": result["prefix"],
                        "message": "Store this key securely. It will not be shown again.",
                    }
                ),
                201,
            )
        except Exception as exc:
            log.exception("Failed to create API key: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to create API key", 500)

    # ------------------------------------------------------------------
    # 9. GET /api/v1/chat/keys — List user's API keys
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/keys", methods=["GET"])
    @chat_auth_required
    def list_api_keys():
        user = get_chat_user()
        try:
            from database import get_db_cursor as _gc

            with _gc() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, key_prefix, name, rate_limit,
                           is_active, created_at, last_used_at
                    FROM chat_api_keys
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (user["id"],),
                )
                rows = cur.fetchall()

            keys = [_serialize_datetime(dict(r)) for r in rows]
            return jsonify({"success": True, "keys": keys}), 200
        except Exception as exc:
            log.exception("Failed to list API keys: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to retrieve API keys", 500)

    # ------------------------------------------------------------------
    # 10. DELETE /api/v1/chat/keys/<int:id> — Revoke API key
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/keys/<int:key_id>", methods=["DELETE"])
    @chat_auth_required
    def revoke_api_key(key_id):
        user = get_chat_user()
        try:
            from database import get_db_cursor as _gc

            with _gc() as (conn, cur):
                cur.execute(
                    """
                    UPDATE chat_api_keys
                    SET is_active = FALSE
                    WHERE id = %s AND user_id = %s AND is_active = TRUE
                    """,
                    (key_id, user["id"]),
                )
                if cur.rowcount == 0:
                    return _error("NOT_FOUND", "API key not found or already revoked", 404)

            return jsonify({"success": True, "message": "API key revoked"}), 200
        except Exception as exc:
            log.exception("Failed to revoke API key: %s", exc)
            return _error("INTERNAL_ERROR", "Failed to revoke API key", 500)

    # ------------------------------------------------------------------
    # 11. GET /api/v1/chat/conversations/search — Search conversations
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/conversations/search", methods=["GET"])
    @chat_auth_required
    def search_convos():
        user = get_chat_user()
        query = request.args.get("q", "").strip()
        if not query:
            return _error("VALIDATION_ERROR", "Query required", 400)
        team_id = get_user_team_id(user["id"])

        from services.conversation_service import search_conversations

        results = search_conversations(user["id"], query, team_id)
        return jsonify({"success": True, "results": results}), 200

    # ------------------------------------------------------------------
    # 12. GET /api/v1/chat/knowledge/search — Direct KB search
    # ------------------------------------------------------------------
    @bp.route("/api/v1/chat/knowledge/search", methods=["GET"])
    @chat_auth_required
    def search_knowledge():
        query = request.args.get("q", "").strip()
        if not query:
            return _error("VALIDATION_ERROR", "Query required", 400)
        limit = min(request.args.get("limit", 10, type=int), 50)
        # TODO: route through platform HTTP API (archie-comms standalone)
        # from ai_bridge.knowledge_retrieval import get_relevant_knowledge
        try:
            return (
                jsonify(
                    {
                        "success": True,
                        "query": query,
                        "results": [],
                    }
                ),
                200,
            )
        except Exception as e:
            log.error("KB search failed: %s", e)
            return _error("ORCHESTRATION_FAILED", str(e)[:200], 500)
