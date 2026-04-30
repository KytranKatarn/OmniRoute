# Media Studio Tab Redesign — Implementation Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign Gallery, Dashboard, Generate, and Social Video tabs in Media Studio as a cohesive production studio for Kytran Empowerment internal use — agent portraits, brand assets, and social content pipeline.

**Architecture:** Hybrid approach — each tab has a clear independent purpose but connects to the others. Agents pulled live from DHQ roster so new agents auto-appear everywhere. Portraits and Queue tabs are excluded (working well).

**Tech Stack:** Flask + Jinja2 + vanilla JS, LCARS LCARS aesthetic, PostgreSQL (`media_library`, `agents`, `media_generation_queue`), ComfyUI via P.I.X.E.L./DHQ, KBS social media for posting, S.I.G.N.A.L. for approval pipeline.

---

## Context & Users

- **Users:** Kytran + company admins only (internal tool)
- **Purpose:** Create AI-generated media for agents (portraits, brand shots), website assets, and social content for Kytran Empowerment channels
- **Agent roster source:** Department HQ — all agent pickers pull live from `/api/agents` or DHQ roster. Human agents (`worker_type='internal'`) and AI acronym agents (`worker_type='ai'`) both appear automatically when added to DHQ.

---

## Tab 1 — Dashboard (Production Overview)

**Purpose:** Open Media Studio and immediately see what needs attention. Full ops center.

### Layout
- **5 stat counters** (top row): Generating Now · Pending Approval · Social Queued · Total Assets · Failed
- **3-column live panel:**
  - ⟳ **Generating Now** — active queue items with agent name, status dot (green=generating, amber=pending), elapsed time
  - ✓ **Needs Approval** — completed portraits/assets awaiting review, inline approve/reject buttons, thumbnail
  - 📤 **Social Queue** — content scheduled via S.I.G.N.A.L./KBS, status (draft/scheduled), quick "+ Create" link
- **Recent Completions** — 6-image grid of latest generated assets, click to open detail modal
- **Auto-refresh:** every 15s while Dashboard tab is active; timer clears on tab switch

### Backend
- `GET /api/dashboard` already exists — extend to include:
  - `pending_approvals`: list of completed queue items not yet approved (portraits where `agent_portraits.is_approved = false` and `canonical_image_path IS NOT NULL`)
  - `social_queue`: items from social video queue (draft + scheduled)
  - `active_jobs`: already implemented (agent name, status, prompt snippet)
- Inline approve/reject calls `POST /api/portraits/<id>/approve` / `DELETE` equivalent

---

## Tab 2 — Gallery (Asset Library)

**Purpose:** Per-subject media kit browser. Persistent state — switching tabs and returning lands you exactly where you left off.

### Layout
- **Left sidebar (persistent):** Subject picker grouped into three sections:
  - **Human Agents** — internal workers with portrait photos (avatar thumbnail + name + asset count)
  - **AI Agents** — acronym agents (small avatar + name + asset count)
  - **Brand** — Kytran Empowerment brand assets (not agent-specific)
  - All sections populated dynamically from DHQ roster — new agents appear automatically
- **Right panel:** Media kit for selected subject
  - Header: avatar, name, department, asset count, contextual **+ Generate** button (pre-routes to Generate tab with subject pre-selected)
  - Sub-tabs: **All · Headshots · Lifestyle · Social** (type categories based on `metadata->>'asset_type'`)
  - Image grid: 4-wide, aspect-ratio 1:1 thumbnails; ★ marks featured/active image for that person
  - Click image → opens detail modal (existing `showMediaDetail`)

### State Persistence
- Selected subject stored in JS variable `_gallerySubjectId` and `_gallerySubjectType`
- On tab switch: state saved. On return: sidebar re-selects previous subject, grid reloads their assets
- URL hash updated: `#gallery/agent/13` so browser back works

### Backend
- `GET /api/gallery?owner_type=agent&owner_id=<id>` — already works, extend to support `asset_type` filter
- `GET /api/agents/gallery-subjects` — new endpoint: returns grouped list `{humans: [...], ai_agents: [...], brand: {...}}` from DHQ roster with asset counts
- `PUT /api/gallery/<id>/asset-type` — set `metadata->>'asset_type'` (headshot/lifestyle/social/brand)
- `PUT /api/gallery/<id>/featured` — mark as ★ featured for that subject

---

## Tab 3 — Generate (Creation Studio)

**Purpose:** Type-first creation flow. Pick what you're making, then who it's for — the form adapts.

### Layout — 3-step flow

**Step 1 — Content Type** (3 large cards):
- **Portrait** → ComfyUI generation for agent identity consistency (routes to P.I.X.E.L./DHQ)
- **Brand Asset** → headshot, lifestyle, or marketing image (routes to ComfyUI)
- **Social Content** → quote card / short video → switches to Social Video tab builder with subject pre-filled

**Step 2 — Who is this for?** (shown after type pick):
- Pill-style agent picker: human agents first, then AI acronym agents
- Pulled live from DHQ roster — no hardcoded list
- Selecting an agent auto-fills Step 3 prompt from their Roster identity prompt

