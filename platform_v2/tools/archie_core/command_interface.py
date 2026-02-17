"""
A.R.C.H.I.E. Command Interface
Main handler for the unified command system
This is ARCHIE's brain - she receives all user input and orchestrates responses
"""

import os
import sys
import json
import uuid
import asyncio
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

from .intent_parser import get_intent_parser
from .command_router import get_command_router


class CommandInterface:
    """
    Main command interface for ARCHIE

    This is the single point of contact for all user interactions.
    It parses intents, routes to appropriate handlers, logs everything,
    and provides ARCHIE's unified voice.
    """

    def __init__(self):
        self.intent_parser = get_intent_parser()
        self.command_router = get_command_router()
        self.db_config = {
            "host": os.getenv("DB_HOST", "archie_database"),
            "port": os.getenv("DB_PORT", "5432"),
            "database": os.getenv("DB_NAME", "archie"),
            "user": os.getenv("DB_USER", "archie"),
            "password": os.getenv("DB_PASSWORD", ""),
        }

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_config)

    async def process_command(self, user_input: str, user_id: int, conversation_id: str = None) -> dict:
        """
        Process a user command through the complete pipeline:
        1. Parse intent
        2. Get/create session context
        3. Route to appropriate handler
        4. Log execution
        5. Format response

        Args:
            user_input: Raw user message
            user_id: Current user ID
            conversation_id: Optional conversation ID for context

        Returns:
            Complete response dict for the frontend
        """
        start_time = datetime.now()
        conversation_id = conversation_id or str(uuid.uuid4())

        try:
            # Step 1: Get or create session context
            context = await self._get_session_context(user_id, conversation_id)

            # Step 2: Parse intent
            intent = self.intent_parser.parse(user_input, context)

            # Step 3: Route to appropriate handler
            result = await self.command_router.route(intent, context, user_id)

            # Step 4: Log execution
            log_id = await self._log_execution(
                conversation_id=conversation_id,
                user_id=user_id,
                raw_input=user_input,
                intent=intent,
                result=result,
            )

            # Step 5: Update session context
            await self._update_session_context(user_id, conversation_id, intent, result)

            # Step 6: Format final response
            response = self._format_response(intent, result, context)
            response["log_id"] = log_id
            response["conversation_id"] = conversation_id

            return response

        except Exception as e:
            # Log error and return graceful failure
            error_response = {
                "success": False,
                "error": str(e),
                "response": f"I ran into an unexpected issue: {str(e)}. Let me try again or would you like to rephrase?",
                "conversation_id": conversation_id,
                "duration_ms": int((datetime.now() - start_time).total_seconds() * 1000),
            }

            # Try to log the error
            try:
                await self._log_execution(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    raw_input=user_input,
                    intent={"type": "error", "error": str(e)},
                    result=error_response,
                )
            except:
                pass

            return error_response

    def process_command_sync(self, user_input: str, user_id: int, conversation_id: str = None) -> dict:
        """Synchronous wrapper for process_command"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.process_command(user_input, user_id, conversation_id))
        finally:
            loop.close()

    async def _get_session_context(self, user_id: int, conversation_id: str) -> dict:
        """Get or create session context"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Check for existing session
            cur.execute(
                """
                SELECT session_id, state, context, current_step, total_steps
                FROM archie_command_sessions
                WHERE user_id = %s AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
            """,
                (user_id,),
            )
            session = cur.fetchone()

            # Get user preferences
            cur.execute(
                """
                SELECT content FROM long_term_memory
                WHERE user_id = %s AND memory_type = 'preference'
                ORDER BY importance_score DESC LIMIT 5
            """,
                (user_id,),
            )
            preferences = [r["content"] for r in cur.fetchall()]

            # Get emotional state
            cur.execute(
                """
                SELECT relationship_strength, current_mood
                FROM archie_emotional_state
                WHERE user_id = %s
                ORDER BY timestamp DESC LIMIT 1
            """,
                (user_id,),
            )
            emotional = cur.fetchone()

            # Get recent conversation history
            cur.execute(
                """
                SELECT message, response, created_at
                FROM ai_conversations
                WHERE user_id = %s AND conversation_id = %s
                ORDER BY created_at DESC LIMIT 5
            """,
                (user_id, conversation_id),
            )
            history = cur.fetchall()

            cur.close()
            conn.close()

            context = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "preferences": preferences,
                "relationship_strength": (float(emotional["relationship_strength"]) if emotional else 0.5),
                "current_mood": emotional["current_mood"] if emotional else "neutral",
                "conversation_history": (
                    [{"role": "user", "content": h["message"]} for h in reversed(history)] if history else []
                ),
                "session": session["state"] if session else {},
            }

            return context

        except Exception as e:
            print(f"Context retrieval error: {e}")
            return {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "preferences": [],
                "relationship_strength": 0.5,
                "current_mood": "neutral",
                "conversation_history": [],
                "session": {},
            }

    async def _update_session_context(self, user_id: int, conversation_id: str, intent: dict, result: dict):
        """Update session context after command execution"""
        try:
            conn = self.get_db()
            cur = conn.cursor()

            # Upsert session
            cur.execute(
                """
                INSERT INTO archie_command_sessions (user_id, session_id, state, context, status)
                VALUES (%s, %s::uuid, %s, %s, 'active')
                ON CONFLICT (user_id) WHERE status = 'active'
                DO UPDATE SET
                    state = archie_command_sessions.state || %s,
                    context = archie_command_sessions.context || %s,
                    updated_at = NOW()
            """,
                (
                    user_id,
                    conversation_id,
                    json.dumps({"last_intent": intent.get("type")}),
                    json.dumps({"conversation_id": conversation_id}),
                    json.dumps({"last_intent": intent.get("type")}),
                    json.dumps({"conversation_id": conversation_id}),
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            print(f"Session update error: {e}")

    async def _log_execution(
        self,
        conversation_id: str,
        user_id: int,
        raw_input: str,
        intent: dict,
        result: dict,
    ) -> int:
        """Log command execution to database"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                INSERT INTO archie_command_log (
                    conversation_id, user_id, raw_input, parsed_intent, intent_type,
                    confidence, routed_to, agent_used, station, escalated_to_contractor,
                    execution_result, success, error_message, duration_ms, tokens_used, cost
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    conversation_id,
                    user_id,
                    raw_input,
                    json.dumps(intent),
                    intent.get("type", "unknown"),
                    intent.get("confidence", 0.5),
                    result.get("station", "Command"),
                    result.get("agent_used", "ARCHIE"),
                    result.get("station", "Command"),
                    result.get("escalation_requested", False),
                    json.dumps({"response": result.get("response", "")[:1000]}),
                    result.get("success", True),
                    result.get("error"),
                    result.get("duration_ms", 0),
                    result.get("tokens", 0),
                    result.get("cost", 0),
                ),
            )

            log_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()

            return log_id

        except Exception as e:
            print(f"Logging error: {e}")
            return 0

    def _format_response(self, intent: dict, result: dict, context: dict) -> dict:
        """Format the final response for the frontend"""
        response = {
            "success": result.get("success", True),
            "response": result.get("response", ""),
            "intent": {
                "type": intent.get("type", "conversation"),
                "confidence": intent.get("confidence", 0.5),
                "entities": intent.get("entities", {}),
            },
            "execution": {
                "agent_used": result.get("agent_used", "ARCHIE"),
                "station": result.get("station", "Command"),
                "model": result.get("model"),
                "duration_ms": result.get("duration_ms", 0),
                "tokens": result.get("tokens", 0),
                "cost": result.get("cost", 0),
            },
            "escalation": {
                "requested": result.get("escalation_requested", False),
                "available": result.get("escalation_available", False),
                "requires_contractor": intent.get("requires_contractor", False),
            },
        }

        # Add complexity info if available
        if intent.get("complexity"):
            response["complexity"] = intent["complexity"]

        # Add sources if available (for knowledge queries)
        if result.get("sources"):
            response["sources"] = result["sources"]

        return response

    async def get_suggestions(self, user_id: int, context: str = None) -> list:
        """Get context-aware command suggestions"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get user's recent command types
            cur.execute(
                """
                SELECT intent_type, COUNT(*) as count
                FROM archie_command_log
                WHERE user_id = %s AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY intent_type
                ORDER BY count DESC
                LIMIT 3
            """,
                (user_id,),
            )
            recent_types = [r["intent_type"] for r in cur.fetchall()]

            cur.close()
            conn.close()

            # Build suggestions based on usage
            suggestions = []

            if "code_task" in recent_types:
                suggestions.append("Review my latest changes")
                suggestions.append("Help me fix a bug")

            if "team_task" in recent_types:
                suggestions.append("Show me the team roster")
                suggestions.append("Who's available right now?")

            if "knowledge_query" in recent_types:
                suggestions.append("What's the status of the project?")

            # Add default suggestions
            default_suggestions = [
                "What's the system status?",
                "Help me with a coding task",
                "Create a workflow",
            ]

            # Fill remaining slots
            for s in default_suggestions:
                if s not in suggestions:
                    suggestions.append(s)
                if len(suggestions) >= 5:
                    break

            return suggestions[:5]

        except Exception as e:
            return [
                "What's the system status?",
                "Help me with a coding task",
                "Show me the team roster",
            ]

    async def get_command_history(self, user_id: int, limit: int = 20) -> list:
        """Get user's command history"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT id, raw_input, intent_type, agent_used, station, success,
                       duration_ms, created_at
                FROM archie_command_log
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (user_id, limit),
            )

            history = cur.fetchall()
            cur.close()
            conn.close()

            return [dict(h) for h in history]

        except Exception as e:
            return []


# Singleton instance
_interface = None


def get_command_interface() -> CommandInterface:
    """Get singleton CommandInterface instance"""
    global _interface
    if _interface is None:
        _interface = CommandInterface()
    return _interface
