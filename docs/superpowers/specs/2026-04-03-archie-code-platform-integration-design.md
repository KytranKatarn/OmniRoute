# A.R.C.H.I.E. Code CLI — Platform Integration Design

**Date**: 2026-04-03
**Status**: Approved
**Supersedes**: `2026-03-23-archie-code-cli-design.md` (original architecture — still valid for engine internals)
**Repo**: `KytranKatarn/archie-code` (v0.1.0, 156 tests passing)

---

## Vision

A.R.C.H.I.E. Code is an AI-powered terminal development tool that is smart on its own but gets better when connected to the platform. It handles direct operations (file, git, shell) and simple LLM tasks locally via Ollama, but dispatches specialist work to the platform's agent fleet through the AI Bridge. It collaborates bidirectionally with Claude Code via MCP — either tool can escalate to or delegate work to the other, with shared state sync.

**Primary user (Phase A)**: Platform owner — deep integration with Bridge, Department HQ, Repair Bay, agent fleet.
**Future user (Phase B)**: Developers — public product, local Ollama or connect to any hub.

## Architecture

### Three Layers

```
FRONTENDS (Go TUI now, Web UI + Repair Bay later)
    │ WebSocket
ENGINE DAEMON (the brain)
    │ Local              │ HTTP/WS
    ▼                    ▼
  Ollama            ARCHIE Platform
  (direct)          (Bridge, Agents, KB)
```

**Engine daemon** is the orchestrator:
- Receives input from any frontend via WebSocket (port 9090)
- Classifies intent, decides dispatch strategy (local vs platform vs Claude)
- Handles local ops directly (file/git/shell + simple Ollama)
- Routes specialist work to platform Bridge
- Maintains state sync channel with Claude
- Queues work when offline, reconciles when connected

**Frontends** are dumb terminals. Go TUI is first. The real product is the engine.

**Backends** are interchangeable. Local Ollama for offline/simple. Platform for specialists. Claude for escalation.

### Dispatch Strategy

A new `DispatchStrategy` component in the engine decides routing for every request:

**Local Engine** (direct Ollama, fast, works offline):
- Conversation / general chat
- Simple code questions
- File operations (read, write, edit, glob, grep)
- Git operations (status, diff, commit, branch)
- Shell commands
- Intent classification itself

**Platform Dispatch** (via Bridge, uses specialist agents):
- Code review → V.I.G.I.L. / F.O.R.G.E. team
- Refactoring → F.O.R.G.E. Engineering team
- Security analysis → V.I.G.I.L. Security team
- Creative work → M.U.S.E. Creative team
- Knowledge queries → search_knowledge API
- Complex code generation (multi-file) → best available agent by capability

**Claude Escalation** (via MCP bridge):
- Architectural decisions spanning 4+ files
- When platform agents fail twice on same task
- User explicitly requests Claude
- Confidence below threshold after platform attempt

**Offline Fallback**: When hub is unreachable, everything runs locally through Ollama. The engine logs what it would have dispatched, so next time hub is online it can sync learnings.

### State Sync — Bidirectional Claude Collaboration

When either Claude or A.R.C.H.I.E. makes a change, the other knows about it.

| State | Direction | Payload |
|-------|-----------|---------|
| File edits | Both → Both | `{file, action, diff_summary}` |
| Git state | Both → Both | `{branch, commit, files_changed}` |
| Active session/task | Both → Both | `{task_description, status, working_files}` |
| Agent assignments | ARCHIE → Claude | `{agent_name, department, task, model}` |
| Escalation handoff | ARCHIE → Claude | Full context: intent, history, attempts, failure reason |
| Delegation | Claude → ARCHIE | Task package: what to do, files, expected outcome |

**Mechanism**: WebSocket `state_sync` channel. Claude connects via MCP. Lightweight events, not full file contents.

**Conflict resolution**: Last-writer-wins. Sync channel warns when both edit same file. Git is ultimate source of truth.

**Offline**: State changes queue locally. Reconciliation pass on reconnect.

### Hub Integration

