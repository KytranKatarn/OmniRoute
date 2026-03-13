# Media Studio Layer 7: Agent Integration & Automation — Design Spec

## Overview

Enable ARCHIE agents to autonomously generate media through the existing Media Studio pipeline. Agents get their own galleries, scheduled generation via the agent loop, and orchestration routing — all built on top of the existing `submit_generation()` infrastructure.

**Goal:** Agents generate media on schedules, with private galleries they can publish to shared, governed by a simple global daily cap, routed through the Bridge dispatcher's existing capability system.

## Scope

Three capabilities:
1. **Bridge-triggered generation** — Agents generate media via dispatcher `request_work(capability=...)`
2. **Scheduled autonomy** — Agent loop checks cron schedules and triggers generation for enabled agents
3. **Orchestration routing** — Orchestration engine routes `media_generate` intents to the agent media service

## Database Schema

### New table: `media_agent_config`

```sql
CREATE TABLE IF NOT EXISTS media_agent_config (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL UNIQUE,  -- matches agents.name
    enabled BOOLEAN DEFAULT FALSE,
    media_type VARCHAR(20) DEFAULT 'image',   -- image, video, audio
    schedule_cron VARCHAR(50) DEFAULT '0 */4 * * *',  -- default: every 4 hours
    default_prompt TEXT,                       -- template with {agent_name}, {station}
    default_negative TEXT DEFAULT '',
    default_params JSONB DEFAULT '{}',        -- width, height, model, etc.
    daily_cap INTEGER DEFAULT 10,             -- per-agent daily limit
    last_generated_at TIMESTAMP,
    gallery_visibility VARCHAR(20) DEFAULT 'private', -- private | shared
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Schema change: `media_generations`

Add column:

```sql
ALTER TABLE media_generations
ADD COLUMN IF NOT EXISTS gallery_visibility VARCHAR(20) DEFAULT 'shared';
```

- Existing user generations: default `'shared'` (no behavior change)
- Agent generations: service sets `'private'` at insert time based on agent config

### Global daily cap

No new table — checked at generation time:

```sql
SELECT COUNT(*) FROM media_generations
WHERE owner_type = 'agent'
AND created_at > NOW() - INTERVAL '1 day';
```

Compared against a system config value (default 100). Can be stored in `system_config` table or as a constant in the service.

## Agent Media Service

**New file:** `platform_v2/tools/media_studio/services/agent_media_service.py` (~150 lines)

### Functions

#### `agent_generate(agent_name, media_type=None, prompt=None, params=None)`

Core generation function for agents:

1. Load agent config from `media_agent_config` (return error if not found or not enabled)
2. Fall back to config defaults for any unset parameters (media_type, prompt, params)
3. Check global daily cap — `SELECT COUNT(*) FROM media_generations WHERE owner_type='agent' AND created_at > NOW() - INTERVAL '1 day'`
4. If over cap, return `{'error': 'Global agent daily cap reached'}`
5. Check per-agent daily cap — same query filtered by `owner_id = agent_name`
6. Call `submit_generation(owner_type='agent', owner_id=agent_name, media_type=..., prompt=..., params=...)`
7. Update `last_generated_at` on the agent config
8. Return `{'generation_id': id}` on success

#### `publish_generation(generation_id, agent_name)`

Set gallery visibility to shared:

1. Verify the generation belongs to `agent_name` (`owner_type='agent' AND owner_id=agent_name`)
2. Update `gallery_visibility = 'shared'` on the generation
3. Return success/error

#### `get_agent_gallery(agent_name, include_private=False)`

Retrieve agent's generations:

1. Query `media_generations WHERE owner_type='agent' AND owner_id=agent_name`
2. If `include_private=False`, add `AND gallery_visibility='shared'`
3. Return list of generations ordered by `created_at DESC`

#### `orchestration_generate(agent_name, intent_data)`

Entry point for orchestration engine:

1. Extract `prompt`, `media_type`, `params` from `intent_data`
2. Call `agent_generate(agent_name, media_type, prompt, params)`
3. Return generation result

## Agent Loop Integration

**Modified file:** `ai_bridge/agent_loop.py`

### New scheduled job: `media_agent_generation`

Added in the `start()` method alongside existing `scheduler.add_job()` calls:

- **Interval:** Every 15 minutes
- **Logic:**
  1. Query `media_agent_config WHERE enabled = TRUE`
  2. For each agent, check if `schedule_cron` is due (compare `last_generated_at` against `croniter(cron).get_prev(datetime)`)
  3. If due, call `dispatcher.request_work(capability=<media_type_capability>)` to route through Bridge
  4. The dispatched work calls `agent_media_service.agent_generate(agent_name)`
  5. Skip if global daily cap is reached

### Cron matching

Uses `croniter` library (already available via APScheduler dependencies):

```python
from croniter import croniter
cron = croniter(agent_config['schedule_cron'])
prev_fire = cron.get_prev(datetime)
if agent_config['last_generated_at'] is None or prev_fire > agent_config['last_generated_at']:
    # Due for generation
