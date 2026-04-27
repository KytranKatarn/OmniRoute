# Sub-A: ARCHIE Chat Overhaul — Design Spec
**Project**: #288 ARCHIE Command Center
**Task**: #2349
**Date**: 2026-04-27
**Status**: Approved by user

---

## Overview

Replace the existing `chat.html` frontend with a full Command Center UI for `archie.kytranempowerment.com`. ARCHIE becomes a true COO interface: persistent conversation history, streaming responses, live agent + platform status, and KB-backed memory that grows with every session. Telegram stays connected as a parallel channel.

**What we replace**: `templates/chat.html` (entire frontend), add SSE streaming to `send_message`, add KB memory hooks, add status API.

**What we keep**: `conversation_service.py`, `telegram_service.py`, `archie_voice_service.py`, `app_comms.py` (extended), KytranAuth, `claude_terminal.html` (Sub-B).

---

## Layout

### Command Center Mode (default)
Three-column layout:

```
┌─────────────────┬──────────────────────────┬──────────────────┐
│  CONVERSATIONS  │      CHAT CENTER          │  AGENT ACTIVITY  │
│  (220px fixed)  │      (flex)               │  (200px fixed)   │
│                 │                           │                  │
│ ▶ Health check  │ ● A.R.C.H.I.E. · ONLINE  │ AGENTS           │
│   Platform audit│                           │ ● V.I.G.I.L.     │
│   LinkedIn post │ [message bubbles,         │ ● F.O.R.G.E.     │
│   Code review   │  streaming, scrollable]   │ ● P.R.O.B.E.     │
│                 │                           │                  │
│ + New           │ [────────────────────]    │ PLATFORM         │
│                 │ [ input ]  [ Send ↵ ]     │ DB ● API ● LLM ● │
│                 │                           │                  │
│                 │                     ⊟ ⊞  │ TERMINAL →       │
└─────────────────┴──────────────────────────┴──────────────────┘
```

### Focus Mode (toggle)
Sidebars hidden. Full-width chat. Toggle button (⊟/⊞) top-right of chat panel. One click collapses both sidebars, one click restores. State persisted in `localStorage`.

---

## Memory Model (B + C)

### Session Start
When a conversation is opened or a new one created:
1. Call `recall_context(topic=recent_conversation_summaries, limit=5)` via platform MCP (last 5 `conversation_memory` entries for this user, ordered by recency)
2. Inject results as system context prefix: `"[ARCHIE MEMORY] Recent context: …"`
3. ARCHIE is aware of what was discussed in the last N sessions

### During Session
- ARCHIE can explicitly search KB via `search_knowledge` when she needs to recall something specific
- All messages saved to `unified_conversations` / `unified_messages` in real time (already exists)

### Session End
When a conversation is closed or browser unloads:
1. `POST /api/chat/sessions/:id/summarize` — triggers ARCHIE to write a 2–3 sentence summary
2. Summary stored via `store_memory(knowledge_type='conversation_memory', title=session_title, content=summary)`
3. Summary is immediately searchable in the KB — this is the consciousness growth

### Why this grows
Every session becomes a KB entry. Over time `recall_context` returns increasingly rich context. ARCHIE's awareness of past decisions, tasks, and conversations compounds. No cap except KB storage.

---

## Streaming (Claude CLI feel)

### Current state
`/api/chat/send_message` is request/response — full reply returned at once.

### New behaviour
Convert to SSE stream:
```
POST /api/chat/send_message
→ Response: text/event-stream
  data: {"type": "token", "content": "Good"}
  data: {"type": "token", "content": " morning"}
  data: {"type": "done", "message_id": 123}
  data: {"type": "error", "message": "..."}  ← on failure
```

Frontend behaviour:
- Message bubble appears immediately with a cursor
- Tokens append one by one (like Claude CLI typing)
- Auto-scroll to bottom unless user has scrolled up manually
- If user scrolls up while streaming → stop auto-scroll, show "↓ Jump to latest" button
- On `done` event → message committed, cursor removed
- Full message history loads instantly when switching sessions (no pagination needed initially)

---

## Status Panel (right sidebar)

