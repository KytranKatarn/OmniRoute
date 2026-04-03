# A.R.C.H.I.E. Code Phase 1 — Smart Local + Platform Dispatch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix intent classification, add DispatchStrategy that routes requests to local Ollama or platform Bridge, wire hub connector for agent dispatch, and add job logging.

**Architecture:** Engine gets a new `DispatchStrategy` between intent classification and routing. It checks: is hub connected? Does this intent type need a specialist agent? If yes → dispatch via `HubConnector.dispatch()`. If no → handle locally via existing `CommandRouter`. Offline fallback is always local Ollama.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, aiohttp, websockets

**Repo:** `/mnt/archie_brain/archie-code/`
**Venv:** `source .venv/bin/activate` before all commands
**Run tests:** `python -m pytest archie_engine/tests/ -v`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `archie_engine/intent.py` | Fix classification priority — knowledge_query must beat shell_command for natural language |
| Create | `archie_engine/dispatch_strategy.py` | Decide: local vs platform vs escalation for each intent |
| Modify | `archie_engine/router.py` | Accept optional `hub_connector` param, add platform dispatch handler |
| Modify | `archie_engine/engine.py` | Wire DispatchStrategy between intent parser and router |
| Modify | `archie_engine/hub/connector.py` | Add `log_job()` and `get_agent_status()` methods |
| Modify | `archie_engine/claude/context_bridge.py` | Fix `datetime.utcnow()` deprecation |
| Create | `archie_engine/tests/test_dispatch_strategy.py` | Unit tests for routing decisions |
| Modify | `archie_engine/tests/test_intent.py` | Add regression tests for misclassification bugs |
| Modify | `archie_engine/tests/test_router.py` | Add platform dispatch handler tests |
| Modify | `archie_engine/tests/test_engine.py` | Add integration test for dispatch flow |

---

### Task 1: Fix datetime.utcnow() Deprecation (Platform Task #1600)

**Files:**
- Modify: `archie_engine/claude/context_bridge.py:4,23`
- Modify: `archie_engine/tests/test_context_bridge.py` (verify warnings gone)

- [ ] **Step 1: Fix the import and usage**

In `archie_engine/claude/context_bridge.py`, change line 4:
```python
# OLD:
from datetime import datetime

# NEW:
from datetime import datetime, timezone
```

And change line 23:
```python
# OLD:
"timestamp": datetime.utcnow().isoformat(),

# NEW:
"timestamp": datetime.now(timezone.utc).isoformat(),
```

- [ ] **Step 2: Run tests to verify fix and no warnings**

Run: `python -m pytest archie_engine/tests/test_context_bridge.py -v -W error::DeprecationWarning`
Expected: 6 passed, 0 warnings (previously had 6 DeprecationWarning)

- [ ] **Step 3: Run full suite to verify no regressions**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: 156 passed

- [ ] **Step 4: Commit**

```bash
git add archie_engine/claude/context_bridge.py
git commit -m "fix: replace datetime.utcnow() with timezone-aware datetime.now(UTC)"
```

---

### Task 2: Fix Intent Parser Misclassification (Platform Task #1596)

**Files:**
- Modify: `archie_engine/intent.py:6-26,32-61`
- Modify: `archie_engine/tests/test_intent.py`

- [ ] **Step 1: Write failing tests for the misclassification bugs**

Add to `archie_engine/tests/test_intent.py`:

```python
def test_classify_question_not_shell(parser):
    """Natural language questions must NOT be classified as shell_command."""
    result = parser.classify("What models are available on Ollama?")
    assert result["type"] != "shell_command", f"Got {result['type']} — questions should not be shell"
    assert result["type"] in ("knowledge_query", "conversation")


def test_classify_how_question_is_knowledge(parser):
    """'How do I...' questions should be knowledge_query."""
    result = parser.classify("How do I configure the database connection?")
    assert result["type"] == "knowledge_query"


def test_classify_what_is_question(parser):
    """'What is...' questions should be knowledge_query."""
    result = parser.classify("What is the Bridge dispatcher?")
    assert result["type"] == "knowledge_query"


def test_classify_list_files_is_file_operation(parser):
    """'list all files in src/' should be file_operation, not conversation."""
    result = parser.classify("list all files in src/")
    assert result["type"] == "file_operation"


def test_classify_run_explicit_is_shell(parser):
    """'run npm install' should still be shell_command."""
    result = parser.classify("run npm install")
    assert result["type"] == "shell_command"


def test_classify_docker_is_shell(parser):
    """'docker compose up' should be shell_command."""
    result = parser.classify("docker compose up -d")
    assert result["type"] == "shell_command"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest archie_engine/tests/test_intent.py -v -k "question_not_shell or how_question or what_is or list_files"`
