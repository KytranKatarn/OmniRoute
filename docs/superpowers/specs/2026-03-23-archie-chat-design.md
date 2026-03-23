# ARCHIE Chat — Design Specification

**Date**: 2026-03-23
**Project**: #178 — ARCHIE Chat: Rebuild from Scratch
**Approach**: A — Orchestration Engine as Core
**Status**: Approved

---

## 1. Overview

ARCHIE Chat is the collaboration layer for the A.R.C.H.I.E. platform — a chat interface that connects users directly to ARCHIE's agent fleet, knowledge base, and orchestration pipeline. It serves as both a direct user-facing chat experience and a programmatic API for Claude CLI and node integration.

### Goals
- Provide a rich, multi-turn chat experience powered by the existing 8-step orchestration pipeline
- Expose full orchestration visibility (flight deck) so users see how their requests are routed
- Support tier-gated multi-tenant access with per-user data isolation for SaaS users
- Enable Claude CLI and external nodes to leverage ARCHIE's agents via REST API
- Allow users to auto-route or direct requests to specific agents/stations

### Non-Goals (v1)
- SSE/streaming responses (JSON request/response only)
- Merging archie_bridge.py into orchestration engine (future project)
- Voice/audio input
- File upload in chat

---

## 2. Architecture

### Data Flow

```
User Input (Browser / Claude CLI / Node API)
    ↓
API Gateway — /api/v1/chat/message
    ↓  auth (session cookie OR bearer token)
    ↓  tier check (Kytran/Enterprise/Pro)
    ↓  rate limit
    ↓
Chat Service
    ↓  load/create conversation
    ↓  inject conversation history as context
    ↓  resolve agent_target (if user-directed)
    ↓
OrchestrationEngine.orchestrate()
    ↓  1. Intent parse
    ↓  2. IAAE pre-check
    ↓  3. Agent welfare check
    ↓  4. Smart routing (tier recommendation)
    ↓  5. GPU state awareness
    ↓  6. Agent selection
    ↓  7. Execution (Ollama / Cloud / Node)
    ↓  8. Logging
    ↓
KB Augmentation
    ↓  get_relevant_knowledge()
    ↓  check_for_known_mistakes()
    ↓
Response
    ↓  OrchestrationResult → JSON
    ↓  Save message + thinking_steps to chat_messages
    ↓  Return to client
```

### Three Interfaces, One Pipeline

| Interface | Route | Users | Features |
|-----------|-------|-------|----------|
| Module UI | `/tools/archie-chat` | All tier-gated users | Full LCARS chat + flight deck + conversation sidebar |
| Global Overlay | Floating widget (every page) | Kytran/admin only | Compact chat, expand to module |
| REST API | `/api/v1/chat/*` | Claude CLI, Nodes, external | Full orchestration access via bearer token |

### Multi-Tenant Model

| Tier | Conversations | KB Access | Agents | Overlay | Node Integration |
|------|---------------|-----------|--------|---------|------------------|
| Kytran | Team-shared namespace (team_id) | Full shared KB | Full fleet | Yes | N/A (is the hub) |
| Enterprise | Per-user isolated (user_id) | Scoped | Full fleet | No | Own node + local DB |
| Pro | Per-user isolated (user_id) | Scoped | Full fleet | No | Own node + local DB |

---

## 3. Database Schema

### chat_conversations

```sql
CREATE TABLE chat_conversations (
    id SERIAL PRIMARY KEY,
    conversation_uuid UUID DEFAULT gen_random_uuid() NOT NULL UNIQUE,  -- matches OrchestrationEngine's conversation_id format
    user_id INTEGER NOT NULL REFERENCES users(id),
    team_id INTEGER,                          -- shared namespace for Kytran tier
    title VARCHAR(255),                       -- auto-generated from first message
    agent_target VARCHAR(100),                -- pinned agent/station if user-directed
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chat_conversations_user ON chat_conversations(user_id);
CREATE INDEX idx_chat_conversations_team ON chat_conversations(team_id) WHERE team_id IS NOT NULL;
CREATE INDEX idx_chat_conversations_updated ON chat_conversations(updated_at DESC);
CREATE INDEX idx_chat_conversations_uuid ON chat_conversations(conversation_uuid);
```

