# Plan: Dual-AI Chat System Implementation

> **For Claude:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add split-panel chat with ARCHIE + Claude CLI, AI-to-AI collaboration mode, and learning integration.

**Architecture:** Three chat modes (Solo, Side-by-Side, Collab) with ttyd terminal, WebSocket bridge, and knowledge extraction.

**Tech Stack:** Python/Flask, ttyd, xterm.js, WebSocket, existing Phase 82 knowledge pipeline

---

## Phase 1: Terminal Infrastructure

### Task 1.1: Install ttyd

**Files:**
- Create: `scripts/install_ttyd.sh`

**Steps:**

1. Create installation script:
```bash
#!/bin/bash
# Install ttyd for terminal-over-WebSocket

# For Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y ttyd

# Verify installation
ttyd --version

echo "ttyd installed successfully"
```

2. Make executable and run:
```bash
chmod +x scripts/install_ttyd.sh
./scripts/install_ttyd.sh
```

**Verify:** `ttyd --version` returns version number.

---

### Task 1.2: Create ttyd Service Configuration

**Files:**
- Create: `scripts/ttyd-claude.service` (systemd unit)
- Create: `scripts/start_ttyd.sh`

**Steps:**

1. Create start script that launches ttyd with claude:
```bash
#!/bin/bash
# Start ttyd with Claude CLI
# Runs on port 7681, requires authentication

ttyd -p 7681 -c <user>:<password> -W claude   # literal credential redacted 2026-09-10; the shipped design uses ttyd_auth_proxy.py instead of ttyd -c
```

2. Create systemd service file for auto-start:
```ini
[Unit]
Description=ttyd Claude CLI Terminal
After=network.target

[Service]
Type=simple
ExecStart=/mnt/archie_brain/scripts/start_ttyd.sh
Restart=always
User=kytran

[Install]
WantedBy=multi-user.target
```

3. Enable and start service:
```bash
sudo systemctl enable ttyd-claude
sudo systemctl start ttyd-claude
```

**Verify:** `curl http://localhost:7681` returns ttyd page.

---

### Task 1.3: Add xterm.js to Static Files

**Files:**
- Create: `platform_v2/static/js/xterm.min.js`
- Create: `platform_v2/static/js/xterm-addon-fit.min.js`
- Create: `platform_v2/static/js/xterm-addon-web-links.min.js`
- Create: `platform_v2/static/css/xterm.css`

**Steps:**

1. Download xterm.js from CDN or npm:
```bash
cd platform_v2/static/js
curl -O https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js
curl -O https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js
curl -O https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.min.js

cd ../css
curl -O https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css
```

**Verify:** Files exist in static directories.

---

## Phase 2: Claude Bridge Backend

### Task 2.1: Create Claude Bridge Module

**Files:**
- Create: `platform_v2/tools/consciousness/claude_bridge.py`

**Contents:**

```python
"""
Claude Bridge - Communication layer for Claude CLI

Handles:
- Sending messages to Claude CLI via ttyd WebSocket
- Capturing Claude's responses
- Session management
"""

import asyncio
import websockets
import json
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)

TTYD_WS_URL = "ws://localhost:7681/ws"


class ClaudeBridge:
    """Bridge to Claude CLI via ttyd WebSocket"""

    def __init__(self):
        self.ws = None
        self.connected = False
        self.response_buffer = ""

    async def connect(self) -> bool:
        """Connect to ttyd WebSocket"""
        try:
            self.ws = await websockets.connect(TTYD_WS_URL)
            self.connected = True
            logger.info("Connected to Claude CLI via ttyd")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to ttyd: {e}")
            return False

    async def send_message(self, message: str) -> Optional[str]:
        """Send message to Claude and get response"""
        if not self.connected:
            await self.connect()

        if not self.ws:
            return None

        try:
            # Send message to terminal
            await self.ws.send(message + "\n")

            # Collect response until prompt returns
            response = await self._collect_response()
            return response

        except Exception as e:
            logger.error(f"Error sending to Claude: {e}")
            return None

    async def _collect_response(self, timeout: float = 120.0) -> str:
        """Collect response from Claude until done"""
        response = ""
        try:
            while True:
                msg = await asyncio.wait_for(
                    self.ws.recv(),
                    timeout=timeout
                )
                response += msg

                # Check for completion indicators
                if self._is_response_complete(response):
                    break

        except asyncio.TimeoutError:
            logger.warning("Claude response timeout")

        return self._clean_response(response)

    def _is_response_complete(self, response: str) -> bool:
        """Check if Claude has finished responding"""
        # Look for prompt return or other indicators
        indicators = ["\n> ", "\n$ ", "❯ "]
        return any(ind in response[-50:] for ind in indicators)

    def _clean_response(self, response: str) -> str:
        """Clean terminal escape codes and formatting"""
        import re
        # Remove ANSI escape codes
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        clean = ansi_escape.sub('', response)
        return clean.strip()

    async def disconnect(self):
        """Close WebSocket connection"""
        if self.ws:
            await self.ws.close()
            self.connected = False

    def health_check(self) -> dict:
        """Check if Claude CLI is available"""
        import subprocess
        try:
            result = subprocess.run(
                ["which", "claude"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return {"status": "healthy", "path": result.stdout.decode().strip()}
            return {"status": "unhealthy", "error": "claude not found"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# Singleton instance
_bridge: Optional[ClaudeBridge] = None

def get_claude_bridge() -> ClaudeBridge:
    global _bridge
    if _bridge is None:
        _bridge = ClaudeBridge()
    return _bridge
```