Expected: At least 3 FAIL (the misclassification bugs)

- [ ] **Step 3: Fix the intent parser**

Replace the `INTENT_PATTERNS` dict and `classify` method in `archie_engine/intent.py`:

```python
"""Intent classification — rule-based keyword matching with LLM fallback stub."""

import re

INTENT_PATTERNS = {
    "knowledge_query": {
        "keywords": ["what does", "how does", "explain", "what is", "describe", "documentation", "how to", "how do", "why does", "why is", "what are", "tell me about"],
        "patterns": [r"\bwhat\s+\w+", r"\bhow\s+\w+", r"\bexplain\b", r"\bdescribe\b", r"\bwhy\s+\w+", r"\btell\s+me\b"],
        "priority": 10,
    },
    "file_operation": {
        "keywords": ["read", "open", "show", "cat", "find", "search", "glob", "grep", "list files", "write file", "create file", "edit file", "list all files"],
        "patterns": [r"\bread\b.*\.\w+", r"\bopen\b.*\.\w+", r"\bshow\b.*\.\w+", r"\bfind\b.*file", r"\bgrep\b", r"\bglob\b", r"\blist\b.*\bfiles?\b"],
        "priority": 8,
    },
    "git_operation": {
        "keywords": ["git", "commit", "branch", "merge", "diff", "push", "pull", "rebase", "stash", "checkout", "log"],
        "patterns": [r"\bgit\b", r"\bcommit\b", r"\bbranch\b", r"\bmerge\b", r"\bdiff\b"],
        "priority": 7,
    },
    "code_task": {
        "keywords": ["fix", "implement", "refactor", "add feature", "write code", "debug", "bug", "error", "build", "create function", "modify", "update code"],
        "patterns": [r"\bfix\b", r"\bimplement\b", r"\brefactor\b", r"\bbug\b", r"\bdebug\b", r"\berror\b"],
        "priority": 6,
    },
    "shell_command": {
        "keywords": ["run", "execute", "npm", "pip", "make", "docker", "curl", "wget", "mkdir"],
        "patterns": [r"\brun\s+\S+", r"\bexecute\s+\S+", r"\bnpm\s+\w+", r"\bpip\s+\w+", r"\bdocker\s+\w+", r"\bmake\b"],
        "priority": 5,
    },
}


class IntentParser:
    def classify(self, text: str) -> dict:
        """Classify user input into an intent type with confidence score."""
        text_lower = text.lower().strip()
        best_type = "conversation"
        best_score = 0.0
        best_priority = 0

        for intent_type, config in INTENT_PATTERNS.items():
            score = 0.0
            # Keyword matching
            keyword_hits = sum(1 for kw in config["keywords"] if kw in text_lower)
            if keyword_hits > 0:
                score += min(keyword_hits * 0.3, 0.6)
            # Regex pattern matching
            regex_hits = sum(1 for p in config["patterns"] if re.search(p, text_lower))
            if regex_hits > 0:
                score += min(regex_hits * 0.2, 0.4)

            priority = config.get("priority", 0)

            # Higher score wins. On tie, higher priority wins.
            if score > best_score or (score == best_score and priority > best_priority):
                best_score = score
                best_type = intent_type
                best_priority = priority

        # Confidence: scale 0-1, conversation fallback gets low confidence
        confidence = min(best_score, 1.0) if best_type != "conversation" else 0.2

        return {
            "type": best_type,
            "confidence": confidence,
            "raw_input": text,
            "entities": self._extract_entities(text),
        }

    def _extract_entities(self, text: str) -> dict:
        """Extract useful entities (file paths, git refs, etc.) from input."""
        entities = {}
        # File paths (e.g., "config.py", "src/main.rs", "./foo/bar.txt")
        file_matches = re.findall(r'[\w./\-]+\.\w+', text)
        if file_matches:
            entities["files"] = file_matches
        # Git refs
        git_ref = re.findall(r'\b(?:main|master|HEAD|[a-f0-9]{7,40})\b', text)
        if git_ref:
            entities["git_refs"] = git_ref
        return entities
```

