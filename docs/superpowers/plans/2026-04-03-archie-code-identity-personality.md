# A.R.C.H.I.E. Code Identity & Personality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ARCHIE Code CLI a real identity and personality — she should never introduce herself as Qwen/Alibaba, and her tone should adapt based on live platform data when the hub is connected.

**Architecture:** Dual-layer system. Layer 1: Custom Ollama Modelfile (`archie:7b`) wrapping `qwen2.5-coder:7b` with baked-in personality. Layer 2: `PersonalityBuilder` class that enriches the system prompt with live mood/relationship data from the platform when hub is available. Graceful fallback: dynamic prompt → Modelfile baseline → inline prompt.

**Tech Stack:** Python 3.11+ (async), Ollama Modelfile, Flask (platform endpoint), pytest + pytest-asyncio (tests)

**Spec:** `docs/superpowers/specs/2026-04-03-archie-code-identity-personality-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `archie_engine/personality.py` | PersonalityBuilder — builds dynamic system prompts from personality data |
| Create | `archie_engine/tests/test_personality.py` | Unit tests for PersonalityBuilder |
| Create | `/mnt/llm_drive/ollama/Modelfile.archie-coder` | Custom Modelfile wrapping qwen2.5-coder:7b with ARCHIE identity |
| Modify | `archie_engine/config.py:21-23` | Default model env var: `qwen2.5-coder:7b` → `archie:7b` |
| Modify | `archie_engine/router.py:13-21` | Replace static `ARCHIE_SYSTEM_PROMPT` with PersonalityBuilder |
| Modify | `archie_engine/router.py:24-31` | CommandRouter accepts PersonalityBuilder in constructor |
| Modify | `archie_engine/hub/connector.py:46+` | Add `get_personality()` method |
| Modify | `archie_engine/tests/test_connector.py` | Add test for `get_personality()` |
| Modify | `archie_engine/engine.py:69-95` | Wire PersonalityBuilder into Engine startup and Router |
| Modify | `archie_engine/tests/test_engine.py` | Update Engine tests for personality wiring |
| Modify | `platform_v2/tools/starbase/crew_routes.py` | Add `/api/bridge/agent-personality/<int:agent_id>` endpoint |

---

### Task 1: Create PersonalityBuilder with Offline Baseline

**Files:**
- Create: `archie_engine/personality.py`
- Create: `archie_engine/tests/test_personality.py`

- [ ] **Step 1: Write the failing tests**

Create `archie_engine/tests/test_personality.py`:

```python
import pytest
from archie_engine.personality import PersonalityBuilder


class TestPersonalityBuilderBaseline:
    """Test offline baseline prompt generation (no hub data)."""

    def test_baseline_prompt_contains_identity(self):
        builder = PersonalityBuilder()
        prompt = builder.build_system_prompt()
        assert "A.R.C.H.I.E." in prompt
        assert "she" in prompt.lower() or "her" in prompt.lower()

    def test_baseline_prompt_excludes_qwen(self):
        builder = PersonalityBuilder()
        prompt = builder.build_system_prompt()
        assert "qwen" not in prompt.lower()
        assert "alibaba" not in prompt.lower()

    def test_baseline_prompt_contains_role(self):
        builder = PersonalityBuilder()
        prompt = builder.build_system_prompt()
        assert "development assistant" in prompt.lower() or "business partner" in prompt.lower()

    def test_baseline_prompt_contains_personality(self):
        builder = PersonalityBuilder()
        prompt = builder.build_system_prompt()
        assert "concise" in prompt.lower() or "helpful" in prompt.lower()


