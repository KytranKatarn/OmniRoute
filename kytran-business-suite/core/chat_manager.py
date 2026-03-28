"""In-memory chat session management with database persistence.

Chat conversations use REST polling (not WebSocket). Active sessions
are cached in memory for fast access, with database as the source of truth.

Usage:
    from core.chat_manager import ChatManager
    manager = ChatManager()
    conv = manager.start_conversation(tenant_id=1, visitor_name="Jane")
    manager.add_message(tenant_id=1, conversation_id=conv["id"],
                        sender_type="visitor", content="Hello!")
    messages = manager.get_messages(tenant_id=1, conversation_id=conv["id"])
"""

import logging
from datetime import datetime

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus

logger = logging.getLogger(__name__)


class ChatManager:
    """Manages live chat conversations with DB persistence."""

    def start_conversation(
        self, tenant_id, visitor_name=None, visitor_email=None, customer_id=None
    ):
        """Create a new chat conversation.

        Args:
            tenant_id: Tenant ID for schema isolation.
            visitor_name: Optional visitor display name.
            visitor_email: Optional visitor email.
            customer_id: Optional CRM customer ID.

        Returns:
            Dict with conversation details including id.
        """
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                INSERT INTO chat_conversations
                    (visitor_name, visitor_email, customer_id, status, channel)
                VALUES (%s, %s, %s, 'active', 'widget')
                RETURNING id, visitor_name, visitor_email, customer_id,
                          status, channel, created_at
                """,
                (visitor_name, visitor_email, customer_id),
            )
            conv = dict(cur.fetchone())

            # Add system greeting message
            cur.execute(
                """
                INSERT INTO chat_messages
                    (conversation_id, sender_type, sender_name, content)
                VALUES (%s, 'system', 'System', 'Welcome! How can we help you today?')
                """,
                (conv["id"],),
            )

        event_bus.emit(
            "chat.started",
            {"conversation_id": conv["id"], "visitor_name": visitor_name},
            tenant_id=tenant_id,
        )

        return conv

    def add_message(
        self, tenant_id, conversation_id, sender_type, content, sender_name=None
    ):
        """Add a message to a conversation.

        Args:
            tenant_id: Tenant ID for schema isolation.
            conversation_id: Chat conversation ID.
            sender_type: One of 'visitor', 'agent', 'system'.
            content: Message text.
            sender_name: Optional display name of sender.

        Returns:
            Dict with message details.
        """
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            # Verify conversation exists and is active
            cur.execute(
                "SELECT id, status FROM chat_conversations WHERE id = %s",
                (conversation_id,),
            )
            conv = cur.fetchone()
            if not conv:
                raise ValueError(f"Conversation {conversation_id} not found")
            if conv["status"] != "active":
                raise ValueError(f"Conversation {conversation_id} is {conv['status']}")

            cur.execute(
                """
                INSERT INTO chat_messages
                    (conversation_id, sender_type, sender_name, content)
                VALUES (%s, %s, %s, %s)
                RETURNING id, conversation_id, sender_type, sender_name,
                          content, created_at
                """,
                (conversation_id, sender_type, sender_name, content),
            )
            msg = dict(cur.fetchone())

        return msg

    def get_messages(self, tenant_id, conversation_id, since=None):
        """Retrieve messages for a conversation, optionally since a timestamp.

        Args:
            tenant_id: Tenant ID for schema isolation.
            conversation_id: Chat conversation ID.
            since: Optional ISO timestamp to get only newer messages.

        Returns:
            List of message dicts ordered by created_at ascending.
        """
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)

            if since:
                cur.execute(
                    """
                    SELECT id, conversation_id, sender_type, sender_name,
                           content, created_at
                    FROM chat_messages
                    WHERE conversation_id = %s AND created_at > %s
                    ORDER BY created_at ASC
                    """,
                    (conversation_id, since),
                )
            else:
                cur.execute(
                    """
                    SELECT id, conversation_id, sender_type, sender_name,
                           content, created_at
                    FROM chat_messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC
                    """,
                    (conversation_id,),
                )
            return [dict(row) for row in cur.fetchall()]

    def close_conversation(self, tenant_id, conversation_id):
        """Close a chat conversation.

        Args:
            tenant_id: Tenant ID for schema isolation.
            conversation_id: Chat conversation ID.

        Returns:
            Dict with updated conversation details.
        """
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                UPDATE chat_conversations
                SET status = 'closed', closed_at = NOW()
                WHERE id = %s AND status = 'active'
                RETURNING id, status, closed_at
                """,
                (conversation_id,),
            )
            result = cur.fetchone()
            if not result:
                raise ValueError(
                    f"Conversation {conversation_id} not found or already closed"
                )

        event_bus.emit(
            "chat.closed",
            {"conversation_id": conversation_id},
            tenant_id=tenant_id,
        )

        return dict(result)

    def get_active_conversations(self, tenant_id):
        """List all active chat conversations.

        Args:
            tenant_id: Tenant ID for schema isolation.

        Returns:
            List of active conversation dicts with latest message preview.
        """
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            cur.execute(
                """
                SELECT cc.id, cc.visitor_name, cc.visitor_email,
                       cc.customer_id, cc.status, cc.created_at,
                       (SELECT content FROM chat_messages
                        WHERE conversation_id = cc.id
                        ORDER BY created_at DESC LIMIT 1) AS last_message,
                       (SELECT COUNT(*) FROM chat_messages
                        WHERE conversation_id = cc.id) AS message_count
                FROM chat_conversations cc
                WHERE cc.status = 'active'
                ORDER BY cc.created_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]