**Verify:** Import works without errors.

---

### Task 2.2: Create Collaboration Engine

**Files:**
- Create: `platform_v2/tools/consciousness/collaboration_engine.py`

**Contents:**

```python
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
                {"role": m.role, "content": m.content, "turn": m.turn, "timestamp": m.timestamp}
                for m in self.messages
            ],
            "current_turn": self.current_turn,
            "max_turns": self.max_turns,
            "created_at": self.created_at
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
            from ai_bridge.knowledge_analyzer import get_knowledge_analyzer
            self._archie = get_knowledge_analyzer()
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
            max_turns=max_turns
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
        user_msg = CollabMessage(
            role="user",
            content=session.topic,
            turn=0
        )
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
                session.messages.append(CollabMessage(
                    role="archie",
                    content=archie_response,
                    turn=session.current_turn
                ))

                # Check if ARCHIE thinks we're done
                if self._is_conclusion(archie_response):
                    break

                # Claude's turn
                claude_response = await self._get_claude_response(session)
                session.messages.append(CollabMessage(
                    role="claude",
                    content=claude_response,
                    turn=session.current_turn
                ))

                # Check if Claude thinks we're done
                if self._is_conclusion(claude_response):
                    break

            session.status = CollabStatus.COMPLETED

            # Extract learnings
            await self._extract_learnings(session)

        except Exception as e:
            logger.error(f"Collaboration error: {e}")
            session.status = CollabStatus.ERROR

        return session

    async def _get_archie_response(self, session: CollabSession) -> str:
        """Get ARCHIE's response based on conversation so far"""
        # Build context from previous messages
        context = self._build_context(session)

        prompt = f"""You are ARCHIE, collaborating with Claude to answer: "{session.topic}"

Previous discussion:
{context}

Provide your thoughts, ask Claude clarifying questions, or build on their points.
Keep response concise (2-3 paragraphs max).
If you think the topic is fully addressed, say "I think we've covered this well."
"""

        # Use local LLM for ARCHIE
        result = self._get_archie()._call_llm(prompt, max_tokens=1000)
        return result[0] if result else "I need more time to think about this."

    async def _get_claude_response(self, session: CollabSession) -> str:
        """Get Claude's response via CLI"""
        context = self._build_context(session)

        message = f"""ARCHIE and I are discussing: "{session.topic}"

Conversation so far:
{context}

Please respond to ARCHIE's latest point. Be helpful and collaborative.
"""

        bridge = self._get_claude()
        response = await bridge.send_message(message)
        return response or "I need a moment to consider this."

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
            "i think we've answered"
        ]
        response_lower = response.lower()
        return any(ind in response_lower for ind in indicators)

    async def _extract_learnings(self, session: CollabSession):
        """Extract knowledge from collaboration and save to ARCHIE's knowledge base"""
        from .learning_extractor import extract_and_save_learnings
        await extract_and_save_learnings(session)

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
            session.messages.append(CollabMessage(
                role="user",
                content=message,
                turn=session.current_turn
            ))
            return True
        return False

    def get_session(self, session_id: str) -> Optional[CollabSession]:
        """Get session by ID"""
        return self.sessions.get(session_id)


# Singleton
_engine: Optional[CollaborationEngine] = None

def get_collaboration_engine() -> CollaborationEngine:
    global _engine
    if _engine is None:
        _engine = CollaborationEngine()
    return _engine
```

**Verify:** Import works without errors.

---

### Task 2.3: Create Learning Extractor

**Files:**
- Create: `platform_v2/tools/consciousness/learning_extractor.py`

**Contents:**

