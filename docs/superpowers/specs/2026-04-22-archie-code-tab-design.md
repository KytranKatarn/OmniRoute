# A.R.C.H.I.E. Code Tab — Design Spec
**Date**: 2026-04-22 | **Status**: Approved | **Project**: Unified Voice #277

---

## Overview

A dedicated "Code" tab added to the existing `archie_chat` module at `/tools/archie-chat`. This is A.R.C.H.I.E.'s own coding workspace — where she executes Repair Bay proposals, manages herself, and accepts user-directed coding sessions. It is not a replacement for Claude Code; it is a collaboration surface where OpenCode CLI, A.R.C.H.I.E., and F.O.R.G.E. coordinate on platform development.

---

## 1. Module Structure

No new module or blueprint. Everything extends `archie_chat`.

### New files
```
platform_v2/tools/archie_chat/
  code_service.py       — OpenCode process lifecycle, session management, Repair Bay integration
  code_routes.py        — HTTP + WebSocket routes, registered via register_code_routes(bp)
```

### Modified files
```
  routes.py                       — import + call register_code_routes(bp)
  templates/archie_chat.html      — add Code tab alongside COMMS, COMs, Settings
```

### New migration
```
database/migrations/NNN_code_sessions.sql
  — code_sessions table
  — code_session_events table
```

---

## 2. Data Model

### `code_sessions`
```sql
id               SERIAL PRIMARY KEY
title            TEXT NOT NULL
source           TEXT NOT NULL CHECK (source IN ('user', 'repair_bay', 'archie_auto'))
status           TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'paused', 'completed', 'failed'))
tier             INTEGER NOT NULL CHECK (tier IN (1, 2))
project_id       INTEGER REFERENCES unified_projects(id)
proposal_id      INTEGER                          -- FK to improvement_proposals (nullable)
conversation_id  INTEGER                          -- FK to conversations if spawned from chat (nullable)
opencode_pid     INTEGER                          -- NULL when not running
created_by       TEXT NOT NULL CHECK (created_by IN ('archie', 'user'))
created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
completed_at     TIMESTAMPTZ
result_branch    TEXT                             -- git branch created on completion
result_pr_url    TEXT                             -- filled for Tier 1 auto-PR
```

### `code_session_events`
```sql
id               SERIAL PRIMARY KEY
session_id       INTEGER NOT NULL REFERENCES code_sessions(id) ON DELETE CASCADE
event_type       TEXT NOT NULL
                 CHECK (event_type IN ('message','diff','file_change','summary','terminal_raw','error'))
content          JSONB NOT NULL
created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Tier assignment
| Proposal severity | Default tier |
|---|---|
| critical / high | 2 — human review |
| medium | 2 — human review |
| low | 1 — auto-PR |

Tier can be manually overridden per session before execution begins.

---

## 3. UI Layout

Three-column layout inside the Code tab:

### Left — Session Browser (200px)
- Three view toggles: **SOURCE** | **PROJECT** | **STATUS**
- Sessions grouped by active view (source groups: Repair Bay / Manual / ARCHIE Auto)
- Each session card: status pill (● ACTIVE / ⏸ PAUSED / ✓ DONE), title, tier + origin label
- **+ New Session** button at bottom
- Switching sessions never loses history — events are persisted to DB

### Center — Session Feed (flex: 1)
- Session header bar: status, title, tier badge, Repair Bay proposal link
- Hybrid output stream: structured event cards by default
  - `message` — ARCHIE conversational updates
  - `diff` — inline before/after diff view
  - `file_change` — file path + summary
  - `summary` — completion summary card
  - `error` — error with context
- **RAW toggle** (bottom bar): switches center to xterm.js terminal, same subprocess, stdin/stdout piped directly. Toggle back restores structured view with full history intact.
- Input bar: free-text message to ARCHIE or code instruction

### Right — Context Panel (160px)
- Project, proposal link, tier, files changed, dispatched agent
- **Abort** button (SIGTERM to OpenCode subprocess, status → paused)
- **→ Repair Bay** button (navigate to the linked proposal)

---

## 4. Repair Bay Integration

### Proposal → Session (inbound)
```
improvement_proposals created (severity determines tier)
    ↓
repair_bay's proposal_service.py calls code_service.create_session_from_proposal(proposal_id)
    ↓
code_sessions row inserted (source='repair_bay', tier set from severity)
    ↓
Code tab sidebar updates via WebSocket push
    ↓
ARCHIE notified via telegram_service.send_info()
    ↓
OpenCode subprocess spawned, F.O.R.G.E. dispatched via Bridge for planning
```

### Session → Result (outbound)
```
code_service.finalize_session(session_id)
    ↓
Tier 1 (low-risk):
    git branch auto-created
    PR opened via `gh pr create` (existing pattern used by Repair Bay)
    improvement_proposals.status = 'auto_merged'
    Repair Bay notified — no human action required

Tier 2 (high-risk):
    improvement_proposals.status = 'fix_ready'
    Repair Bay proposal card shows "Fix Ready — review in Code tab"
    User approves in Repair Bay → triggers existing Ship step → deploy
```

---

## 5. OpenCode Process Model

### Subprocess lifecycle
```python
# code_service.py

def start_session(session_id: int) -> int:
    # spawn opencode --json --no-interactive  (verify exact flags against OpenCode docs before impl)
    # returns PID, stores in code_sessions.opencode_pid
    # stdout piped → parse JSON events → insert code_session_events
    # WebSocket pushes each event to browser

def resume_session(session_id: int):
    # check PID alive → reconnect pipe
    # if dead → respawn, replay last 50 events as context window

def terminate_session(session_id: int, final_status: str):
    # SIGTERM to PID
    # opencode_pid = NULL, status = final_status
```

### Structured mode (default)
- OpenCode runs with `--json` flag
- Each stdout line parsed as a JSON event
- `event_type` mapped from OpenCode event schema → `code_session_events`
- Browser receives structured cards via WebSocket

### RAW mode (toggle)
- Same subprocess, no JSON parsing
- stdout → xterm.js via WebSocket (raw bytes)
- stdin from xterm.js → subprocess stdin
- Toggling back to structured: stops raw pipe, resumes JSON parsing, history intact

### Working directory
```
/mnt/archie_brain/   — full platform repo, same as Claude Code
```

### Agent coordination
```
A.R.C.H.I.E. orchestrates:
  1. Bridge → F.O.R.G.E. (planning + reasoning slice)
  2. F.O.R.G.E. plan → passed to OpenCode as initial instruction
  3. OpenCode executes file edits
  4. code_service.finalize_session() → routes result by tier
```

---

## 6. Out of Scope (this spec)

- Multi-file diff viewer beyond inline event cards (future enhancement)
- Concurrent OpenCode sessions on the same file set (serialize per-session for now)
- OpenCode running on fleet nodes (hub only for initial implementation)
- Billing / usage tracking for OpenCode compute

---

## 7. Success Criteria

- [ ] Code tab visible in archie_chat alongside COMMS
- [ ] Session browser shows Source / Project / Status views with live status
- [ ] Repair Bay proposal auto-creates a Code session
- [ ] Structured event stream renders diffs, file changes, summaries correctly
- [ ] RAW toggle switches to xterm.js and back without losing history
- [ ] Tier 1 completion auto-opens PR and updates proposal status
- [ ] Tier 2 completion sets proposal to `fix_ready`, Repair Bay reflects it
- [ ] Sessions persist across page reloads — no history lost