**Note:** `conversation_uuid` is the key passed to `OrchestrationEngine.orchestrate(conversation_id=...)`. The engine already generates UUIDs for `orchestration_sessions.conversation_id`. The chat service creates the UUID, passes it to the engine, and uses the integer `id` for internal FK references only.

### chat_messages

```sql
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id),  -- no CASCADE: soft-delete only via is_archived
    role VARCHAR(20) NOT NULL,                -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    thinking_steps JSONB,                     -- OrchestrationResult.thinking_steps
    agent_used VARCHAR(100),                  -- agent code name
    model_used VARCHAR(100),                  -- model name
    station_code VARCHAR(20),                 -- station that handled it
    governance_events JSONB,                  -- IAAE events
    duration_ms INTEGER,                      -- response time
    token_count INTEGER,                      -- for rate limiting/billing
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chat_messages_conversation ON chat_messages(conversation_id, created_at);
```

### chat_api_keys

```sql
CREATE TABLE chat_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    key_hash VARCHAR(64) NOT NULL,            -- SHA-256 of the API key
    key_prefix VARCHAR(8) NOT NULL,           -- first 8 chars for identification
    name VARCHAR(100) NOT NULL,               -- "Claude CLI", "My Node", etc.
    scopes JSONB DEFAULT '["chat"]'::jsonb,   -- allowed capabilities
    rate_limit INTEGER DEFAULT 30,            -- requests per minute
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_chat_api_keys_hash ON chat_api_keys(key_hash) WHERE is_active = TRUE;
CREATE INDEX idx_chat_api_keys_user ON chat_api_keys(user_id);
```

### Design Decisions
- **conversation_uuid** (UUID) matches `OrchestrationEngine`'s existing `conversation_id` format. Integer `id` used only for internal FK references. Chat service creates the UUID and passes it to `orchestrate(conversation_id=uuid)`.
- **team_id** on conversations enables Kytran shared namespace — all team members see same threads
- **thinking_steps as JSONB** per message — flight deck can replay any past conversation
- **API keys** separate from session auth — CLI uses bearer tokens, browser uses session cookies
- **No CASCADE on messages** — conversations use soft-delete (`is_archived`). A future hard-purge job can clean up archived conversations + messages.
- Per-user isolation for SaaS enforced by user_id filtering on all queries

---

## 4. API Design

### Authentication

Two auth paths:

| Client | Method | Header |
|--------|--------|--------|
| Browser (Module + Overlay) | Session cookie | Existing Flask `login_required` |
| API (Claude CLI + Nodes) | Bearer token | `Authorization: Bearer archie_xxxxx` |

Auth middleware checks for bearer token first, falls back to session cookie.

### Core Endpoints

#### POST /api/v1/chat/message

Send a message and get the orchestrated response.

**Request:**
```json
{
    "message": "Analyze our API latency trends",
    "conversation_id": "uuid-optional",
    "agent_target": "ANALYTICS",
    "include_thinking": true,
    "include_knowledge": true,
    "voice_mode": false
}
```

- `conversation_id` — omit to auto-create a new conversation
- `agent_target` — station code (`ANALYTICS`) or agent name (`Nexus`). Omit for auto-routing.
- `include_thinking` — return thinking_steps[] in response (default: true for module, false for overlay)
- `include_knowledge` — return KB entries used for augmentation
- `voice_mode` — (Phase 5) pass-through to `orchestrate(voice_mode=...)`. Concise responses without markdown.

