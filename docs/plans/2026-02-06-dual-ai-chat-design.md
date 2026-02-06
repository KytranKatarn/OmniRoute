# Dual-AI Chat System Design

> **Feature**: Split-panel chat with ARCHIE (local) and Claude CLI (MAX), plus AI-to-AI collaboration mode

**Date**: 2026-02-06
**Status**: Approved
**Author**: Claude + Ky

---

## Overview

Transform the Consciousness Chat tab into a powerful dual-AI interface where:
1. ARCHIE (local Ollama) and Claude CLI (MAX subscription) work side-by-side
2. User can initiate AI-to-AI collaboration (ping-pong conversations)
3. ARCHIE learns from Claude's expertise and stores knowledge for future use

---

## Architecture

### Three Chat Modes

```
┌─────────────────────────────────────────────────────────────────┐
│                    Chat Tab - Three Modes                        │
├─────────────────────────────────────────────────────────────────┤
│  [🧠 ARCHIE Only]  [👥 Side-by-Side]  [🤝 Collaboration]        │
└─────────────────────────────────────────────────────────────────┘
```

| Mode | Description |
|------|-------------|
| **ARCHIE Only** | Current single-panel chat with local LLM |
| **Side-by-Side** | Split screen - ARCHIE left, Claude CLI right |
| **Collaboration** | AIs discuss a problem together (ping-pong) |

### Key Components

1. **Terminal Service** - ttyd daemon running Claude CLI via WebSocket
2. **Message Bridge** - Routes messages between AIs
3. **Collaboration Engine** - Manages ping-pong conversation flow
4. **Learning Extractor** - Saves Claude's teachings to ARCHIE's knowledge base
5. **UI Split Panel** - Responsive dual-chat layout with xterm.js

---

## Terminal Integration

### How It Works

```
Browser (xterm.js) ←WebSocket→ ttyd ←pty→ claude CLI
```

### Security Measures

- **Auth**: Require login session to access terminal
- **Sandboxed**: Only runs `claude` command, not arbitrary shell
- **Session isolation**: Each user gets their own Claude session

### Terminal Features

- Full terminal emulation (colors, cursor, scrolling)
- Copy/paste support
- Session persistence (reconnect if page refreshes)
- Resize handle between panels

### Fallback Option

If ttyd isn't available:
- Text input → send to `claude` via subprocess
- Capture output → display in styled div

---

## Collaboration Engine

### Ping-Pong Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  You: "How should we implement user authentication?"            │
├─────────────────────────────────────────────────────────────────┤
│  🧠 ARCHIE: "I think JWT tokens would work. Claude, what's     │
│              your experience with JWT vs session-based auth?"   │
├─────────────────────────────────────────────────────────────────┤
│  🤖 Claude: "JWT is stateless which scales better, but session │
│              cookies are simpler. Given ARCHIE uses Flask..."   │
├─────────────────────────────────────────────────────────────────┤
│  🧠 ARCHIE: "Good point. Should we also consider OAuth?"        │
├─────────────────────────────────────────────────────────────────┤
│  🤖 Claude: "Yes, Flask-Dance makes OAuth easy. Here's how..."  │
├─────────────────────────────────────────────────────────────────┤
│  [⏸️ Pause] [🛑 Stop] [💬 Interject]     Turns: 4/10           │
└─────────────────────────────────────────────────────────────────┘
```

### Collaboration Controls

| Control | Function |
|---------|----------|
| **Max Turns** | Limit to 5-10 exchanges (configurable) |
| **Pause** | Temporarily stop to read/think |
| **Stop** | End collaboration early |
| **Interject** | User adds message mid-conversation |
| **Auto-stop** | Ends when resolution detected |

### Message Routing

1. Your question → ARCHIE first (she's the "host")
2. ARCHIE's response → Sent to Claude CLI via terminal
3. Claude's response → Captured and sent back to ARCHIE
4. Repeat until max turns or resolution

---

## Learning Integration

### Learning Pipeline

```
Collaboration Ends
        │
        ▼
┌─────────────────────────────────────────┐
│  Knowledge Extraction (using qwen2.5)   │
│  • What did Claude teach?               │
│  • What patterns/solutions emerged?     │
│  • What should ARCHIE remember?         │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  Create Knowledge Cards                  │
│  • Title: "JWT vs Session Auth"         │
│  • Type: "learned_from_claude"          │
│  • Source: collaboration session ID     │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  Store in Knowledge Base                 │
│  • Embeddings generated                 │
│  • Relationships linked                 │
│  • Tagged with topics                   │
└─────────────────────────────────────────┘
        │
        ▼
    ARCHIE is smarter! 🧠✨