Key changes:
- Added `priority` field to each intent type — knowledge_query (10) beats shell_command (5)
- On tied scores, higher priority wins — questions go to knowledge, not shell
- Expanded knowledge_query patterns: `\bwhat\s+\w+` catches "What models...", "What is..."
- Shell patterns now require `\brun\s+\S+` (must have something after "run"), not bare `\brun\b`
- Removed "ls" and "cd" from shell keywords (too common in natural language)
- Added "list all files" to file_operation keywords, `\blist\b.*\bfiles?\b` pattern

- [ ] **Step 4: Run the new tests**

Run: `python -m pytest archie_engine/tests/test_intent.py -v`
Expected: All tests PASS (original 9 + 6 new = 15)

- [ ] **Step 5: Run full suite**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: 162 passed (156 original + 6 new)

- [ ] **Step 6: Commit**

```bash
git add archie_engine/intent.py archie_engine/tests/test_intent.py
git commit -m "fix: intent parser priority system — knowledge_query beats shell_command for questions"
```

---

### Task 3: Create DispatchStrategy Component (Platform Task #1597)

**Files:**
- Create: `archie_engine/dispatch_strategy.py`
- Create: `archie_engine/tests/test_dispatch_strategy.py`

- [ ] **Step 1: Write failing tests**

Create `archie_engine/tests/test_dispatch_strategy.py`:

```python
"""Tests for DispatchStrategy — local vs platform vs escalation routing."""

import pytest
from archie_engine.dispatch_strategy import DispatchStrategy, DispatchTarget


@pytest.fixture
def strategy_connected():
    """Strategy with hub connected."""
    return DispatchStrategy(hub_available=True)


@pytest.fixture
def strategy_offline():
    """Strategy with no hub."""
    return DispatchStrategy(hub_available=False)


def test_conversation_stays_local(strategy_connected):
    intent = {"type": "conversation", "confidence": 0.2, "raw_input": "hello"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_file_operation_stays_local(strategy_connected):
    intent = {"type": "file_operation", "confidence": 0.6, "raw_input": "read config.py"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_git_operation_stays_local(strategy_connected):
    intent = {"type": "git_operation", "confidence": 0.5, "raw_input": "git status"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_shell_command_stays_local(strategy_connected):
    intent = {"type": "shell_command", "confidence": 0.5, "raw_input": "run npm install"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_code_task_dispatches_to_platform(strategy_connected):
    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "refactor the auth module"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.PLATFORM
    assert result.capability is not None


def test_knowledge_query_dispatches_to_platform(strategy_connected):
    intent = {"type": "knowledge_query", "confidence": 0.5, "raw_input": "what does the Bridge do?"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.PLATFORM


def test_code_task_falls_back_local_when_offline(strategy_offline):
    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "refactor the auth module"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_knowledge_query_falls_back_local_when_offline(strategy_offline):
    intent = {"type": "knowledge_query", "confidence": 0.5, "raw_input": "what does the Bridge do?"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_low_confidence_escalates_to_claude(strategy_connected):
    intent = {"type": "code_task", "confidence": 0.15, "raw_input": "do something complex"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.CLAUDE


def test_low_confidence_offline_stays_local(strategy_offline):
    intent = {"type": "code_task", "confidence": 0.15, "raw_input": "do something complex"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_decide_returns_capability_for_code_task(strategy_connected):
    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "review this code"}
    result = strategy_connected.decide(intent)
    assert result.capability in ("code_review", "code_generation", "refactoring")


def test_decide_returns_reason(strategy_connected):
    intent = {"type": "conversation", "confidence": 0.2, "raw_input": "hello"}
    result = strategy_connected.decide(intent)
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest archie_engine/tests/test_dispatch_strategy.py -v`
Expected: FAIL — ModuleNotFoundError: No module named 'archie_engine.dispatch_strategy'

