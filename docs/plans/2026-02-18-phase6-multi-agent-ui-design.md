# Phase 6: Multi-Agent Orchestration UI — Design Doc

**Date:** 2026-02-18
**Status:** Approved
**Scope:** Mission Control tab, enhanced agent roster, multi-agent execution log, SSE streaming, chat activity badge

---

## Context

The ARCHIE platform has extensive multi-agent backend infrastructure:
- **Orchestration Engine** (8-step pipeline: intent → IAAE → route → GPU → agent → welfare → execute → log)
- **Agent Delegation** (fast keyword-based agent selection, department routing, worker type handling)
- **10 Bridge Stations** (COMMAND through AWAY_TEAM, DB-driven config)
- **9 Named Agents** (ARCHIE + 8 specialists with diverse identities)
- **IAAE Governance** (creation limits, depth caps, budget enforcement, welfare monitoring)
- **Multi-Agent Orchestrator** (Phase 63 foundation: decompose → delegate → execute → synthesize)

The Team Management module already has 6 tabs (Roster, Stations, Work Queue, HR, IAAE, Performance) with 15s polling and Chart.js visualizations.

**What's missing:** Real-time activity visibility, expandable agent details, and multi-agent execution history UI.

## Architecture

3 features added to the existing Team Management module (`team_management.html`):

| Feature | Tab | What |
|---------|-----|------|
| Mission Control | New tab (first position) | SSE-powered live agent activity feed + fleet status + metrics |
| Enhanced Roster | Existing roster tab | Expandable agent cards with details drawer |
| Multi-Agent Log | New tab | Historical view of multi-agent decompose/delegate/synthesize sessions |

Plus:
- 1 SSE endpoint (`GET /api/dispatch/stream`) in bridge routes
- 1 migration (`110_agent_activity_events.sql`) for SSE event backing store
- 3 new API endpoints for agent detail data
- Chat tab gets a small activity badge in the status bar

## Component 1: Mission Control Tab

### Layout
Top-to-bottom sections:

**Fleet Status Bar** — Horizontal row of mini-cards, one per active agent. Each shows avatar emoji, agent name (truncated), status dot:
- Green = idle (available)
- Amber = executing (running a task)
- Red = error (last execution failed)
- Gray = resting (in lounge)

Updates via SSE `agent_status` events.

**Live Activity Feed** (left, 60%) — Vertical scrolling feed, newest at top. Each event card shows:
- Timestamp (relative: "2s ago", "1m ago")
- Agent name + avatar
- Action type badge: executing (blue), completed (green), error (red), welfare (plum)
- Task snippet (first 80 chars)
- Model used + duration (for completed events)
- Max 50 visible events, older events slide out

New events animate in from top with a subtle slide-down.

**Fleet Metrics Panel** (right, 40%) — Metric cards:
- Active agents: count / total with progress ring
- Tasks this hour: count + avg duration
- Error rate: percentage with color coding
- GPU model: currently loaded Ollama model name
- Top agent: most tasks today with count

### SSE Endpoint

`GET /api/dispatch/stream` — Server-Sent Events endpoint.

**Event types:**
- `agent_status` — Agent state change (idle, executing, error, resting)
- `task_start` — Orchestration begins (agent_id, task_type, model)
- `task_complete` — Orchestration finishes (agent_id, duration_ms, success)
- `task_error` — Execution failed (agent_id, error summary)
- `welfare_event` — Agent welfare intervention (agent_id, type, action)
- `metrics` — Periodic fleet metrics update (every 30s)

**Implementation:**
- In-memory event queue: `collections.deque(maxlen=200)` in bridge routes
- Events pushed via `push_agent_event()` function, called from:
  - `orchestration_engine.py` — on execute start/complete/error
  - `agent_delegation.py` — on agent selection
- SSE generator yields events with 30s heartbeat keepalive
- Backed by `agent_activity_events` table for page-load history (last 50 events)

### Data Sources
- `agent_executions` — recent execution history
- `agent_emotional_state` — current mood per agent
- `orchestration_sessions` / `orchestration_steps` — pipeline run data
- `agents` — roster with status

## Component 2: Enhanced Agent Roster

### Expandable Agent Cards

Click an agent card → details drawer expands below it (accordion, one at a time).

**Drawer sections:**

1. **Profile** — Full name (display_name), title, department, bio, model, tier, worker_type badge. Status toggle button (active ↔ lounge). Station assignment dropdown (current station highlighted).