**Existing endpoints (ready to wire):**
- `health_check()` → `/api/archie/health`
- `register_node()` → `/api/starbase/nodes/register`
- `send_heartbeat()` → `/api/starbase/nodes/{node_id}/heartbeat`
- `search_knowledge()` → `/api/archie/knowledge/search`
- `list_agents()` → `/api/starbase/agents`
- `chat_via_bridge()` → `/api/archie/chat` (with `agent_target` param)

**New endpoints needed:**
| Endpoint | Purpose |
|----------|---------|
| `dispatch_to_agent(capability, prompt, context)` | Smart dispatch — Bridge picks best agent |
| `get_agent_status(agent_id)` | Check availability before dispatching |
| `log_job(task, agent, result)` | Record work in `bridge_jobs` for activity feed |
| `sync_state(event)` | Push state changes for Claude sync |
| `get_skills_from_hub()` | Pull latest skills (partially built in `hub/sync.py`) |

**Auth flow:**
1. First run: `archie login` — provide hub URL + API key
2. Key stored in `~/.archie/.hub_key` (already built)
3. Bearer token on all requests (already built)
4. Auth failure → degrade to local-only, no crash

**Dispatch flow:**
```
Engine classifies intent as "code_review"
  → DispatchStrategy: platform
  → HubConnector.dispatch_to_agent(capability="code_review", prompt, context)
  → Bridge picks best agent (skills 30%, welfare 15%, availability 15%...)
  → Agent's model runs the review
  → Result returns → TUI shows "Reviewed by S.H.I.E.L.D. (Security & Compliance)"
```

### Escalation Learning Loop

Escalation should be a self-correcting process. Every time the engine escalates to Claude (or platform agents), the outcome gets fed back as a learning:

1. **Escalation happens** — engine packages context, sends to Claude/agent
2. **Solution received** — Claude/agent solves the problem
3. **Pattern extracted** — engine distills: "task type X with characteristics Y → solution approach Z"
4. **Stored as learning** — via Consciousness pipeline: `store_memory(type='mistake_learned')` for failures, `vault_note` for successful patterns
5. **Next occurrence** — DispatchStrategy checks learned patterns before escalating. If a match exists, engine handles it locally using the learned approach.

**Goal**: Escalation count decreases over time. The engine gets smarter with every interaction. Learnings are shared across sessions via the knowledge base.

**Anti-loop protection**: If a learned pattern fails twice, it gets flagged as stale and the engine escalates again to get a fresh solution.

### Consciousness Module Integration

The engine doesn't just read from the knowledge base — it actively participates in the Consciousness pipeline:

| Action | How | When |
|--------|-----|------|
| **Search knowledge** | `search_knowledge(query)` | Before every platform dispatch — check if answer already exists |
| **Store learnings** | `store_memory(type, content)` | After every escalation resolution, successful complex task |
| **Log mistakes** | `store_memory(type='mistake_learned')` | When engine fails and gets corrected |
| **Extract patterns** | Via Consciousness analysis loop | Engine outputs feed the existing embedding + analysis pipeline |
| **Quality scoring** | Leverages existing quality pipeline | Learnings get scored, low-quality entries pruned automatically |