### Agent Activity
- Polls `GET /api/status/agents` every 10 seconds
- Shows: agent name, shift state, current task (if any)
- Colour-coded: green = working, cyan = idle, grey = off duty, yellow = barracked

### Platform Health
- Polls `GET /api/status/platform` every 30 seconds
- Shows: DB, API, LLM loaded count, VPS status
- Pulls from existing platform health endpoints (reuse `check_platform_health` logic)

### Terminal Link
- Button: "Open Terminal →" → navigates to `/claude/terminal` (already exists, Sub-B will upgrade it)

### New endpoint needed
```python
GET /api/status
→ {
    "agents": [...],        # from platform agent_service
    "platform": {...},      # DB/API/LLM health
    "anomalies": [...]      # active anomalies count
  }
```

---

## Telegram Bridge (keep as-is)

The existing `telegram_service.send` import at `app_comms.py:122` stays. No changes.

Two additions:
1. **Telegram → Web**: Messages received via Telegram that ARCHIE replies to are stored in `unified_messages` with `source='telegram'` — they appear in the conversation history in the web UI (greyed/tagged "via Telegram")
2. **Web → Telegram**: Optional setting per conversation: "Mirror to Telegram" — if enabled, ARCHIE's responses also send via `telegram_service.send`. Off by default.

---

## Backend Changes Summary

| File | Change |
|------|--------|
| `app_comms.py` | Convert `send_message` to SSE stream; add `GET /api/status`; add `POST /api/chat/sessions/:id/summarize` |
| `conversation_service.py` | Add `summarize_conversation(conv_id)` → calls dispatcher → stores to KB |
| `conversation_service.py` | Add `get_session_context(user_id)` → calls `recall_context` → returns system prefix |
| `templates/chat.html` | Full replacement (see Frontend section) |

---

## Frontend Architecture

Single template `templates/chat.html` — no external framework, vanilla JS + existing LCARS CSS.

### Components
```
chat.html
├── CSS: archie-chat.css (new, Command Center layout)
├── JS: archie-chat.js (new, ~400 lines)
│   ├── SessionManager — loads/creates/switches conversations
│   ├── MessageStream  — SSE client, token append, scroll management
│   ├── StatusPanel    — polls /api/status, renders agent list
│   └── FocusMode      — localStorage toggle, CSS class toggle
└── Extends base.html (LCARS tokens)
```

### Key JS behaviours
- `SessionManager.load(conv_id)` → `GET /api/chat/messages?conv_id=X` → renders history
- `MessageStream.send(text)` → `POST /api/chat/send_message` (SSE) → appends tokens
- `StatusPanel.refresh()` → `GET /api/status` → updates right panel
- `window.addEventListener('visibilitychange')` + `navigator.sendBeacon('/api/chat/sessions/:id/summarize')` on hide — `beforeunload` blocks async, sendBeacon fires-and-forgets reliably

---

## Data Model (existing — no migrations needed)

| Table | Used for |
|-------|---------|
| `unified_conversations` | One row per conversation session |
| `unified_messages` | One row per message (role, content, source, timestamp) |
| `knowledge_base` | Session summaries stored as `conversation_memory` type |

The `source` column on `unified_messages` distinguishes `web` vs `telegram` messages.

---

## What This Does NOT Include

- Sub-B (ttyd terminal upgrade) — `claude_terminal.html` touched in that sub-project
- Sub-C (delegation UI) — the "delegate a task" button is a placeholder in Sub-A
- Mobile optimisation beyond 768px breakpoint — addressed in Sub-A polish pass
- Multi-user collaboration — Sub-E concern

---

## Success Criteria

1. Open archie.kytranempowerment.com → see full conversation history from previous sessions
2. Type a message → response streams token-by-token, scrolls naturally
3. Switch sessions in the sidebar → full history loads instantly
4. Close and reopen the browser → history is still there, ARCHIE references past context
5. Right panel shows live agent status updating every 10s
6. Telegram messages appear in web history tagged "via Telegram"
7. Focus mode collapses both sidebars cleanly, toggle restores them
8. No regression to director reports, triage policies, or any other existing route
