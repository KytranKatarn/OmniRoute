# Chat Phase 2: ARCHIE Manages Agents via Chat

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable ARCHIE to create, manage, assign, and monitor sub-agents through the Chat interface — making Chat the primary control surface for team operations.

**Architecture:** Extend the orchestration engine with new intent types (create_agent, manage_team, assign_station, check_status) that route to Team Management and Bridge Command APIs. Add agent hierarchy tracking (parent/child) and IAAE sub-agent governance (budgets, lifecycle, scope constraints).

**Tech Stack:** Python/Flask, PostgreSQL, Ollama (dolphin3 for chat, qwen2.5:7b for intent parsing), existing orchestration pipeline.

**Status:** Planning (Feb 14, 2026)

---

## Context

Phase 1 (sidebar conversations, file upload) and Phase 3 (terminal SSO, tmux persistence) are deployed in commit `967df52` + `2837d56`. Phase 2 connects ARCHIE's Chat to the Team Management and Bridge Command modules so ARCHIE can:

1. **Create agents** via natural language ("Create a Python code reviewer agent")
2. **Assign agents to stations** ("Put the new agent on Engineering station")
3. **Check team status** ("Who's on duty?", "Show me the Engineering team")
4. **Manage agent lifecycle** ("Pause Agent X", "Retire the backup agent")
5. **Monitor workload** ("How busy is the Operations station?")

### User Vision
> "What I'd like to do is see if the CHAT of ARCHIE can interact and create the TEAM members inside the Team Management Module. That's the purpose — to use the Chat so that she can interact with her system and work with all her features. MCP Server, the Modules. An Interactive Chat Similar to Claude Code. When it comes to spinning up agents etc. all this would be very useful to complete so that her Chat becomes the main point of contact."

---

## Dependencies

- **Orchestration Reconnection Design** (`docs/plans/2026-02-13-orchestration-reconnection-design.md`) — Phase A fixes (local Ollama routing, agent_select finding ARCHIE) should be applied first or in parallel. Phase B (wire orchestration into Bridge & Team) directly overlaps with this plan.
- Phase A items A1-A7 are prerequisites (fix .env routing, smart_router defaults, intent_parser model, agent_select fallback)

---

## Task 1: Database Migration — Agent Hierarchy & Budgets

**Files:**
- Create: `database/migrations/089_agent_hierarchy.sql`

**Step 1: Write the migration**

```sql
-- 089: Agent Hierarchy & Sub-Agent Governance
-- Supports Phase 2: ARCHIE creating/managing agents via Chat

-- 1. Agent hierarchy columns
ALTER TABLE agents ADD COLUMN IF NOT EXISTS parent_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by_agent_id INTEGER REFERENCES agents(id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(id);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS agent_generation INTEGER DEFAULT 0;
-- 0 = human-created (seed data), 1+ = created by another agent

COMMENT ON COLUMN agents.parent_agent_id IS 'Supervising agent (NULL = top-level)';
COMMENT ON COLUMN agents.created_by_agent_id IS 'Which agent requested creation';
COMMENT ON COLUMN agents.created_by_user_id IS 'Which user approved creation';
COMMENT ON COLUMN agents.agent_generation IS '0=seed, 1+=sub-agent depth';

CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_agent_id) WHERE parent_agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agents_generation ON agents(agent_generation);

-- 2. Agent creation events (immutable audit trail)
CREATE TABLE IF NOT EXISTS agent_creation_events (
    id SERIAL PRIMARY KEY,
    parent_agent_id INTEGER REFERENCES agents(id),
    child_agent_id INTEGER NOT NULL REFERENCES agents(id),
    created_by_user_id INTEGER REFERENCES users(id),
    creation_reason TEXT,
    creation_source VARCHAR(50) DEFAULT 'chat',  -- 'chat', 'api', 'migration', 'admin_ui'
    capabilities_requested JSONB,
    station_requested VARCHAR(50),
    is_approved BOOLEAN DEFAULT FALSE,
    approved_at TIMESTAMP,
    terminated_at TIMESTAMP,
    termination_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_creation_events_parent ON agent_creation_events(parent_agent_id);
CREATE INDEX IF NOT EXISTS idx_creation_events_child ON agent_creation_events(child_agent_id);

-- 3. Agent budgets (token/task limits per agent)
CREATE TABLE IF NOT EXISTS agent_budgets (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) UNIQUE,
    token_limit_per_day INTEGER DEFAULT 100000,
    tokens_used_today INTEGER DEFAULT 0,
    token_reset_at TIMESTAMP DEFAULT (NOW() + INTERVAL '1 day'),
    task_queue_limit INTEGER DEFAULT 10,
    current_task_count INTEGER DEFAULT 0,
    can_create_sub_agents BOOLEAN DEFAULT FALSE,
    max_sub_agents INTEGER DEFAULT 0,
    max_lifespan_hours INTEGER,  -- NULL = unlimited
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 4. Set ARCHIE (id=2) as top-level with sub-agent creation rights
INSERT INTO agent_budgets (agent_id, can_create_sub_agents, max_sub_agents, token_limit_per_day)
VALUES (2, TRUE, 20, 500000)
ON CONFLICT (agent_id) DO UPDATE SET can_create_sub_agents = TRUE, max_sub_agents = 20;

-- 5. Mark all existing agents as generation 0 (human-created)
UPDATE agents SET agent_generation = 0 WHERE agent_generation IS NULL;
```