2. **Stats Row** — 5 inline metrics: Tasks today, Avg duration (ms), Error rate (%), Tokens used today, Budget remaining (tokens or "unlimited").

3. **Emotional State** — Current mood as text + emoji, stress bar (0-1 scale, color-coded), energy bar (0-1 scale). Last rest cycle timestamp. Data from `agent_emotional_state` table.

4. **Recent Executions** — Table of last 10 executions: timestamp, task snippet (60 chars), model, duration, status badge (success/failed/in_progress), cost.

5. **Quick Actions** — Button row:
   - Assign to Station (dropdown)
   - Send to Lounge / Return from Lounge
   - View All Executions (scrolls to Performance tab with agent filter)

### New Endpoints
- `GET /api/agents/<id>/executions?limit=10` — Recent execution history
- `GET /api/agents/<id>/emotional-state` — Current emotional state + last rest cycle

## Component 3: Multi-Agent Execution Log

### Layout
Split panel:

**Session List** (left, 30%) — Reverse-chronological list of multi-agent orchestration sessions. Each item shows:
- Timestamp
- Task summary (first 60 chars of original message)
- Agent count badge (e.g., "3 agents")
- Status: completed (green), in_progress (amber), failed (red)

Click to select → shows detail on right.

**Session Detail** (right, 70%) — Selected session breakdown:

1. **Original Task** — Full user message that triggered multi-agent orchestration.

2. **Decomposition** — How the task was split. Shows each sub-task with index, description, assigned agent, assigned station.

3. **Agent Contributions** — Collapsible panels per agent:
   - Header: agent name + avatar, model used, duration, status
   - Body: their sub-task description + response text

4. **Synthesized Output** — The final combined response that was shown to the user.

### Data Sources
- `orchestration_sessions` WHERE total_steps > 3 (multi-step = likely multi-agent)
- `orchestration_steps` filtered by session — step_type IN ('decompose', 'delegate', 'synthesize')
- `delegation_tasks` — per-agent sub-task assignments and responses

### New Endpoint
- `GET /api/dispatch/multi-agent-sessions?page=1&per_page=20` — Paginated multi-agent session list
- `GET /api/dispatch/multi-agent-sessions/<session_id>` — Full session detail with steps and delegation tasks

## Component 4: Chat Activity Badge

In `archie_chat.html` status bar (`.status-right`), add a small indicator:
- Pulsing dot (green if agents active, gray if idle)
- Count of currently executing agents
- Click → opens Team Management in new tab at Mission Control
- Polls `/tools/bridge/api/dispatch/work-queue` every 30s (reuses existing endpoint)

## Migration

`database/migrations/110_agent_activity_events.sql`:
```sql
CREATE TABLE IF NOT EXISTS agent_activity_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    agent_id INTEGER REFERENCES agents(id),
    data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_agent_activity_events_created ON agent_activity_events(created_at DESC);
CREATE INDEX idx_agent_activity_events_agent ON agent_activity_events(agent_id);

-- Auto-cleanup: events older than 24h will be pruned by agent_loop job
COMMENT ON TABLE agent_activity_events IS 'Lightweight event store for SSE streaming. Auto-pruned to 24h.';
```

## Error Handling

- SSE connection drop → EventSource auto-reconnect (browser-native)
- SSE unsupported (rare) → fallback to 15s polling
- Empty multi-agent log → "No multi-agent sessions yet" placeholder
- Agent detail fetch fails → show stale card with "Last updated X ago"
- Emotional state missing → show "No data" with muted text

## Not Included (YAGNI)

- No drag-and-drop station assignment (dropdowns sufficient)
- No real-time chat between agents (agents don't converse)
- No agent creation from Team Management (use chat or Bridge module)
- No custom agent avatars/profile pictures
- No per-agent chat history viewer (use main chat)
- No live streaming of agent responses during execution
- No WebSocket (SSE is simpler and sufficient for server→client)

## Key Files

- Modify: `platform_v2/templates/tools/team_management.html` (Mission Control tab, enhanced roster, multi-agent log)
- Modify: `platform_v2/tools/bridge/routes.py` (SSE endpoint, agent detail endpoints, multi-agent session endpoints)
- Modify: `platform_v2/templates/tools/archie_chat.html` (activity badge)
- Modify: `ai_bridge/orchestration_engine.py` (push events to activity queue)
- Create: `database/migrations/110_agent_activity_events.sql`