**Response (success):**
```json
{
    "success": true,
    "conversation_id": "uuid",
    "message_id": 42,
    "response": "Based on the last 7 days...",
    "agent": {
        "name": "Nexus",
        "display_name": "Jin Park",
        "station": "ANALYTICS"
    },
    "model_used": "dolphin3-8k:latest",
    "thinking_steps": [
        {"step_type": "intent_parse", "label": "Intent Parse", "data": {"intent": "analytics_query", "confidence": 0.94}, "duration_ms": 12},
        {"step_type": "iaae_check", "label": "IAAE Check", "data": {"approved": true}, "duration_ms": 3},
        {"step_type": "agent_select", "label": "Agent Select", "data": {"agent": "Nexus", "score": 0.87}, "duration_ms": 8},
        {"step_type": "route_decision", "label": "Smart Route", "data": {"tier": "tier-2", "model": "dolphin3-8k"}, "duration_ms": 5},
        {"step_type": "execute", "label": "Execute", "data": {"tokens": 342}, "duration_ms": 1230}
    ],
    "governance_events": [],
    "duration_ms": 1303,
    "knowledge_used": [
        {"title": "API Performance Baseline", "relevance": 0.92}
    ]
}
```

**Response (error):**
```json
{
    "success": false,
    "error": {
        "code": "AGENT_UNAVAILABLE",
        "message": "Targeted agent Nexus is currently stressed (stress: 0.85). Try ANALYTICS station instead.",
        "suggestion": "ANALYTICS"
    },
    "conversation_id": "uuid"
}
```

Error codes: `VALIDATION_ERROR`, `AUTH_FAILED`, `TIER_REQUIRED`, `RATE_LIMITED`, `AGENT_UNAVAILABLE`, `ORCHESTRATION_FAILED`, `MODEL_UNAVAILABLE`, `CONVERSATION_NOT_FOUND`.

#### GET /api/v1/chat/conversations

List user's conversations (or team conversations for Kytran tier).

**Params:** `?page=1&limit=20&archived=false`

#### GET /api/v1/chat/conversations/{id}/messages

Get conversation history with optional thinking steps.

**Params:** `?include_thinking=true&limit=50&before=msg_id`

#### POST /api/v1/chat/conversations

Create a new conversation explicitly.

**Body:** `{"title": "optional", "agent_target": "optional"}`

#### DELETE /api/v1/chat/conversations/{id}

Archive a conversation (soft delete).

### Support Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v1/chat/agents` | Available agents for targeting |
| GET | `/api/v1/chat/stations` | Station roster with capabilities |
| GET | `/api/v1/chat/knowledge/search` | Direct KB search (without chat) |
| POST | `/api/v1/chat/keys` | Generate API key (admin) |
| GET | `/api/v1/chat/keys` | List user's API keys |
| DELETE | `/api/v1/chat/keys/{id}` | Revoke API key |

### Rate Limiting

| Tier | Requests/min | Max conversations | Max messages/conversation |
|------|-------------|-------------------|--------------------------|
| Kytran | Unlimited | Unlimited | Unlimited |
| Enterprise | 60 | 100 | 500 |
| Pro | 30 | 50 | 200 |
| API key | Per-key config | Per-user limits | Per-user limits |

---

## 5. Frontend Design

### Module UI — /tools/archie-chat

Three-panel layout:

**Left Panel — Conversation Sidebar (240px)**
- New chat button
- Conversation list sorted by updated_at
- Active conversation highlighted
- Agent target dropdown at bottom (Auto-route / specific station / specific agent)

**Center Panel — Chat Area**
- Messages with agent avatars, display names, station badges
- User messages right-aligned, agent responses left-aligned
- Message input at bottom with send button
- Auto-scroll on new messages

**Right Panel — Flight Deck (260px, collapsible)**
- Thinking steps rendered as color-coded cards per step type
- Each card shows: step name, key data, duration
- Station colors match the 10 canonical stations
- Toggle button to show/hide
- Total duration and step count at bottom