**Step 2: Run migration**

```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/089_agent_hierarchy.sql
```

**Step 3: Commit**

```bash
git add database/migrations/089_agent_hierarchy.sql
git commit -m "feat(db): agent hierarchy, creation events, budgets (Phase 2)"
```

---

## Task 2: New Intent Types in Intent Parser

**Files:**
- Modify: `platform_v2/tools/archie_core/intent_parser.py`

Add team management intent detection to the keyword-based classifier. The intent parser already classifies messages into types like `code_task`, `knowledge_query`, `conversation`, etc. We need to add:

- `team_management` — create/update/delete agents, manage team
- `station_management` — assign/unassign agents to stations, check station status
- `status_query` — who's on duty, team overview, workload check

**Step 1: Add intent patterns**

In `_classify_intent()` or equivalent method, add keyword patterns:

```python
# Team management intents
TEAM_KEYWORDS = {
    'team_management': [
        'create agent', 'new agent', 'spawn agent', 'hire', 'recruit',
        'retire agent', 'deactivate agent', 'pause agent', 'remove agent',
        'update agent', 'change agent', 'modify agent',
        'agent capabilities', 'agent skills', 'agent model',
        'sub-agent', 'subagent', 'team member',
    ],
    'station_management': [
        'assign to station', 'assign station', 'put on station',
        'move to station', 'station assignment', 'unassign',
        'engineering station', 'command station', 'operations station',
        'security station', 'creative station', 'consciousness station',
    ],
    'status_query': [
        "who's on duty", 'team status', 'station status',
        'who is assigned', 'show team', 'show roster',
        'how busy', 'workload', 'active agents',
        'agent performance', 'leaderboard',
    ],
}
```

**Step 2: Wire into classification logic**

After existing keyword checks, add team/station/status detection. These should have higher priority than generic `conversation` but lower than `system_status`.

**Step 3: Commit**

```bash
git add platform_v2/tools/archie_core/intent_parser.py
git commit -m "feat(intent): add team_management, station_management, status_query intents"
```

---

## Task 3: Orchestration Engine — Team Management Actions

**Files:**
- Modify: `ai_bridge/orchestration_engine.py`

Extend `_step_execute()` to handle the new intent types. When intent is `team_management`, `station_management`, or `status_query`, the orchestration engine should:

1. Parse the user's natural language into structured parameters
2. Call the appropriate Team Management / Bridge API internally
3. Return a formatted response describing what was done