- [ ] **Step 3: Implement DispatchStrategy**

Create `archie_engine/dispatch_strategy.py`:

```python
"""Dispatch strategy — decides local vs platform vs Claude for each intent."""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class DispatchTarget(Enum):
    LOCAL = "local"
    PLATFORM = "platform"
    CLAUDE = "claude"


@dataclass
class DispatchDecision:
    target: DispatchTarget
    reason: str
    capability: str | None = None


# Intents that always run locally (tool-based, no LLM needed or simple LLM)
LOCAL_INTENTS = {"file_operation", "git_operation", "shell_command", "conversation"}

# Intents that benefit from specialist agents on the platform
PLATFORM_INTENTS = {
    "code_task": "code_generation",
    "knowledge_query": "knowledge_search",
}

# Confidence below this triggers Claude escalation (when hub is available)
ESCALATION_THRESHOLD = 0.2


class DispatchStrategy:
    """Decide where to route each intent: local engine, platform Bridge, or Claude."""

    def __init__(self, hub_available: bool = False):
        self.hub_available = hub_available

    def decide(self, intent: dict) -> DispatchDecision:
        """Return a DispatchDecision for the given classified intent."""
        intent_type = intent.get("type", "conversation")
        confidence = intent.get("confidence", 0.2)
        raw_input = intent.get("raw_input", "")

        # Low confidence + hub available → escalate to Claude
        if confidence < ESCALATION_THRESHOLD and self.hub_available:
            return DispatchDecision(
                target=DispatchTarget.CLAUDE,
                reason=f"Low confidence ({confidence:.2f}) — escalating to Claude",
                capability=None,
            )

        # Local intents always stay local
        if intent_type in LOCAL_INTENTS:
            return DispatchDecision(
                target=DispatchTarget.LOCAL,
                reason=f"Intent '{intent_type}' handled locally",
            )

        # Platform intents → dispatch if hub available, else fallback local
        if intent_type in PLATFORM_INTENTS:
            capability = self._resolve_capability(intent_type, raw_input)
            if self.hub_available:
                return DispatchDecision(
                    target=DispatchTarget.PLATFORM,
                    reason=f"Dispatching '{intent_type}' to platform agent",
                    capability=capability,
                )
            return DispatchDecision(
                target=DispatchTarget.LOCAL,
                reason=f"Hub offline — handling '{intent_type}' locally",
                capability=capability,
            )

        # Unknown intent type → local fallback
        return DispatchDecision(
            target=DispatchTarget.LOCAL,
            reason=f"Unknown intent '{intent_type}' — local fallback",
        )

    def _resolve_capability(self, intent_type: str, raw_input: str) -> str:
        """Map intent + raw input to a specific agent capability string."""
        base = PLATFORM_INTENTS.get(intent_type, "general")
        if intent_type != "code_task":
            return base

        lower = raw_input.lower()
        if any(kw in lower for kw in ("review", "audit", "check")):
            return "code_review"
        if any(kw in lower for kw in ("refactor", "clean", "simplify")):
            return "refactoring"
        return "code_generation"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest archie_engine/tests/test_dispatch_strategy.py -v`
Expected: 12 passed

- [ ] **Step 5: Run full suite**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: 174 passed (162 + 12)

- [ ] **Step 6: Commit**

```bash
git add archie_engine/dispatch_strategy.py archie_engine/tests/test_dispatch_strategy.py
git commit -m "feat: add DispatchStrategy — routes intents to local, platform, or Claude"
```

---

### Task 4: Wire DispatchStrategy into Engine + Router (Platform Tasks #1597, #1598)

**Files:**
- Modify: `archie_engine/router.py:1-17,24-31`
- Modify: `archie_engine/engine.py:32-46,162-213`
- Modify: `archie_engine/tests/test_router.py`
- Modify: `archie_engine/tests/test_engine.py`

- [ ] **Step 1: Write failing test for platform dispatch in router**

