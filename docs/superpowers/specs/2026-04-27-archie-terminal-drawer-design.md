# Sub-B: Terminal Slide-over Drawer — Design Spec
**Project**: #288 ARCHIE Command Center
**Task**: #2350
**Date**: 2026-04-27
**Status**: Approved by user

---

## Overview

Embed the existing ttyd Claude Code terminal into `archie.kytranempowerment.com` as a
slide-over drawer panel. ARCHIE reads terminal output automatically and injects it into
every chat response while the drawer is open — no extra toggle needed.

**Nothing new to install.** ttyd is already live on port 17681 (`tmux attach-session -t
claude-code`, matrix green theme), and a Python auth proxy is already running on port 7682.

---

## Layout & UX

### Drawer behaviour
- Triggered by "Open Terminal →" button in the Command Center right panel
- Slides in from the right, covering 65% of viewport width
- Semi-transparent dark overlay dims the Command Center behind it
- Close: X button in drawer header, Escape key, or clicking the overlay
- Command Center stays mounted behind — chat history and status panel remain in DOM

### Drawer structure
```
┌──────────────────────────────────────────────┐
│  CLAUDE CODE TERMINAL   ● connected      [✕] │  ← header (35px)
│──────────────────────────────────────────────│
│                                              │
│  <iframe src="/api/terminal/proxy">          │  ← ttyd iframe (flex 1)
│   $ claude /mnt/archie_brain                 │
│   ▶ Claude Code active                       │
│   What can I help with?                      │
│   $ _                                        │
│                                              │
└──────────────────────────────────────────────┘
```

### CSS classes (new)
- `.ac-terminal-overlay` — fixed full-screen dim behind drawer
- `.ac-terminal-drawer` — fixed right-side panel, transform: translateX(100%) when closed
- `.ac-terminal-drawer.open` — transform: translateX(0), transition 0.25s ease
- `.ac-terminal-header` — flex row, status dot, title, close button
- `.ac-terminal-iframe` — 100% width/height, border: none

---

## ARCHIE Awareness

### Snapshot endpoint
New route in `app_comms.py`:

```
GET /api/terminal/snapshot   (auth required)
→ { "lines": ["$ claude ...", "▶ ...", ...], "session": "claude-code", "captured_at": "..." }
```

Implementation: `subprocess.run(["tmux", "capture-pane", "-p", "-t", "claude-code", "-J"],
capture_output=True, text=True)` — returns last 50 lines. Returns `{"lines": []}` if tmux
session not found (graceful degradation).

### Frontend polling
`TerminalDrawer` polls `/api/terminal/snapshot` every 5 seconds while drawer is open.
Stores the last snapshot in `this._lastSnapshot`. Polling stops when drawer closes.

### Chat integration
`doSend()` in `archie-chat.js` passes `terminal_context` to `POST /api/chat/send_message`
when the terminal drawer is open and a snapshot exists:

```js
body: JSON.stringify({
  message,
  conversation_id: this.currentConvId,
  terminal_context: terminalDrawer.isOpen() ? terminalDrawer.getSnapshot() : null,
})
```

`stream_send_message()` in `conversation_service.py` injects terminal context into the
system prompt prefix when `terminal_context` is provided:

```
[TERMINAL CONTEXT] Last 50 lines from claude-code session:
<lines>

You can reference this terminal state in your response.
```

If `terminal_context` is null or empty, nothing is injected — terminal-unaware chat is
unchanged.

---

## ttyd Proxy Route

The iframe source is a new route `GET /api/terminal/proxy` (auth-required) that proxies
requests to the ttyd auth proxy (port 7682). This keeps ttyd behind archie_comms auth
and avoids CORS issues with direct iframe src to port 17681/7682.

**During implementation:** read `scripts/ttyd_auth_proxy.py` to confirm port 7682 is
the correct auth-protected endpoint. If it already handles cookie auth from archie_comms
sessions, direct iframe to `http://192.168.1.200:7682` may be sufficient without a proxy
route. Pick the simpler path after reading the proxy code.

---

## `/claude/terminal` Standalone Route

Add `GET /claude/terminal` to `app_comms.py` (auth-required) rendering `claude_terminal.html`.
This gives a full-page terminal at `/claude/terminal` for users who navigate there directly
(e.g., from a bookmark or the "Open Terminal" link in the existing LCARS nav).

Update `claude_terminal.html` iframe src to point to the ttyd endpoint (same determination
as above — 7682 or proxy route).

---

## Components Touched

| File | Change |
|------|--------|
| `archie-comms/app_comms.py` | Add `GET /claude/terminal`; `GET /api/terminal/snapshot`; `GET /api/terminal/proxy` (or direct ttyd); modify `POST /api/chat/send_message` to accept `terminal_context` |
| `archie-comms/services/conversation_service.py` | Modify `stream_send_message(user_id, message, ..., terminal_context=None)` to inject context into system prompt |
| `archie-comms/templates/chat.html` | Add drawer HTML (overlay + panel + iframe + header) |
| `archie-comms/templates/claude_terminal.html` | Wire iframe src to ttyd; add status indicator |
| `archie-comms/static/css/archie-chat.css` | `.ac-terminal-overlay`, `.ac-terminal-drawer`, `.ac-terminal-drawer.open`, `.ac-terminal-header`, `.ac-terminal-iframe` |
| `archie-comms/static/js/archie-chat.js` | `TerminalDrawer` class; modify `doSend` |

---

## What This Does NOT Include

- Sub-C (ARCHIE delegation in chat) — the delegation button in the chat input is a separate sub-project
- ARCHIE proactively commenting on terminal errors without being asked — she responds to terminal context when you message her, but does not interrupt unprompted (Sub-C territory)
- Multi-user collaboration view on the terminal
- Mobile: terminal drawer is desktop-only (hidden at ≤768px via `display:none` on `.ac-terminal-drawer` and the trigger button)

---

## Success Criteria

1. "Open Terminal →" button opens the drawer without navigating away from chat
2. Drawer slides in smoothly, Command Center visible but dimmed behind
3. ttyd iframe shows the live `claude-code` tmux session
4. Escape or clicking overlay closes the drawer
5. Sending a message to ARCHIE while drawer is open — her reply references terminal state
6. Sending a message with drawer closed — no terminal context injected
7. `/claude/terminal` standalone page still works for direct navigation
8. No regression to Sub-A chat features (streaming, session list, status panel)