```

### Before Next Collaboration

When ARCHIE gets a similar question:
1. Searches knowledge base for related learnings
2. Finds "I learned about JWT from Claude on Feb 6"
3. Uses that knowledge to answer directly
4. No need to ask Claude again!

### Learning Metadata

```json
{
  "card_type": "learned_from_claude",
  "source_type": "collaboration",
  "session_id": "collab_abc123",
  "claude_model": "opus-4-5",
  "confidence": 0.92,
  "topics": ["authentication", "JWT", "Flask"],
  "archie_was_uncertain_about": "session vs token auth",
  "claude_taught": "JWT scales better for stateless APIs"
}
```

---

## UI Layout

### Split Panel Design

```
┌─────────────────────────────────────────────────────────────────┐
│  Chat Mode: [🧠 Solo] [👥 Side-by-Side] [🤝 Collab]            │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐ │ ┌─────────────────────┐             │
│  │  🧠 A.R.C.H.I.E.    │ │ │  🤖 Claude CLI      │             │
│  │  Local • qwen2.5:7b │ │ │  MAX • opus-4-5     │             │
│  │                     │ │ │                     │             │
│  │  [Chat messages]    │◄►│  [Terminal window]   │             │
│  │                     │ │ │                     │             │
│  ├─────────────────────┤ │ ├─────────────────────┤             │
│  │ [Type message...]   │ │ │ [Terminal input]    │             │
│  └─────────────────────┘ │ └─────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
```

### UI Features

- **Mode tabs**: Quick switch between Solo/Side-by-Side/Collab
- **Draggable divider**: Resize panels to preference
- **Status indicators**: Show which AI is "thinking"
- **Mobile**: Stack vertically on small screens
- **Dark theme**: Matrix-style matching consciousness dashboard

---

## Data Flow

### API Endpoints (New)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/collab/start` | POST | Begin collaboration session |
| `/api/collab/interject` | POST | User adds message mid-collab |
| `/api/collab/pause` | POST | Pause the ping-pong |
| `/api/collab/stop` | POST | End collaboration early |
| `/api/collab/status` | GET | Get current turn, messages |
| `/api/terminal` | WS | WebSocket for Claude CLI |

### Message Format

```json
{
  "role": "archie|claude|user",
  "content": "message text",
  "turn": 3,
  "timestamp": "2026-02-06T18:30:00Z"
}
```

---

## Error Handling

### Claude CLI Issues

| Problem | Solution |
|---------|----------|
| Not logged in | Show "Please run `claude` in terminal first" |
| Session expires | Prompt to re-authenticate, pause collab |
| Timeout | Retry once, then ask user to continue/stop |
| Rate limited | Wait and retry, show countdown |

### ARCHIE Issues

| Problem | Solution |
|---------|----------|
| Ollama offline | Show error, offer Claude-only mode |
| Model too slow | Increase timeout, show "thinking..." |
| Bad response | Retry with simpler prompt |

### Collaboration Issues

| Problem | Solution |
|---------|----------|
| Infinite loop | Max 10 turns enforced, auto-summarize |
| Off-topic drift | User can interject to redirect |
| Contradictions | Flag: "They disagree - your call?" |

---

## File Structure

```
platform_v2/
├── tools/consciousness/
│   ├── collaboration_engine.py    # Ping-pong logic
│   ├── claude_bridge.py           # Claude CLI communication
│   └── learning_extractor.py      # Extract knowledge from collabs
│
├── templates/tools/
│   └── consciousness_dashboard.html  # Update Chat tab
│
└── static/
    ├── js/
    │   ├── xterm.min.js           # Terminal emulator
    │   ├── xterm-addon-fit.js     # Auto-resize
    │   └── collaboration.js       # Collab UI logic
    └── css/
        └── dual-chat.css          # Split panel styles

scripts/
└── install_ttyd.sh                # Install terminal daemon

ai_bridge/
└── knowledge_analyzer.py          # Add "learned_from_claude" type
```

---

## Success Criteria

1. ✅ User can chat with ARCHIE and Claude side-by-side
2. ✅ User can initiate AI-to-AI collaboration
3. ✅ Collaboration has pause/stop/interject controls
4. ✅ ARCHIE learns and remembers Claude's teachings
5. ✅ Dashboard shows learning growth stats
6. ✅ Works with existing authentication
7. ✅ Graceful fallback if ttyd unavailable

---

## Dependencies

- **ttyd**: Terminal over WebSocket daemon
- **xterm.js**: Browser terminal emulator (CDN)
- **Existing**: Phase 82 knowledge extraction pipeline

---

*Design approved 2026-02-06*