Add to `archie_engine/tests/test_router.py`:

```python
@pytest.mark.asyncio
async def test_route_platform_dispatch(mock_tools, mock_inference):
    """When hub connector is provided, platform intents dispatch through it."""
    from unittest.mock import AsyncMock

    mock_hub = AsyncMock()
    mock_hub.dispatch = AsyncMock(return_value={
        "response": "Code review complete. Found 2 issues.",
        "agent_name": "S.H.I.E.L.D.",
        "model": "qwen2.5:7b",
    })

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "review auth module"}
    context = {"working_dir": "/tmp", "history": []}

    result = await router.route(intent, context, dispatch_target="platform", capability="code_review")
    assert result["success"] is True
    assert "S.H.I.E.L.D." in result["response"] or "Code review" in result["response"]
    assert result["model_used"] is not None
    mock_hub.dispatch.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest archie_engine/tests/test_router.py::test_route_platform_dispatch -v`
Expected: FAIL — TypeError (unexpected keyword argument 'hub_connector')

- [ ] **Step 3: Add platform dispatch to CommandRouter**

Modify `archie_engine/router.py` — update `__init__` and add platform handler:

```python
"""Command router — dispatches intents to tools or inference."""

import logging
import re

from archie_engine.tools import ToolRegistry
from archie_engine.inference import InferenceClient

logger = logging.getLogger(__name__)


class CommandRouter:
    def __init__(self, tools: ToolRegistry, inference: InferenceClient,
                 default_model: str = "qwen2.5:7b", hub_connector=None):
        self.tools = tools
        self.inference = inference
        self.default_model = default_model
        self.hub_connector = hub_connector

    async def route(self, intent: dict, context: dict,
                    dispatch_target: str | None = None, capability: str | None = None) -> dict:
        """Route an intent to the appropriate handler. Returns response dict."""
        # Platform dispatch takes priority when specified
        if dispatch_target == "platform" and self.hub_connector:
            return await self._handle_platform_dispatch(
                intent["raw_input"], intent.get("entities", {}), context, capability
            )

        intent_type = intent.get("type", "conversation")
        raw_input = intent.get("raw_input", "")
        entities = intent.get("entities", {})

        handler = {
            "file_operation": self._handle_file_operation,
            "git_operation": self._handle_git_operation,
            "shell_command": self._handle_shell_command,
            "code_task": self._handle_code_task,
            "knowledge_query": self._handle_knowledge_query,
            "conversation": self._handle_conversation,
        }.get(intent_type, self._handle_conversation)

        try:
            return await handler(raw_input, entities, context)
        except Exception as e:
            logger.error("Router error for %s: %s", intent_type, e)
            return {"success": False, "response": f"Error: {e}", "tool_calls": []}

    async def _handle_platform_dispatch(self, raw_input: str, entities: dict,
                                        context: dict, capability: str | None) -> dict:
        """Dispatch to platform Bridge via hub connector."""
        user_context = {
            "working_dir": context.get("working_dir", ""),
            "files": entities.get("files", []),
            "history_length": len(context.get("history", [])),
        }

        resp = await self.hub_connector.dispatch(
            prompt=raw_input,
            agent_target=f"capability:{capability}" if capability else None,
            user_context=user_context,
        )

        if "error" in resp:
            logger.warning("Platform dispatch failed: %s — falling back to local", resp["error"])
            return await self._handle_code_task(raw_input, entities, context)

        agent_name = resp.get("agent_name", "platform agent")
        response_text = resp.get("response", "")
        model_used = resp.get("model", self.default_model)

        return {
            "success": True,
            "response": f"[{agent_name}] {response_text}",
            "tool_calls": [],
            "model_used": model_used,
            "agent_name": agent_name,
        }
```

Keep all existing handler methods (`_handle_file_operation`, `_handle_git_operation`, etc.) unchanged after this.

- [ ] **Step 4: Wire DispatchStrategy into engine.py**

Modify `archie_engine/engine.py` — add DispatchStrategy to imports and `__init__`, update `_process_chat_message`:

Add import at top (after line 6):
```python
from archie_engine.dispatch_strategy import DispatchStrategy, DispatchTarget
```

Add to `__init__` (after line 43, `self.server = ...`):
```python
        self.dispatch_strategy = DispatchStrategy(
            hub_available=is_hub_configured(config)
        )
```

Update router construction (around line 39) to pass hub_connector:
```python
        self.router = CommandRouter(
            tools=self.tools,
            inference=self.inference,
            default_model=config.default_model,
            hub_connector=self.hub_connector,
        )
```

Note: `self.hub_connector` is set later in `__init__` (line 72). Move the router construction AFTER the hub connector setup block (after line 89). The engine `__init__` order becomes:
1. Config, DB, sessions, inference, intent_parser, tools
2. Hub connector setup (if configured)
3. Router (now with hub_connector)
4. DispatchStrategy
5. Skills, Claude collaboration

Replace `_process_chat_message` method (lines 162-213):
```python
    async def _process_chat_message(self, msg: dict) -> dict:
        content = msg.get("content", "")
        session_id = msg.get("session_id")

        # Create session if needed
        if not session_id:
            session = await self.sessions.create(working_dir=str(Path.cwd()))
            session_id = session["id"]

        # Record user message
        await self.sessions.add_message(session_id, "user", content)

        # Check for slash command
        if content.startswith("/"):
            name, raw_args = self.skill_registry.parse_command(content)
            skill = self.skill_registry.get(name)
            if skill:
                args = {}
                if raw_args:
                    args["input"] = raw_args
                context = await self.sessions.build_context(session_id)
                result = await self.skill_registry.execute(name, args=args, context=context)
                response_text = result.get("response", "")
                await self.sessions.add_message(session_id, "assistant", response_text)
                return {
                    "type": "response",
                    "session_id": session_id,
                    "content": response_text,
                    "intent": f"skill:{name}",
                    "tool_calls": result.get("tool_calls", []),
                }

        # Classify intent
        intent = self.intent_parser.classify(content)

        # Decide dispatch target
        decision = self.dispatch_strategy.decide(intent)
        logger.info("Dispatch: %s → %s (%s)", intent["type"], decision.target.value, decision.reason)

        # Build context
        context = await self.sessions.build_context(session_id)

        # Route based on dispatch decision
        result = await self.router.route(
            intent, context,
            dispatch_target=decision.target.value if decision.target != DispatchTarget.LOCAL else None,
            capability=decision.capability,
        )

        # Record assistant response
        response_text = result.get("response", "")
        await self.sessions.add_message(session_id, "assistant", response_text)

        return {
            "type": "response",
            "session_id": session_id,
            "content": response_text,
            "intent": intent["type"],
            "dispatch_target": decision.target.value,
            "tool_calls": result.get("tool_calls", []),
        }
```

- [ ] **Step 5: Update hub_available when heartbeat connects**

In `engine.py`, update the `start()` method — after heartbeat starts, update dispatch_strategy:
```python
    async def start(self) -> None:
        self.config.ensure_dirs()
        await self.db.initialize()
        self.server.set_handler(self.handle_message)
        await self.server.start()
        if self.hub_heartbeat:
            await self.hub_heartbeat.start()
            self.dispatch_strategy.hub_available = (self.hub_heartbeat.status == HubStatus.CONNECTED)
            if self.hub_sync and self.hub_heartbeat.status == HubStatus.CONNECTED:
                await self.hub_sync.sync_all()
        self.skill_registry.load()
        logger.info("ARCHIE Engine started")
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: All pass (existing tests should still work because dispatch_target defaults to None → local routing)

- [ ] **Step 7: Commit**

```bash
git add archie_engine/router.py archie_engine/engine.py archie_engine/tests/test_router.py archie_engine/tests/test_engine.py
git commit -m "feat: wire DispatchStrategy into engine — routes intents through platform Bridge when hub connected"
```

---

### Task 5: Add Hub Connector Endpoints — log_job + get_agent_status (Platform Tasks #1598, #1599)

**Files:**
- Modify: `archie_engine/hub/connector.py:77-97`
- Modify: `archie_engine/tests/test_connector.py`

- [ ] **Step 1: Write failing tests**

Add to `archie_engine/tests/test_connector.py`:

```python
@pytest.mark.asyncio
async def test_log_job(connector, mock_server):
    mock_server.post("/api/archie/jobs", json={"success": True, "job_id": 42})
    result = await connector.log_job(
        task="code_review",
        agent_name="S.H.I.E.L.D.",
        result_summary="Found 2 issues",
        duration_ms=1500,
    )
    assert result.get("success") is True
    assert result.get("job_id") == 42