**Step 1: Add action handlers**

```python
# In _step_execute() or as new methods:

async def _execute_team_action(self, intent, message, user_id, conversation_id):
    """Handle team management actions via chat."""

    if intent == 'team_management':
        return await self._handle_team_management(message, user_id)
    elif intent == 'station_management':
        return await self._handle_station_management(message, user_id)
    elif intent == 'status_query':
        return await self._handle_status_query(message, user_id)

async def _handle_team_management(self, message, user_id):
    """Parse and execute team management commands."""
    msg_lower = message.lower()

    # Detect sub-intent
    if any(kw in msg_lower for kw in ['create', 'new', 'spawn', 'hire']):
        return await self._create_agent_from_chat(message, user_id)
    elif any(kw in msg_lower for kw in ['retire', 'deactivate', 'pause', 'remove']):
        return await self._deactivate_agent_from_chat(message, user_id)
    elif any(kw in msg_lower for kw in ['update', 'change', 'modify']):
        return await self._update_agent_from_chat(message, user_id)
    else:
        return await self._describe_team(message)

async def _create_agent_from_chat(self, message, user_id):
    """Extract agent spec from natural language and create."""
    # Use Ollama (dolphin3) to extract structured params from message
    extraction_prompt = f"""Extract agent creation parameters from this request.
    Return JSON with: model, first_name, last_name, department, title, system_prompt, capabilities
    Available models: dolphin3:latest, qwen2.5:7b, nomic-embed-text
    Available departments: {self._get_departments()}

    Request: {message}

    JSON:"""

    params = await self._extract_params(extraction_prompt)

    # Validate and create via Team Management API
    # ... (call POST /api/agents internally)

    # Log creation event
    # ... (insert into agent_creation_events)

    return f"Created agent {params['first_name']} ({params['model']}) in {params['department']} department."
```

**Step 2: Add station management handler**

```python
async def _handle_station_management(self, message, user_id):
    """Parse and execute station assignments."""
    # Extract agent name/id and station code from message
    # Call POST /api/agents/<id>/assign-station internally
    pass

async def _handle_status_query(self, message, user_id):
    """Return team/station status information."""
    # Query agents, station_assignments, agent_emotional_state
    # Format as readable chat response
    pass
```

**Step 3: Wire into main orchestration pipeline**

In the existing `_step_execute()`, add a check:

```python
if intent_type in ('team_management', 'station_management', 'status_query'):
    response = await self._execute_team_action(intent_type, message, user_id, conversation_id)
    return response
```

**Step 4: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(orchestration): team management actions via chat pipeline"
```

---

## Task 4: Parameter Extraction Service

**Files:**
- Create: `ai_bridge/param_extractor.py`

A lightweight service that uses Ollama (dolphin3) to extract structured parameters from natural language chat messages. This is the "NLP bridge" between freeform chat and structured API calls.

**Step 1: Create the extractor**

```python
"""
Parameter extraction from natural language for team management actions.
Uses Ollama dolphin3 to parse chat messages into structured API parameters.
"""

import json
import os
import requests

OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://host.docker.internal:11434')
EXTRACTION_MODEL = os.getenv('ARCHIE_CHAT_MODEL', 'dolphin3:latest')

# Template prompts for different action types
TEMPLATES = {
    'create_agent': """Extract agent creation parameters from this request.
Return ONLY valid JSON, no explanation.

Available Ollama models (local, free): dolphin3:latest, qwen2.5:7b, tinyllama
Available departments: Engineering, Operations, Customer Support, Marketing, Finance, Legal, HR, Security, Documentation, AI Operations, Creative, Research, Compliance, Administration

Request: "{message}"

JSON format:
{{"model": "string", "first_name": "string", "last_name": "string", "department": "string", "title": "string", "system_prompt": "string", "capabilities": ["string"]}}
""",

    'assign_station': """Extract station assignment parameters from this request.
Return ONLY valid JSON, no explanation.

Available stations: COMMAND, CONSCIOUSNESS, HR, RND, OPERATIONS, ENGINEERING, CREATIVE, SECURITY, MEDICAL, AWAY_TEAM

Request: "{message}"

JSON format:
{{"agent_name": "string", "station_code": "string", "assignment_type": "primary|backup"}}
""",

    'agent_action': """Extract agent action parameters from this request.
Return ONLY valid JSON, no explanation.

Request: "{message}"

JSON format:
{{"agent_name": "string", "action": "deactivate|activate|update", "updates": {{}}}}
""",
}