**Step 3 — Prompt** (pre-filled, editable):
- Populated from `agent_portraits.identity_prompt` or `agents.system_prompt` for the selected agent
- Label shows "pre-filled from [Agent Name]'s identity — edit to refine"
- For Brand/Social types: blank prompt with template suggestions

**Advanced (collapsed by default):** model · steps · CFG · seed · negative prompt · size presets

**Generate button:** Labels P.I.X.E.L. by name — "⚡ GENERATE via P.I.X.E.L." — reinforces DHQ orchestration. Inline status feedback below button (no browser alerts).

### Backend
- Existing `POST /api/generate` — already works
- `GET /api/agents/picker` — new endpoint: returns `{humans: [{id, name, display_name, avatar_thumb_url}], ai_agents: [...]}` from DHQ for the agent picker UI
- `GET /api/portraits/<agent_id>/identity` — returns current identity_prompt for pre-fill

---

## Tab 4 — Social Video (Content Builder)

**Purpose:** AutoShorts-style pipeline — build short slideshow videos with images + text + audio, then schedule to post via S.I.G.N.A.L. → KBS → Kytran's connected social profiles.

### Layout — Builder + Queue panel

**Left: Builder (4 steps)**
1. **Text/Quote** — textarea for quote or caption, or pick from template library
2. **Images** — source tabs: **Gallery** (brand shots, lifestyle) or **Portraits** (approved canonical portraits); filter by subject; drag to reorder selected images
3. **Audio** — Background Music / Narration (TTS via audio service) / Silent
4. **Post via S.I.G.N.A.L.** — channel selector (KBS social accounts: Kytran's LinkedIn, etc.), schedule datetime; shows "S.I.G.N.A.L. → KBS → Kytran's LinkedIn ● connected"

**Actions:** Preview · Queue for Posting

**Right: Queue panel**
- Filter tabs: All · Draft · Scheduled · Posted
- Queue items show thumbnail, title, platform, status badge (DRAFT/SCHED/POSTED)
- Draft items have inline Edit/Delete; Scheduled shows countdown

### Posting Architecture
- Social Video → generates video file (ComfyUI AnimateDiff when available, or slide export) → stores in `media_library`
- Queue for Posting → creates `social_video_queue` entry with status='pending_approval'
- S.I.G.N.A.L. picks up via existing Telegram approval pipeline
- Approved → S.I.G.N.A.L. calls KBS `POST /api/social-media/post` using `social_accounts` (Kytran's connected profile)
- Posted status recorded back to queue item

### Future: Per-Agent Social Profiles
- **Dependency: Agent Social Media Playwright Skill** (separate spec — see below)
- Once agents have their own social accounts, the channel selector expands to include agent profiles
- Each agent's Playwright vault stores their credentials and action library

---

## Dependency: Agent Social Media Playwright Skill (Separate Spec)

> **This is a separate project — brainstorm and spec separately.**

**Concept:** Each AI agent gets their own social media accounts (LinkedIn, Instagram, etc.). A Playwright skill handles:
- **Account creation automation** — sign up flow per platform, per agent
- **Credential vault** — stored in Playwright vault per agent (like the existing LinkedIn skill for Kytran)
- **Action library** — post, comment, like, connect — same Playwright moves as Kytran's skill but scoped to the agent's profile

**Why it matters for Media Studio:** Social Video tab channel selector can then offer "Post as V.I.G.I.L." / "Post as M.U.S.E." / "Post as Kytran" — multi-brand content strategy from one interface.

**Status:** Not in scope for this spec. Create task in DHQ to brainstorm.

---

## Cross-Cutting Concerns

### Agent Roster Integration
- All agent pickers (Generate Step 2, Gallery sidebar) call a shared service function that queries DHQ agents table
- Filter: `is_deleted = false AND shift_state != 'decommissioned'`
- Grouped by: `worker_type = 'internal'` → Human Agents, `worker_type = 'ai'` → AI Agents
- New agent added in DHQ → automatically appears in Media Studio within one page load — no code changes needed

### State Persistence
- Gallery subject selection: `sessionStorage.setItem('ms_gallery_subject', JSON.stringify({type, id}))`
- Gallery filter (headshots/lifestyle/social): `sessionStorage.setItem('ms_gallery_filter', filter)`
- Generate type selection: not persisted (intentional — fresh each time)
- URL hash navigation: `#gallery`, `#gallery/agent/13`, `#generate`, `#social-video`

### LCARS Visual Language
- Dashboard accent: cyan (`#00ffff`) — matches existing
- Gallery accent: green (`#22c55e`) — assets/library
- Generate accent: blue (`#3b82f6`) — creation
- Social Video accent: purple (`#8b5cf6`) — publishing
- All tabs use existing LCARS frame pattern with sidebar + header bar

---

## What Is NOT Changing
- **Portraits tab** — working well, excluded from this spec
- **Queue tab** — working well, excluded from this spec
- **Backend generation pipeline** — P.I.X.E.L./DHQ/ComfyUI orchestration stays as-is
- **KBS social media connection** — existing OAuth, not rebuilding
- **S.I.G.N.A.L. approval flow** — existing Telegram pipeline, not rebuilding
