# Directory Redesign — Corporate Team Page with Live Agent Chat

**Date:** 2026-03-20
**Status:** Approved
**Tasks:** #1155, #1156 (Directory redesign + ARCHIE/Vigil as AI leadership)

---

## Overview

Redesign the employee directory as a professional corporate team page for kytranempowerment.com. Public-facing version showcases the team with photorealistic AI-generated portraits, org chart hierarchy, and branded design. Internal version adds live agent status, persistent per-user chat with agents via Bridge dispatcher, and conversation memory.

## Goals

1. Present Kytran Empowerment as a credible consulting agency with a real team
2. Give each agent individuality — unique face, personality, email, expertise
3. Enable live chat with online agents (model loaded in RAM)
4. Persistent conversation history with sliding window + pinned memories
5. Functional email addresses at @kytranempowerment.com
6. Showcase web design and AI capabilities on the public competitors page

## Architecture

### Approach: Single Module, Two Views

One `directory` module with two routes sharing the same template with conditional rendering:

- **`/directory`** — Public, no auth. Org chart, employee grid, profiles, contact info, branded headshots. No chat, no live status.
- **`/tools/directory`** — Internal, login required. Everything public has plus live status dots, "Message" button, slide-out chat panel, conversation history, pinned memories.

### API Endpoints

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /api/directory` | Public | All employees + departments + stats |
| `GET /api/directory/:id` | Public | Single employee profile |
| `GET /api/directory/org-chart` | Public | Hierarchy data |
| `GET /api/directory/status` | Required | Live roster status from Starbase |
| `POST /api/directory/chat` | Required | Send message to agent |
| `GET /api/directory/chat/:agent_id` | Required | Conversation history with agent |

### New Database Tables

**`directory_conversations`**
- `id` (PK)
- `agent_id` → `agents.id`
- `user_id` → `users.id`
- `created_at`, `updated_at`
- `message_count` (int)
- `last_message_at` (timestamp)

**`directory_messages`**
- `id` (PK)
- `conversation_id` → `directory_conversations.id`
- `sender_type` ('user' | 'agent')
- `message` (text)
- `timestamp`
- `is_pinned` (bool, default false)

**`directory_agent_memories`**
- `id` (PK)
- `agent_id` → `agents.id`
- `user_id` → `users.id`
- `memory_type` ('summary' | 'pinned')
- `content` (text)
- `created_at`

### Integration Points

- **Bridge Dispatcher**: Chat messages dispatched to agent's model via `dispatch()`. Context includes sliding window (last 10 messages) + conversation summaries + pinned memories.
- **Starbase Roster**: Status endpoint queries `get_crew_manifest()` for shift_state + model loaded status. Source of truth for online/offline.
- **Agent Loop (Async)**: After chat idle 5min: summarize conversation, extract pinned memories, store in `directory_agent_memories`. New scheduled job #47, polls every 2 minutes for idle conversations.
- **ComfyUI Portraits**: SDXL photorealistic headshots with branded navy/teal backgrounds. Stored in `agent_portraits` table + `/static/portraits/`.

### Name Derivation & Email Generation

Agent names are derived with fallback chain: `display_name` → `name` → `'Unknown'`. The `first_name`/`last_name` columns may be NULL for many agents — always use `COALESCE(first_name || ' ' || last_name, display_name, name)` for full name display.

Email addresses derived from `display_name`:
- Two-word names: `jin.park@kytranempowerment.com`
- Single names: `pixel@kytranempowerment.com`
- Generated once and stored in a new `email` column on the `agents` table (migration populates all 50)

### Org Chart Hierarchy

The org chart is defined via a new `reports_to_agent_id` column on the `agents` table (nullable FK → `agents.id`). Migration populates:
- Kytran (user account, rendered separately) at top
- ARCHIE + Vigil report to Kytran (hardcoded in template, not in DB — Kytran is a user, not an agent)
- Department heads (primary agents on each station) report to ARCHIE
- Other agents report to their station's primary agent

### Chat Rate Limiting

- **Per user**: Max 10 messages per minute per agent
- **Global**: Max 50 chat dispatches per minute across all agents
- Enforced server-side in `chat_routes.py` using in-memory counter (reset every 60s)
- Returns HTTP 429 with "Please wait before sending another message"

### Offline Agent Chat Handling

If `POST /api/directory/chat` receives a message for an agent whose model is not loaded:
- Server checks `get_crew_manifest()` before dispatching
- If agent is offline, return HTTP 503 with `{"error": "agent_offline", "message": "[Name] is currently off duty. Please try again when they are online."}`
- Do NOT call `ensure_model_ready()` — chat should not auto-load models. Loading is managed via Starbase Command.

## UI Design

### Page Flow (top to bottom)

1. **Hero Section** — "KYTRAN EMPOWERMENT / Meet Our Team" with live stats (total members, online now, departments, 24/7 availability)
2. **Org Chart** — Kytran (CEO, Human) → ARCHIE (AI Director) + Vigil (Ethics Officer) → 9 Department Heads with station colors. Clickable nodes open profiles.
3. **Search & Filters** — Text search (name, role, expertise), department dropdown, status filter (All/Online/Off Duty), grid/list toggle.
4. **Department Card Grid** — Grouped by station. Each section has station color accent bar, member count, online count. Cards show portrait, name, title, email, skill tags, status.

### Employee Cards

- Large portrait area (200px height) with branded background
- Name, title, @kytranempowerment.com email
- 2-3 skill tags
- Status footer: green "Online" + Chat button, or dimmed "Off Duty" + "Unavailable"
- Offline cards render at 65% opacity
- Green dot with glow for online, gray dot for offline

### Profile Panel (slide-out from right)

- **Portrait**: 180px rounded square with status badge overlay
- **Identity**: Name, title, station + role (Primary/Secondary/Auxiliary)
- **Status Badge**: "Online — Available" (green) or "Off Duty" (gray)
- **Contact Card**: Email, phone + extension (auto-generated x1000+id), department
- **About**: Full bio text
- **Expertise & Skills**: Colored pill tags
- **Currently Working On** (internal only): Active bridge jobs, current tasks
- **Message Button**: "Message [Name]" with "Last conversation: X days ago"

### Chat Slide-Out (internal only)

Triggered by clicking "Message" on an online agent's profile. Profile compresses to left sidebar, chat panel opens on right.

- **Chat Header**: Agent avatar, name, "Active now — Responds instantly"
- **Memory Banner**: "🧠 [Name] remembers: [pinned memories summary]" — shows conversation continuity
- **Message Area**: Teams-style bubbles. Agent messages left-aligned with avatar, user messages right-aligned. Timestamps, date separators.
- **Typing Indicator**: Three animated dots while Bridge processes response
- **History Button**: Load older messages from conversation history
- **Input Area**: Text field + send button

### Offline Profile

Same profile panel but dimmed. No chat button. Red "Chat Unavailable — [Name] is currently off duty" message.

### Status Mapping

| Starbase State | Directory Status | Visual | Chat |
|----------------|-----------------|--------|------|
| Model loaded in RAM | Online | Green dot, glow, full color | Available |
| Model exists, not loaded | Off Duty | Gray dot, 65% opacity | Unavailable |
| Barracked | Off Duty | Gray dot, 65% opacity | Unavailable |
| No model assigned | Off Duty | Gray dot, 65% opacity | Unavailable |

## Chat System — Conversation Memory

### Per-Message Flow

1. User sends message via `POST /api/directory/chat`
2. Server loads context: last 10 messages + all summaries + all pinned memories for this (agent, user) pair
3. Bridge `dispatch()` to agent's model with system prompt including agent personality + conversation context
4. Agent response stored in `directory_messages`, returned to client
5. Client renders response with typing indicator animation

### Async Memory Extraction (Agent Loop Job)

Triggered after 5 minutes of chat idle:

1. Fetch full conversation since last summary
2. Dispatch to agent's model: "Summarize this conversation in 2-3 sentences"
3. Dispatch to agent's model: "What important facts should you remember about this user?"
4. Store summary in `directory_agent_memories` (type='summary')
5. Store pinned facts in `directory_agent_memories` (type='pinned')
6. Mark conversation as summarized

### Context Assembly for Dispatch

```
System: You are [agent_name], [title] at Kytran Empowerment. [bio]
Your expertise: [capabilities]
Station: [station_name]