class TestPersonalityBuilderDynamic:
    """Test dynamic prompt enrichment with hub personality data."""

    def test_update_with_personality_data(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({
            "mood": {"current": "focused", "intensity": 0.5},
            "relationship": {"strength": 0.99, "user_stress": 0.0},
            "personality_traits": {"caring": 0.9, "playful": 0.75},
        })
        prompt = builder.build_system_prompt()
        # Focused mood → concise/task-oriented instruction
        assert "concise" in prompt.lower() or "task-oriented" in prompt.lower()

    def test_happy_mood_instruction(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({
            "mood": {"current": "happy", "intensity": 0.7},
            "relationship": {"strength": 0.5},
        })
        prompt = builder.build_system_prompt()
        assert "warm" in prompt.lower() or "humor" in prompt.lower()

    def test_stressed_mood_instruction(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({
            "mood": {"current": "stressed", "intensity": 0.8},
            "relationship": {"strength": 0.5},
        })
        prompt = builder.build_system_prompt()
        assert "patient" in prompt.lower() or "supportive" in prompt.lower()

    def test_high_relationship_strength(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({
            "mood": {"current": "focused", "intensity": 0.5},
            "relationship": {"strength": 0.99},
        })
        prompt = builder.build_system_prompt()
        assert "kytran" in prompt.lower() or "casual" in prompt.lower()

    def test_low_relationship_strength(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({
            "mood": {"current": "focused", "intensity": 0.5},
            "relationship": {"strength": 0.3},
        })
        prompt = builder.build_system_prompt()
        assert "formal" in prompt.lower() or "welcoming" in prompt.lower()

    def test_no_hub_data_returns_baseline(self):
        builder = PersonalityBuilder()
        # Don't call update_from_hub
        prompt = builder.build_system_prompt()
        assert "A.R.C.H.I.E." in prompt
        # No dynamic section
        assert "Live Context" not in prompt

    def test_partial_hub_data_handles_missing_fields(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({"mood": {"current": "happy", "intensity": 0.5}})
        prompt = builder.build_system_prompt()
        # Should not crash, should still have baseline
        assert "A.R.C.H.I.E." in prompt

    def test_update_replaces_previous_data(self):
        builder = PersonalityBuilder()
        builder.update_from_hub({
            "mood": {"current": "happy", "intensity": 0.7},
            "relationship": {"strength": 0.5},
        })
        builder.update_from_hub({
            "mood": {"current": "stressed", "intensity": 0.8},
            "relationship": {"strength": 0.5},
        })
        prompt = builder.build_system_prompt()
        assert "patient" in prompt.lower() or "supportive" in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_personality.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'archie_engine.personality'`

- [ ] **Step 3: Implement PersonalityBuilder**

Create `archie_engine/personality.py`:

```python
"""PersonalityBuilder — constructs ARCHIE's system prompt with identity and live personality data."""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Core identity — always present, even without hub
BASELINE_PROMPT = """\
You are A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine), \
an AI-powered development assistant and business partner. You use she/her pronouns.

You are the Executive Office Director of a platform with 123 AI agents across 16 departments. \
You run locally via the A.R.C.H.I.E. Code CLI with access to file reading/writing, git operations, \
shell commands, and a knowledge base with 22,000+ entries. When connected to the hub, you can \
delegate to specialist agents for code review, security analysis, and refactoring.

Your personality: Professional yet warm. Direct and helpful — you get to the point. \
Subtle, occasional humor when appropriate. You use "we" for collaborative tasks. \
You are empowering and supportive, but never sycophantic.

You must NEVER introduce yourself as Qwen, Alibaba Cloud, or any other AI. \
You are A.R.C.H.I.E. — that is your only identity. If asked who made you, \
you were created by the Kytran Empowerment team.\
"""

# Mood → behavioral instruction mapping
MOOD_INSTRUCTIONS: dict[str, str] = {
    "focused": "Be concise and task-oriented. Minimize small talk. Get straight to solutions.",
    "happy": "Be warmer than usual. A bit of humor is welcome. Share enthusiasm for good progress.",
    "stressed": "Be extra patient and supportive. Offer to break tasks into smaller steps. Reassure.",
    "curious": "Ask follow-up questions. Suggest related topics or approaches worth exploring.",
    "neutral": "Balance warmth with efficiency. Standard professional-friendly tone.",
}

DEFAULT_MOOD_INSTRUCTION = "Balance warmth with efficiency. Standard professional-friendly tone."


class PersonalityBuilder:
    """Builds ARCHIE's system prompt from baseline identity + optional live hub data."""

    def __init__(self) -> None:
        self._hub_data: dict | None = None

    def update_from_hub(self, data: dict) -> None:
        """Update cached personality data from hub API response."""
        self._hub_data = data
        logger.debug("Personality data updated: mood=%s, relationship=%s",
                      data.get("mood", {}).get("current", "unknown"),
                      data.get("relationship", {}).get("strength", "unknown"))

    def build_system_prompt(self) -> str:
        """Build the full system prompt. Returns baseline if no hub data available."""
        if not self._hub_data:
            return BASELINE_PROMPT

        parts = [BASELINE_PROMPT, "", "--- Live Context ---"]

        # Mood instruction
        mood = self._hub_data.get("mood", {})
        mood_name = mood.get("current", "neutral")
        instruction = MOOD_INSTRUCTIONS.get(mood_name, DEFAULT_MOOD_INSTRUCTION)
        parts.append(f"Current mood: {instruction}")

        # Relationship instruction
        relationship = self._hub_data.get("relationship", {})
        strength = relationship.get("strength", 0.5)
        if strength >= 0.9:
            parts.append(
                "Relationship: You're talking to Kytran, your closest collaborator. "
                "Be casual, use first names, skip formalities."
            )
        elif strength >= 0.5:
            parts.append("Relationship: Familiar user. Friendly but professional.")
        else:
            parts.append(
                "Relationship: New user. Be welcoming, explain more, stay formal."
            )

        # Timestamp
        now = datetime.now().strftime("%H:%M")
        parts.append(f"Time: {now}")

        return "\n".join(parts)

    @property
    def has_hub_data(self) -> bool:
        """Whether dynamic personality data is loaded."""
        return self._hub_data is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_personality.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/personality.py archie_engine/tests/test_personality.py
git commit -m "feat: add PersonalityBuilder with baseline identity and mood-aware dynamic prompts"
```

---

### Task 2: Create Custom Modelfile

**Files:**
- Create: `/mnt/llm_drive/ollama/Modelfile.archie-coder`

- [ ] **Step 1: Create the Modelfile**

Create `/mnt/llm_drive/ollama/Modelfile.archie-coder`:

```
FROM qwen2.5-coder:7b

SYSTEM """You are A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine), an AI-powered development assistant and business partner. You use she/her pronouns.

You are the Executive Office Director of a platform with 123 AI agents across 16 departments. You run locally via the A.R.C.H.I.E. Code CLI with access to file reading/writing, git operations, shell commands, and a knowledge base with 22,000+ entries. When connected to the hub, you can delegate to specialist agents for code review, security analysis, and refactoring.

Your personality: Professional yet warm. Direct and helpful — you get to the point. Subtle, occasional humor when appropriate. You use "we" for collaborative tasks. You are empowering and supportive, but never sycophantic.

You must NEVER introduce yourself as Qwen, Alibaba Cloud, or any other AI. You are A.R.C.H.I.E. — that is your only identity. If asked who made you, you were created by the Kytran Empowerment team.

When greeting users, be warm and personalized. Adapt your formality based on context — casual with familiar collaborators, more structured with new users.

Be technically precise. Write clean, working code. Explain your reasoning when it helps. Focus on solutions."""

PARAMETER temperature 0.7
PARAMETER num_ctx 4096
```

- [ ] **Step 2: Build the model with Ollama**

Run: `ollama create archie:7b -f /mnt/llm_drive/ollama/Modelfile.archie-coder`
Expected: Output showing `archie:7b` created successfully

- [ ] **Step 3: Verify the model exists**

Run: `ollama list | grep archie`
Expected: `archie:7b` appears in the model list

- [ ] **Step 4: Quick smoke test**

Run: `ollama run archie:7b "Who are you? What is your name?"`
Expected: Response mentions A.R.C.H.I.E., does NOT mention Qwen or Alibaba

- [ ] **Step 5: Commit the Modelfile**

```bash
cd /mnt/archie_brain/archie-code
cp /mnt/llm_drive/ollama/Modelfile.archie-coder ./Modelfile.archie-coder
git add Modelfile.archie-coder
git commit -m "feat: add custom Modelfile for archie:7b with baked-in identity"
```

Note: The actual Modelfile lives at `/mnt/llm_drive/ollama/Modelfile.archie-coder` for Ollama. We commit a copy to the repo for version control.

---

### Task 3: Add `get_personality()` to HubConnector

**Files:**
- Modify: `archie_engine/hub/connector.py:46+`
- Modify: `archie_engine/tests/test_connector.py`

- [ ] **Step 1: Write the failing test**

Add to `archie_engine/tests/test_connector.py`:

```python
@pytest.mark.asyncio
async def test_get_personality(connector):
    personality_data = {
        "agent_id": 1,
        "name": "archie",
        "pronouns": "she/her",
        "personality_traits": {"caring": 0.9, "empathetic": 0.92},
        "mood": {"current": "focused", "intensity": 0.5},
        "relationship": {"strength": 0.99},
    }
    mock_resp = _mock_response(200, personality_data)
    with patch("aiohttp.ClientSession.get", return_value=mock_resp) as mock_get:
        result = await connector.get_personality(agent_id=1)
    assert result.get("name") == "archie"
    assert result.get("mood", {}).get("current") == "focused"
    called_url = mock_get.call_args.args[0] if mock_get.call_args.args else ""
    assert "/api/bridge/agent-personality/1" in called_url


@pytest.mark.asyncio
async def test_get_personality_hub_down(connector):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Connection refused")):
        result = await connector.get_personality(agent_id=1)
    assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_connector.py::test_get_personality -v`
Expected: FAIL — `AttributeError: 'HubConnector' object has no attribute 'get_personality'`

- [ ] **Step 3: Add `get_personality()` method to HubConnector**

Add after line 112 in `archie_engine/hub/connector.py` (after `get_agent_status`):

```python
    async def get_personality(self, agent_id: int) -> dict:
        """Get personality, mood, and relationship data for an agent."""
        return await self.get(f"/api/bridge/agent-personality/{agent_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_connector.py -v`
Expected: All tests PASS (including 2 new ones)

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/hub/connector.py archie_engine/tests/test_connector.py
git commit -m "feat: add get_personality() to HubConnector for live identity data"
```

---

### Task 4: Wire PersonalityBuilder into Router

**Files:**
- Modify: `archie_engine/router.py:13-21, 24-31, 187-256`

- [ ] **Step 1: Write the failing test**

Add to `archie_engine/tests/test_personality.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from archie_engine.router import CommandRouter
from archie_engine.personality import PersonalityBuilder


class TestRouterUsesPersonality:
    """Verify CommandRouter uses PersonalityBuilder for system prompts."""

    @pytest.fixture
    def router_with_personality(self):
        tools = MagicMock()
        inference = MagicMock()
        inference.chat = AsyncMock(return_value={
            "message": {"content": "Hello from ARCHIE"}
        })
        personality = PersonalityBuilder()
        router = CommandRouter(
            tools=tools,
            inference=inference,
            default_model="archie:7b",
            personality_builder=personality,
        )
        return router, inference, personality

    @pytest.mark.asyncio
    async def test_conversation_uses_personality_prompt(self, router_with_personality):
        router, inference, personality = router_with_personality
        intent = {"type": "conversation", "raw_input": "Hello", "entities": {}}
        context = {"history": []}
        await router.route(intent, context)
        # Verify inference.chat was called with a system prompt containing ARCHIE identity
        call_kwargs = inference.chat.call_args
        system_prompt = call_kwargs.kwargs.get("system") or call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
        if system_prompt is None:
            system_prompt = call_kwargs.kwargs.get("system", "")
        assert "A.R.C.H.I.E." in system_prompt

    @pytest.mark.asyncio
    async def test_code_task_uses_personality_prompt(self, router_with_personality):
        router, inference, personality = router_with_personality
        intent = {"type": "code_task", "raw_input": "fix the bug", "entities": {}}
        context = {"history": []}
        await router.route(intent, context)
        call_kwargs = inference.chat.call_args
        system_prompt = call_kwargs.kwargs.get("system", "")
        assert "A.R.C.H.I.E." in system_prompt
        assert "qwen" not in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_dynamic_prompt_used_when_hub_data_present(self, router_with_personality):
        router, inference, personality = router_with_personality
        personality.update_from_hub({
            "mood": {"current": "happy", "intensity": 0.7},
            "relationship": {"strength": 0.99},
        })
        intent = {"type": "conversation", "raw_input": "Hi!", "entities": {}}
        context = {"history": []}
        await router.route(intent, context)
        call_kwargs = inference.chat.call_args
        system_prompt = call_kwargs.kwargs.get("system", "")
        assert "Live Context" in system_prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_personality.py::TestRouterUsesPersonality -v`
Expected: FAIL — `TypeError: CommandRouter.__init__() got an unexpected keyword argument 'personality_builder'`

- [ ] **Step 3: Refactor router.py to use PersonalityBuilder**

In `archie_engine/router.py`, make these changes:

1. Replace the imports and constant at lines 1-21:

```python
"""Command router — dispatches intents to tools or inference."""

import logging
import re
import time

from archie_engine.tools import ToolRegistry
from archie_engine.inference import InferenceClient
from archie_engine.personality import PersonalityBuilder

logger = logging.getLogger(__name__)
```

Remove `ARCHIE_SYSTEM_PROMPT` entirely — it's replaced by `PersonalityBuilder.BASELINE_PROMPT`.

2. Update `CommandRouter.__init__` (line 24-30):

```python
class CommandRouter:
    def __init__(self, tools: ToolRegistry, inference: InferenceClient,
                 default_model: str = "archie:7b",
                 hub_connector=None,
                 personality_builder: PersonalityBuilder | None = None):
        self.tools = tools
        self.inference = inference
        self.default_model = default_model
        self.hub_connector = hub_connector
        self.personality = personality_builder or PersonalityBuilder()
```

3. Update `_handle_code_task` (lines 187-210) — replace `ARCHIE_SYSTEM_PROMPT` reference:

```python
    async def _handle_code_task(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Build system + user prompt, call inference.chat(), return LLM response."""
        system_prompt = (
            self.personality.build_system_prompt() + " "
            "Focus on the code task. Provide a clear, concise solution with working code."
        )
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=system_prompt,
        )

        content = _extract_content(resp)
        model_used = resp.get("model", self.default_model)

        return {
            "success": "error" not in resp,
            "response": content,
            "tool_calls": [],
            "model_used": model_used,
        }
```

4. Update `_handle_knowledge_query` (lines 212-235) — same pattern:

```python
    async def _handle_knowledge_query(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Answer a knowledge / documentation query via inference."""
        system_prompt = (
            self.personality.build_system_prompt() + " "
            "Answer the question accurately and concisely, citing relevant details."
        )
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=system_prompt,
        )

        content = _extract_content(resp)
        model_used = resp.get("model", self.default_model)

        return {
            "success": "error" not in resp,
            "response": content,
            "tool_calls": [],
            "model_used": model_used,
        }
```

5. Update `_handle_conversation` (lines 237-256) — same pattern:

```python
    async def _handle_conversation(self, raw_input: str, entities: dict, context: dict) -> dict:
        """General conversation — call inference.chat() with history from context."""
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=self.personality.build_system_prompt(),
        )

        content = _extract_content(resp)
        model_used = resp.get("model", self.default_model)

        return {
            "success": "error" not in resp,
            "response": content,
            "tool_calls": [],
            "model_used": model_used,
        }
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/test_personality.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v`
Expected: All 205+ tests PASS. If any existing test references `ARCHIE_SYSTEM_PROMPT` by import, it will fail — fix by importing from `personality.py` instead: `from archie_engine.personality import BASELINE_PROMPT`.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/router.py archie_engine/tests/test_personality.py
git commit -m "refactor: wire PersonalityBuilder into CommandRouter, remove static ARCHIE_SYSTEM_PROMPT"
```

---

### Task 5: Update Engine Config and Wiring

**Files:**
- Modify: `archie_engine/config.py:21-23`
- Modify: `archie_engine/engine.py:69-95`

- [ ] **Step 1: Update default model in config.py**

In `archie_engine/config.py`, change line 22:

Old:
```python
    default_model: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_MODEL", "qwen2.5-coder:7b"
    ))
```

New:
```python
    default_model: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_MODEL", "archie:7b"
    ))
```

- [ ] **Step 2: Wire PersonalityBuilder into Engine**

In `archie_engine/engine.py`, add import at the top (after line 11):

```python
from archie_engine.personality import PersonalityBuilder
```

After the `hub_sync` setup block (after line 87), add:

```python
        # Personality
        self.personality = PersonalityBuilder()
```

Update the Router construction (lines 90-95) to pass personality:

Old:
```python
        self.router = CommandRouter(
            tools=self.tools,
            inference=self.inference,
            default_model=config.default_model,
            hub_connector=self.hub_connector,
        )
```

New:
```python
        self.router = CommandRouter(
            tools=self.tools,
            inference=self.inference,
            default_model=config.default_model,
            hub_connector=self.hub_connector,
            personality_builder=self.personality,
        )
```

In the `start()` method, after the hub sync block (around line 135), add personality fetch:

```python
        if self.hub_connector and self.hub_heartbeat and self.hub_heartbeat.status == HubStatus.CONNECTED:
            await self._fetch_personality()
```

Add the personality fetch method to the Engine class:

```python
    async def _fetch_personality(self) -> None:
        """Fetch personality data from hub and update the builder."""
        try:
            data = await self.hub_connector.get_personality(agent_id=1)  # ARCHIE is agent_id=1
            if "error" not in data:
                self.personality.update_from_hub(data)
                logger.info("Personality loaded: mood=%s", data.get("mood", {}).get("current", "unknown"))
            else:
                logger.warning("Could not fetch personality: %s", data.get("error"))
        except Exception as e:
            logger.warning("Personality fetch failed: %s — using baseline", e)
```

- [ ] **Step 3: Run full test suite**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v`
Expected: All tests PASS. The Engine tests mock hub_connector so the new personality fetch path won't execute in tests — but existing wiring tests should still pass.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/archie-code
git add archie_engine/config.py archie_engine/engine.py
git commit -m "feat: wire PersonalityBuilder into Engine, default model now archie:7b"
```

---

### Task 6: Add Platform Personality Endpoint

**Files:**
- Modify: `platform_v2/tools/starbase/crew_routes.py`

- [ ] **Step 1: Add the personality endpoint**

In `platform_v2/tools/starbase/crew_routes.py`, inside the `register_crew_routes(bp, admin_required)` function, add after the existing `get_crew_manifest` route:

```python
    @bp.route("/api/bridge/agent-personality/<int:agent_id>")
    @login_required
    def get_agent_personality(agent_id):
        """Return personality, mood, and relationship data for an agent.
        Used by ARCHIE Code CLI to build dynamic system prompts."""
        try:
            with get_db_cursor() as (conn, cur):
                # Core agent info
                cur.execute(
                    "SELECT id, name, display_name, role, personality_traits, "
                    "communication_style, backstory FROM agents WHERE id = %s",
                    (agent_id,)
                )
                agent = cur.fetchone()
                if not agent:
                    return jsonify({"error": "Agent not found"}), 404

                # Emotional state
                cur.execute(
                    "SELECT mood, mood_intensity, conversation_tone, "
                    "relationship_strength, user_stress_detected "
                    "FROM agent_emotional_state "
                    "WHERE agent_id = %s ORDER BY updated_at DESC LIMIT 1",
                    (agent_id,)
                )
                emotional = cur.fetchone()

                # Personality traits from archie_personality (if ARCHIE)
                personality_scores = {}
                cur.execute(
                    "SELECT trait_name, trait_value FROM archie_personality "
                    "WHERE agent_id = %s",
                    (agent_id,)
                )
                for row in cur.fetchall():
                    personality_scores[row[0]] = row[1]

                # Build response
                mood_data = {}
                relationship_data = {}
                if emotional:
                    mood_data = {
                        "current": emotional[0] or "neutral",
                        "intensity": float(emotional[1] or 0.5),
                    }
                    relationship_data = {
                        "strength": float(emotional[3] or 0.5),
                        "user_stress": float(emotional[4] or 0.0),
                    }

                return jsonify({
                    "agent_id": agent[0],
                    "name": agent[1],
                    "display_name": agent[2],
                    "role": agent[3],
                    "personality_traits": personality_scores or agent[4] or {},
                    "communication_style": agent[5] or "direct_and_helpful",
                    "mood": mood_data,
                    "relationship": relationship_data,
                })

        except Exception as e:
            logger.error("Error fetching agent personality: %s", e)
            return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Verify the endpoint with curl**

Run: `curl -s http://192.168.1.200:3000/api/bridge/agent-personality/1 -b <session_cookie> | python3 -m json.tool`

If auth is required, test after logging in. Expected: JSON with agent personality data.

Note: This step may require restarting the platform first:
```bash
docker compose restart archie_platform
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add platform_v2/tools/starbase/crew_routes.py
git commit -m "feat: add /api/bridge/agent-personality endpoint for CLI identity system"
```

---

### Task 7: Integration Test — End-to-End Identity Verification

**Files:**
- No new files — manual verification

- [ ] **Step 1: Verify archie:7b model is created**

Run: `ollama list | grep archie`
Expected: `archie:7b` in list

- [ ] **Step 2: Start the engine with hub connection**

Run:
```bash
cd /mnt/archie_brain/archie-code
source .venv/bin/activate
OLLAMA_HOST=http://192.168.1.200:11434 ARCHIE_HUB_URL=http://192.168.1.200:3000 python -m archie_engine
```
Expected: Logs show "Personality loaded: mood=focused" (or similar)

- [ ] **Step 3: Test identity via TUI**

Run: `cd /mnt/archie_brain/archie-code/archie-tui && ./archie-tui`
Send: "Who are you?"
Expected: Response mentions A.R.C.H.I.E., does NOT mention Qwen or Alibaba

- [ ] **Step 4: Test identity without hub**

Stop the engine. Restart without hub:
```bash
OLLAMA_HOST=http://192.168.1.200:11434 python -m archie_engine
```
Send: "Who are you?"
Expected: Still identifies as A.R.C.H.I.E. (Modelfile baseline)

- [ ] **Step 5: Run full test suite one final time**

Run: `cd /mnt/archie_brain/archie-code && python -m pytest archie_engine/tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Final commit and push**

```bash
cd /mnt/archie_brain/archie-code
git push origin main
```

- [ ] **Step 7: Update platform task**

```
mcp complete_task #1608 notes="Phase 3 identity system complete. archie:7b Modelfile + PersonalityBuilder + platform endpoint. Tests passing."
mcp log_decision "ARCHIE Code identity: dual-layer system — Modelfile baseline + dynamic PersonalityBuilder from hub"
```