@pytest.mark.asyncio
async def test_get_agent_status(connector, mock_server):
    mock_server.get("/api/starbase/agents/15/status", json={
        "agent_id": 15,
        "shift_state": "active",
        "current_task": None,
    })
    result = await connector.get_agent_status(15)
    assert result.get("shift_state") == "active"
```

Note: Adapt the mock_server fixture pattern from the existing test file (uses `aioresponses` or similar).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest archie_engine/tests/test_connector.py -v -k "log_job or agent_status"`
Expected: FAIL — AttributeError (no method `log_job`)

- [ ] **Step 3: Add methods to HubConnector**

Add to `archie_engine/hub/connector.py` after the `get_model_state` method (line 97):

```python
    async def log_job(self, task: str, agent_name: str,
                      result_summary: str, duration_ms: int) -> dict:
        """Log a completed job to the hub for activity tracking."""
        return await self.post("/api/archie/jobs", data={
            "task": task,
            "agent_name": agent_name,
            "result_summary": result_summary,
            "duration_ms": duration_ms,
            "source": "archie-code",
        })

    async def get_agent_status(self, agent_id: int) -> dict:
        """Get current status of a specific agent."""
        return await self.get(f"/api/starbase/agents/{agent_id}/status")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest archie_engine/tests/test_connector.py -v`
Expected: All pass

