# Phase 7: Intelligence Layer — Design Doc

**Date:** 2026-02-18
**Status:** Approved
**Scope:** Analytics dashboard, contextual memory system, proactive chat integration, conversation export

---

## Context

Phases 1-6 built the chat UI, collaboration modes, voice integration, and multi-agent orchestration visibility. The platform now has rich data accumulating across multiple tables:
- `ai_conversations` (110+ messages with metadata JSONB: response_time_ms, model, agent_used, tokens)
- `orchestration_sessions` (76 sessions) + `orchestration_steps` (529 steps with timing)
- `long_term_memory` (344 records across 8 types)
- `user_memory_preferences` (2 records, preference injection already works)
- `system_notifications` (278 entries)
- `briefings` (2 configured, 0 generated)
- `anomaly_rules` (4 rules), `anomaly_detections` (1 detection)
- `cloud_model_usage` (cost tracking)
- Pre-built views: `v_bridge_analytics`, `v_command_analytics`

**What's missing:** User-facing analytics, active memory management, proactive alerts surfaced in chat, and conversation export.

## Architecture

4 components added to the existing Chat module (`archie_chat.html`, 4230 lines) and archie_core routes:

| Component | Where | What |
|-----------|-------|------|
| Analytics Dashboard | New sidebar section in chat | Per-user conversation metrics, model/agent usage charts, cost tracking, voice stats |
| Contextual Memory | Intent parser + sidebar panel | "Remember/forget/list" commands, auto-extraction, memory management UI |
| Proactive Integration | Chat header + SSE | Notification feed, briefing delivery, anomaly alerts, proactive suggestions |
| Chat Export | Conversation sidebar + modals | Export as Markdown/JSON, save to KB, analytics CSV, conversation summary |

Plus:
- 1 migration (`111_intelligence_layer.sql`) for schema additions
- ~10 new API endpoints across archie_core routes
- Intent parser additions for memory/briefing commands
- SSE event type addition for anomaly alerts

## Component 1: Analytics Dashboard

### Layout

New "Analytics" section in the chat sidebar (tab alongside Conversations/Files or a dedicated panel toggle).

**Conversation Metrics** (top):
- Messages today / this week / this month (counts from `ai_conversations`)
- Avg response time (from `metadata->>'response_time_ms'`)
- Active conversations count (from `ai_conversation_threads` WHERE not archived)
- 7-day sparkline trend (daily message counts)

**Model & Agent Usage** (middle):
- Donut chart: model distribution (from `orchestration_steps.model_used` GROUP BY)
- Horizontal bar chart: agent usage ranking (top 5 agents by step count)
- Pipeline timing table: avg duration per step_type (intent_parse, execute, route_decision, etc.)

**Cost & Tokens** (bottom):
- Token consumption by tier: local (free) vs cloud (metered)
- Cloud spend this month (from `cloud_model_usage.cost_usd` SUM)
- Budget gauge (if `external_api_keys` has monthly budget set)

**Voice Stats** (compact):
- TTS generations today, cache hit rate (from `voice_word_cache` hit/miss), avg latency

### Endpoints

- `GET /api/analytics/conversation-metrics?range=7d|30d` — Message counts, avg response time, trends
- `GET /api/analytics/model-usage?range=7d|30d` — Model/agent distribution, step timing
- `GET /api/analytics/cost?range=30d` — Token/cost breakdown
- `GET /api/analytics/voice?range=7d` — Voice generation stats

### Data Sources

- `ai_conversations` + `ai_conversation_threads` (conversation metrics)
- `orchestration_steps` (model/agent usage, timing)
- `cloud_model_usage` (cost tracking)
- `voice_generation_log` + `voice_word_cache` (voice stats)

## Component 2: Contextual Memory System

### Chat Commands

Handled by adding new intent types to the intent parser:

| Command Pattern | Intent Type | Action |
|----------------|-------------|--------|
| "Remember that...", "Note that..." | `memory_store` | Store to `long_term_memory` with auto-categorization |
| "Forget about...", "Remove memory..." | `memory_forget` | Soft-delete matching entries |
| "What do you remember?", "My preferences" | `memory_list` | Return grouped memory list |

