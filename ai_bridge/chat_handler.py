"""
Chat Handler for A.R.C.H.I.E. Improvements Lab
Manages real-time chat between humans, internal agents, and external contractors

Features:
- Message persistence in proposal_chat_messages table
- Agent personality integration
- Contractor routing for escalated proposals
- Typing indicators support
- Message history retrieval

Author: A.R.C.H.I.E.
Date: 2026-01-14
"""

import os
from db import _get_db_password
import sys
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/app")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    logger.error("psycopg2 not available")
    psycopg2 = None

# Import contractor routing
try:
    from archie_bridge import call_contractor, get_contractor_by_id
except ImportError:

    def call_contractor(*args, **kwargs):
        return {"success": False, "error": "archie_bridge not available"}

    def get_contractor_by_id(contractor_id):
        return None


class ProposalChatHandler:
    """
    Manages chat for improvement proposals.

    Supports:
    - Human messages
    - Agent responses (internal)
    - Contractor responses (external API)
    - System messages (status updates)
    """

    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": _get_db_password(),
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    def send_message(
        self,
        proposal_id: int,
        content: str,
        sender_type: str,
        sender_id: int = None,
        sender_name: str = None,
        message_type: str = "text",
        metadata: Dict = None,
    ) -> Dict:
        """
        Send a message in the proposal chat.

        Args:
            proposal_id: Target proposal
            content: Message content
            sender_type: 'human', 'agent', 'contractor', or 'system'
            sender_id: User or agent ID
            sender_name: Display name
            message_type: 'text', 'code', 'proposal', or 'action'
            metadata: Additional message data

        Returns:
            {
                'success': bool,
                'message_id': int,
                'created_at': str
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute(
                """
                INSERT INTO proposal_chat_messages
                (proposal_id, sender_type, sender_id, sender_name, content, message_type, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
            """,
                (
                    proposal_id,
                    sender_type,
                    sender_id,
                    sender_name or sender_type.title(),
                    content,
                    message_type,
                    json.dumps(metadata or {}),
                ),
            )

            result = cur.fetchone()
            conn.commit()

            logger.info(f"Chat message sent to proposal #{proposal_id} by {sender_type}")

            return {
                "success": True,
                "message_id": result["id"],
                "created_at": result["created_at"].isoformat(),
            }

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to send chat message: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def get_chat_history(
        self,
        proposal_id: int,
        limit: int = 50,
        offset: int = 0,
        include_system: bool = True,
    ) -> Dict:
        """
        Get chat history for a proposal.

        Args:
            proposal_id: Target proposal
            limit: Max messages to return
            offset: Pagination offset
            include_system: Include system messages

        Returns:
            {
                'success': bool,
                'messages': [...],
                'total': int
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Build query
            where_clause = "WHERE proposal_id = %s"
            params = [proposal_id]

            if not include_system:
                where_clause += " AND sender_type != 'system'"

            # Get total count
            cur.execute(
                f"""
                SELECT COUNT(*) as total
                FROM proposal_chat_messages
                {where_clause}
            """,
                params,
            )
            total = cur.fetchone()["total"]

            # Get messages
            cur.execute(
                f"""
                SELECT
                    id, proposal_id, sender_type, sender_id, sender_name,
                    content, message_type, metadata, created_at, is_read
                FROM proposal_chat_messages
                {where_clause}
                ORDER BY created_at ASC
                LIMIT %s OFFSET %s
            """,
                params + [limit, offset],
            )

            messages = cur.fetchall()

            return {
                "success": True,
                "messages": [self._format_message(dict(m)) for m in messages],
                "total": total,
                "limit": limit,
                "offset": offset,
            }

        except Exception as e:
            logger.error(f"Failed to get chat history: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def _format_message(self, message: Dict) -> Dict:
        """Format message for frontend display."""
        return {
            "id": message["id"],
            "proposal_id": message["proposal_id"],
            "sender": {
                "type": message["sender_type"],
                "id": message["sender_id"],
                "name": message["sender_name"],
            },
            "content": message["content"],
            "type": message["message_type"],
            "metadata": (message["metadata"] if isinstance(message["metadata"], dict) else {}),
            "created_at": (
                message["created_at"].isoformat()
                if hasattr(message["created_at"], "isoformat")
                else message["created_at"]
            ),
            "is_read": message["is_read"],
        }

    def send_to_contractor(self, proposal_id: int, message: str, user_id: int, user_name: str = "Human") -> Dict:
        """
        Send a message to the assigned contractor and get their response.

        Args:
            proposal_id: Proposal ID (must be escalated)
            message: Human's message
            user_id: Sending user's ID
            user_name: Display name

        Returns:
            {
                'success': bool,
                'human_message_id': int,
                'contractor_response': str,
                'contractor_message_id': int
            }
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get proposal and contractor info
            cur.execute(
                """
                SELECT
                    ip.id, ip.title, ip.escalation_status,
                    ip.contractor_agent_id, ip.test_failure_context,
                    a.name as contractor_name,
                    a.api_provider, a.model, a.personality_prompt,
                    a.communication_style
                FROM improvement_proposals ip
                LEFT JOIN agents a ON ip.contractor_agent_id = a.id
                WHERE ip.id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            if not proposal:
                return {"success": False, "error": "Proposal not found"}

            if proposal["escalation_status"] != "contractor_consulting":
                return {
                    "success": False,
                    "error": "Proposal not in contractor consultation",
                }

            if not proposal["contractor_agent_id"]:
                return {"success": False, "error": "No contractor assigned"}

        except Exception as e:
            logger.error(f"Failed to send to contractor: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        try:
            # Save human message
            human_msg = self.send_message(
                proposal_id=proposal_id,
                content=message,
                sender_type="human",
                sender_id=user_id,
                sender_name=user_name,
            )

            if not human_msg["success"]:
                return human_msg

            # Build context for contractor
            chat_history = self.get_chat_history(proposal_id, limit=10)
            recent_messages = chat_history.get("messages", [])[-5:]

            context = f"""You are {proposal['contractor_name']}, consulting on Proposal #{proposal_id}: {proposal['title']}

Previous messages:
"""
            for msg in recent_messages:
                context += f"\n[{msg['sender']['name']}]: {msg['content'][:200]}"

            context += f"""

Communication style: {proposal.get('communication_style', 'professional')}

Human's new message: {message}

Respond helpfully and in character. If they ask about code, provide specific solutions.
"""

            # Get contractor response
            contractor_agent = {
                "id": proposal["contractor_agent_id"],
                "name": proposal["contractor_name"],
                "api_provider": proposal["api_provider"],
                "model": proposal["model"],
                "personality_prompt": proposal["personality_prompt"],
            }

            result = call_contractor(contractor_agent, context)

            if not result.get("success"):
                # Save error as system message
                self.send_message(
                    proposal_id=proposal_id,
                    content=f"Contractor unavailable: {result.get('error', 'Unknown error')}",
                    sender_type="system",
                    message_type="action",
                )
                return {"success": False, "error": result.get("error")}

            # Save contractor response
            contractor_msg = self.send_message(
                proposal_id=proposal_id,
                content=result["response"],
                sender_type="contractor",
                sender_id=proposal["contractor_agent_id"],
                sender_name=proposal["contractor_name"],
                metadata={
                    "tokens_used": result.get("tokens_used", 0),
                    "model": result.get("model"),
                    "provider": result.get("provider"),
                },
            )

            return {
                "success": True,
                "human_message_id": human_msg["message_id"],
                "contractor_response": result["response"],
                "contractor_message_id": contractor_msg.get("message_id"),
                "tokens_used": result.get("tokens_used", 0),
            }

        except Exception as e:
            logger.error(f"Failed to send to contractor: {e}")
            return {"success": False, "error": str(e)}

    def send_to_agent(self, proposal_id: int, message: str, user_id: int, user_name: str = "Human") -> Dict:
        """
        Send a message to the assigned internal agent.

        Args:
            proposal_id: Proposal ID
            message: Human's message
            user_id: Sending user's ID
            user_name: Display name

        Returns:
            Similar to send_to_contractor
        """
        conn = self.get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get proposal and assigned agent
            cur.execute(
                """
                SELECT
                    ip.id, ip.title, ip.assigned_agent_id,
                    a.name as agent_name,
                    a.model, a.system_prompt,
                    a.personality_prompt, a.communication_style
                FROM improvement_proposals ip
                LEFT JOIN agents a ON ip.assigned_agent_id = a.id
                WHERE ip.id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            if not proposal:
                return {"success": False, "error": "Proposal not found"}

            if not proposal["assigned_agent_id"]:
                return {"success": False, "error": "No agent assigned to this proposal"}

        except Exception as e:
            logger.error(f"Failed to send to agent: {e}")
            return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

        try:
            # Save human message
            human_msg = self.send_message(
                proposal_id=proposal_id,
                content=message,
                sender_type="human",
                sender_id=user_id,
                sender_name=user_name,
            )

            # For internal agents, we typically use Ollama
            # Build agent prompt
            agent_prompt = (
                proposal.get("personality_prompt")
                or proposal.get("system_prompt")
                or f"You are {proposal['agent_name']}, working on improvement proposals."
            )

            context = f"""Proposal: {proposal['title']}

Human message: {message}

Respond helpfully as {proposal['agent_name']}.
"""

            try:
                from tools.department_hq.services.department_dispatcher import get_dispatcher

                dispatcher = get_dispatcher()
                result = dispatcher.request_work(
                    "chat", context, "improvement_chat", system_prompt=agent_prompt, timeout=120
                )
            except Exception as e:
                return {"success": False, "error": f"Agent call failed: {e}"}

            if not result.success:
                return {"success": False, "error": result.error}

            # Save agent response
            agent_msg = self.send_message(
                proposal_id=proposal_id,
                content=result.response,
                sender_type="agent",
                sender_id=proposal["assigned_agent_id"],
                sender_name=proposal["agent_name"],
            )

            return {
                "success": True,
                "human_message_id": human_msg["message_id"],
                "agent_response": result.response,
                "agent_message_id": agent_msg.get("message_id"),
            }

        except Exception as e:
            logger.error(f"Failed to send to agent: {e}")
            return {"success": False, "error": str(e)}

    def mark_as_read(self, proposal_id: int, user_id: int = None) -> Dict:
        """Mark all messages in a proposal as read."""
        conn = self.get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                UPDATE proposal_chat_messages
                SET is_read = TRUE
                WHERE proposal_id = %s AND is_read = FALSE
            """,
                (proposal_id,),
            )

            updated = cur.rowcount
            conn.commit()

            return {"success": True, "marked_read": updated}

        except Exception as e:
            conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def get_unread_count(self, proposal_id: int) -> int:
        """Get count of unread messages for a proposal."""
        conn = self.get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT COUNT(*) FROM proposal_chat_messages
                WHERE proposal_id = %s AND is_read = FALSE
            """,
                (proposal_id,),
            )

            return cur.fetchone()[0]

        except Exception as e:
            logger.warning("Failed to get unread count: %s", e)
            return 0
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def add_system_message(self, proposal_id: int, content: str, message_type: str = "action") -> Dict:
        """Add a system message (for status updates, notifications)."""
        return self.send_message(
            proposal_id=proposal_id,
            content=content,
            sender_type="system",
            sender_name="System",
            message_type=message_type,
        )


# Singleton instance
_chat_handler = None


def get_chat_handler() -> ProposalChatHandler:
    """Get singleton chat handler instance"""
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = ProposalChatHandler()
    return _chat_handler


# Convenience functions
def send_chat_message(proposal_id: int, content: str, sender_type: str, **kwargs) -> Dict:
    """Send a chat message"""
    return get_chat_handler().send_message(proposal_id, content, sender_type, **kwargs)


def get_chat_history(proposal_id: int, **kwargs) -> Dict:
    """Get chat history for a proposal"""
    return get_chat_handler().get_chat_history(proposal_id, **kwargs)


def chat_with_contractor(proposal_id: int, message: str, user_id: int, user_name: str = "Human") -> Dict:
    """Chat with contractor for an escalated proposal"""
    return get_chat_handler().send_to_contractor(proposal_id, message, user_id, user_name)


# CLI testing
if __name__ == "__main__":
    print("Chat Handler - Diagnostic Mode")
    print("=" * 60)

    handler = get_chat_handler()

    # Test database connection
    try:
        conn = handler.get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT COUNT(*) as count FROM proposal_chat_messages")
            count = cur.fetchone()["count"]
            print(f"✅ Database connected. {count} chat messages found.")
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        print(f"❌ Database error: {e}")

    print("\nChat Handler ready for use.")