```python
"""
Learning Extractor - Extract knowledge from ARCHIE-Claude collaborations

Analyzes collaboration sessions and saves learnings to knowledge base.
"""

import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


async def extract_and_save_learnings(session) -> dict:
    """
    Extract learnings from a collaboration session and save to knowledge base.

    Args:
        session: CollabSession object

    Returns:
        dict with extraction stats
    """
    from ai_bridge.knowledge_analyzer import get_knowledge_analyzer, KnowledgeCard
    from ai_bridge.knowledge_cards import save_knowledge_card
    from ai_bridge.embedding_service import generate_embedding

    stats = {"cards_created": 0, "topics": [], "error": None}

    try:
        analyzer = get_knowledge_analyzer()

        # Build full conversation text
        conversation = "\n\n".join([
            f"{m.role.upper()}: {m.content}"
            for m in session.messages
        ])

        # Create extraction prompt
        prompt = f"""Analyze this collaboration between ARCHIE (local AI) and Claude.

TOPIC: {session.topic}

CONVERSATION:
{conversation}

Extract the key learnings that ARCHIE should remember. Return JSON:
{{
    "learnings": [
        {{
            "title": "Clear, specific title for this learning",
            "summary": "2-3 sentence summary of what was learned",
            "detailed": "Full explanation with examples if any",
            "topics": ["topic1", "topic2"],
            "technologies": ["tech1", "tech2"],
            "archie_was_uncertain_about": "What ARCHIE didn't know",
            "claude_taught": "Key insight Claude provided",
            "confidence": 0.0-1.0
        }}
    ]
}}

Focus on actionable knowledge ARCHIE can use in future conversations.
Return ONLY valid JSON."""

        # Use local LLM to extract
        response, _, _, _ = analyzer._call_llm(prompt, max_tokens=2000)

        # Parse response
        import json
        data = json.loads(response.strip().strip("```json").strip("```"))

        learnings = data.get("learnings", [])

        for learning in learnings:
            # Create knowledge card
            card = KnowledgeCard(
                title=learning.get("title", "Untitled Learning"),
                card_type="learned_from_claude",
                summary=learning.get("summary", ""),
                detailed=learning.get("detailed", ""),
                topics=learning.get("topics", []),
                technologies=learning.get("technologies", []),
                confidence=float(learning.get("confidence", 0.8)),
                source_type="collaboration",
                source_ref=session.id
            )

            # Add extra metadata
            card.detailed += f"\n\n---\nARCHIE was uncertain about: {learning.get('archie_was_uncertain_about', 'N/A')}"
            card.detailed += f"\nClaude taught: {learning.get('claude_taught', 'N/A')}"

            # Generate embedding
            embedding = generate_embedding(f"{card.title}. {card.summary}")

            # Save card
            card_id = save_knowledge_card(card, embedding, f"collab_{session.id}")

            if card_id:
                stats["cards_created"] += 1
                stats["topics"].extend(learning.get("topics", []))
                logger.info(f"Saved learning: {card.title} (ID: {card_id})")

        stats["topics"] = list(set(stats["topics"]))  # Dedupe

    except Exception as e:
        logger.error(f"Learning extraction failed: {e}")
        stats["error"] = str(e)

    return stats


def get_learning_stats() -> dict:
    """Get stats about learnings from collaborations"""
    import psycopg2
    import os

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", "archiepass"),
        )
        cur = conn.cursor()

        # Count learnings from Claude
        cur.execute("""
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'collaboration'
        """)
        total = cur.fetchone()[0]

        # Count from last week
        cur.execute("""
            SELECT COUNT(*) FROM knowledge_base
            WHERE source_type = 'collaboration'
            AND created_at > NOW() - INTERVAL '7 days'
        """)
        last_week = cur.fetchone()[0]

        # Top topics
        cur.execute("""
            SELECT unnest(tags) as topic, COUNT(*) as cnt
            FROM knowledge_base
            WHERE source_type = 'collaboration'
            GROUP BY topic
            ORDER BY cnt DESC
            LIMIT 5
        """)
        top_topics = [row[0] for row in cur.fetchall()]

        cur.close()
        conn.close()

        return {
            "total_learnings": total,
            "learnings_last_week": last_week,
            "top_topics": top_topics
        }

    except Exception as e:
        logger.error(f"Failed to get learning stats: {e}")
        return {"error": str(e)}
```

**Verify:** Import works without errors.

---

## Phase 3: API Routes

### Task 3.1: Add Collaboration Routes

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py`

**Add these routes:**

```python
# Add to imports
from .collaboration_engine import get_collaboration_engine, CollabStatus
from .learning_extractor import get_learning_stats
import asyncio