Processing flow:
1. Intent parser detects memory intent (keyword: remember, forget, preferences, memory)
2. Orchestration engine routes to new `_handle_memory_command()` method
3. For `memory_store`: classify content category via qwen25-classify, insert into `long_term_memory` with `source_type='manual'`
4. For `memory_forget`: fuzzy match on content/category, set `is_deleted=true`
5. For `memory_list`: query active memories grouped by category, format as readable list

### Auto-Extraction (passive)

After each successful orchestration (in `orchestrate()` success path):
- Check if conversation contains extractable preferences using qwen25-classify
- Prompt: "Does this message contain a user preference, decision, or fact worth remembering? If yes, extract it as a single sentence. If no, return NONE."
- If extracted: insert into `user_memory_preferences` with `confidence=0.5`, increment on repeat
- Rate-limited: max 1 extraction per conversation to avoid noise

### Memory-Enhanced Prompts

Enhance existing preference injection (already in `ai_chat.py` line 96):
- Include top 10 memories by: `confidence DESC, last_confirmed_at DESC NULLS LAST`
- Format as: "User preferences: {category}: {content} (confidence: {confidence})"
- Cap at 500 tokens to avoid prompt bloat

### Memory Management Panel

New "Memory" section in the chat sidebar:
- Scrollable list of memories with category badge, confidence bar (0-1), relative timestamp
- Each entry: click to expand with full content + metadata
- Delete button per entry (sets `is_deleted = true`)
- Search/filter box at top
- Fetches from `GET /api/memory/list?user_id=current`

### Endpoints

- `GET /api/memory/list` — User's active memories, grouped by category
- `POST /api/memory/store` — Manually store a memory
- `POST /api/memory/<id>/delete` — Soft-delete a memory
- `GET /api/memory/preferences` — User's preference entries with confidence

### Migration Additions

On `long_term_memory`:
- Add `source_type TEXT DEFAULT 'system'` — values: manual, auto-extracted, system
- Add `is_deleted BOOLEAN DEFAULT FALSE`
- Backfill: existing entries get `source_type='system'`, `is_deleted=false`

## Component 3: Proactive Chat Integration

### Notification Feed

A dismissible notification bar below the chat input area (or above messages):
- Shows unread `system_notifications` count with most recent preview
- Notification types with color coding: anomaly (amber), briefing (cyan), email (blue), HR alert (plum)
- Click to expand full notification inline
- Dismiss marks as read
- Polls `GET /api/notifications/unread` every 30s (reuses existing polling pattern)

### Briefing Delivery in Chat

Fix the existing BriefingGenerator pipeline:
- Ensure `_generate_briefings()` agent loop job actually produces output
- When a briefing generates, insert it into `ai_conversations` as a system message with `metadata: {chat_mode: 'briefing', source: 'proactive'}`
- Display in chat as a formatted card with date header, section summaries
- "Generate briefing" command triggers immediate generation
- New intent type: `briefing_command` (keywords: briefing, daily summary, morning report)

### Anomaly Alerts in Chat

When AnomalyDetector creates a detection:
- Push event to SSE stream: event type `anomaly_alert`
- Chat JS picks up SSE event and shows a toast-style notification at top
- Toast has dismiss + "View details" button
- Existing `push_agent_event()` in bridge routes is reused

### Proactive Suggestions

Lightweight, no LLM:
- After each chat response render, check notification count via existing badge poll
- If unread notifications > 0 and oldest is > 1 hour, show a subtle hint: "You have N unread notifications"
- Rendered as a small text below the response, not a separate message

### Briefing Configuration

"Configure briefings" command opens a settings modal:
- Briefing name, schedule (preset: daily 8am, weekly Monday 9am, custom cron)
- Section toggles: notifications summary, email digest, task updates, anomaly report, calendar
- Delivery channels: chat (always), Telegram (toggle)
- Saved to `briefings` table per user

### Endpoints

- `GET /api/notifications/unread` — Unread notification count + recent previews
- `POST /api/notifications/<id>/read` — Mark notification as read
- `POST /api/briefings/generate-now` — Trigger immediate briefing
- `GET /api/briefings/config` — User's briefing configuration
- `POST /api/briefings/config` — Update briefing settings