### Global Overlay — Kytran/Admin Only

**Minimized State:**
- Floating bubble icon, bottom-right corner
- Subtle pulse animation when ARCHIE has a notification

**Expanded State:**
- 360px wide compact chat window
- Header with ARCHIE status indicator + expand/minimize buttons
- Scrollable message area (no flight deck — too compact)
- Compact input with send button
- "Expand to full" button opens `/tools/archie-chat` with current conversation

**Integration:**
- Loaded via `archie-chat-overlay.js` injected in `base.html`
- Only for users with Kytran/admin tier (checked server-side in template)
- Shares same API endpoints as module
- Persists minimized/expanded state in localStorage

### File Structure

```
platform_v2/tools/archie_chat/
  ├── __init__.py              # Blueprint + register_*_routes (ADR-045)
  ├── routes.py                # Page routes (render template)
  ├── api_routes.py            # /api/v1/chat/* endpoints
  ├── chat_service.py          # Business logic, conversation mgmt, tier-gating
  ├── auth_middleware.py        # Dual auth (session + API key)
  └── templates/
      └── archie_chat.html     # LCARS module template

platform_v2/static/
  ├── css/archie-chat.css      # Chat + flight deck styles
  ├── js/archie-chat.js        # Chat UI, conversation mgmt, flight deck
  └── js/archie-chat-overlay.js # Global overlay widget
```

### Blueprint Registration (ADR-045 pattern)

```python
# tools/archie_chat/__init__.py
from flask import Blueprint

archie_chat_bp = Blueprint(
    "archie_chat",
    __name__,
    template_folder="templates",
    url_prefix="/tools/archie-chat"
)

def register_page_routes(bp, admin_required):
    from .routes import register_routes
    register_routes(bp, admin_required)

def register_api_routes(bp, admin_required):
    from .api_routes import register_routes
    register_routes(bp, admin_required)

# Called at module scope — matches starbase/dev_pipeline pattern
register_page_routes(archie_chat_bp, None)   # admin_required injected by app.py
register_api_routes(archie_chat_bp, None)
```

**Note:** `admin_required` is `None` at import time — `app.py` calls the register functions again with the real decorator during startup, matching the existing pattern in starbase and dev_pipeline modules.

---

## 6. Orchestration Engine Changes

### Conversation Context — Use Existing Mechanism

The engine already has `conversation_id` (UUID) and `_load_conversation_history()` (line ~773, ~2506) which retrieves history from `orchestration_sessions`. The chat service does **not** pass pre-built history. Instead:

1. Chat service creates/loads `chat_conversations.conversation_uuid`
2. Passes it to `orchestrate(conversation_id=uuid)` — the engine's existing parameter
3. The engine's `_load_conversation_history()` retrieves prior context from `orchestration_sessions`
4. Chat service separately stores messages in `chat_messages` for the UI (flight deck replay, conversation list)

This avoids a redundant history parameter and uses the engine's existing session management as the source of truth for LLM context.

### Agent Targeting — New Parameter

Add a **new** `agent_target` parameter to `orchestrate()`:

```python
# New parameter (does not exist today)
def orchestrate(self, message, user_id=None, agent_target=None, ...):
    # agent_target: station code or agent name string
```

Pipeline override behavior:
- **Station code** (e.g., `ANALYTICS`): overrides **step 4** (smart routing skips station selection), step 6 (agent selection) picks best agent from that station only
- **Agent name** (e.g., `Nexus`): overrides **steps 4 and 6** (skip both routing and agent selection, use that agent directly)
- **Steps 2, 3, 5** still run** — IAAE check, welfare check, and GPU check still apply. If the targeted agent is stressed/exhausted, return an error with `AGENT_UNAVAILABLE` code and suggest alternatives.
- **Omitted**: normal auto-routing through all 8 steps

### KB Augmentation in Response

