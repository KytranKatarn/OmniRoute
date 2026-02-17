# Phase 5: Voice Integration Polish — Design Doc

**Date:** 2026-02-17
**Status:** Approved
**Scope:** STT input UI, voice sidebar, profile locking UX, voice metrics

---

## Context

The ARCHIE platform has a mature TTS system (Kokoro-82M + XTTS v2), per-agent voice profiles, pre-generation caching with DB-level locking, and complete STT code in collaboration.js. However:

1. **Chat tab has no mic button** — collaboration.js has full STT functions (`startVoiceInput`, `stopVoiceInput`) but the DOM elements they reference don't exist in archie_chat.html
2. **No voice config in chat** — Users must navigate to Consciousness Voice tab to change any settings
3. **Locking UX is invisible** — DB locking works (is_locked + ON CONFLICT immutability) but the UI doesn't show lock status, warn on profile changes, or offer regeneration
4. **No voice metrics in chat** — TTS latency, cache hit rate, engine status are not visible

Voice will be used across phone, chat, and voice messages. Each agent will have their own voice. Once a voice is set and words pre-generated, the profile must stay locked unless regeneration is explicitly triggered.

## Architecture

4 components across 4 files:

| Component | File | What |
|-----------|------|------|
| STT Input UI | `archie_chat.html` | Mic button + waveform + voice status |
| Voice Sidebar | `archie_chat.html` | Collapsible config, status, metrics panel |
| Profile Locking UX | `consciousness_dashboard.html` | Lock indicators, change warnings, regeneration |
| Backend Endpoints | `archie_core/routes.py` | Cache invalidation + recent activity |

Plus one migration for lock audit metadata.

## Component 1: STT Input UI (Chat Tab)

### DOM Elements
Added to the input area of `archie_chat.html`:
- `#voice-input-btn` — Mic toggle button next to send button
- `#voice-status` — Container for status text + waveform (overlays input when listening)
- `#voice-status-text` — "Listening..." / "Processing..."
- `#voice-waveform` — 5 animated CSS bars

### Behavior
- Click mic → start Web Speech API STT (browser-native, free)
- Real-time transcript fills `#messageInput`
- 8s silence → auto-send via `sendArchieMessage()` bridge
- Escape or click mic again → stop
- `.listening` class on mic button for visual state
- Browser unsupported → mic button hidden via feature detection

### JS Bridge
- `archie-chat-input` alias → `messageInput` (collaboration.js references the former)
- Existing collaboration.js `startVoiceInput()` / `stopVoiceInput()` handle all STT logic

### CSS (~50 lines)
- Waveform `@keyframes` animation (5 bars, staggered)
- Mic button states (default, listening, hover)
- Voice status overlay transform

## Component 2: Voice Sidebar (Chat Tab)

### Layout
Collapsible right panel, 300px wide, slides in from right. Toggle button in top status bar (speaker icon). Same pattern as thinking panel.

### Sections

**Quick Config** (top):
- Voice on/off toggle (syncs `voiceEnabled` + `voiceConfig.enabled`)
- Volume slider
- Auto-play toggle
- Current engine badge (Kokoro/XTTS)

**Voice Status** (middle):
- Engine health: green/red dot for Kokoro + XTTS
- Cache stats: cached words count, hit rate %
- Last TTS latency (ms)
- Current agent voice profile name + speaker

**Recent Activity** (bottom):
- Last 5 TTS generations: text snippet, latency, cache hit/miss badge
- Refreshes on each new TTS response

### Data Sources
- `GET /api/voice/status` — engine health, cache stats
- `GET /api/voice/config` — user preferences
- `GET /api/voice/recent` — **NEW** endpoint, queries `voice_generation_log` last 5

### CSS (~150 lines)
- Panel slide animation, sections layout
- Toggle button, status dots, metric cards

## Component 3: Profile Locking UX (Consciousness Voice Tab)

### A. Visual Lock Indicators
- Profile cards: lock icon + "Locked (247 words)" badge when cache has locked entries
- Cache browser table: "Locked" column with lock/unlock icon per entry
- Cache browser filter: "Locked" / "Unlocked" / "All" status filter

### B. Profile Edit Warnings
When editing a profile with locked cache:
1. Warning banner: "This profile has 247 locked cached words. Changing voice parameters will NOT update existing cache."
2. Two actions:
   - **Save without regeneration** — Profile updates, locked cache stays immutable
   - **Save and regenerate** — Profile updates, cache unlocked/cleared, new pre-gen starts

### C. Cache Invalidation Endpoint
`POST /api/voice/profiles/<id>/invalidate-cache`:
- Unlocks all `voice_word_cache` entries for agent+engine+language
- Param `clear=true` → deletes entries instead of unlocking
- Param `regenerate=true` → triggers new pre-gen job after clearing
- Returns: `{unlocked: N, deleted: N, pregen_job_id: X}`

### D. Lock Audit Metadata
Migration adds to `voice_word_cache`:
- `locked_at TIMESTAMP` — when entry was locked
- `locked_with_params JSONB` — snapshot of voice parameters at lock time

## Component 4: Backend Endpoints

### New: `GET /api/voice/recent`
Returns last 5 entries from `voice_generation_log` for the current user.
Response: `{recent: [{text, latency_ms, cache_hit, emotion, engine, created_at}]}`

### New: `POST /api/voice/profiles/<id>/invalidate-cache`
Unlocks or clears cache entries for a profile.
Params: `clear` (bool), `regenerate` (bool)
Response: `{success, unlocked, deleted, pregen_job_id}`

### Existing (no changes):
- `GET /api/voice/status`
- `GET/POST /api/voice/config`
- `POST /api/voice/synthesize`

## Migration

`database/migrations/109_voice_locking_metadata.sql`:
```sql
ALTER TABLE voice_word_cache
ADD COLUMN IF NOT EXISTS locked_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS locked_with_params JSONB;
```
Update pre-gen locking to populate these columns.

## Error Handling

- Speech API unsupported → mic button hidden
- TTS fails → toast "Voice unavailable" + text response still shows
- Sidebar API errors → stale data with "Last updated X ago"
- Cache invalidation fails → toast error, cache stays locked (safe default)
- Pre-gen fails mid-way → progress shows failed count, retry available

## Not Included (YAGNI)

- No phone/voice-message integration (future)
- No VAD — browser silence detection sufficient
- No voice cloning or training
- No streaming TTS
- No voice selection from chat sidebar (use Consciousness Voice tab)
- No per-conversation voice settings

## Key Files

- Modify: `platform_v2/templates/tools/archie_chat.html`
- Modify: `platform_v2/templates/tools/consciousness_dashboard.html`
- Modify: `platform_v2/tools/archie_core/routes.py`
- Modify: `platform_v2/tools/consciousness/voice_pregen.py` (update locking to set locked_at/locked_with_params)
- Create: `database/migrations/109_voice_locking_metadata.sql`
- Existing: `platform_v2/static/js/collaboration.js` (STT code, may need minor fixes)
- Existing: `ai_bridge/voice_synthesis.py` (core TTS engine)