## Component 4: Chat Export & Sharing

### Conversation Export

Export button in conversation sidebar (kebab menu or dedicated icon per conversation):

| Format | Content | Use Case |
|--------|---------|----------|
| Markdown | Messages + timestamps + model/agent labels | Human-readable sharing |
| JSON | Full data: messages, metadata, thinking steps, orchestration IDs | Backup / programmatic use |

Download triggers a file download via `<a download>` pattern.

### Save to Knowledge Base

- Button on conversation sidebar (per conversation) and on individual messages (context menu)
- Creates a `vault_note` in `knowledge_base` with:
  - `title`: Auto-generated from conversation content (first user message or AI-generated title)
  - `content`: Full conversation formatted as markdown
  - `tags`: Auto-classified via qwen25-classify
  - `source_type`: 'chat_export'
  - `importance_score`: 0.6 (default)
- Confirmation toast with knowledge entry ID

### Analytics Export

CSV download button on the Analytics panel:
- Exports current time range data as CSV
- Columns: date, messages, avg_response_ms, model, agent, tokens, cost
- Filename: `archie-analytics-{range}-{date}.csv`

### Conversation Summary

"Summarize" button (per conversation):
- Sends conversation content to dolphin3 with prompt: "Summarize this conversation in 3-5 bullet points"
- Result displayed in a modal with copy-to-clipboard button
- Optional: save summary to knowledge base

### Endpoints

- `GET /api/conversations/<id>/export?format=md|json` — Export conversation
- `POST /api/conversations/<id>/save-to-kb` — Save to knowledge base
- `GET /api/analytics/export?range=7d|30d&format=csv` — Analytics CSV
- `POST /api/conversations/<id>/summarize` — Generate summary

## Migration

`database/migrations/111_intelligence_layer.sql`:

```sql
-- Migration 111: Intelligence Layer additions
-- Phase 7: Analytics, Memory, Proactive, Export

-- Memory system enhancements
ALTER TABLE long_term_memory ADD COLUMN IF NOT EXISTS source_type TEXT DEFAULT 'system';
ALTER TABLE long_term_memory ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_ltm_user_active ON long_term_memory(user_id) WHERE is_deleted = FALSE;

-- Notification read tracking (if not exists)
ALTER TABLE system_notifications ADD COLUMN IF NOT EXISTS is_read BOOLEAN DEFAULT FALSE;
ALTER TABLE system_notifications ADD COLUMN IF NOT EXISTS read_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_sn_user_unread ON system_notifications(user_id) WHERE is_read = FALSE;

-- Chat export log (optional, for tracking exports)
CREATE TABLE IF NOT EXISTS chat_export_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    export_format TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Error Handling

- Analytics endpoint failures → show "Unable to load analytics" with retry button
- Memory store failures → show error toast, don't lose user's text
- Briefing generation timeout → log warning, skip this cycle
- Export of large conversations → stream response, show progress indicator
- SSE anomaly event missed → notification feed poll catches it on next cycle
- Classifier failure → skip auto-extraction, don't block chat response

## Not Included (YAGNI)

- No PDF export (complex dependency, Markdown/JSON sufficient)
- No conversation sharing via URL (security concern, export is sufficient)
- No real-time collaborative analytics (single user is sufficient)
- No custom analytics dashboard builder (pre-built layout is sufficient)
- No memory import from external sources (manual + auto-extract is sufficient)
- No push notifications (polling + SSE is sufficient)

## Key Files

- Modify: `platform_v2/templates/tools/archie_chat.html` (analytics panel, memory panel, notification feed, export buttons)
- Modify: `platform_v2/tools/archie_core/routes.py` (10+ new API endpoints)
- Modify: `ai_bridge/orchestration_engine.py` (memory command handling, auto-extraction hook)
- Modify: `ai_bridge/intent_parser.py` (new intent types: memory_store, memory_forget, memory_list, briefing_command)
- Modify: `ai_bridge/proactive_intelligence.py` (fix briefing generation, add chat delivery)
- Create: `database/migrations/111_intelligence_layer.sql`