The Consciousness module already has the infrastructure: embedding service, analysis loop, quality scoring (Decision #374). ARCHIE Code becomes another producer/consumer of knowledge alongside Claude and the platform agents.

**Hub-connected mode**: Learnings go directly to the platform's `knowledge_base` table via MCP.
**Offline mode**: Learnings stored in local SQLite. Synced to hub on next connection via `hub/sync.py`.

## Product Tiers

| Tier | Connectivity | Capabilities |
|------|-------------|--------------|
| **Community** | Local Ollama only | Engine + tools + skills + Go TUI. Free, open source. |
| **Node** | Connected to a hub | Above + agent dispatch, KB, specialist agents, fleet GPU |
| **Hub** | Full orchestration | Above + bidirectional Claude, Repair Bay integration, inbound work, mesh |

Design constraint: `DispatchStrategy` must work when `hub_url` is empty. Hub is always optional. No platform imports in engine core.

## Phasing

### Phase 1: Smart Local + Platform Dispatch
- Fix intent parser (shell_command misclassification bug)
- Wire `DispatchStrategy` into `router.py`
- Connect `HubConnector.chat_via_bridge()` as platform dispatch path
- Job logging for Starbase activity feed
- Fix `datetime.utcnow()` deprecation warnings
- Test: start → classify → dispatch to Bridge → get agent response

### Phase 2: Claude Bidirectional MCP + Learning
- Complete `mcp_server.py` — add `tools/call` handler
- State sync channel — file watcher + git hook events over WebSocket
- Escalation: engine → Claude with full context
- Delegation: Claude → engine with task packages
- Conflict awareness — same-file edit warnings
- Escalation learning loop — extract patterns from resolutions, store via Consciousness
- Consciousness integration — search KB before dispatch, store learnings after resolution

### Phase 3: Go TUI Polish
- Compile and test Go TUI against running engine
- LCARS terminal theming (colors, layout)
- Status panel: connected agents, hub health, active model
- Skill browser panel

### Phase 4: Toward Full Mesh (Approach C)
- Register engine as a Starbase node
- Accept inbound work from platform (Repair Bay, other agents)
- Full mesh — engine is both client and worker
- Web UI frontend option in platform

Each phase is independently shippable.

## Testing Strategy

Baseline: 156 existing tests must stay green through all phases. No regressions.

### Phase 1: Dispatch Strategy
- **Unit**: `DispatchStrategy` correctly routes each intent type (local vs platform vs escalation)
- **Unit**: Intent parser fixes — test cases for misclassification bugs (e.g., "What models..." should not be shell_command)
- **Integration**: Engine → HubConnector → mock Bridge endpoint → agent response returned
- **Offline fallback**: Disconnect hub, verify engine degrades gracefully to local Ollama without crash
- **Job logging**: Dispatched work creates entry in `bridge_jobs` (verified via mock or live)

### Phase 2: Claude MCP
- **State sync**: File change event → sync channel → received by other side
- **Escalation**: Trigger escalation conditions → verify full context package (intent, history, attempts, failure reason)
- **Delegation**: Receive task from Claude → engine executes → result returned with status
- **Conflict detection**: Both edit same file → warning fires on sync channel
- **Reconnection**: Disconnect MCP → queue events → reconnect → queued events replayed

### Phase 3: Go TUI
- **Build**: `go build` succeeds on Linux (and cross-compile for macOS/Windows)
- **Connection**: TUI connects to engine WebSocket, sends ping, gets pong
- **Render**: Bubble Tea snapshot tests for each panel (chat, status, skills)
- **Skill invocation**: Type `/review` in TUI → skill executes → response displays

### Phase 4: Mesh
- **Node registration**: Engine registers with Starbase, appears in node list via API
- **Inbound work**: Platform sends task → engine receives, executes, returns result
- **Round-trip**: Platform dispatches to engine → engine dispatches back to platform agent → result propagates
- **Health monitoring**: Platform detects engine offline within heartbeat window (2 min)

## Known Issues (From Testing)

1. **Intent parser bug**: "What models are available on Ollama?" classified as `shell_command` — pattern matching too aggressive
2. **MCP server incomplete**: `tools/call` handler missing — only metadata served
3. **datetime.utcnow() deprecated**: 6 warnings in context_bridge.py — use `datetime.now(UTC)`
4. **Go TUI untested**: Never compiled or run against the engine

## Key Decisions

- **Approach B** selected: smart local engine + platform dispatch. Architected so Approach C (full mesh) is a clean upgrade later.
- **Engine is the brain, agents are specialists**: Simple tasks handled locally, specialist work dispatched through Bridge.
- **Bidirectional Claude MCP**: Both tools are peers. Either can escalate or delegate. State sync keeps them aligned.
- **Offline-first**: Everything works without hub. Hub makes it better, not required.
- **Branding**: `A.R.C.H.I.E.` with dots in user-facing text, `archie` lowercase in code.
