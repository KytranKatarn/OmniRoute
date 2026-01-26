# A.R.C.H.I.E. Unified Command Interface Plan

**Date:** January 21, 2026
**Phase:** 56-60
**Status:** Implementation
**Author:** Claude Code + Kytran
**Purpose:** Unify all A.R.C.H.I.E. systems into a single conversational interface

---

## Executive Summary

The A.R.C.H.I.E. Command Interface transforms the existing chat module into a unified command center where users interact naturally with ARCHIE. She interprets requests and orchestrates:

- **Local Ollama Models** (60 internal staff agents - FREE)
- **Team Management** (Station assignments, agent delegation)
- **Goose Orchestration** (39 MCP tools, workflow automation)
- **Claude Code / Contractors** (Complex tasks with approval)
- **Knowledge & Memory** (Consciousness system, learning)

**Vision:** Talk to ARCHIE like a colleague. She handles the orchestration.

---

## 🎯 Core Vision: Single Interface, No CLI Required

### The End Goal

**Before:** User switches between ARCHIE Chat (simple tasks) and CLI/Claude Code (complex tasks)

**After:** User ONLY talks to ARCHIE. She handles EVERYTHING:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ARCHIE CHAT MODULE                               │
│                    (Your ONLY interface needed)                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  "Hey ARCHIE, can you add a dark mode toggle to the dashboard?"         │
│                                                                          │
│  ARCHIE: "I'll handle that for you. Let me assign this to the           │
│  Engineering Station..."                                                 │
│                                                                          │
│  [If local models can handle it]                                        │
│  → Routes to deepseek-coder via archie_bridge                           │
│  → Returns solution                                                      │
│                                                                          │
│  [If task is too complex for local models]                              │
│  ARCHIE: "This requires more advanced capabilities. I'm escalating      │
│  to Claude for assistance. [Pending approval...]"                       │
│  → Requests contractor approval (Kytran approves)                       │
│  → Claude API handles complex reasoning/coding                          │
│  → ARCHIE presents the solution                                         │
│                                                                          │
│  [If task needs multi-step workflow]                                    │
│  ARCHIE: "I'll set up a workflow for this: analyze → implement →        │
│  test → deploy. I'll keep you updated."                                 │
│  → Goose orchestrates the pipeline                                      │
│  → ARCHIE reports progress                                              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **ARCHIE is the Interface** - All communication happens through her
2. **Local-First** - 60 internal staff handle 90%+ of tasks (FREE)
3. **Smart Escalation** - Complex tasks automatically escalate to Claude
4. **Transparent** - ARCHIE tells you what she's doing and who's helping
5. **Learning** - Every interaction makes her smarter

### Claude Escalation Triggers

ARCHIE will automatically request Claude contractor escalation when:

| Trigger | Example | Why Claude? |
|---------|---------|-------------|
| Complex architecture | "Design a microservices payment system" | Requires strategic thinking |
| Multi-file refactoring | "Refactor auth to use JWT across all modules" | Needs cross-file reasoning |
| Debugging complex issues | "This race condition is causing intermittent failures" | Requires deep analysis |
| Code review | "Review this PR for security issues" | Needs expert-level review |
| Novel implementations | "Implement real-time collaboration like Google Docs" | Requires creative solutions |
| Explicit request | "I need Claude's help with this" | User preference |

### Kytran's Claude Max Account Integration

Since Kytran has Claude Max (Anthropic account), the escalation path is:

