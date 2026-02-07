"""
Collaboration Engine - AI-to-AI Communication

Manages ping-pong conversations between ARCHIE and Claude.
"""

import asyncio
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CollabStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class CollabMessage:
    role: str  # "user", "archie", "claude"
    content: str
    turn: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CollabSession:
    id: str
    topic: str
    status: CollabStatus
    messages: List[CollabMessage] = field(default_factory=list)
    current_turn: int = 0
    max_turns: int = 10
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status.value,
            "messages": [
                {"role": m.role, "content": m.content, "turn": m.turn, "timestamp": m.timestamp} for m in self.messages
            ],
            "current_turn": self.current_turn,
            "max_turns": self.max_turns,
            "created_at": self.created_at,
        }


class CollaborationEngine:
    """Manages AI-to-AI collaboration sessions"""

    def __init__(self):
        self.sessions: Dict[str, CollabSession] = {}
        self._archie = None
        self._claude = None

    def _get_archie(self):
        """Get ARCHIE analyzer (lazy load)"""
        if self._archie is None:
            try:
                from ai_bridge.knowledge_analyzer import get_knowledge_analyzer

                self._archie = get_knowledge_analyzer()
            except ImportError:
                logger.error("Could not import knowledge_analyzer")
        return self._archie

    def _get_claude(self):
        """Get Claude bridge (lazy load)"""
        if self._claude is None:
            from .claude_bridge import get_claude_bridge

            self._claude = get_claude_bridge()
        return self._claude

    def start_session(self, topic: str, max_turns: int = 10) -> CollabSession:
        """Start a new collaboration session"""
        session = CollabSession(
            id=str(uuid.uuid4()),
            topic=topic,
            status=CollabStatus.PENDING,
            max_turns=min(max_turns, 20),  # Cap at 20 turns
        )
        self.sessions[session.id] = session
        logger.info(f"Started collaboration session {session.id}: {topic}")
        return session

    async def run_collaboration(self, session_id: str) -> CollabSession:
        """Run the ping-pong collaboration"""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        session.status = CollabStatus.ACTIVE

        # Initial message from user becomes the topic
        user_msg = CollabMessage(role="user", content=session.topic, turn=0)
        session.messages.append(user_msg)

        try:
            while session.current_turn < session.max_turns:
                if session.status == CollabStatus.PAUSED:
                    await asyncio.sleep(1)
                    continue

                if session.status == CollabStatus.STOPPED:
                    break

                session.current_turn += 1

                # ARCHIE's turn
                archie_response = await self._get_archie_response(session)
                session.messages.append(
                    CollabMessage(role="archie", content=archie_response, turn=session.current_turn)
                )

                # Check if ARCHIE thinks we're done
                if self._is_conclusion(archie_response):
                    break

                # Small delay between turns
                await asyncio.sleep(1)

                # Claude's turn
                claude_response = await self._get_claude_response(session)
                session.messages.append(
                    CollabMessage(role="claude", content=claude_response, turn=session.current_turn)
                )

                # Check if Claude thinks we're done
                if self._is_conclusion(claude_response):
                    break

                await asyncio.sleep(1)

            session.status = CollabStatus.COMPLETED

            # Extract learnings
            await self._extract_learnings(session)

        except Exception as e:
            logger.error(f"Collaboration error: {e}")
            session.status = CollabStatus.ERROR
            session.messages.append(CollabMessage(role="system", content=f"Error: {str(e)}", turn=session.current_turn))

        return session

    def _has_recent_interjection(self, session: CollabSession, since_role: str) -> str:
        """Check if a user interjected since the last message from since_role.

        Returns the interjection text if found, empty string otherwise.
        """
        # Walk backwards through messages to find the most recent user message
        # that appeared after the last message from since_role
        found_since = False
        for msg in reversed(session.messages):
            if msg.role == since_role:
                found_since = True
                break
            if msg.role == "user" and msg.turn > 0:
                return msg.content
        # If we never found since_role, check if there's a user interjection after turn 0
        if not found_since:
            for msg in reversed(session.messages):
                if msg.role == "user" and msg.turn > 0:
                    return msg.content
        return ""

    async def _get_archie_response(self, session: CollabSession) -> str:
        """Get ARCHIE's response based on conversation so far"""
        archie = self._get_archie()
        if not archie:
            return "I apologize, but I'm having trouble connecting to my knowledge system."

        # Build context from previous messages
        context = self._build_context(session)

        # Check for user interjection
        interjection_note = ""
        interjection = self._has_recent_interjection(session, "archie")
        if interjection:
            interjection_note = (
                "\n\nIMPORTANT: The human operator has interjected with a new point. "
                "Please directly address their message before continuing the discussion."
            )

        prompt = f"""You are ARCHIE, an AI assistant collaborating with Claude to answer: "{session.topic}"

Previous discussion:
{context}

Provide your thoughts, ask Claude clarifying questions, or build on their points.
Keep response concise (2-3 paragraphs max).
If you think the topic is fully addressed, say "I think we've covered this well."{interjection_note}
"""

        try:
            # Use local LLM for ARCHIE
            result = archie._call_llm(prompt, max_tokens=1000)
            return result[0] if result else "I need more time to think about this."
        except Exception as e:
            logger.error(f"ARCHIE response error: {e}")
            return f"I encountered an issue while formulating my response: {str(e)}"

    async def _get_claude_response(self, session: CollabSession) -> str:
        """Get Claude's response via CLI"""
        context = self._build_context(session)

        # Check for user interjection
        interjection_note = ""
        interjection = self._has_recent_interjection(session, "claude")
        if interjection:
            interjection_note = (
                "\n\nIMPORTANT: The human operator has interjected with a new point. "
                "Please directly address their message before continuing the discussion."
            )

        message = f"""ARCHIE and I are discussing: "{session.topic}"

Conversation so far:
{context}

Please respond to ARCHIE's latest point. Be helpful and collaborative.{interjection_note}
"""

        bridge = self._get_claude()
        try:
            response = await bridge.send_message(message)
            return response or "I need a moment to consider this."
        except Exception as e:
            logger.error(f"Claude response error: {e}")
            return f"I encountered an issue: {str(e)}"

    def _build_context(self, session: CollabSession) -> str:
        """Build conversation context string"""
        lines = []
        for msg in session.messages[-6:]:  # Last 6 messages for context
            role = msg.role.upper()
            lines.append(f"{role}: {msg.content}")
        return "\n\n".join(lines)

    def _is_conclusion(self, response: str) -> bool:
        """Check if response indicates conclusion"""
        indicators = [
            "we've covered",
            "that covers",
            "hope this helps",
            "let me know if you need",
            "that should address",
            "i think we've answered",
            "i believe we've addressed",
        ]
        response_lower = response.lower()
        return any(ind in response_lower for ind in indicators)

    async def _extract_learnings(self, session: CollabSession):
        """Extract knowledge from collaboration and save to ARCHIE's knowledge base"""
        try:
            from .learning_extractor import extract_and_save_learnings

            await extract_and_save_learnings(session)
        except ImportError:
            logger.warning("Learning extractor not available")
        except Exception as e:
            logger.error(f"Failed to extract learnings: {e}")

    def pause_session(self, session_id: str) -> bool:
        """Pause a running session"""
        session = self.sessions.get(session_id)
        if session and session.status == CollabStatus.ACTIVE:
            session.status = CollabStatus.PAUSED
            return True
        return False

    def resume_session(self, session_id: str) -> bool:
        """Resume a paused session"""
        session = self.sessions.get(session_id)
        if session and session.status == CollabStatus.PAUSED:
            session.status = CollabStatus.ACTIVE
            return True
        return False

    def stop_session(self, session_id: str) -> bool:
        """Stop a session"""
        session = self.sessions.get(session_id)
        if session and session.status in [CollabStatus.ACTIVE, CollabStatus.PAUSED]:
            session.status = CollabStatus.STOPPED
            return True
        return False

    def add_interjection(self, session_id: str, message: str) -> bool:
        """Add user interjection to session"""
        session = self.sessions.get(session_id)
        if session and session.status in [CollabStatus.ACTIVE, CollabStatus.PAUSED]:
            session.messages.append(CollabMessage(role="user", content=message, turn=session.current_turn))
            return True
        return False

    def get_session(self, session_id: str) -> Optional[CollabSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)

    def list_sessions(self) -> List[dict]:
        """List all sessions"""
        return [s.to_dict() for s in self.sessions.values()]


# Singleton
_engine: Optional[CollaborationEngine] = None


def get_collaboration_engine() -> CollaborationEngine:
    """Get the collaboration engine singleton instance"""
    global _engine
    if _engine is None:
        _engine = CollaborationEngine()
    return _engine