- [ ] **Step 5: Run full suite**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add archie_engine/hub/connector.py archie_engine/tests/test_connector.py
git commit -m "feat: add log_job and get_agent_status to HubConnector"
```

---

### Task 6: Add Job Logging to Platform Dispatch (Platform Task #1599)

**Files:**
- Modify: `archie_engine/router.py` (the `_handle_platform_dispatch` method)
- Modify: `archie_engine/tests/test_router.py`

- [ ] **Step 1: Write test for job logging after dispatch**

Add to `archie_engine/tests/test_router.py`:

```python
@pytest.mark.asyncio
async def test_platform_dispatch_logs_job(mock_tools, mock_inference):
    """After successful platform dispatch, log_job should be called."""
    from unittest.mock import AsyncMock

    mock_hub = AsyncMock()
    mock_hub.dispatch = AsyncMock(return_value={
        "response": "Review complete.",
        "agent_name": "S.H.I.E.L.D.",
        "model": "qwen2.5:7b",
    })
    mock_hub.log_job = AsyncMock(return_value={"success": True, "job_id": 99})

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "review auth"}
    context = {"working_dir": "/tmp", "history": []}

    await router.route(intent, context, dispatch_target="platform", capability="code_review")
    mock_hub.log_job.assert_called_once()
    call_kwargs = mock_hub.log_job.call_args
    assert call_kwargs[1]["agent_name"] == "S.H.I.E.L.D." or call_kwargs[0][1] == "S.H.I.E.L.D."
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest archie_engine/tests/test_router.py::test_platform_dispatch_logs_job -v`
Expected: FAIL — log_job never called

- [ ] **Step 3: Add job logging to _handle_platform_dispatch**

In `archie_engine/router.py`, update `_handle_platform_dispatch` — add timing and log_job call:

```python
    async def _handle_platform_dispatch(self, raw_input: str, entities: dict,
                                        context: dict, capability: str | None) -> dict:
        """Dispatch to platform Bridge via hub connector."""
        import time
        start = time.monotonic()

        user_context = {
            "working_dir": context.get("working_dir", ""),
            "files": entities.get("files", []),
            "history_length": len(context.get("history", [])),
        }

        resp = await self.hub_connector.dispatch(
            prompt=raw_input,
            agent_target=f"capability:{capability}" if capability else None,
            user_context=user_context,
        )

        duration_ms = int((time.monotonic() - start) * 1000)

        if "error" in resp:
            logger.warning("Platform dispatch failed: %s — falling back to local", resp["error"])
            return await self._handle_code_task(raw_input, entities, context)

        agent_name = resp.get("agent_name", "platform agent")
        response_text = resp.get("response", "")
        model_used = resp.get("model", self.default_model)

        # Log the job for activity tracking
        try:
            await self.hub_connector.log_job(
                task=capability or "general",
                agent_name=agent_name,
                result_summary=response_text[:200],
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning("Failed to log job: %s", e)

        return {
            "success": True,
            "response": f"[{agent_name}] {response_text}",
            "tool_calls": [],
            "model_used": model_used,
            "agent_name": agent_name,
        }
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest archie_engine/tests/test_router.py -v`
Expected: All pass

- [ ] **Step 5: Run full suite**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add archie_engine/router.py archie_engine/tests/test_router.py
git commit -m "feat: log dispatched jobs to hub for Starbase activity feed"
```

---

### Task 7: Integration Test — Full Dispatch Flow (Platform Task #1601)

**Files:**
- Modify: `archie_engine/tests/test_engine.py`

- [ ] **Step 1: Write integration test**

Add to `archie_engine/tests/test_engine.py`:

```python
@pytest.mark.asyncio
async def test_engine_dispatch_decision_in_response():
    """Engine responses should include dispatch_target field."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999")
    engine = Engine(config)
    await engine.start()

    try:
        async with websockets.connect(f"ws://127.0.0.1:{engine.server.port}") as ws:
            # Send a knowledge query — should show dispatch target
            await ws.send(json.dumps({
                "type": "message",
                "content": "What is the Bridge dispatcher?",
            }))
            resp = json.loads(await ws.recv())
            assert resp["type"] == "response"
            assert "dispatch_target" in resp
            # No hub configured → should be local
            assert resp["dispatch_target"] == "local"
            assert resp["intent"] == "knowledge_query"
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_engine_shell_not_triggered_by_questions():
    """Regression: natural language questions must not run as shell commands."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999")
    engine = Engine(config)
    await engine.start()

    try:
        async with websockets.connect(f"ws://127.0.0.1:{engine.server.port}") as ws:
            await ws.send(json.dumps({
                "type": "message",
                "content": "What models are available?",
            }))
            resp = json.loads(await ws.recv())
            assert resp["intent"] != "shell_command", \
                f"Question classified as shell_command — intent parser bug not fixed"
    finally:
        await engine.stop()
```

- [ ] **Step 2: Run integration tests**

Run: `python -m pytest archie_engine/tests/test_engine.py -v -k "dispatch_decision or shell_not_triggered"`
Expected: PASS

- [ ] **Step 3: Run full suite — final verification**

Run: `python -m pytest archie_engine/tests/ -v`
Expected: All pass. Note the final count — should be ~180+ (156 original + new tests from all tasks)

- [ ] **Step 4: Commit**

```bash
git add archie_engine/tests/test_engine.py
git commit -m "test: integration tests for dispatch flow and intent regression"
```

---

## Plan Self-Review

**Spec coverage check:**
- ✅ Fix intent parser (Task 2)
- ✅ DispatchStrategy component (Task 3)
- ✅ Wire to Bridge via HubConnector (Task 4)
- ✅ Job logging for Starbase (Tasks 5, 6)
- ✅ datetime.utcnow() fix (Task 1)
- ✅ Phase 1 testing — unit + integration + offline fallback (Tasks 1-7 all include tests)

**Placeholder scan:** No TBDs, TODOs, or vague steps. All code blocks complete.

**Type consistency check:**
- `DispatchStrategy.decide()` returns `DispatchDecision` — used correctly in engine.py
- `DispatchTarget.LOCAL/PLATFORM/CLAUDE` — consistent enum usage
- `CommandRouter` accepts `hub_connector` and `dispatch_target`/`capability` — matches test expectations
- `HubConnector.dispatch()` signature matches existing code (line 77-85 of connector.py)
- `HubConnector.log_job()` params match test expectations
