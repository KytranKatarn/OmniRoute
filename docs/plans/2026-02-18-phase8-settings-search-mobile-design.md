# Phase 8: Settings, Search & Mobile — Design Doc

**Date:** 2026-02-18
**Status:** Approved
**Scope:** Mobile sidebar drawer, user settings/preferences UI, conversation search

---

## Context

Phases 1-7 built a feature-rich chat interface with 3 modes (Solo, Side-by-Side, Collaborate), voice integration, analytics, memory management, notifications, and export. The template is now 4,608 lines with 27 API endpoints.

**What's missing:** The left sidebar has no mobile drawer (just `display: none` at <900px), there's no user preferences UI (only auto-extracted memories), and no way to search across conversations.

**Approach:** Bottom-up — mobile drawer first (structural CSS), then settings UI (persistence layer), then conversation search (uses the same sidebar patterns). Lightweight cleanup happens naturally.

## Architecture

3 components added to the existing Chat module:

| Component | Where | What |
|-----------|-------|------|
| Mobile Sidebar Drawer | archie_chat.html CSS/JS | Hamburger toggle, slide-in overlay, backdrop, close-on-navigate |
| Settings / Preferences | Sidebar section + modal + API | Quick toggles, detailed modal, JSONB persistence, 2 endpoints |
| Conversation Search | Sidebar section + API | Debounced search input, filtered results, snippet highlighting, 1 endpoint |

Plus:
- 1 migration (`112_user_chat_settings.sql`) for settings table
- 3 new API endpoints
- CSS additions (~100 lines) for drawer, settings, search
- JS additions (~250 lines) for all 3 features

## Component 1: Mobile Sidebar Drawer

### Problem

The left sidebar (280px) gets `display: none` at `<900px`. Users on tablets or narrow windows lose access to navigation, analytics, memory, and conversation list.

### Solution

Replace the CSS hide with a slide-in drawer pattern:

- **Hamburger button** in the status bar, visible only at `<900px` via media query
- **Drawer slides in** from left with `transform: translateX(-100%)` → `translateX(0)` transition (300ms ease)
- **Backdrop overlay** (`position: fixed`, `background: rgba(0,0,0,0.4)`, `z-index: 998`) — click to close
- **Close triggers:** backdrop click, X button inside drawer, Escape key, navigation link click
- **Desktop (>900px):** No change — sidebar remains static

### CSS

```css
/* Mobile drawer toggle */
.sidebar-hamburger{display:none;background:none;border:none;color:var(--archie-text,#e2e8f0);font-size:1.2rem;cursor:pointer;padding:4px 8px}
.sidebar-backdrop{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:998}
.sidebar-backdrop.open{display:block}

@media(max-width:900px){
    .sidebar-hamburger{display:inline-flex}
    .sidebar{position:fixed;top:0;left:0;bottom:0;width:280px;z-index:999;transform:translateX(-100%);transition:transform .3s ease;background:var(--archie-bg-primary,#030b1a)}
    .sidebar.drawer-open{transform:translateX(0)}
}
```

### JS

- `toggleSidebar()` — adds/removes `.drawer-open` class + shows/hides backdrop
- Close on: backdrop click, Escape key, nav link click

### Data Sources

None — pure CSS/JS, no backend changes.

## Component 2: Settings / Preferences UI

### Layout

**Sidebar section** — "Settings" collapsible panel (like Analytics/Memory) with quick toggles:
- Theme toggle (dark/light)
- Voice auto-speak toggle (on/off)
- Notification sound toggle (on/off)
- Default chat mode (Solo / Side-by-Side / Collaborate)
- "More Settings..." link opens modal

**Settings modal** — Full configuration:

| Section | Settings | Type |
|---------|----------|------|
| Appearance | Font size (small/medium/large) | select |
| Appearance | Thinking panel auto-open | toggle |
| Chat | Default model preference | select |
| Chat | Max memory entries to inject (1-20) | number |
| Notifications | Briefing delivery (chat / chat+telegram) | select |
| Notifications | Polling interval (15s/30s/60s) | select |
| Data | Clear conversation history | button (with confirm) |
| Data | Export all memories | button |

### Persistence

New table:

```sql
CREATE TABLE IF NOT EXISTS user_chat_settings (
    user_id INTEGER PRIMARY KEY,
    settings JSONB DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT NOW()
);
```

Settings JSONB structure:
```json
{
    "theme": "dark",
    "fontSize": "medium",
    "voiceAutoSpeak": true,
    "notifSound": true,
    "defaultMode": "solo",
    "thinkingAutoOpen": false,
    "defaultModel": null,
    "maxMemoryInject": 10,
    "briefingDelivery": "chat",
    "notifPollInterval": 30
}
```

### Endpoints