# Add routes

@consciousness_bp.route("/api/collab/start", methods=["POST"])
def start_collaboration():
    """Start a new AI-to-AI collaboration session"""
    try:
        data = request.get_json() or {}
        topic = data.get("topic", "")
        max_turns = min(int(data.get("max_turns", 10)), 20)

        if not topic:
            return jsonify({"success": False, "error": "Topic required"}), 400

        engine = get_collaboration_engine()
        session = engine.start_session(topic, max_turns)

        # Run collaboration in background
        def run_async():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(engine.run_collaboration(session.id))
            loop.close()

        import threading
        thread = threading.Thread(target=run_async)
        thread.start()

        return jsonify({
            "success": True,
            "session_id": session.id,
            "status": session.status.value
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/status/<session_id>", methods=["GET"])
def get_collaboration_status(session_id):
    """Get current status of a collaboration session"""
    try:
        engine = get_collaboration_engine()
        session = engine.get_session(session_id)

        if not session:
            return jsonify({"success": False, "error": "Session not found"}), 404

        return jsonify({
            "success": True,
            "session": session.to_dict()
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@consciousness_bp.route("/api/collab/pause/<session_id>", methods=["POST"])
def pause_collaboration(session_id):
    """Pause a running collaboration"""
    engine = get_collaboration_engine()
    success = engine.pause_session(session_id)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/resume/<session_id>", methods=["POST"])
def resume_collaboration(session_id):
    """Resume a paused collaboration"""
    engine = get_collaboration_engine()
    success = engine.resume_session(session_id)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/stop/<session_id>", methods=["POST"])
def stop_collaboration(session_id):
    """Stop a collaboration early"""
    engine = get_collaboration_engine()
    success = engine.stop_session(session_id)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/interject/<session_id>", methods=["POST"])
def add_interjection(session_id):
    """Add user message to ongoing collaboration"""
    data = request.get_json() or {}
    message = data.get("message", "")

    if not message:
        return jsonify({"success": False, "error": "Message required"}), 400

    engine = get_collaboration_engine()
    success = engine.add_interjection(session_id, message)
    return jsonify({"success": success})


@consciousness_bp.route("/api/collab/learnings", methods=["GET"])
def get_learnings():
    """Get learning statistics from collaborations"""
    stats = get_learning_stats()
    return jsonify({"success": True, **stats})
```

**Verify:** Routes return expected responses.

---

## Phase 4: UI Implementation

### Task 4.1: Add CSS for Dual Chat

**Files:**
- Create: `platform_v2/static/css/dual-chat.css`

**Contents:**

```css
/* Dual-AI Chat Styles */

.chat-mode-tabs {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    padding: 0.5rem;
    background: var(--archie-bg-secondary);
    border-radius: 8px;
}

.chat-mode-btn {
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 6px;
    background: transparent;
    color: var(--archie-text-muted);
    cursor: pointer;
    transition: all 0.2s;
}

.chat-mode-btn:hover {
    background: var(--archie-bg-tertiary);
    color: var(--archie-text);
}

.chat-mode-btn.active {
    background: var(--module-accent);
    color: white;
}

/* Split Panel Layout */
.dual-chat-container {
    display: flex;
    height: calc(100vh - 300px);
    min-height: 400px;
    gap: 4px;
}

.chat-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    background: var(--archie-bg-secondary);
    border-radius: 8px;
    overflow: hidden;
}

.chat-panel-header {
    padding: 0.75rem 1rem;
    background: var(--archie-bg-tertiary);
    border-bottom: 1px solid var(--archie-border);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.chat-panel-header .ai-name {
    font-weight: 600;
    color: var(--archie-text);
}

.chat-panel-header .ai-model {
    font-size: 0.75rem;
    color: var(--archie-text-muted);
}

.chat-panel-header.archie {
    border-left: 3px solid #8b5cf6;
}

.chat-panel-header.claude {
    border-left: 3px solid #00ffff;
}

/* Resize Handle */
.resize-handle {
    width: 4px;
    background: var(--archie-border);
    cursor: col-resize;
    transition: background 0.2s;
}

.resize-handle:hover {
    background: var(--module-accent);
}

/* Terminal Panel */
.terminal-container {
    flex: 1;
    background: #1a1a2e;
}

.terminal-container .xterm {
    height: 100%;
    padding: 0.5rem;
}

/* Collaboration Mode */
.collab-container {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 300px);
}

.collab-messages {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
}

.collab-message {
    margin-bottom: 1rem;
    padding: 1rem;
    border-radius: 8px;
    animation: fadeIn 0.3s ease;
}

.collab-message.archie {
    background: rgba(139, 92, 246, 0.1);
    border-left: 3px solid #8b5cf6;
}

.collab-message.claude {
    background: rgba(0, 255, 255, 0.1);
    border-left: 3px solid #00ffff;
}

.collab-message.user {
    background: rgba(255, 255, 255, 0.05);
    border-left: 3px solid #888;
}

.collab-message .role {
    font-weight: 600;
    margin-bottom: 0.5rem;
}

.collab-message.archie .role { color: #8b5cf6; }
.collab-message.claude .role { color: #00ffff; }
.collab-message.user .role { color: #888; }

/* Collab Controls */
.collab-controls {
    padding: 1rem;
    background: var(--archie-bg-tertiary);
    border-top: 1px solid var(--archie-border);
    display: flex;
    gap: 1rem;
    align-items: center;
}

.collab-controls .turn-counter {
    color: var(--archie-text-muted);
    font-size: 0.875rem;
}

.collab-controls .status-indicator {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.collab-controls .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    animation: pulse 1.5s infinite;
}

.collab-controls .status-dot.active { background: #00ff41; }
.collab-controls .status-dot.paused { background: #ffaa00; }
.collab-controls .status-dot.completed { background: #8b5cf6; }

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

/* Responsive */
@media (max-width: 768px) {
    .dual-chat-container {
        flex-direction: column;
    }

    .resize-handle {
        width: 100%;
        height: 4px;
        cursor: row-resize;
    }
}
```

**Verify:** CSS file created.

---

### Task 4.2: Update Chat Tab HTML

**Files:**
- Modify: `platform_v2/templates/tools/consciousness_dashboard.html`

**Changes:**

Update the Chat tab (tab-chat div) with mode switcher and split panel layout. Add mode tabs, dual panel container, collaboration view, and terminal integration.

Key additions:
1. Mode switcher buttons (Solo, Side-by-Side, Collab)
2. Split panel layout for Side-by-Side mode
3. Collaboration view with controls
4. xterm.js terminal for Claude CLI
5. JavaScript for mode switching and collaboration

**Verify:** Chat tab shows mode switcher and panels render correctly.

---

### Task 4.3: Add Collaboration JavaScript

**Files:**
- Create: `platform_v2/static/js/collaboration.js`

**Contents:** JavaScript functions for:
- Mode switching (solo/side-by-side/collab)
- Terminal initialization with xterm.js
- Collaboration controls (start/pause/stop/interject)
- Message streaming and display
- Panel resize functionality

**Verify:** Mode switching works, terminal connects.

---

## Phase 5: Integration & Testing

### Task 5.1: Test Terminal Connection

**Steps:**
1. Start ttyd service
2. Load Chat tab
3. Switch to Side-by-Side mode
4. Verify terminal connects and shows claude prompt

**Verify:** Can type in terminal and see Claude responses.

---

### Task 5.2: Test Collaboration Flow

**Steps:**
1. Switch to Collab mode
2. Enter a topic
3. Click Start
4. Watch ARCHIE and Claude discuss
5. Test pause/resume/stop
6. Check learnings saved to knowledge base

**Verify:** Full ping-pong works, learnings extracted.

---

### Task 5.3: Final Commit

**Commit message:**
```
feat(consciousness): add dual-AI chat with ARCHIE-Claude collaboration

- Add ttyd terminal integration for Claude CLI
- Create collaboration engine for AI-to-AI ping-pong
- Add learning extractor to save Claude's teachings
- Implement three chat modes: Solo, Side-by-Side, Collab
- Add xterm.js for browser terminal
- Create collaboration API routes
- Add responsive split-panel UI

ARCHIE can now learn from Claude and become smarter over time.

Phase 83: Dual-AI Chat System
```

---

## Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1.1-1.3 | Terminal infrastructure (ttyd, xterm.js) |
| 2 | 2.1-2.3 | Backend (Claude bridge, collab engine, learning extractor) |
| 3 | 3.1 | API routes for collaboration |
| 4 | 4.1-4.3 | UI (CSS, HTML, JavaScript) |
| 5 | 5.1-5.3 | Testing and commit |

**Total: 12 tasks**

---

## Dependencies

- ttyd (system package)
- xterm.js (CDN/static)
- websockets (pip) - for Claude bridge
- Existing Phase 82 knowledge pipeline

---

## Risk Notes

- **ttyd auth**: Use basic auth or integrate with ARCHIE session
- **Claude CLI login**: User must login to claude CLI first
- **Timeout handling**: Long responses need proper timeouts
- **Learning quality**: Local LLM extraction may vary in quality
