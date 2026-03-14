# Game Studio Phase 1: Core UI + Engine + Template — Design Spec

## Overview

Build the Game Studio frontend and a standalone HTML5 Canvas game engine. Ship with a playable top-down shooter template. Users create game projects, configure entities via a form-based editor or Monaco code editor, preview games live in an iframe, and use AI chat to modify game configs via Bridge. Games are cross-platform (mobile + PC) with virtual joystick support.

**Goal:** Transform Game Studio from a backend-only skeleton (15 API endpoints, 4 DB tables, no UI) into a functional game creation tool with a playable top-down shooter template, config-driven editor, Monaco code mode, live preview, and AI chat builder.

## Scope

Five capabilities:
1. **Game engine** — standalone Canvas engine reading JSON config, game loop, entity system, collision, input handling (keyboard + touch)
2. **Top-down shooter template** — player, enemies (chase/patrol/circle AI), bullets, walls, waves, score, game over
3. **Three-panel LCARS UI** — project dashboard, config editor, code editor, live preview
4. **AI chat builder** — Bridge-powered chat that generates config patches or code edits
5. **Cross-platform controls** — PC keyboard+mouse, mobile virtual joystick+touch

## Game Engine

**New file:** `platform_v2/static/js/game-engine.js` (~300 lines)

Standalone HTML5 Canvas engine loaded inside the preview iframe. No dependency on editor UI.

### Architecture

```javascript
class GameEngine {
    constructor(canvas, config) { ... }
    start() { ... }       // begin requestAnimationFrame loop
    stop() { ... }        // pause
    update(dt) { ... }    // physics + logic tick (delta-time based)
    render() { ... }      // draw frame
    handleInput() { ... } // keyboard + touch
}
```

### Config structure

```json
{
  "title": "My Shooter",
  "type": "top_down_shooter",
  "map": { "width": 1200, "height": 800, "backgroundColor": "#111" },
  "player": {
    "x": 600, "y": 400, "speed": 200, "health": 100,
    "size": 20, "color": "#4af", "fireRate": 0.2
  },
  "enemies": [
    { "x": 200, "y": 200, "speed": 80, "health": 30, "size": 16, "color": "#f44", "ai": "chase" }
  ],
  "bullets": { "speed": 400, "size": 4, "color": "#ff0", "damage": 10 },
  "walls": [
    { "x": 100, "y": 100, "width": 200, "height": 20, "color": "#555" }
  ],
  "ui": { "showScore": true, "showHealth": true, "showMinimap": false }
}
```

### Game loop

`requestAnimationFrame` with delta-time. 60fps target. Updates entity positions, checks collisions (AABB), handles bullet spawning/despawning, enemy AI, score tracking.

### Input handling

- **PC**: WASD movement, mouse aim, mouse click shoot
- **Mobile**: left 40% of screen = virtual joystick (touch+drag), right 60% = tap to shoot toward touch position
- Auto-detect: `touchstart` event switches to mobile mode

### Collision

AABB (axis-aligned bounding box). Bullet-enemy, player-enemy, entity-wall collisions. Entities have x, y, size.

### Rendering

Canvas 2D context. Entities as colored circles/rects (no sprites in Phase 1). Camera follows player. HUD overlay for score + health bar.

## Top-Down Shooter Template

Default config created when user starts a "Top-Down Shooter" project:

- Player (blue circle, center spawn)
- 5 enemies (red circles, edge spawn, "chase" AI)
- WASD + mouse aim + click to shoot
- Enemies killed = score, all dead = next wave (more enemies, faster)
- Player health 0 = Game Over + score + Play Again

### Enemy AI types (config-driven)

- `chase` — move directly toward player
- `patrol` — move between two waypoints, chase if player within range
- `circle` — orbit a point, shoot at player periodically (boss)

### Mobile virtual joystick

Two transparent touch zones. Left = movement joystick (circle overlay on touch). Right = tap to shoot. Subtle visual indicators only while touching.

## Three-Panel LCARS UI

### Layout

CSS Grid: `grid-template-columns: 250px 1fr 280px`. Green accent (`--gs-accent: #4f6`).

**Left Panel:** project selector dropdown, scene list, asset list placeholder, new project/scene buttons.

**Center Panel:** tab bar (Config | Code | Preview) + toolbar + content area + AI chat bar.

- **Config tab**: form-based editor with sections (Player, Enemies, Map, Walls, UI). Sliders, inputs, color pickers. Entity cards with add/remove. Changes update config JSON in memory.
- **Code tab**: Monaco editor showing raw config JSON. Power users edit directly.
- **Preview tab**: sandboxed iframe running game-engine.js with current config.

**Right Panel:** entity properties, add entity buttons (+ Enemy, + Wall), game settings, preview controls (play/pause, restart).

### Dashboard (no project open)

Project cards grid + template selector:
- Top-Down Shooter (active)
- Blank Canvas (active)
- Space Explorer (Coming Soon, grayed)
- Base Builder (Coming Soon, grayed)

## AI Chat Builder

### Chat bar

Docked at bottom of center panel. Same pattern as Website Designer.

### Flow

1. User types: "Add 3 patrol enemies at the top"
2. JS sends `POST /api/ai/chat` with `{message, game_id, context: {current_config}}`
3. Backend builds game-dev system prompt with current config
4. Dispatches to Bridge via `archie_bridge` (upgrade from v2 REST)
5. AI returns config patch: `{"config_patch": {"enemies": [...]}}`
6. JS merges patch into config, refreshes preview
7. Chat history persisted per project (`game_projects.chat_history` JSONB)

### Config mode vs Code mode

- Config mode (default): AI generates config patches, applied automatically
- Code mode: AI generates raw JS, shown in Monaco, user reviews
- Toggle via toolbar button

## Database

### Migration

```sql
ALTER TABLE game_projects
ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
```

No new tables — existing 4 tables are sufficient. Scene config stored in `game_scenes.scene_data` JSONB.

### Backend route updates

- Upgrade `ai_chat()` from v2 REST to direct `archie_bridge` import with game-dev system prompt
- Add game object CRUD endpoints (the `game_objects` table exists but has no API)
- Fix template rendering path

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/159_game_studio_phase1.sql` | chat_history column on game_projects |
| **Create** | `platform_v2/static/js/game-engine.js` | Standalone Canvas game engine (~300 lines) |
| **Create** | `platform_v2/static/js/game-studio.js` | Editor UI: dashboard, config editor, tabs, AI chat (~500 lines) |
| **Create** | `platform_v2/static/css/game-studio.css` | LCARS green theme with gs- prefix (~180 lines) |
| **Create** | `platform_v2/templates/tools/game_studio.html` | Three-panel LCARS template (~250 lines) |
| **Modify** | `platform_v2/tools/game_studio/routes.py` | Upgrade AI chat, add object CRUD, fix template (~50 lines changed) |

**Total:** ~1,230 lines new code, ~50 lines modifications

## CSS Design

`gs-` prefix. Green accent `var(--gs-accent, #4f6)`. Antonio font headers, IBM Plex Mono for code. Dark theme matching platform. ~180 lines.

## Dependencies

- Monaco Editor 0.45.0 (CDN)
- Existing backend API (15 endpoints)
- archie_bridge for AI chat

## Scope constraints (Phase 1)

- One template (top-down shooter) — others in Phase 2
- No sprites — shapes only (circles/rects)
- No visual drag-and-drop — config form + code mode
- No multiplayer — single player only
- No export — play in preview iframe only
- No sound/audio
- Editor: tablet-minimum responsive. Games: fully responsive (mobile + PC)
