# Game Studio Phase 2: Visual Scene Editor + Templates — Design Spec

## Overview

Add a visual scene editor and two new game templates (Space Explorer, Base Builder) to Game Studio. Refactor the monolithic game engine into a core + plugin module architecture. The scene editor overlays on the game canvas for click-to-select, drag-to-move, and right-click-to-add entity editing. Each game type is a standalone module that registers with the core engine.

**Goal:** Make game creation visual (drag entities, place buildings, position stars) and ship three distinct playable game types: top-down shooter, Star Control 2-style space explorer, and RimWorld-style colony builder — all sharing a common engine core and visual editor.

## Scope

Four capabilities:
1. **Engine refactor** — core engine with plugin module interface, shared utilities
2. **Visual scene editor** — canvas overlay with select/drag/add/delete, grid snapping, postMessage sync
3. **Space Explorer module** — three-layer navigation (galaxy → solar system → planet), fuel economy, trade, encounters
4. **Base Builder module** — grid colony management, buildings, colonists, resources, day/night, raids

## Engine Refactor

**Modified file:** `platform_v2/static/js/game-engine.js` (~300 lines, refactored)

Core engine provides: canvas, game loop, entity management, camera (pan/zoom), input (keyboard/mouse/touch), collision detection, drawing primitives (circle, rect, text). Delegates `update()`, `render()`, `handleInput()` to the registered module.

### Module interface

Each game type implements:
```javascript
{
    type: 'string',                    // matches config.type
    init(engine, config) {},           // setup from config
    update(engine, dt) {},             // game logic
    render(engine, ctx) {},            // draw frame
    handleInput(engine, input) {},     // input processing
    getEntities() {},                  // entity list for editor
    addEntity(type, x, y) {},          // editor adds entity
    removeEntity(id) {},               // editor removes
    moveEntity(id, x, y) {},           // editor moves
    getConfig() {},                    // export state as config JSON
}
```

Module auto-selected by `config.type`: `top_down_shooter`, `space_explorer`, `base_builder`.

### Module files

- **`game-module-shooter.js`** (~200 lines) — extracted from Phase 1 engine. Same gameplay: player, enemies (chase/patrol/circle AI), bullets, waves, scoring.
- **`game-module-explorer.js`** (~300 lines) — new. Star Control 2 style.
- **`game-module-builder.js`** (~300 lines) — new. RimWorld style.

## Visual Scene Editor

**New file:** `platform_v2/static/js/scene-editor.js` (~250 lines)

### SceneEditor class

Overlays on the game canvas inside the preview iframe. When "Edit Mode" toggled on, game pauses and editor takes over input.

**Modes:**
- **Select** (default): click entity to select (blue outline + handles), drag to move
- **Add**: right-click opens context menu with entity types for current game type. Click canvas to place.
- **Delete**: click selected entity's delete handle to remove

**Grid snapping:** configurable grid size (32px for builder, 1px for shooter/explorer). Toggle on/off. Grid lines drawn as subtle overlay.

**Communication via postMessage:**
- Main page → iframe: `enableEditor`, `disableEditor`, `getEntities`
- Iframe → main page: `entitySelected` (updates properties panel), `configUpdated` (syncs config editor)

## Space Explorer Module

**New file:** `platform_v2/static/js/game-module-explorer.js` (~300 lines)

### Three navigation layers

**Galaxy Map (Layer 1):**
- Black background, ~50-100 star dots colored by type (yellow/blue/red/white)
- Player ship icon at current position
- Fuel range circle (grey oval)
- Click star within range → HyperSpace travel animation → enter solar system
- Pan by dragging
- HUD: fuel gauge, credits, cargo

**Solar System (Layer 2):**
- Central star, planets orbiting at different radii (cosmetic rotation)
- Player ship flies freely (WASD/joystick)
- Click planet → approach → planet view
- Random encounters: pirate ships trigger combat
- "Leave System" → return to galaxy map
- HUD: fuel, credits, cargo, system name

**Planet Surface (Layer 3):**
- Planet stats: type, temperature, gravity, resources
- "Scan" → reveal resource deposits
- "Collect" → gather resources (add to cargo)
- Hazard events: storms, quakes
- "Launch" → return to solar system

### Config structure

```json
{
  "type": "space_explorer",
  "player": {"x": 500, "y": 400, "fuel": 100, "maxFuel": 100, "credits": 500, "cargo": [], "cargoMax": 20},
  "stars": [
    {
      "id": "sol", "name": "Sol", "x": 500, "y": 400, "type": "yellow", "color": "#ff0",
      "planets": [
        {"name": "Earth", "orbitRadius": 80, "size": 10, "color": "#48f", "type": "terran", "resources": {"minerals": 3, "bio": 8}, "hazard": 0.1}
      ]
    }
  ],
  "stations": [{"starId": "sol", "name": "Starbase", "services": ["refuel", "trade", "upgrade"]}],
  "fuelPerJump": 5,
  "encounters": {"pirateChance": 0.15}
}
```