```

### Why dispatcher.request_work?

- Bridge remains the single routing authority
- Generation appears in Bridge Command logs
- If the capable agent is busy, it queues normally
- No special-casing needed

## Orchestration Hook

**Modified file:** `ai_bridge/orchestration_engine.py`

Add a route handler in the intent→execute mapping:

```python
'media_generate': lambda intent: agent_media_service.orchestration_generate(
    intent['agent_name'], intent
)
```

This allows any agent to request media generation through natural language → orchestration → media pipeline. The orchestration engine handles intent parsing and agent identification. The agent media service handles cap checks and generation.

No new tables, no new capabilities — one function call and one route mapping.

## API Routes

**Modified file:** `platform_v2/tools/media_studio/routes.py`

### Existing endpoint modification

`GET /api/generations` — Add `owner_type` query parameter filter:
- `?owner_type=agent` returns only agent generations with `gallery_visibility='shared'`
- `?owner_type=agent&agent_name=Pixel` filters to specific agent
- Default behavior unchanged (returns user's own generations)

### New endpoints (3)

#### `GET /api/agent-config`
List all agent media configs. Admin only.

Response: `[{agent_name, enabled, media_type, schedule_cron, daily_cap, last_generated_at, ...}]`

#### `PUT /api/agent-config/<agent_name>`
Update agent media config. Admin only.

Body: `{enabled, media_type, schedule_cron, default_prompt, default_negative, default_params, daily_cap, gallery_visibility}`

#### `POST /api/agent-config/<agent_name>/trigger`
Manually trigger a generation for an agent. Admin only.

Calls `agent_generate(agent_name)` immediately, bypassing schedule check (still respects daily cap).

Response: `{generation_id}` or `{error}`

#### `POST /api/agent-config/<agent_name>/publish/<generation_id>`
Publish an agent's generation to the shared gallery. Admin only.

Calls `publish_generation(generation_id, agent_name)`.

Response: `{success: true}` or `{error}`

## Frontend

**Modified file:** `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html`

### Gallery filter

Add filter buttons alongside existing gallery controls:

- **All** | **Mine** | **Agent Art**
- "All" shows the user's own generations plus all agent generations with `gallery_visibility='shared'`
- "Mine" shows only the current user's generations (existing behavior)
- "Agent Art" queries `GET /api/generations?owner_type=agent` (shared only)
- Each generation card shows agent name badge ("by Pixel") instead of user name
- Clicking agent name filters to that agent's published work

### Admin config panel

Accessible from Media Studio settings area (gear icon):

- Table listing agents with media capabilities
- Toggle enabled/disabled per agent (inline)
- Edit schedule cron, default prompt template, daily cap (inline)
- Preview next scheduled generation time
- Manual "Generate Now" button per agent (calls trigger endpoint)

### JS additions

- `loadAgentGallery()` — fetch and render agent art
- `loadAgentConfig()` — fetch and render admin config table
- `updateAgentConfig(agentName, field, value)` — inline edit handler
- `triggerAgentGeneration(agentName)` — manual trigger

## CSS

**Modified file:** `platform_v2/tools/media_studio/static/css/media-studio.css`

New styles:
- `.ms-agent-badge` — agent name badge on gallery cards
- `.ms-agent-config` — admin config table
- `.ms-agent-config-row` — individual config row
- `.ms-gallery-filter` — filter button group
- `.ms-gallery-filter-active` — active filter state

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `platform_v2/tools/media_studio/services/agent_media_service.py` | Core service (~150 lines): `agent_generate`, `publish_generation`, `get_agent_gallery`, `orchestration_generate` |
| **Create** | `database/migrations/XXX_media_agent_config.sql` | New `media_agent_config` table + `gallery_visibility` column on `media_generations` |
| **Modify** | `platform_v2/tools/media_studio/routes.py` | 3 admin endpoints + `owner_type` filter on existing generations endpoint |
| **Modify** | `ai_bridge/agent_loop.py` | `media_agent_generation` scheduled job (15-min tick, cron check) |
| **Modify** | `ai_bridge/orchestration_engine.py` | `media_generate` intent route (~3 lines) |
| **Modify** | `platform_v2/tools/media_studio/templates/tools/media_studio/media_studio.html` | Agent gallery filter + admin config panel + JS handlers |
| **Modify** | `platform_v2/tools/media_studio/static/css/media-studio.css` | Agent badge styles, admin panel styles |

## Dependencies

- `croniter` — verify if installed, add to requirements if not

## Scope constraints

- No event-driven triggers (scheduled only)
- No per-agent quotas (simple global + per-agent daily cap)
- No agent-to-agent media sharing
- No media editing by agents (generation only)
- Total: ~400 lines new code, ~100 lines modifications
