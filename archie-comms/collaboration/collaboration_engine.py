"""
Collaboration Engine - AI-to-AI Communication

Manages ping-pong conversations between ARCHIE and Claude.
Sessions are persisted to PostgreSQL (collaboration_sessions / collaboration_messages)
so they survive container restarts. In-memory cache provides fast access to active sessions.
"""

import asyncio
import os
from database import _get_db_password
import uuid
import time
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# TODO: route through platform HTTP API (archie-comms standalone — no direct dispatcher access)
_dispatcher = None


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


class CollabStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class CollabMessage:
    role: str  # "user", "archie", "claude", "system"
    content: str
    turn: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    model_used: str = ""
    duration_ms: int = 0


@dataclass
class CollabSession:
    id: str
    topic: str
    status: CollabStatus
    messages: List[CollabMessage] = field(default_factory=list)
    current_turn: int = 0
    max_turns: int = 10
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    db_id: Optional[int] = None  # DB primary key
    user_id: Optional[int] = None
    system_hint: str = ""  # Optional template hint for guiding AI responses

    work_products: List[Dict] = field(default_factory=list)
    _context_summaries: Dict[int, str] = field(default_factory=dict)  # Cached summaries keyed by message count

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status.value,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "turn": m.turn,
                    "timestamp": m.timestamp,
                    "model_used": m.model_used,
                    "duration_ms": m.duration_ms,
                }
                for m in self.messages
            ],
            "current_turn": self.current_turn,
            "max_turns": self.max_turns,
            "created_at": self.created_at,
            "work_products": self.work_products,
        }