def extract_params(message: str, action_type: str) -> dict:
    """Extract structured parameters from natural language."""
    template = TEMPLATES.get(action_type)
    if not template:
        return {}

    prompt = template.format(message=message)

    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": EXTRACTION_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_ctx": 4096}
            },
            timeout=60
        )
        resp.raise_for_status()

        text = resp.json().get("response", "").strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        return json.loads(text)
    except (json.JSONDecodeError, requests.RequestException) as e:
        return {"error": str(e)}


def resolve_agent_by_name(name: str, conn) -> int | None:
    """Find agent ID by fuzzy name match."""
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT id, name, first_name, last_name
        FROM agents
        WHERE LOWER(name) LIKE %s
           OR LOWER(first_name) LIKE %s
        ORDER BY status = 'active' DESC, id
        LIMIT 1
    """, (f"%{name.lower()}%", f"%{name.lower()}%"))
    row = cur.fetchone()
    cur.close()
    return row['id'] if row else None
```

**Step 2: Commit**

```bash
git add ai_bridge/param_extractor.py
git commit -m "feat: parameter extraction service for chat→API bridge"
```

---

## Task 5: IAAE Sub-Agent Governance Constraints

**Files:**
- Create: `database/migrations/090_iaae_subagent_constraints.sql`
- Modify: `ai_bridge/ethics_monitor.py`

**Step 1: Add constraint types for sub-agent governance**

```sql
-- 090: IAAE Sub-Agent Governance Constraints

-- Add sub-agent governance constraints
INSERT INTO ethics_constraints (constraint_type, name, description, severity, enforcement_action, is_active)
VALUES
    ('autonomy', 'sub_agent_creation_limit',
     'Maximum number of sub-agents any single agent can create',
     'warning', 'log_and_warn', TRUE),
    ('autonomy', 'sub_agent_generation_limit',
     'Maximum depth of agent creation chain (prevents recursive spawning)',
     'mandatory', 'block', TRUE),
    ('workload', 'sub_agent_token_budget',
     'Daily token budget enforcement for sub-agents',
     'warning', 'log_and_warn', TRUE),
    ('autonomy', 'agent_creation_approval',
     'Require human approval before creating new agents via chat',
     'advisory', 'log_and_warn', TRUE)
ON CONFLICT DO NOTHING;

-- Add governance event types for sub-agent lifecycle
-- (These are logged via governance_audit_log, no schema change needed)
```

**Step 2: Add ethics monitor checks**

In `ethics_monitor.py`, add methods:

```python
def check_agent_creation_allowed(self, parent_agent_id: int, conn) -> dict:
    """Check if agent is allowed to create sub-agents."""
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Check budget
    cur.execute("SELECT * FROM agent_budgets WHERE agent_id = %s", (parent_agent_id,))
    budget = cur.fetchone()

    if not budget or not budget['can_create_sub_agents']:
        return {"allowed": False, "reason": "Agent not authorized to create sub-agents"}

    # Check current sub-agent count
    cur.execute("""
        SELECT COUNT(*) as count FROM agents
        WHERE parent_agent_id = %s AND status = 'active'
    """, (parent_agent_id,))
    count = cur.fetchone()['count']

    if count >= budget['max_sub_agents']:
        return {"allowed": False, "reason": f"Sub-agent limit reached ({count}/{budget['max_sub_agents']})"}

    # Check generation depth
    cur.execute("SELECT agent_generation FROM agents WHERE id = %s", (parent_agent_id,))
    gen = cur.fetchone()
    if gen and gen['agent_generation'] >= 3:
        return {"allowed": False, "reason": "Maximum agent generation depth reached"}

    cur.close()
    return {"allowed": True, "remaining": budget['max_sub_agents'] - count}
```

**Step 3: Commit**

```bash
git add database/migrations/090_iaae_subagent_constraints.sql ai_bridge/ethics_monitor.py
git commit -m "feat(iaae): sub-agent governance constraints and budget checks"
```

---

## Task 6: Chat Response Formatting for Team Actions

**Files:**
- Modify: `ai_bridge/orchestration_engine.py` (team action response formatting)

When ARCHIE performs team management actions, the response should be conversational and include the thinking steps. For example:

**User**: "Create a Python code review agent and put them on Engineering"

**ARCHIE response**:
> I've created a new agent for you! Here's what I set up:
>
> **Nova Chen** — Python Code Review Specialist
> - Model: qwen2.5:7b (local, free)
> - Department: Engineering
> - Station: ENGINEERING (primary)
> - Capabilities: code review, Python analysis, best practices
>
> Nova is now active and ready to receive tasks. Want me to adjust anything?

**Thinking panel** shows:
1. Intent: team_management (create + assign)
2. IAAE: Sub-agent creation allowed (ARCHIE: 3/20 sub-agents)
3. Extraction: {model: qwen2.5:7b, name: Nova Chen, dept: Engineering}
4. Creation: Agent #59 created successfully
5. Assignment: Assigned to ENGINEERING station (primary)

**Step 1: Add response templates**

```python
TEAM_RESPONSE_TEMPLATES = {
    'agent_created': """I've created a new agent for you!