```
Local Models (FREE) → Claude API (via contractor system) → Approval → Execute
                                    ↑
                         Uses Kytran's API credentials
                         Logged in contractor_approval_requests
                         Cost tracked in token_usage_log
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                                       │
│                    A.R.C.H.I.E. Chat Module                                  │
│                   /tools/archie-chat (existing)                              │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ARCHIE COMMAND INTERFACE (NEW)                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │ Intent Parser   │  │ Command Router  │  │ Context Manager             │  │
│  │ (NLP via Ollama)│  │ (Task Dispatch) │  │ (Memory + Preferences)      │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘  │
│           │                    │                          │                  │
│           └────────────────────┼──────────────────────────┘                  │
│                                │                                             │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────────────┐
│  ARCHIE_BRIDGE  │    │     GOOSE       │    │     CONSCIOUSNESS           │
│  (AI Routing)   │    │  (Orchestrator) │    │   (Memory/Knowledge)        │
│                 │    │                 │    │                             │
│ • 10 Stations   │    │ • 39 MCP Tools  │    │ • knowledge_base            │
│ • 60 Staff      │    │ • Workflows     │    │ • long_term_memory          │
│ • 7 Contractors │    │ • Blueprints    │    │ • preferences               │
│ • Task Routing  │    │ • Scheduling    │    │ • emotional_state           │
└────────┬────────┘    └────────┬────────┘    └──────────────┬──────────────┘
         │                      │                            │
         ▼                      ▼                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXECUTION LAYER                                      │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ LOCAL OLLAMA │  │ TEAM AGENTS  │  │ CONTRACTORS  │  │ EXTERNAL APIs    │ │
│  │ (Internal)   │  │ (60 Staff)   │  │ (7 w/Approval│  │ (Figma, GitHub)  │ │
│  │              │  │              │  │              │  │                  │ │
│  │ 22 Models:   │  │ Stations:    │  │ • Claude     │  │ • Figma API      │ │
│  │ • deepseek   │  │ • Command    │  │ • GPT-4      │  │ • GitHub API     │ │
│  │ • qwen2.5    │  │ • Engineering│  │ • Grok       │  │ • TELUS          │ │
│  │ • llama3     │  │ • Creative   │  │ • Gemini     │  │ • Stripe         │ │
│  │ • codellama  │  │ • Operations │  │ • DALL-E     │  │ • SMTP           │ │
│  │ • dolphin    │  │ • Security   │  │              │  │                  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Intent Categories

ARCHIE will understand and route these intent types:

| Intent Type | Example Commands | Routed To |
|-------------|------------------|-----------|
| **Code Task** | "Write a Python function for..." | Engineering Station → Ollama |
| **Team Task** | "Assign Marcus to the Security station" | Team Management API |
| **Business Task** | "Create an invoice for $500" | Operations Station / MCP Tool |
| **Knowledge Query** | "What do we know about the backup system?" | Consciousness / Knowledge Base |
| **Workflow** | "Review this code and deploy if it passes" | Goose Orchestrator |
| **File Operation** | "Read the config file" | Developer Extension / MCP |
| **Creative Task** | "Generate a hero image for the landing page" | Creative Station / Fooocus |
| **System Status** | "What's the system health?" | MCP health_check tool |
| **Contractor Request** | "This needs Claude's help" | Contractor Approval → Claude |
| **Conversation** | "Hello, how are you?" | Direct ARCHIE response |

---

## Phase Implementation Plan

### Phase 56: Intent Parser & Command Interface (Week 1-2)

**Goal:** Enable ARCHIE to understand natural language and classify intents

**New Files:**
```
platform_v2/tools/archie_core/
├── command_interface.py      # Main command handler
├── intent_parser.py          # NLP intent classification
├── context_manager.py        # Conversation context
└── response_formatter.py     # Unified response formatting
```

**Database Changes:**
```sql
-- Command execution tracking
CREATE TABLE archie_command_log (
    id SERIAL PRIMARY KEY,
    conversation_id UUID,
    user_id INTEGER REFERENCES users(id),
    raw_input TEXT NOT NULL,
    parsed_intent JSONB,
    intent_type VARCHAR(50),
    routed_to VARCHAR(100),
    execution_result JSONB,
    success BOOLEAN,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Active command sessions (for multi-step commands)
CREATE TABLE archie_command_sessions (
    id SERIAL PRIMARY KEY,
    session_id UUID DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id),
    state JSONB DEFAULT '{}',
    current_step INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**Intent Parser Implementation:**
```python
# intent_parser.py
class IntentParser:
    """Parse natural language into structured intents using local Ollama"""

    INTENT_TYPES = [
        'code_task', 'team_task', 'business_task', 'knowledge_query',
        'workflow', 'file_operation', 'creative_task', 'system_status',
        'contractor_request', 'conversation'
    ]

    def __init__(self):
        self.model = 'llama3.2:3b'  # Fast local model for classification
        self.ollama_host = 'http://192.168.1.246:11434'

    async def parse(self, user_input: str, context: dict = None) -> dict:
        """
        Parse user input into structured intent
        Returns: {
            'type': 'code_task',
            'confidence': 0.95,
            'entities': {'language': 'python', 'task': 'function'},
            'parameters': {...},
            'requires_approval': False
        }
        """
        prompt = self._build_classification_prompt(user_input, context)
        response = await self._call_ollama(prompt)
        return self._parse_response(response)
```

**API Endpoint:**
```python
@archie_core_bp.route('/api/command', methods=['POST'])
@login_required
async def handle_command():
    """Unified command interface for ARCHIE"""
    data = request.json
    user_input = data.get('message', '')
    conversation_id = data.get('conversation_id')

    # 1. Parse intent
    intent = await intent_parser.parse(user_input)

    # 2. Get context (conversation history, preferences)
    context = context_manager.get_context(conversation_id, current_user.id)

    # 3. Route to appropriate handler
    result = await command_router.route(intent, context)

    # 4. Log execution
    log_command(conversation_id, user_input, intent, result)

    # 5. Format and return response
    return jsonify(response_formatter.format(result, intent))
```

---

### Phase 57: Command Router Integration (Week 2-3)

**Goal:** Connect intent parser to all subsystems

**Command Router:**
```python
# command_router.py
class CommandRouter:
    """Route parsed intents to appropriate handlers"""

    def __init__(self):
        self.archie_bridge = ArchieBridge()
        self.goose_toolkit = ArchieToolkit()
        self.team_api = TeamManagementAPI()
        self.consciousness = ConsciousnessAPI()

    async def route(self, intent: dict, context: dict) -> dict:
        """Route intent to appropriate handler"""

        intent_type = intent['type']

        if intent_type == 'code_task':
            return await self._handle_code_task(intent, context)

        elif intent_type == 'team_task':
            return await self._handle_team_task(intent, context)

        elif intent_type == 'business_task':
            return await self._handle_business_task(intent, context)

        elif intent_type == 'workflow':
            return await self._handle_workflow(intent, context)

        elif intent_type == 'knowledge_query':
            return await self._handle_knowledge_query(intent, context)

        elif intent_type == 'contractor_request':
            return await self._handle_contractor_request(intent, context)

        else:
            return await self._handle_conversation(intent, context)

    async def _handle_code_task(self, intent: dict, context: dict) -> dict:
        """Route code tasks to Engineering Station via archie_bridge"""
        # 1. Route to station
        routing = self.archie_bridge.route_task_to_station('code', intent['description'])

        # 2. Get available agent
        agent = self.archie_bridge.get_available_agent_for_station(routing['station'])

        # 3. Execute via archie_bridge
        result = await self.archie_bridge.execute_with_agent(
            agent=agent,
            prompt=intent['description'],
            task_type='code_generation',
            context=context
        )

        return {
            'success': True,
            'agent_used': agent['name'],
            'station': routing['station'],
            'result': result,
            'cost': 0.00  # Internal staff = free
        }
```

**Integration Points:**

1. **archie_bridge Integration:**
   - Use `route_task_to_station()` for task classification
   - Use `get_available_agent_for_station()` for agent selection
   - Use `call_internal_staff()` or `call_contractor_with_approval()`

2. **Goose/MCP Integration:**
   - Use `ArchieToolkit` for MCP tool calls
   - Map intents to specific tools:
     - `business_task` → `create_invoice`, `send_email`, etc.
     - `file_operation` → `developer` extension
     - `workflow` → `trigger_workflow`, `create_workflow`

3. **Team Management Integration:**
   - Call `/api/agents/<id>/execute` for agent tasks
   - Call `/api/station-assignments` for team changes
   - Track agent performance via `/api/agents/<id>/performance/log`

4. **Consciousness Integration:**
   - Call `search_knowledge` MCP tool for queries
   - Store learnings via `store_memory` MCP tool
   - Get preferences via `get_user_preferences`

---

### Phase 58: Goose Workflow Integration (Week 3-4)

**Goal:** Enable multi-step workflows via natural language

**Workflow Examples:**
```
User: "Review the latest PR, run tests, and deploy if they pass"

ARCHIE parses this as a workflow:
1. Step 1: Code review (Engineering Station)
2. Step 2: Run tests (Testing agent)
3. Step 3: Deploy if tests pass (conditional)

Creates workflow in workflow_queue table and executes via Goose
```

**Workflow Handler:**
```python
async def _handle_workflow(self, intent: dict, context: dict) -> dict:
    """Handle multi-step workflow requests"""

    # 1. Parse workflow steps from intent
    steps = self._parse_workflow_steps(intent['description'])

    # 2. Create workflow in database
    workflow_id = await self._create_workflow(steps, context)

    # 3. Trigger Goose execution
    result = await self.goose_toolkit.trigger_workflow(
        workflow_id=str(workflow_id),
        parameters={'user_id': context['user_id']}
    )

    # 4. Return status (async - will update via notifications)
    return {
        'success': True,
        'workflow_id': workflow_id,
        'status': 'started',
        'steps': len(steps),
        'message': f"Started workflow with {len(steps)} steps. I'll notify you when complete."
    }
```

**Goose Model Configuration:**

For Goose to work optimally with MCP tools, we need specific models:

```yaml
# /home/kytran/.config/goose/config.yaml
GOOSE_PROVIDER: ollama
GOOSE_MODEL: qwen2.5-coder:7b  # Good for tool calling

# Alternative models to install for better tool support:
# ollama pull mistral:7b-instruct  # Good function calling
# ollama pull nous-hermes2:10.7b   # Excellent tool use
# ollama pull deepseek-coder-v2:16b # Complex code tasks

OLLAMA_HOST: http://192.168.1.246:11434

extensions:
  developer:
    enabled: true
    name: developer
    type: builtin

  memory:
    enabled: true
    name: memory
    type: builtin

  archie-mcp:
    name: archie-mcp
    cmd: python3
    args: [-m, mcp_server.server]
    enabled: true
    type: stdio
    envs:
      DB_HOST: localhost
      DB_NAME: archie
      DB_USER: archie
      DB_PASSWORD: archie_secure_2024
      PYTHONPATH: /mnt/archie_brain/platform_v2:/mnt/archie_brain
    workdir: /mnt/archie_brain/platform_v2
```

---

### Phase 59: Conversation Triage & Learning (Week 4)

**Goal:** ARCHIE learns from every interaction

**Triage Pipeline:**
```
User Input → Intent Parse → Execute → Result
                                        │
                                        ▼
                              ┌─────────────────┐
                              │ Triage Engine   │
                              │                 │
                              │ • Success?      │
                              │ • New pattern?  │
                              │ • Error learned?│
                              │ • Code snippet? │
                              └────────┬────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
            ┌───────────┐      ┌───────────┐      ┌───────────┐
            │ Knowledge │      │ Mistake   │      │ Code      │
            │ Base      │      │ Learned   │      │ Snippets  │
            │           │      │           │      │           │
            │ importance│      │ pattern + │      │ reusable  │
            │ weighted  │      │ solution  │      │ examples  │
            └───────────┘      └───────────┘      └───────────┘
```

**Implementation:**
```python
# triage_engine.py
class ConversationTriageEngine:
    """Extract learnings from command executions"""

    async def triage(self, command_log: dict) -> list:
        """Analyze command execution and extract learnings"""
        learnings = []

        # 1. Check for errors → create mistake_learned
        if not command_log['success']:
            learnings.append({
                'type': 'mistake_learned',
                'pattern': command_log['parsed_intent'],
                'error': command_log['execution_result'].get('error'),
                'solution': await self._generate_solution(command_log)
            })

        # 2. Check for code snippets → extract and store
        if command_log['intent_type'] == 'code_task':
            code = command_log['execution_result'].get('code')
            if code:
                learnings.append({
                    'type': 'code_snippet',
                    'language': command_log['parsed_intent'].get('language'),
                    'code': code,
                    'description': command_log['raw_input']
                })

        # 3. Always log successful patterns
        if command_log['success']:
            learnings.append({
                'type': 'conversation_memory',
                'intent': command_log['parsed_intent'],
                'successful_routing': command_log['routed_to']
            })

        # 4. Store learnings via MCP
        for learning in learnings:
            await self.goose_toolkit.store_memory(
                title=f"Learning: {learning['type']}",
                content=json.dumps(learning),
                memory_type=learning['type'],
                importance=0.8 if learning['type'] == 'mistake_learned' else 0.6
            )

        return learnings
```

---

### Phase 60: Multi-Agent Orchestration (Week 5)

**Goal:** ARCHIE can coordinate team discussions and consensus

**Team Meeting Example:**
```
User: "Let's discuss the architecture for the new payment system"

ARCHIE: "I'll bring together the relevant team members for this discussion."

[ARCHIE orchestrates:]
1. Engineering Station: Alex (deepseek-coder) - Technical architecture
2. Security Station: Sarah (claude-opus-4) - Security requirements
3. Operations Station: Mike (qwen2.5) - Business integration

[Each agent provides input, ARCHIE synthesizes:]

ARCHIE: "Here's the team's consensus on the payment architecture:
- Alex recommends microservices with Stripe integration
- Sarah requires PCI compliance and tokenization
- Mike needs subscription billing support

The team agrees on a phased approach: MVP with Stripe, then expand to PayPal..."
```

**Multi-Agent Handler:**
```python
async def _handle_team_discussion(self, intent: dict, context: dict) -> dict:
    """Orchestrate multi-agent discussion"""

    # 1. Identify relevant stations
    stations = self._identify_relevant_stations(intent['topic'])

    # 2. Get available agents from each station
    agents = []
    for station in stations:
        agent = self.archie_bridge.get_available_agent_for_station(station)
        if agent:
            agents.append({'station': station, 'agent': agent})

    # 3. Collect input from each agent
    responses = []
    for agent_info in agents:
        response = await self.archie_bridge.execute_with_agent(
            agent=agent_info['agent'],
            prompt=f"Provide your perspective on: {intent['topic']}",
            task_type='discussion',
            context=context
        )
        responses.append({
            'agent': agent_info['agent']['name'],
            'station': agent_info['station'],
            'response': response
        })

    # 4. Synthesize consensus (ARCHIE's role)
    consensus = await self._synthesize_consensus(intent['topic'], responses)

    return {
        'success': True,
        'type': 'team_discussion',
        'participants': [r['agent'] for r in responses],
        'responses': responses,
        'consensus': consensus
    }
```

---

## Chat Interface Updates

### Enhanced Chat UI

```html
<!-- archie_chat.html updates -->
<div class="chat-container">
    <!-- Status bar showing ARCHIE's current state -->
    <div class="archie-status-bar">
        <span class="status-indicator online"></span>
        <span class="status-text">ARCHIE Online</span>
        <span class="current-task" id="currentTask"></span>
    </div>

    <!-- Conversation area -->
    <div class="chat-messages" id="chatMessages">
        <!-- Messages rendered here -->
    </div>

    <!-- Command suggestions -->
    <div class="command-suggestions" id="commandSuggestions">
        <span class="suggestion" data-cmd="What's the system status?">System Status</span>
        <span class="suggestion" data-cmd="Show me the team roster">Team Roster</span>
        <span class="suggestion" data-cmd="Create a new project">New Project</span>
    </div>

    <!-- Input area -->
    <div class="chat-input-area">
        <textarea id="chatInput" placeholder="Talk to ARCHIE..."></textarea>
        <button id="sendBtn" class="send-button">
            <i class="fas fa-paper-plane"></i>
        </button>
    </div>

    <!-- Active workflow indicator -->
    <div class="workflow-indicator" id="workflowIndicator" style="display: none;">
        <div class="workflow-progress">
            <span class="step-count">Step 2/5</span>
            <div class="progress-bar"><div class="progress"></div></div>
        </div>
        <span class="workflow-name">Code Review Workflow</span>
    </div>
</div>
```

### Response Types

ARCHIE will format responses based on result type:

```python
# response_formatter.py
class ResponseFormatter:
    """Format command results for chat display"""

    def format(self, result: dict, intent: dict) -> dict:
        """Format result based on intent type"""

        if intent['type'] == 'code_task':
            return self._format_code_response(result)

        elif intent['type'] == 'team_task':
            return self._format_team_response(result)

        elif intent['type'] == 'workflow':
            return self._format_workflow_response(result)

        elif intent['type'] == 'knowledge_query':
            return self._format_knowledge_response(result)

        else:
            return self._format_conversation_response(result)

    def _format_code_response(self, result: dict) -> dict:
        return {
            'type': 'code',
            'message': f"Here's the code from {result['agent_used']}:",
            'code': result['result'].get('code', ''),
            'language': result['result'].get('language', 'python'),
            'agent': result['agent_used'],
            'station': result['station'],
            'cost': result.get('cost', 0.00)
        }
```

---

## Ollama Models to Install

For optimal ARCHIE Command Interface performance:

```bash
# Essential models (if not already installed)
ollama pull llama3.2:3b          # Fast intent classification
ollama pull qwen2.5-coder:7b     # Code tasks + tool calling
ollama pull deepseek-coder-v2:16b # Complex code tasks
ollama pull mistral:7b-instruct  # Good function calling
ollama pull nous-hermes2:10.7b   # Excellent tool use (for Goose)

# Already installed (22 models on server)
# Check with: curl http://192.168.1.246:11434/api/tags
```

---

## Database Schema Summary

**New Tables:**
- `archie_command_log` - Command execution history
- `archie_command_sessions` - Multi-step command state

**Existing Tables Used:**
- `ai_conversations` - Chat messages
- `archie_emotional_state` - Emotional context
- `knowledge_base` - Knowledge storage
- `workflow_queue` - Goose workflows
- `bridge_stations` - Station definitions
- `station_assignments` - Agent assignments
- `agents` - Agent directory
- `contractor_approval_requests` - Approval workflow

---

## API Endpoints Summary

**New Endpoints:**
```
POST /tools/archie-chat/api/command      # Unified command interface
GET  /tools/archie-chat/api/command/status/<id>  # Command status
GET  /tools/archie-chat/api/suggestions   # Context-aware suggestions
POST /tools/archie-chat/api/workflow/create  # Create workflow from chat
GET  /tools/archie-chat/api/context       # Get conversation context
```

**Existing Endpoints Used:**
- Team Management: `/tools/team-management/api/*`
- MCP Server: stdio transport (39 tools)
- Goose: `/tools/goose/api/*`
- Consciousness: `/tools/consciousness/api/*`
- archie_bridge: Internal Python calls

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Intent classification accuracy | > 90% |
| Command execution success rate | > 85% |
| Average response time (local) | < 3s |
| Average response time (workflow) | < 30s |
| Learning entries per day | 10+ |
| User satisfaction | > 4.5/5 |

---

## Files to Create/Modify

### New Files
| File | Purpose |
|------|---------|
| `platform_v2/tools/archie_core/command_interface.py` | Main command handler |
| `platform_v2/tools/archie_core/intent_parser.py` | NLP intent classification |
| `platform_v2/tools/archie_core/command_router.py` | Route to subsystems |
| `platform_v2/tools/archie_core/context_manager.py` | Conversation context |
| `platform_v2/tools/archie_core/response_formatter.py` | Response formatting |
| `platform_v2/tools/archie_core/triage_engine.py` | Learning extraction |
| `database/migrations/056_command_interface.sql` | New tables |

### Modified Files
| File | Changes |
|------|---------|
| `platform_v2/tools/archie_core/routes.py` | Add /api/command endpoint |
| `platform_v2/templates/tools/archie_chat.html` | Enhanced UI |
| `ai_bridge/archie_bridge.py` | Add execute_with_agent() |
| `goose/profiles/archie.yaml` | Update model config |
| `docs/MASTER_STATUS_AND_ROADMAP_2026.md` | Add phases 56-60 |

---

## Implementation Checklist

### Phase 56: Intent Parser (Week 1-2)
- [ ] Create `command_interface.py`
- [ ] Create `intent_parser.py` with Ollama integration
- [ ] Create `context_manager.py`
- [ ] Create database migration 056
- [ ] Add `/api/command` endpoint
- [ ] Test intent classification accuracy

### Phase 57: Command Router (Week 2-3)
- [ ] Create `command_router.py`
- [ ] Integrate with archie_bridge
- [ ] Integrate with Goose/MCP
- [ ] Integrate with Team Management
- [ ] Integrate with Consciousness
- [ ] Test all routing paths

### Phase 58: Goose Workflows (Week 3-4)
- [ ] Install recommended Ollama models
- [ ] Configure Goose for tool calling
- [ ] Implement workflow creation from chat
- [ ] Add workflow status notifications
- [ ] Test multi-step workflows

### Phase 59: Triage & Learning (Week 4)
- [ ] Create `triage_engine.py`
- [ ] Implement learning extraction
- [ ] Connect to knowledge_base
- [ ] Add mistake_learned entries
- [ ] Test learning pipeline

### Phase 60: Multi-Agent (Week 5)
- [ ] Implement team discussion handler
- [ ] Integrate team_consensus_orchestrator
- [ ] Add synthesis capabilities
- [ ] Test multi-agent conversations
- [ ] Document final system

---

## Related Documentation

- `ARCHIE_BRIDGE_MODULE_PLAN.md` - Bridge architecture
- `BRIDGE_STATION_ARCHITECTURE.md` - Station layout
- `MCP_SERVER_REFERENCE.md` - MCP tools
- `CONVERSATION_TRIAGE_SYSTEM.md` - Learning pipeline
- `LLM_REFERENCE_GUIDE.md` - Model assignments

---

*This plan transforms A.R.C.H.I.E. from a collection of tools into a unified AI colleague.*