class CollaborationEngine:
    """Manages AI-to-AI collaboration sessions with DB persistence"""

    def __init__(self):
        # In-memory cache for active sessions (fast access during collaboration)
        self.sessions: Dict[str, CollabSession] = {}
        self._archie = None
        self._claude = None

    def _get_archie(self):
        """Get ARCHIE analyzer (lazy load)"""
        # TODO: route through platform HTTP API (archie-comms standalone — no direct ai_bridge access)
        if self._archie is None:
            try:
                from ai_bridge.knowledge_analyzer import get_knowledge_analyzer  # noqa: F401

                self._archie = get_knowledge_analyzer()
            except ImportError:
                logger.warning("knowledge_analyzer not available in archie-comms standalone")
        return self._archie

    def _get_claude(self):
        """Get Claude bridge (lazy load)"""
        if self._claude is None:
            from .claude_bridge import get_claude_bridge

            self._claude = get_claude_bridge()
        return self._claude

    def start_session(
        self,
        topic: str,
        max_turns: int = 10,
        user_id: int = None,
        system_hint: str = "",
    ) -> CollabSession:
        """Start a new collaboration session — creates DB record + in-memory cache"""
        session_uuid = str(uuid.uuid4())
        capped_turns = min(max_turns, 20)

        # Persist to DB (store system_hint in metadata JSONB)
        db_id = None
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            metadata = {}
            if system_hint:
                metadata["system_hint"] = system_hint
            cur.execute(
                """
                INSERT INTO collaboration_sessions (session_uuid, user_id, topic, max_turns, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    session_uuid,
                    user_id,
                    topic,
                    capped_turns,
                    psycopg2.extras.Json(metadata) if metadata else None,
                ),
            )
            db_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to persist collab session to DB: {e}")

        session = CollabSession(
            id=session_uuid,
            topic=topic,
            status=CollabStatus.PENDING,
            max_turns=capped_turns,
            db_id=db_id,
            user_id=user_id,
            system_hint=system_hint,
        )
        self.sessions[session.id] = session
        logger.info(f"Started collaboration session {session.id}: {topic}")
        return session

    async def run_collaboration(self, session_id: str) -> CollabSession:
        """Run the ping-pong collaboration with DB persistence"""
        session = self.sessions.get(session_id)
        if not session:
            # Try loading from DB
            session = self._load_session_from_db(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")
            self.sessions[session_id] = session

        session.status = CollabStatus.ACTIVE
        self._update_session_status(session, "active")

        # Initial message from user becomes the topic
        user_msg = CollabMessage(role="user", content=session.topic, turn=0)
        session.messages.append(user_msg)
        self._persist_message(session, user_msg)

        try:
            while session.current_turn < session.max_turns:
                if not await self._run_turn(session):
                    break

            session.status = CollabStatus.COMPLETED
            self._update_session_status(session, "completed")

            # Extract learnings
            await self._extract_learnings(session)

        except Exception as e:
            logger.error(f"Collaboration error: {e}")
            session.status = CollabStatus.ERROR
            error_msg = CollabMessage(role="system", content=f"Error: {str(e)}", turn=session.current_turn)
            session.messages.append(error_msg)
            self._persist_message(session, error_msg)
            self._update_session_status(session, "error")

        return session

    async def _run_turn(self, session: CollabSession) -> bool:
        """Run a single ARCHIE+Claude turn. Returns False if session should stop."""
        if session.status == CollabStatus.PAUSED:
            await asyncio.sleep(1)
            return True  # Keep looping, just paused
        if session.status == CollabStatus.STOPPED:
            return False

        session.current_turn += 1

        # ARCHIE's turn
        t0 = time.time()
        archie_response = await self._get_archie_response(session)
        archie_ms = int((time.time() - t0) * 1000)
        archie_msg = CollabMessage(
            role="archie",
            content=archie_response,
            turn=session.current_turn,
            model_used=(_dispatcher.get_model_for_capability("conversation") if _dispatcher else "unknown"),
            duration_ms=archie_ms,
        )
        session.messages.append(archie_msg)
        self._persist_message(session, archie_msg)
        self._update_session_turn(session)

        if self._is_conclusion(archie_response):
            return False

        await asyncio.sleep(1)

        # Claude's turn
        t0 = time.time()
        claude_response = await self._get_claude_response(session)
        claude_ms = int((time.time() - t0) * 1000)
        claude_msg = CollabMessage(
            role="claude",
            content=claude_response,
            turn=session.current_turn,
            model_used="claude-proxy",
            duration_ms=claude_ms,
        )
        session.messages.append(claude_msg)
        self._persist_message(session, claude_msg)

        if self._is_conclusion(claude_response):
            return False

        await asyncio.sleep(1)
        return True

    def _has_recent_interjection(self, session: CollabSession, since_role: str) -> str:
        """Check if a user interjected since the last message from since_role."""
        found_since = False
        for msg in reversed(session.messages):
            if msg.role == since_role:
                found_since = True
                break
            if msg.role == "user" and msg.turn > 0:
                return msg.content
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

        context = self._build_context(session)

        interjection_note = ""
        interjection = self._has_recent_interjection(session, "archie")
        if interjection:
            interjection_note = (
                "\n\nIMPORTANT: The human operator has interjected with a new point. "
                "Please directly address their message before continuing the discussion."
            )

        hint = f"\nGuideline: {session.system_hint}" if session.system_hint else ""
        prompt = f"""You are A.R.C.H.I.E., an AI assistant collaborating with Claude to answer: "{session.topic}"
{hint}
Previous discussion:
{context}

Provide your thoughts, ask Claude clarifying questions, or build on their points.
Keep response concise (2-3 paragraphs max).
If you think the topic is fully addressed, say "I think we've covered this well."{interjection_note}
"""

        try:
            result = archie._call_llm(prompt, max_tokens=1000)
            return result[0] if result else "I need more time to think about this."
        except Exception as e:
            logger.error(f"A.R.C.H.I.E. response error: {e}")
            return f"I encountered an issue while formulating my response: {str(e)}"

    async def _get_claude_response(self, session: CollabSession) -> str:
        """Get Claude's response via CLI"""
        context = self._build_context(session)

        interjection_note = ""
        interjection = self._has_recent_interjection(session, "claude")
        if interjection:
            interjection_note = (
                "\n\nIMPORTANT: The human operator has interjected with a new point. "
                "Please directly address their message before continuing the discussion."
            )

        hint = f"\nGuideline: {session.system_hint}" if session.system_hint else ""
        message = f"""A.R.C.H.I.E. and I are discussing: "{session.topic}"
{hint}
Conversation so far:
{context}

Please respond to A.R.C.H.I.E.'s latest point. Be helpful and collaborative.{interjection_note}
"""

        bridge = self._get_claude()
        try:
            response = await bridge.send_message(message)
            return response or "I need a moment to consider this."
        except Exception as e:
            logger.error(f"Claude response error: {e}")
            return f"I encountered an issue: {str(e)}"

    def _build_context(self, session: CollabSession) -> str:
        """Build conversation context string with summarization for long conversations"""
        messages = session.messages
        if len(messages) <= 6:
            # Short conversation — return all messages verbatim
            lines = []
            for msg in messages:
                lines.append(f"{msg.role.upper()}: {msg.content}")
            return "\n\n".join(lines)

        # Long conversation — summarize older messages, keep last 4 verbatim
        older_messages = messages[:-4]
        recent_messages = messages[-4:]

        # Check cache (re-summarize when older message count changes)
        cache_key = len(older_messages)
        if cache_key not in session._context_summaries:
            summary = self._summarize_history(older_messages, session.topic)
            session._context_summaries[cache_key] = summary

        summary = session._context_summaries[cache_key]

        recent_lines = []
        for msg in recent_messages:
            recent_lines.append(f"{msg.role.upper()}: {msg.content}")
        recent_text = "\n\n".join(recent_lines)

        return f"[Summary of earlier discussion]\n{summary}\n\n[Recent messages]\n{recent_text}"

    def _summarize_history(self, messages: List[CollabMessage], topic: str) -> str:
        """Summarize older messages using ARCHIE's Ollama (dolphin3, already loaded)"""
        archie = self._get_archie()
        if not archie:
            # Fallback: just return last 6 of the older messages
            lines = []
            for msg in messages[-6:]:
                lines.append(f"{msg.role.upper()}: {msg.content}")
            return "\n\n".join(lines)

        # Build the text to summarize
        msg_texts = []
        for msg in messages:
            msg_texts.append(f"{msg.role.upper()}: {msg.content}")
        full_text = "\n\n".join(msg_texts)

        # Truncate if too long for model context
        if len(full_text) > 6000:
            full_text = full_text[:6000] + "\n...(truncated)"

        prompt = f"""Summarize the key points from this AI discussion about "{topic}" in 3-5 concise bullet points. Focus on decisions made, insights shared, and any conclusions reached.

Discussion:
{full_text}

Summary (bullet points only):"""

        try:
            result = archie._call_llm(prompt, max_tokens=500)
            if result and result[0]:
                return result[0]
        except Exception as e:
            logger.warning(f"Context summarization failed: {e}")

        # Fallback: return last few older messages verbatim
        lines = []
        for msg in messages[-4:]:
            lines.append(f"{msg.role.upper()}: {msg.content}")
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
            self._update_session_status(session, "paused")
            return True
        return False

    def resume_session(self, session_id: str) -> bool:
        """Resume a paused session"""
        session = self.sessions.get(session_id)
        if session and session.status == CollabStatus.PAUSED:
            session.status = CollabStatus.ACTIVE
            self._update_session_status(session, "active")
            return True
        return False

    def stop_session(self, session_id: str) -> bool:
        """Stop a session"""
        session = self.sessions.get(session_id)
        if session and session.status in [CollabStatus.ACTIVE, CollabStatus.PAUSED]:
            session.status = CollabStatus.STOPPED
            self._update_session_status(session, "stopped")
            return True
        return False

    async def continue_session(self, session_id: str) -> CollabSession:
        """Continue a stopped/completed session from where it left off.

        Different from resume_session (which unpauses an in-memory session) —
        this re-starts the async collaboration loop for a DB-persisted
        stopped/completed session.
        """
        session = self._load_session_from_db(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if session.status not in (CollabStatus.STOPPED, CollabStatus.COMPLETED):
            raise ValueError(f"Session is {session.status.value}, cannot continue")

        # Reset status and put back into in-memory cache
        session.status = CollabStatus.ACTIVE
        self.sessions[session_id] = session
        self._update_session_status(session, "active")

        # Resume the collaboration loop from current_turn
        try:
            while session.current_turn < session.max_turns:
                if not await self._run_turn(session):
                    break

            session.status = CollabStatus.COMPLETED
            self._update_session_status(session, "completed")
            await self._extract_learnings(session)

        except Exception as e:
            logger.error(f"Continue collaboration error: {e}")
            session.status = CollabStatus.ERROR
            error_msg = CollabMessage(role="system", content=f"Error: {str(e)}", turn=session.current_turn)
            session.messages.append(error_msg)
            self._persist_message(session, error_msg)
            self._update_session_status(session, "error")

        return session

    def add_interjection(self, session_id: str, message: str) -> bool:
        """Add user interjection to session"""
        session = self.sessions.get(session_id)
        if session and session.status in [CollabStatus.ACTIVE, CollabStatus.PAUSED]:
            msg = CollabMessage(role="user", content=message, turn=session.current_turn)
            session.messages.append(msg)
            self._persist_message(session, msg)
            return True
        return False

    def get_session(self, session_id: str) -> Optional[CollabSession]:
        """Get session by ID (in-memory first, then DB)"""
        session = self.sessions.get(session_id)
        if session:
            return session
        # Try loading from DB
        session = self._load_session_from_db(session_id)
        if session:
            self.sessions[session_id] = session
        return session

    def list_sessions(self) -> List[dict]:
        """List all sessions (merges in-memory active + recent DB sessions)"""
        # Get recent sessions from DB
        db_sessions = self._load_recent_sessions_from_db(limit=50)

        # Merge with in-memory (in-memory takes priority for active sessions)
        result = {}
        for s in db_sessions:
            result[s["id"]] = s
        for sid, session in self.sessions.items():
            result[sid] = session.to_dict()

        return list(result.values())

    # =========================================================================
    # DB Persistence Methods
    # =========================================================================

    def _persist_message(self, session: CollabSession, msg: CollabMessage):
        """Persist a single message to DB"""
        if not session.db_id:
            return
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO collaboration_messages
                (session_id, role, content, turn, model_used, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    session.db_id,
                    msg.role,
                    msg.content,
                    msg.turn,
                    msg.model_used or None,
                    msg.duration_ms,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to persist collab message: {e}")

    def _update_session_status(self, session: CollabSession, status: str):
        """Update session status in DB"""
        if not session.db_id:
            return
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE collaboration_sessions
                SET status = %s, completed_at = CASE WHEN %s THEN NOW() ELSE NULL END
                WHERE id = %s
            """,
                (status, status in ("completed", "stopped", "error"), session.db_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to update collab session status: {e}")

    def _update_session_turn(self, session: CollabSession):
        """Update current turn in DB"""
        if not session.db_id:
            return
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE collaboration_sessions
                SET current_turn = %s
                WHERE id = %s
            """,
                (session.current_turn, session.db_id),
            )
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to update collab session turn: {e}")

    def _load_session_from_db(self, session_uuid: str) -> Optional[CollabSession]:
        """Load a session from DB by UUID"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, session_uuid::text as session_uuid, user_id, topic, status,
                       current_turn, max_turns, created_at, metadata
                FROM collaboration_sessions
                WHERE session_uuid = %s
            """,
                (session_uuid,),
            )
            row = cur.fetchone()
            if not row:
                cur.close()
                conn.close()
                return None

            # Load messages
            cur.execute(
                """
                SELECT role, content, turn, created_at, model_used, duration_ms
                FROM collaboration_messages
                WHERE session_id = %s
                ORDER BY id
            """,
                (row["id"],),
            )
            msg_rows = cur.fetchall()
            cur.close()
            conn.close()

            messages = [
                CollabMessage(
                    role=m["role"],
                    content=m["content"],
                    turn=m["turn"],
                    timestamp=m["created_at"].isoformat() if m["created_at"] else "",
                    model_used=m.get("model_used", ""),
                    duration_ms=m.get("duration_ms", 0),
                )
                for m in msg_rows
            ]

            # Extract system_hint from metadata if present
            metadata = row.get("metadata") or {}
            system_hint = metadata.get("system_hint", "") if isinstance(metadata, dict) else ""

            return CollabSession(
                id=row["session_uuid"],
                topic=row["topic"],
                status=CollabStatus(row["status"]),
                messages=messages,
                current_turn=row["current_turn"],
                max_turns=row["max_turns"],
                created_at=row["created_at"].isoformat() if row["created_at"] else "",
                db_id=row["id"],
                user_id=row["user_id"],
                system_hint=system_hint,
            )
        except Exception as e:
            logger.warning(f"Failed to load collab session from DB: {e}")
            return None

    def _load_recent_sessions_from_db(self, limit: int = 20) -> List[dict]:
        """Load recent sessions from DB (summary only, no messages)"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT session_uuid::text as id, topic, status,
                       current_turn, max_turns, created_at,
                       (SELECT COUNT(*) FROM collaboration_messages cm WHERE cm.session_id = cs.id) as message_count
                FROM collaboration_sessions cs
                ORDER BY created_at DESC
                LIMIT %s
            """,
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            return [
                {
                    "id": r["id"],
                    "topic": r["topic"],
                    "status": r["status"],
                    "current_turn": r["current_turn"],
                    "max_turns": r["max_turns"],
                    "created_at": (r["created_at"].isoformat() if r["created_at"] else ""),
                    "message_count": r["message_count"],
                    "messages": [],  # Not loaded for list view
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"Failed to load recent collab sessions: {e}")
            return []

    # =========================================================================
    # Joint Work Mode — Structured Collaboration with Work Products
    # =========================================================================

    async def run_joint_collaboration(self, session_id: str) -> CollabSession:
        """
        Run a structured joint collaboration that produces work products.

        Flow:
        1. ARCHIE creates an execution plan (work product: plan)
        2. Each plan step is delegated — some to ARCHIE, some to Claude
        3. Results are collected as work products (code, analysis, design, etc.)
        4. ARCHIE synthesizes a final summary
        5. User can approve/modify at each step
        """
        session = self.sessions.get(session_id)
        if not session:
            session = self._load_session_from_db(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")
            self.sessions[session_id] = session

        session.status = CollabStatus.ACTIVE
        self._update_session_status(session, "active")

        # Initial user message
        user_msg = CollabMessage(role="user", content=session.topic, turn=0)
        session.messages.append(user_msg)
        self._persist_message(session, user_msg)

        try:
            # Step 1: ARCHIE creates execution plan
            session.current_turn = 1
            t0 = time.time()
            plan = await self._create_execution_plan(session)
            plan_ms = int((time.time() - t0) * 1000)

            plan_msg = CollabMessage(
                role="archie",
                content=f"**Execution Plan:**\n\n{plan}",
                turn=1,
                model_used=(_dispatcher.get_model_for_capability("conversation") if _dispatcher else "unknown"),
                duration_ms=plan_ms,
            )
            session.messages.append(plan_msg)
            self._persist_message(session, plan_msg)
            self._update_session_turn(session)

            # Save plan as work product
            self._save_work_product(session, "plan", "Execution Plan", plan, "archie")

            # Step 2: Claude reviews and refines the plan
            session.current_turn = 2
            t0 = time.time()
            review = await self._claude_review_plan(session, plan)
            review_ms = int((time.time() - t0) * 1000)

            review_msg = CollabMessage(
                role="claude",
                content=review,
                turn=2,
                model_used="claude-proxy",
                duration_ms=review_ms,
            )
            session.messages.append(review_msg)
            self._persist_message(session, review_msg)
            self._update_session_turn(session)

            # Step 3: Execute plan steps (alternating between ARCHIE and Claude)
            steps = self._parse_plan_steps(plan)
            for i, step in enumerate(steps[: session.max_turns - 3]):  # Reserve turns for synthesis
                if session.status in (CollabStatus.STOPPED, CollabStatus.PAUSED):
                    while session.status == CollabStatus.PAUSED:
                        await asyncio.sleep(1)
                    if session.status == CollabStatus.STOPPED:
                        break

                session.current_turn += 1
                t0 = time.time()

                # Alternate delegation: odd steps to ARCHIE, even to Claude
                if i % 2 == 0:
                    result = await self._archie_execute_step(session, step)
                    author = "archie"
                    model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else "unknown"
                else:
                    result = await self._claude_execute_step(session, step)
                    author = "claude"
                    model = "claude-proxy"

                step_ms = int((time.time() - t0) * 1000)

                step_msg = CollabMessage(
                    role=author,
                    content=result,
                    turn=session.current_turn,
                    model_used=model,
                    duration_ms=step_ms,
                )
                session.messages.append(step_msg)
                self._persist_message(session, step_msg)
                self._update_session_turn(session)

                # Determine product type from step content
                product_type = self._classify_work_product(step, result)
                self._save_work_product(session, product_type, f"Step {i+1}: {step[:80]}", result, author)

                await asyncio.sleep(1)

            # Step 4: ARCHIE synthesizes final summary
            session.current_turn += 1
            t0 = time.time()
            synthesis = await self._synthesize_results(session)
            synth_ms = int((time.time() - t0) * 1000)

            synth_msg = CollabMessage(
                role="archie",
                content=synthesis,
                turn=session.current_turn,
                model_used=(_dispatcher.get_model_for_capability("conversation") if _dispatcher else "unknown"),
                duration_ms=synth_ms,
            )
            session.messages.append(synth_msg)
            self._persist_message(session, synth_msg)

            self._save_work_product(session, "analysis", "Final Synthesis", synthesis, "joint")

            session.status = CollabStatus.COMPLETED
            self._update_session_status(session, "completed")

            # Extract learnings
            await self._extract_learnings(session)

        except Exception as e:
            logger.error(f"Joint collaboration error: {e}")
            session.status = CollabStatus.ERROR
            error_msg = CollabMessage(role="system", content=f"Error: {str(e)}", turn=session.current_turn)
            session.messages.append(error_msg)
            self._persist_message(session, error_msg)
            self._update_session_status(session, "error")

        return session

    async def _create_execution_plan(self, session: CollabSession) -> str:
        """A.R.C.H.I.E. creates a structured execution plan for the topic"""
        archie = self._get_archie()
        if not archie:
            return "1. Research the topic\n2. Analyze findings\n3. Synthesize conclusions"

        prompt = f"""You are A.R.C.H.I.E., an AI orchestrator. Create a concise execution plan for this task:

"{session.topic}"

Format as numbered steps (3-6 steps). Each step should be:
- Specific and actionable
- Indicate who should handle it (A.R.C.H.I.E. for local analysis, Claude for complex reasoning)
- Include expected output type (code, analysis, plan, design)

Keep it brief — just the steps, no preamble."""

        try:
            result = archie._call_llm(prompt, max_tokens=800)
            return (
                result[0] if result else "1. Analyze the request\n2. Research relevant context\n3. Produce deliverables"
            )
        except Exception as e:
            logger.error(f"Plan creation error: {e}")
            return "1. Analyze the request\n2. Research relevant context\n3. Produce deliverables"

    async def _claude_review_plan(self, session: CollabSession, plan: str) -> str:
        """Claude reviews and provides feedback on A.R.C.H.I.E.'s plan"""
        bridge = self._get_claude()
        if not bridge:
            return "Plan looks good. Let's proceed with execution."

        message = f"""A.R.C.H.I.E. created this execution plan for: "{session.topic}"

{plan}

Please briefly review this plan:
- Is anything missing?
- Any steps that should be reordered?
- Suggestions for improvement?

Keep response concise (1-2 paragraphs)."""

        try:
            response = await bridge.send_message(message)
            return response or "Plan looks solid. Let's proceed."
        except Exception as e:
            return f"Plan review encountered an issue: {e}. Proceeding with current plan."

    async def _archie_execute_step(self, session: CollabSession, step: str) -> str:
        """A.R.C.H.I.E. executes a plan step"""
        archie = self._get_archie()
        if not archie:
            return f"Completed analysis for: {step}"

        context = self._build_context(session)
        prompt = f"""You are A.R.C.H.I.E. executing a task step in a joint collaboration about: "{session.topic}"

Current step: {step}

Recent context:
{context[-1500:]}

Execute this step and provide the result. Be thorough but concise."""

        try:
            result = archie._call_llm(prompt, max_tokens=1200)
            return result[0] if result else f"Analysis complete for: {step}"
        except Exception as e:
            return f"Step execution encountered an issue: {e}"

    async def _claude_execute_step(self, session: CollabSession, step: str) -> str:
        """Claude executes a plan step"""
        bridge = self._get_claude()
        if not bridge:
            return f"Completed analysis for: {step}"

        context = self._build_context(session)
        message = f"""We're working on: "{session.topic}"

Your assigned step: {step}

Recent context:
{context[-1500:]}

Execute this step and provide the result. Be thorough but concise."""

        try:
            response = await bridge.send_message(message)
            return response or f"Analysis complete for: {step}"
        except Exception as e:
            return f"Step execution encountered an issue: {e}"

    async def _synthesize_results(self, session: CollabSession) -> str:
        """A.R.C.H.I.E. synthesizes all results into a final summary"""
        archie = self._get_archie()

        # Collect all work products
        products = self.get_work_products(session.id)
        product_summaries = []
        for p in products:
            product_summaries.append(f"[{p['product_type']}] {p['title']}: {p['content'][:200]}...")

        context = "\n".join(product_summaries) if product_summaries else self._build_context(session)

        prompt = f"""You are A.R.C.H.I.E. Synthesize the results of our joint collaboration on: "{session.topic}"

Work completed:
{context[:2000]}

Provide a clear, structured final summary covering:
1. Key findings/deliverables
2. Recommendations
3. Next steps (if any)

Keep concise (2-3 paragraphs)."""

        if archie:
            try:
                result = archie._call_llm(prompt, max_tokens=1000)
                return result[0] if result else "Collaboration complete. See work products for detailed outputs."
            except Exception:
                pass
        return "Collaboration complete. See work products for detailed outputs."

    def _parse_plan_steps(self, plan: str) -> List[str]:
        """Parse numbered steps from a plan string"""
        import re

        lines = plan.strip().split("\n")
        steps = []
        for line in lines:
            line = line.strip()
            # Match numbered lines: "1. ...", "1) ...", "- ..."
            match = re.match(r"^(?:\d+[\.\)]\s*|-\s+)(.*)", line)
            if match:
                step_text = match.group(1).strip()
                if step_text:
                    steps.append(step_text)
        return steps if steps else [plan]  # Fallback: entire plan as one step

    def _classify_work_product(self, step: str, content: str) -> str:
        """Classify the type of work product based on step description and content"""
        step_lower = (step + " " + content[:200]).lower()
        if any(
            kw in step_lower
            for kw in [
                "code",
                "implement",
                "function",
                "class",
                "script",
                "def ",
                "import ",
            ]
        ):
            return "code"
        elif any(kw in step_lower for kw in ["plan", "roadmap", "strategy", "steps", "approach"]):
            return "plan"
        elif any(kw in step_lower for kw in ["design", "architecture", "diagram", "layout", "wireframe"]):
            return "design"
        elif any(kw in step_lower for kw in ["review", "audit", "evaluate", "assess"]):
            return "review"
        elif any(kw in step_lower for kw in ["document", "readme", "guide", "tutorial"]):
            return "documentation"
        return "analysis"

    # =========================================================================
    # Work Product Persistence
    # =========================================================================

    def _save_work_product(
        self,
        session: CollabSession,
        product_type: str,
        title: str,
        content: str,
        author: str,
        parent_id: int = None,
    ) -> Optional[int]:
        """Save a work product to DB"""
        if not session.db_id:
            return None
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO collaboration_work_products
                (session_id, product_type, title, content, author, parent_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (session.db_id, product_type, title, content, author, parent_id),
            )
            wp_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

            # Cache in session
            session.work_products.append(
                {
                    "id": wp_id,
                    "product_type": product_type,
                    "title": title,
                    "content": content,
                    "author": author,
                    "approved": False,
                    "version": 1,
                }
            )
            return wp_id
        except Exception as e:
            logger.warning(f"Failed to save work product: {e}")
            return None

    def get_work_products(self, session_uuid: str) -> List[dict]:
        """Get all work products for a session"""
        # Check in-memory cache first
        session = self.sessions.get(session_uuid)
        if session and session.work_products:
            return session.work_products

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT wp.id, wp.product_type, wp.title, wp.content, wp.author,
                       wp.version, wp.parent_id, wp.approved, wp.approved_by,
                       wp.approved_at, wp.metadata, wp.created_at
                FROM collaboration_work_products wp
                JOIN collaboration_sessions cs ON wp.session_id = cs.id
                WHERE cs.session_uuid = %s
                ORDER BY wp.id
            """,
                (session_uuid,),
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            products = []
            for r in rows:
                products.append(
                    {
                        "id": r["id"],
                        "product_type": r["product_type"],
                        "title": r["title"],
                        "content": r["content"],
                        "author": r["author"],
                        "version": r["version"],
                        "parent_id": r["parent_id"],
                        "approved": r["approved"],
                        "approved_by": r["approved_by"],
                        "approved_at": (r["approved_at"].isoformat() if r["approved_at"] else None),
                        "metadata": r["metadata"],
                        "created_at": (r["created_at"].isoformat() if r["created_at"] else None),
                    }
                )
            return products
        except Exception as e:
            logger.warning(f"Failed to get work products: {e}")
            return []

    def approve_work_product(self, product_id: int, approved_by: str) -> bool:
        """Approve a work product"""
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE collaboration_work_products
                SET approved = TRUE, approved_by = %s, approved_at = NOW()
                WHERE id = %s
            """,
                (approved_by, product_id),
            )
            conn.commit()
            affected = cur.rowcount
            cur.close()
            conn.close()
            return affected > 0
        except Exception as e:
            logger.warning(f"Failed to approve work product: {e}")
            return False

    def revise_work_product(self, product_id: int, new_content: str, revised_by: str) -> Optional[int]:
        """Create a new version of a work product"""
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            # Get original
            cur.execute(
                """
                SELECT session_id, product_type, title, version
                FROM collaboration_work_products WHERE id = %s
            """,
                (product_id,),
            )
            original = cur.fetchone()
            if not original:
                cur.close()
                conn.close()
                return None

            # Create new version
            cur.execute(
                """
                INSERT INTO collaboration_work_products
                (session_id, product_type, title, content, author, version, parent_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    original["session_id"],
                    original["product_type"],
                    original["title"],
                    new_content,
                    revised_by,
                    original["version"] + 1,
                    product_id,
                ),
            )
            new_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()
            return new_id
        except Exception as e:
            logger.warning(f"Failed to revise work product: {e}")
            return None


# Singleton
_engine: Optional[CollaborationEngine] = None


def get_collaboration_engine() -> CollaborationEngine:
    """Get the collaboration engine singleton instance"""
    global _engine
    if _engine is None:
        _engine = CollaborationEngine()
    return _engine
