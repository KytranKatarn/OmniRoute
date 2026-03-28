"""Chat routes for live chat widget and agent interface."""

import logging

from flask import g, jsonify, request
from flask_login import current_user, login_required

from core.chat_manager import ChatManager
from core.tenant import require_module

logger = logging.getLogger(__name__)

_chat_manager = ChatManager()


def register_chat_routes(bp):
    """Attach chat routes to the blueprint."""

    # ------------------------------------------------------------------
    # Public widget endpoints (no login required)
    # ------------------------------------------------------------------

    @bp.route("/api/chat/start", methods=["POST"])
    def chat_start():
        """Start a new chat conversation from the widget."""
        data = request.get_json(force=True)
        tenant_id = data.get("tenant_id")
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        conv = _chat_manager.start_conversation(
            tenant_id=tenant_id,
            visitor_name=data.get("visitor_name"),
            visitor_email=data.get("visitor_email"),
        )
        return jsonify(conv), 201

    @bp.route("/api/chat/<int:conversation_id>/message", methods=["POST"])
    def chat_send_message(conversation_id):
        """Send a message in a chat conversation (visitor or agent)."""
        data = request.get_json(force=True)
        tenant_id = data.get("tenant_id")
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        try:
            msg = _chat_manager.add_message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                sender_type=data.get("sender_type", "visitor"),
                content=data.get("content", ""),
                sender_name=data.get("sender_name"),
            )
            return jsonify(msg), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/api/chat/<int:conversation_id>/messages", methods=["GET"])
    def chat_get_messages(conversation_id):
        """Poll for messages in a conversation (REST polling)."""
        tenant_id = request.args.get("tenant_id", type=int)
        if not tenant_id:
            return jsonify({"error": "tenant_id required"}), 400

        since = request.args.get("since")
        messages = _chat_manager.get_messages(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            since=since,
        )
        return jsonify({"messages": messages})

    # ------------------------------------------------------------------
    # Agent-side endpoints (login required)
    # ------------------------------------------------------------------

    @bp.route("/api/chat/active", methods=["GET"])
    @login_required
    @require_module("communications")
    def chat_active():
        """List all active chat conversations for the agent dashboard."""
        convs = _chat_manager.get_active_conversations(tenant_id=g.tenant_id)
        return jsonify({"conversations": convs})

    @bp.route("/api/chat/<int:conversation_id>/reply", methods=["POST"])
    @login_required
    @require_module("communications")
    def chat_agent_reply(conversation_id):
        """Agent sends a reply to a chat conversation."""
        data = request.get_json(force=True)
        content = data.get("content", "").strip()
        if not content:
            return jsonify({"error": "content required"}), 400

        try:
            msg = _chat_manager.add_message(
                tenant_id=g.tenant_id,
                conversation_id=conversation_id,
                sender_type="agent",
                content=content,
                sender_name=current_user.email if current_user else "Agent",
            )
            return jsonify(msg), 201
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @bp.route("/api/chat/<int:conversation_id>/close", methods=["POST"])
    @login_required
    @require_module("communications")
    def chat_close(conversation_id):
        """Close a chat conversation."""
        try:
            result = _chat_manager.close_conversation(
                tenant_id=g.tenant_id,
                conversation_id=conversation_id,
            )
            return jsonify(result)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