Default template: ~15 stars, 3-5 planets each, one starbase at home star.

## Base Builder Module

**New file:** `platform_v2/static/js/game-module-builder.js` (~300 lines)

### Grid-based colony management

**World:** top-down grid (32px cells), default 40x30 (1280x960). Terrain: grass, rock, water, sand.

**Buildings** (7 types):
- `shelter` — houses colonists (cap 4)
- `farm` — produces food per cycle (needs water nearby)
- `workshop` — crafts tools, speeds tasks
- `storage` — increases resource cap
- `wall` — blocks enemies
- `turret` — auto-attacks in range
- `well` — provides water

**Colonists:** auto-assign to tasks (gather/build/farm/defend). Priority: eat > defend > task. Simple BFS pathfinding. New colonists arrive with shelter capacity + food surplus.

**Resources:** wood, stone, metal, food. HUD counters.

**Day/night:** visual dimming every 60s (1 cycle). Farms produce per cycle. Threats arrive every N cycles.

**Threats:** raiders approach from map edges, attack buildings/colonists. Turrets auto-fire. Colonists flee to shelters.

**Controls:** PC: click cell to select, click building button → click to place, WASD pan. Mobile: tap, pinch zoom, drag pan.

### Config structure

```json
{
  "type": "base_builder",
  "map": {"width": 40, "height": 30, "cellSize": 32},
  "terrain": [[0,0,1,2], ...],
  "buildings": [{"type": "shelter", "gridX": 5, "gridY": 5}],
  "colonists": [{"id": 1, "name": "Alex", "gridX": 6, "gridY": 5, "task": "idle", "health": 100}],
  "resources": {"wood": 50, "stone": 30, "metal": 10, "food": 20},
  "resourceNodes": [{"type": "tree", "gridX": 3, "gridY": 2, "amount": 10}],
  "threats": {"raidInterval": 8, "raidSize": 3, "raidScaling": 1.2},
  "cycle": 0, "cycleLength": 60
}
```

Default template: small clearing, trees + rocks border, one shelter, 3 colonists, first raid at cycle 8.

## Frontend Updates

### game-studio.js modifications (~80 lines added)
- Edit Mode toggle button → sends `postMessage` to iframe
- Listen for iframe messages: `entitySelected` → properties panel, `configUpdated` → sync config
- Template selector: Space Explorer + Base Builder cards active (remove "Coming Soon")
- Default config constants for all 3 templates

### game_studio.html modifications
- Edit Mode button in toolbar
- Building palette in right panel (visible for base_builder only)
- Entity context menu for right-click add

### game-studio.css modifications (~30 lines)
- `.gs-editor-active` — green border glow on preview
- `.gs-context-menu` — right-click popup
- `.gs-building-palette` — building type buttons

### Preview iframe loading
Loads all files: `game-engine.js`, `game-module-shooter.js`, `game-module-explorer.js`, `game-module-builder.js`, `scene-editor.js`

### Backend: routes.py
Update `create_game()` to seed default configs for `space_explorer` and `base_builder` templates (same pattern as existing shooter default).

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Refactor** | `platform_v2/static/js/game-engine.js` | Core engine + plugin architecture (~300 lines) |
| **Create** | `platform_v2/static/js/game-module-shooter.js` | Shooter module (~200 lines) |
| **Create** | `platform_v2/static/js/game-module-explorer.js` | Space Explorer module (~300 lines) |
| **Create** | `platform_v2/static/js/game-module-builder.js` | Base Builder module (~300 lines) |
| **Create** | `platform_v2/static/js/scene-editor.js` | Visual scene editor (~250 lines) |
| **Modify** | `platform_v2/static/js/game-studio.js` | Edit mode, templates, postMessage (~80 lines) |
| **Modify** | `platform_v2/templates/tools/game_studio.html` | Edit button, palette, context menu |
| **Modify** | `platform_v2/static/css/game-studio.css` | Editor styles (~30 lines) |
| **Modify** | `platform_v2/tools/game_studio/routes.py` | Default configs for new templates |

**Total:** ~1,350 lines new, ~150 refactored, ~110 modified

## Dependencies

None new. All Canvas 2D API.

## Scope constraints

- Shapes/colors only (no sprite assets)
- No save/load mid-game
- No sound
- Explorer combat is simplified (not full shooter module crossover)
- Builder pathfinding is BFS (not A*)
- No multiplayer
- No procedural generation