- `GET /api/settings` — Returns current user's settings (merges defaults with stored values)
- `POST /api/settings` — Updates settings (partial update via JSONB merge)

### JS Behavior

- On page load: fetch settings, apply to UI (theme, font size, etc.)
- Quick toggles update immediately via POST and apply in-place
- Modal saves on close (or per-field on change)
- Settings applied via CSS classes on `<body>`: `.font-small`, `.font-large`, etc.

### Data Sources

- `user_chat_settings` table (new)
- Existing theme cookie (read on load, migrate to DB)

## Component 3: Conversation Search

### Layout

New "Search" section at the top of the sidebar (above conversation list):
- Text input with magnifying glass icon
- Filter chips below: "All Time" | "This Week" | "This Month" (toggleable)
- Results list replacing the conversation list when search is active
- "Clear search" button to return to normal conversation list

### Search Behavior

- **Debounced** — 300ms after last keystroke
- **Minimum 3 characters** to trigger
- **Results capped at 20** per query
- Searches `ai_conversations.message` and `ai_conversations.response` via `ILIKE`
- Each result shows:
  - Thread title (from `ai_conversation_threads`) or "Untitled"
  - Matching snippet (60 chars around match)
  - Relative timestamp
  - Model badge (if available from metadata)
- Clicking a result loads that conversation thread

### Endpoint

`GET /api/conversations/search?q=keyword&range=7&limit=20`

Returns:
```json
{
    "results": [
        {
            "conversation_id": "abc-123",
            "thread_title": "Discussion about Python",
            "snippet": "...I prefer using **Python** for data...",
            "matched_in": "message",
            "created_at": "2026-02-18T01:23:45",
            "model": "dolphin3-8k"
        }
    ],
    "total": 5
}
```

**SQL approach:**
```sql
SELECT DISTINCT ON (c.conversation_id)
    c.conversation_id,
    t.title as thread_title,
    CASE
        WHEN c.message ILIKE '%' || %s || '%' THEN
            substring(c.message from greatest(1, position(lower(%s) in lower(c.message)) - 30) for 60)
        ELSE
            substring(c.response from greatest(1, position(lower(%s) in lower(c.response)) - 30) for 60)
    END as snippet,
    CASE WHEN c.message ILIKE '%' || %s || '%' THEN 'message' ELSE 'response' END as matched_in,
    c.created_at,
    c.metadata->>'model' as model
FROM ai_conversations c
LEFT JOIN ai_conversation_threads t ON t.conversation_id = c.conversation_id
WHERE c.user_id = %s
AND (c.message ILIKE '%' || %s || '%' OR c.response ILIKE '%' || %s || '%')
AND c.created_at > NOW() - make_interval(days => %s)
ORDER BY c.conversation_id, c.created_at DESC
LIMIT 20
```

### Performance

- ILIKE on text columns is adequate for the current dataset (~110 messages)
- If the table grows past 10K rows, add a GIN trigram index: `CREATE INDEX idx_ai_conv_search ON ai_conversations USING gin (message gin_trgm_ops, response gin_trgm_ops)`
- Query timeout of 5 seconds via `SET statement_timeout`

### JS Behavior

- `searchConversations(query)` with 300ms debounce
- Results rendered with `createElement` + `textContent` (no innerHTML)
- Matching text in snippet shown with a highlight wrapper span (CSS `background: var(--archie-accent-dim)`)
- Click result → call existing conversation loading function
- "X" button clears search and restores normal conversation list

## Migration

`database/migrations/112_user_chat_settings.sql`:

```sql
-- Migration 112: User chat settings
-- Phase 8: Settings, Search & Mobile

CREATE TABLE IF NOT EXISTS user_chat_settings (
    user_id INTEGER PRIMARY KEY,
    settings JSONB DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT NOW()
);
```

## Error Handling

- Settings endpoint fails → use defaults (hardcoded in JS), show retry button
- Search endpoint fails → show "Search unavailable" with retry
- Mobile drawer CSS fails to load → sidebar falls back to existing `display: none` behavior
- Settings save fails → show error toast, don't lose user's changes (keep in local state)
- Empty search results → show "No conversations match your search"

## Not Included (YAGNI)

- No keyboard shortcuts (could be Phase 9 — low complexity, independent)
- No full-text search (ILIKE sufficient for current scale)
- No settings import/export
- No per-conversation settings override
- No sidebar position toggle (always left)
- No swipe gestures (just tap hamburger — simpler, more reliable)

## Key Files

- Modify: `platform_v2/templates/tools/archie_chat.html` (drawer CSS/JS, settings panel, search UI)
- Modify: `platform_v2/tools/archie_core/routes.py` (3 new endpoints)
- Create: `database/migrations/112_user_chat_settings.sql`