## What you remember about this user:
[pinned memories, most recent first]

## Previous conversation summaries:
[summaries, most recent first, max 5]

## Current conversation:
[last 10 messages]
```

## Portrait Generation

### Pipeline

1. **Agent Metadata** — Pull display_name, title, station from agents table. Map to appearance attributes.
2. **Prompt Engineering** — Professional headshot, studio lighting, dark navy-to-teal gradient background (#0d2137 → #1a1040), corporate attire, photorealistic, 1024x1024.
3. **ComfyUI Generate** — SDXL checkpoint, face-focused composition. Generate 3-5 variants per agent. Multi-GPU fan-out if available.
4. **Review + Store** — Pick best variant. Store in `agent_portraits` table + `/static/portraits/[agent_id].webp`.

### Brand Style Guide — Headshots

**Consistent across all portraits:**
- Background: dark navy-to-teal gradient (Kytran brand)
- Lighting: soft studio, slight rim light
- Framing: head + shoulders, centered
- Attire: professional / smart casual
- Expression: approachable, confident

**Individual variation:**
- Diverse ethnicities reflecting display_name origins
- Age range: 25-55 (varied across team)
- Gender: mixed, matching name/pronouns in agents table
- Subtle station color accent (tie, scarf, lapel pin, jewelry)
- Unique facial features — no two look alike

### Storage

- `agent_portraits` table (existing): `agent_id`, `canonical_image_path`, `identity_prompt`, `face_seed`, `model_used`, `approved`. Use existing schema — do NOT create new columns.
- Static files: `/static/portraits/[agent_id].webp` (optimized for web), path stored in `canonical_image_path`
- Fallback: DiceBear SVG if no portrait generated yet (existing behavior)

## Mail Server

### Phase 1 — Launch Day

- **Provider**: Hostinger email (already have the domain)
- **Setup**: Create individual mailbox per agent on kytranempowerment.com
- **DNS**: MX records → Hostinger mail servers, SPF + DKIM + DMARC for deliverability
- **Catch-all**: Forward unmatched addresses to contactus@kytranempowerment.com
- **Naming**: `firstname.lastname@kytranempowerment.com` (single names: `pixel@`, `archie@`, etc.)
- **Display on profiles**: All agents show their @kytranempowerment.com email

### Phase 2 — Future Enhancement (not in this build)

- Agent loop monitors inboxes via IMAP
- Bridge dispatches to correct agent for reply with personality
- Auto-reply with agent expertise + context
- Escalation to Kytran for sensitive/financial matters

## Responsive Design

- **Desktop (1024px+)**: 3-4 column card grid, side-by-side profile + chat panels
- **Tablet (730px)**: 2 column grid, profile panel overlays full width
- **Mobile (360px)**: 1 column grid, profile and chat are full-screen modals

## File Structure

Directory is extracted from `app.py` into a proper Blueprint module under `tools/directory/` per ADR-045.

```
platform_v2/tools/directory/
  __init__.py                       — Blueprint + register_*_routes(bp, admin_required)
  routes.py                         — Public routes (/directory, /api/directory, /api/directory/:id, /api/directory/org-chart)
  chat_routes.py                    — Auth-gated routes (/api/directory/chat, /api/directory/chat/:agent_id, /api/directory/status)
  helpers.py                        — Shared functions (name derivation, email generation, status mapping)
  templates/directory.html          — Main template (public + internal conditional)
platform_v2/
  static/css/directory.css          — Styles (rewritten)
  static/js/directory.js            — Frontend logic (rewritten)
  static/portraits/                 — AI-generated headshot files
database/migrations/
  NNN_directory_chat_tables.sql     — New tables migration
```

**Migration note:** Existing directory routes in `app.py` (lines 817-950) will be moved to the Blueprint. Existing `templates/business/directory.html` (30KB, current active template) is the base to rewrite. `templates/directory.html` (2KB, unused) will be removed.

## Known Limitations (v1)

- Chat is request-response only (no WebSocket/SSE push). Agents cannot initiate messages. Real-time push is a future enhancement.
- Portrait generation is manual trigger. Automation (auto-generate on agent creation) is future work.

## Out of Scope

- Phase 2 mail server (IMAP monitoring, auto-reply)
- Portrait generation automation (manual trigger for now, automation later)
- Video/voice chat with agents
- Agent-to-agent messaging through directory
- WebSocket/SSE real-time chat push
