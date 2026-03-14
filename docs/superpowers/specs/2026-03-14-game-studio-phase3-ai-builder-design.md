# Game Studio Phase 3: AI Game Builder — Design Spec

## Overview

Upgrade Game Studio's AI from basic chat to a full agent-driven game builder. A 4-stage pipeline (Concept, Level, Mechanics, QA) generates complete playable games from text descriptions. Custom behavior code runs in a sandboxed engine runtime. Enhanced chat with role detection routes requests to specialized system prompts.

**Goal:** Users describe a game in natural language, and a multi-agent pipeline generates a playable game with custom mechanics — pausing at checkpoints for user review. The AI chat becomes a context-aware co-pilot that can generate config patches, custom behavior code, and full code files.

## Scope

Five capabilities:
1. **Build pipeline** — 4-stage agent orchestration: concept, level design, mechanics, QA
2. **Code sandbox** — custom JS behavior functions stored in DB, loaded at runtime with security restrictions
3. **Enhanced chat** — role detection (design/level/mechanics/build), specialized system prompts, whole-project context
4. **Build wizard UI** — description input, pipeline progress, checkpoint approval, playable game
5. **Custom behaviors** — entities can reference named JS functions for unique game logic

## Database Schema

### New table: game_build_sessions

```sql
CREATE TABLE IF NOT EXISTS game_build_sessions (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES game_projects(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    current_stage VARCHAR(30) DEFAULT 'concept',
    status VARCHAR(20) DEFAULT 'running',
    stage_outputs JSONB DEFAULT '{}',
    checkpoint_approved JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
```

Status values: running, checkpoint, completed, failed.
stage_outputs stores each stage's JSON output keyed by stage ID.
checkpoint_approved tracks which checkpoint stages the user has approved.

### Schema change: game_assets

```sql
ALTER TABLE game_assets ADD COLUMN IF NOT EXISTS content TEXT;
```

Stores inline JS code for custom behaviors (asset_type='code').

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_game_build_sessions_project ON game_build_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_game_assets_type ON game_assets(game_id, asset_type);
```

## Game Builder Service

**New file:** platform_v2/tools/game_studio/game_builder_service.py (~200 lines)

### Pipeline stages

Four stages, two with checkpoints:
- concept (checkpoint: true) — game type, theme, mechanics, entities, win condition
- level (checkpoint: false) — complete game config JSON for the chosen game type
- mechanics (checkpoint: false) — custom behavior functions for entities
- qa (checkpoint: true) — issue identification, quality score, suggested fixes

### start_build(user_id, description, game_type=None)

Creates project + build session, runs Stage 1 immediately. Returns session_id + project_id.

### Stage execution

Each stage dispatches to Bridge with specialized system prompt + previous stage outputs as context.

Stage 1 (Concept Agent): outputs game_type, theme, mechanics list, entity catalog, win_condition, difficulty_curve.

Stage 2 (Level Designer): outputs complete game config JSON matching the chosen module schema.

Stage 3 (Mechanics Agent): outputs array of named behavior functions as JS code strings.

Stage 4 (QA Agent): outputs issues list with severity + fix suggestions, quality score 0-100.

### advance_build(session_id)

Runs next stage. If checkpoint stage completes, pauses for user review.

### get_build_status(session_id)

Returns current stage, all stage outputs, checkpoint status.

### apply_build_result(session_id)

Creates game_scenes with final config, stores behaviors as game_assets, updates project status.

## Code Sandbox

Custom behavior functions execute inside the game iframe (already sandboxed from main page). Additional JS-level safety wraps each function in strict mode with dangerous APIs explicitly set to undefined (document, window, fetch, XMLHttpRequest, eval, Function). The function receives only: entity object, engine drawing API, and delta time.

NOTE: This intentionally uses dynamic function construction to create the sandbox. The iframe sandbox attribute + the JS-level API blocking provides defense in depth. All behavior code is AI-generated (not arbitrary user input) and reviewed at the QA checkpoint.

### Engine integration

game-engine.js gains loadBehaviors(behaviors) and runBehavior(name, entity, dt) methods. Modules check entity.behavior in their update loops and delegate to the named behavior if it exists. Error in a behavior is caught and logged, not propagated.

Behaviors loaded via postMessage: type='loadBehaviors', behaviors=[{name, code}].

### Config extension

Entities reference named behaviors in the config JSON: {"behavior": "zigzag_chase"}.

## Enhanced AI Chat

### Role detection

Keyword classification in routes.py:
- Build keywords (build me, create a game, make a game) trigger full pipeline
- Design keywords (theme, color, style, visual) use visual/theme prompt
- Level keywords (map, place, spawn, layout, terrain) use placement prompt
- Mechanics keywords (behavior, speed, ability, code, function) use code generation prompt
- Default: general game-dev assistant

### Whole-project context

Sends game_type, config (truncated 4000 chars), existing behaviors, scene/asset counts to Bridge.

### Response types

AI returns one of:
- config_patch JSON: merged into game config
- behaviors array: stored as code assets, loaded into engine
- Plain text: shown in chat

## API Routes

4 new endpoints in routes.py:

POST /api/ai/build — start pipeline (body: description, game_type)
GET /api/ai/build/session_id — pipeline status + outputs
POST /api/ai/build/session_id/approve — approve checkpoint, continue
POST /api/ai/build/session_id/apply — apply result, create playable game

## Frontend

### Build wizard modal

"Build with AI" button on dashboard. Modal with:
- Step 1: description textarea + game type dropdown + "Build It" button
- Step 2: 4-stage horizontal progress bar with status indicators (pending/running/complete/checkpoint)
- Checkpoint pause: stage output summary + approve/edit buttons
- Step 3: "Your game is ready! Play it now" button

### JS additions (~100 lines)

openBuildWizard, startBuild, pollBuildStatus, approveBuildCheckpoint, completeBuild, renderPipelineProgress

### CSS additions (~20 lines)

gs-build-wizard modal, gs-pipeline-stages horizontal bar, gs-pipeline-stage states (complete/running/checkpoint)

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| Create | database/migrations/161_game_builder.sql | build_sessions table + content column + indexes |
| Create | platform_v2/tools/game_studio/game_builder_service.py | Pipeline orchestrator (~200 lines) |
| Modify | platform_v2/static/js/game-engine.js | Behavior sandbox + loading (~30 lines) |
| Modify | platform_v2/static/js/game-module-shooter.js | Behavior hook in update (~5 lines) |
| Modify | platform_v2/static/js/game-module-explorer.js | Behavior hook in update (~5 lines) |
| Modify | platform_v2/static/js/game-module-builder.js | Behavior hook in update (~5 lines) |
| Modify | platform_v2/tools/game_studio/routes.py | Role detection + 4 build routes (~80 lines) |
| Modify | platform_v2/static/js/game-studio.js | Build wizard + behavior loading (~100 lines) |
| Modify | platform_v2/templates/tools/game_studio.html | Build wizard modal HTML |
| Modify | platform_v2/static/css/game-studio.css | Build wizard + pipeline CSS (~20 lines) |

Total: ~440 lines new, ~125 lines modified

## Dependencies

None new. Uses existing Bridge dispatch.

## Scope constraints

- No sprite generation (text descriptions only)
- No sound generation
- Custom behaviors limited to entity-level logic
- QA agent gives text feedback only (no automated playtesting)
- Sequential pipeline (no parallel agents)
- One build session per project at a time