The existing `get_relevant_knowledge()` runs during orchestration. For the chat API, we capture which KB entries were used and include them in the response when `include_knowledge=true`.

---

## 7. Phased Implementation Plan

### Phase 1 — Foundation (Backend)

| Task | Description | Priority |
|------|-------------|----------|
| 1.1 | DB migration: `chat_conversations`, `chat_messages`, `chat_api_keys` tables | 10 |
| 1.2 | `chat_service.py` — conversation CRUD, message storage, history retrieval, tier-gating | 10 |
| 1.3 | Add `agent_target` param to `OrchestrationEngine.orchestrate()` — overrides steps 4/6 (see Section 6) | 9 |
| 1.4 | `api_routes.py` — `POST /api/v1/chat/message` + conversation endpoints | 9 |
| 1.5 | `auth_middleware.py` — dual auth (session cookie + bearer token) | 9 |

### Phase 2 — Module UI

| Task | Description | Priority |
|------|-------------|----------|
| 2.1 | Blueprint scaffold: `tools/archie_chat/` with `__init__.py`, `routes.py`, template | 8 |
| 2.2 | LCARS chat template — conversation sidebar, message area, input | 8 |
| 2.3 | `archie-chat.js` — message send/receive, conversation switching, agent target selector | 8 |
| 2.4 | Flight deck panel — render thinking_steps, collapsible | 7 |
| 2.5 | `archie-chat.css` — LCARS styling, responsive breakpoints (480/768/1024px) | 7 |

### Phase 3 — Global Overlay

| Task | Description | Priority |
|------|-------------|----------|
| 3.1 | `archie-chat-overlay.js` — floating bubble, expand/collapse, compact chat | 7 |
| 3.2 | Inject in `base.html` for Kytran/admin tier only (server-side check) | 7 |
| 3.3 | Expand-to-full button linking to module with current conversation | 6 |

### Phase 4 — API & Integration

| Task | Description | Priority |
|------|-------------|----------|
| 4.1 | API key management — generate, list, revoke in Account Center | 6 |
| 4.2 | Claude CLI integration test + documentation | 6 |
| 4.3 | Node proxy endpoint — forward chat to user's local orchestration | 6 |
| 4.4 | Rate limiting per tier (decorator-based) | 5 |

### Phase 5 — Memory & Polish

| Task | Description | Priority |
|------|-------------|----------|
| 5.1 | Cross-session memory via `conversation_ingest` — recall past context | 5 |
| 5.2 | KB augmentation display — show which entries informed the response | 5 |
| 5.3 | Conversation search and archive UI | 5 |
| 5.4 | Voice mode toggle (concise responses, no markdown) | 4 |

---

## 8. Module Registration

Add to `module_registry.py`:

```python
{
    "name": "archie-chat",
    "display_name": "ARCHIE Chat",
    "description": "Chat with ARCHIE's agent fleet",
    "category": "AI_COMMAND",
    "icon": "💬",
    "route": "/tools/archie-chat",
    "tier_required": ["kytran", "enterprise", "pro"]
}
```

Add to `rbac.py`:
```python
# Permission key
"archie_chat": {"name": "ARCHIE Chat", "description": "Chat with ARCHIE agent fleet"}

# Tier mappings — add "archie_chat" to these tiers:
# - "kytran" tier: full access (module + overlay + API)
# - "enterprise" tier: module + API (no overlay)
# - "pro" tier: module + API (no overlay)
# - "free"/"basic" tiers: no access
```

---

## 9. Future Roadmap (Post v1)

- **Approach C merge**: Fold archie_bridge.py conversation memory + emotional intelligence into orchestration engine
- **SSE streaming**: Real-time token streaming for long responses
- **File upload**: Share images/documents in chat for agent analysis
- **Voice input**: Speech-to-text → chat → text-to-speech
- **Chat commands**: `/status`, `/roster`, `/kb search` inline commands
- **Agent handoff**: Mid-conversation transfer between agents with context