**{name}** — {title}
- Model: {model}
- Department: {department}
- Capabilities: {capabilities}

{name} is now active and ready to receive tasks.""",

    'agent_assigned': """Done! **{agent_name}** has been assigned to **{station_name}** station as {assignment_type}.""",

    'team_status': """Here's the current team status:

**Active Agents**: {active_count}
**On Stations**: {stationed_count}
**Resting**: {resting_count}

{station_summary}""",

    'agent_deactivated': """**{agent_name}** has been deactivated. They'll be moved to the lounge.
Reason: {reason}""",
}
```

**Step 2: Commit**

```bash
git add ai_bridge/orchestration_engine.py
git commit -m "feat(chat): conversational response formatting for team actions"
```

---

## Task 7: Integration Tests

**Files:**
- Create: `tests/test_phase2_team_chat.py`

Test the full flow: chat message → intent parse → param extract → API call → response.

**Step 1: Write tests**

```python
"""Tests for Phase 2: Team management via chat."""
import pytest
import json


class TestIntentParsing:
    """Test that team management intents are correctly classified."""

    def test_create_agent_intent(self):
        from platform_v2.tools.archie_core.intent_parser import classify_intent
        result = classify_intent("Create a new Python code review agent")
        assert result['intent_type'] == 'team_management'

    def test_assign_station_intent(self):
        from platform_v2.tools.archie_core.intent_parser import classify_intent
        result = classify_intent("Assign Nova to the Engineering station")
        assert result['intent_type'] == 'station_management'

    def test_status_query_intent(self):
        from platform_v2.tools.archie_core.intent_parser import classify_intent
        result = classify_intent("Who's on duty right now?")
        assert result['intent_type'] == 'status_query'

    def test_regular_conversation_unchanged(self):
        from platform_v2.tools.archie_core.intent_parser import classify_intent
        result = classify_intent("Hello, how are you today?")
        assert result['intent_type'] == 'conversation'


class TestParamExtraction:
    """Test parameter extraction from natural language."""

    def test_create_agent_params(self):
        from ai_bridge.param_extractor import extract_params
        result = extract_params(
            "Create a Python code review agent named Nova",
            'create_agent'
        )
        assert 'model' in result
        assert 'first_name' in result

    def test_assign_station_params(self):
        from ai_bridge.param_extractor import extract_params
        result = extract_params(
            "Assign Nova to Engineering station as primary",
            'assign_station'
        )
        assert result.get('station_code') in ['ENGINEERING', 'engineering']


class TestIAAEGovernance:
    """Test sub-agent governance checks."""

    def test_archie_can_create_subagents(self):
        """ARCHIE (id=2) should be allowed to create sub-agents."""
        from ai_bridge.ethics_monitor import get_monitor
        monitor = get_monitor()
        # This requires DB access — run inside Docker
        pass

    def test_generation_limit_enforced(self):
        """Agents at max generation depth should be blocked."""
        pass
```

**Step 2: Commit**

```bash
git add tests/test_phase2_team_chat.py
git commit -m "test: Phase 2 team management via chat integration tests"
```

---

## Task 8: Template Sync + Docker Rebuild + Verify

**Step 1: Template sync (if any template changes)**
```bash
cp platform_v2/tools/consciousness/templates/consciousness_dashboard.html \
   platform_v2/templates/tools/consciousness_dashboard.html
```

**Step 2: Docker rebuild**
```bash
docker compose build archie_platform && docker compose up -d
```

**Step 3: Run migration**
```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/089_agent_hierarchy.sql
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/090_iaae_subagent_constraints.sql
```

**Step 4: Verify in chat**
1. Open Chat → ARCHIE Solo mode
2. Type: "Show me the team status"
3. Verify: ARCHIE responds with agent count and station info
4. Type: "Create a test agent using dolphin3"
5. Verify: ARCHIE extracts params, checks IAAE, creates agent, responds conversationally
6. Type: "Assign the test agent to Operations station"
7. Verify: Station assignment succeeds

**Step 5: Commit**
```bash
git add -A
git commit -m "feat(phase2): ARCHIE manages agents via chat - complete implementation"
```

---

## Execution Order

| # | Task | Depends On | Est. Complexity |
|---|------|-----------|----------------|
| 1 | DB Migration (hierarchy + budgets) | None | Low |
| 2 | Intent Parser (new types) | None | Low |
| 3 | Orchestration Engine (team actions) | 1, 2, 4 | High |
| 4 | Parameter Extractor | None | Medium |
| 5 | IAAE Constraints | 1 | Low |
| 6 | Response Formatting | 3 | Low |
| 7 | Integration Tests | 1-6 | Medium |
| 8 | Deploy + Verify | 1-7 | Low |

Tasks 1, 2, 4, 5 can be done in parallel. Task 3 is the core integration.

---

## Critical Files

| File | Change |
|------|--------|
| `database/migrations/089_agent_hierarchy.sql` | New: hierarchy columns, creation events, budgets |
| `database/migrations/090_iaae_subagent_constraints.sql` | New: governance constraints |
| `platform_v2/tools/archie_core/intent_parser.py` | Add team/station/status intents |
| `ai_bridge/orchestration_engine.py` | Team action handlers, response formatting |
| `ai_bridge/param_extractor.py` | New: NLP → structured params |
| `ai_bridge/ethics_monitor.py` | Sub-agent creation/budget checks |
| `tests/test_phase2_team_chat.py` | New: integration tests |

---

## Future (Phase 2b)

These are intentionally deferred to keep Phase 2a focused:

- **Agent-to-agent delegation**: Sub-agents delegating tasks to each other
- **Family tree visualization**: UI showing parent/child hierarchy
- **Voice commands**: "Hey ARCHIE, create a new agent" via voice
- **Auto-scaling**: ARCHIE automatically spawns agents when station workload is high
- **Agent templates**: Pre-built agent archetypes (code reviewer, analyst, writer)
- **MCP tool access**: Sub-agents can use MCP tools through ARCHIE
- **Budget dashboard**: Real-time token usage per agent in UI
