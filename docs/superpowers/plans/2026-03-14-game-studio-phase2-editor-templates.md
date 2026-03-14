# Game Studio Phase 2: Visual Editor + Templates — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the game engine into a plugin architecture, add a visual scene editor overlay, and ship Space Explorer (Star Control 2 style) and Base Builder (RimWorld style) templates — giving users three playable game types with visual editing.

**Architecture:** Core `game-engine.js` refactored to delegate update/render to registered modules. Each game type (`game-module-shooter.js`, `game-module-explorer.js`, `game-module-builder.js`) is a standalone module implementing a common interface. `scene-editor.js` overlays on the game canvas for click/drag/add entity editing, communicating with the editor UI via postMessage. All files load inside the preview iframe.

**Tech Stack:** HTML5 Canvas 2D, vanilla JS, postMessage API

**Key patterns from Phase 1:**
- Game engine runs inside preview iframe, receives config via `postMessage({type:'loadConfig', config})`
- `game-studio.js` (991 lines) is the editor IIFE with API_BASE='/tools/game-studio'
- `game_studio.html` has three-panel layout (left: scenes, center: config/code/preview, right: properties)
- Config stored in `game_scenes.scene_data` JSONB
- `create_game()` in routes.py seeds default scene when template selected
- IMPORTANT: No innerHTML for dynamic content — createElement/textContent only
- Iframe HTML built by `refreshPreview()` in game-studio.js

**Spec clarifications (from review):**
- Explorer simplified combat: HP bar exchange — player and pirate auto-fire at each other, first to 0 HP loses. No dodging, no bullets — timed encounter.
- Builder "water nearby" = orthogonal adjacent cells (4-directional, not diagonal)
- Colonist arrival: checked once per cycle, requires shelter free capacity + food > 10
- SceneEditor instantiated on iframe load, dormant until `enableEditor` received
- Script load order: engine → modules → editor

---

## Task 1: Refactor Game Engine — Core + Plugin Interface

**Files:**
- Rewrite: `platform_v2/static/js/game-engine.js`
- Create: `platform_v2/static/js/game-module-shooter.js`

- [ ] **Step 1: Read current game-engine.js to understand the full structure**

The current file is ~694 lines with GameEngine class containing all shooter logic. We need to split it into core engine (shared) + shooter module (extracted).

- [ ] **Step 2: Rewrite game-engine.js as core engine (~300 lines)**

The core engine keeps:
- `GameEngine` class with constructor, start, stop, game loop (requestAnimationFrame + delta time)
- Camera system: `{x, y, zoom, follow(entity), screenToWorld(sx,sy), worldToScreen(wx,wy)}`
- Input system: keyboard (keys dict), mouse (x,y,down), touch (joystick left, aim right), auto-detect mobile
- Drawing primitives: `drawCircle(x,y,r,color)`, `drawRect(x,y,w,h,color)`, `drawText(text,x,y,opts)`, `drawLine(x1,y1,x2,y2,color,width)`
- Collision: `checkCircleCollision(a,b)` (circle vs circle), `checkRectCollision(a,b)` (AABB)
- HUD helpers: `drawBar(x,y,w,h,value,max,color)` for health/fuel bars

Adds new plugin interface:
- `registerModule(module)` — stores module, calls `module.init(this, this.config)`
- `update(dt)` delegates to `this._module.update(this, dt)`
- `render()` delegates to `this._module.render(this, this.ctx)`
- Module registry: `GameEngine.MODULES = {}` — modules register themselves via `GameEngine.registerModuleType(type, ModuleClass)`

postMessage listener updated:
```javascript
window.addEventListener('message', function(e) {
    if (e.data.type === 'loadConfig') {
        var config = e.data.config;
        var ModuleClass = GameEngine.MODULES[config.type];
        if (!ModuleClass) { console.error('Unknown game type:', config.type); return; }
        window._engine = new GameEngine(canvas, config);
        window._engine.registerModule(new ModuleClass());
        window._engine.start();
    }
    if (e.data.type === 'enableEditor' && window._sceneEditor) { window._sceneEditor.enable(); }
    if (e.data.type === 'disableEditor' && window._sceneEditor) { window._sceneEditor.disable(); }
    if (e.data.type === 'restart' && window._engine) { window._engine._module.init(window._engine, window._engine.config); }
});
```

- [ ] **Step 3: Extract shooter module to game-module-shooter.js (~200 lines)**

Move all shooter-specific code from old engine into a module object:
- `init(engine, config)` — create player, enemies, bullets, walls from config
- `update(engine, dt)` — player movement, shooting, bullet update, enemy AI (chase/patrol/circle), collision checks, wave logic, game over check
- `render(engine, ctx)` — draw walls, enemies, bullets, player, HUD (score, health, wave)
- `spawnWave(num)` — enemy wave spawning
- `getEntities()` — return player + enemies + walls as entity list
- `addEntity(type, x, y)` — add enemy or wall at position
- `removeEntity(id)` — remove by id
- `moveEntity(id, x, y)` — update position
- `getConfig()` — export current state back to config JSON

Register: `GameEngine.registerModuleType('top_down_shooter', ShooterModule);`

- [ ] **Step 4: Verify shooter still works**

Update `refreshPreview()` in game-studio.js to load both files in the iframe:
```javascript
html += '<script src="/static/js/game-engine.js"><\/script>';
html += '<script src="/static/js/game-module-shooter.js"><\/script>';
```

Test: create a new shooter project, verify it plays in preview.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/game-engine.js platform_v2/static/js/game-module-shooter.js
git commit -m "refactor(game-studio): split engine into core + shooter module plugin"
```

---

## Task 2: Space Explorer Module

**Files:**
- Create: `platform_v2/static/js/game-module-explorer.js`

- [ ] **Step 1: Write the Space Explorer module (~300 lines)**

### State management

```javascript
var ExplorerModule = {
    type: 'space_explorer',
    _layer: 'galaxy',  // 'galaxy', 'system', 'planet'
    _player: null,
    _stars: [],
    _currentStar: null,
    _currentPlanet: null,
    _planets: [],       // current system's planets
    _orbitAngle: 0,     // cosmetic planet rotation
    _encounter: null,   // active combat encounter
};
```

### init(engine, config)
Parse config: player (x, y, fuel, credits, cargo), stars array, stations. Set layer to 'galaxy'.

### update(engine, dt) — branch by layer

**Galaxy layer:**
- No movement (click-to-travel). Just animate stars (subtle twinkle).
- If travel in progress: animate ship moving toward target star, consume fuel on arrival, switch to 'system' layer.

**System layer:**
- WASD/joystick moves player ship within system bounds
- Planets orbit: `_orbitAngle += dt * 0.5`
- Check proximity to planets: if player within planet.size + 20px → show "Land" prompt
- Random encounter check: on system entry, `Math.random() < config.encounters.pirateChance` → start encounter

**Planet layer:**
- No movement. Scan/collect buttons handled via click.

**Encounter (combat):**
- Simple HP exchange: player and pirate each have HP bar
- Both auto-fire every 0.5s, dealing 10 damage
- Player can "Flee" (costs 5 fuel) or fight to the end
- Winner gets credits/resources. Loser = game over or pirate destroyed.
- Render: two ships facing each other, HP bars above, damage flash animation

### render(engine, ctx) — branch by layer

**Galaxy:**
- Black bg, draw each star as colored circle (size by type)
- Draw fuel range circle (grey, dashed)
- Draw player ship icon at current position
- Highlight hovered star (name + fuel cost label)
- HUD: fuel bar, credits, cargo count

**System:**
- Dark bg with star glow center
- Draw orbit lines (grey circles), planets on orbits at current angle
- Draw stations (diamond shape)
- Draw player ship
- HUD: system name, fuel, credits

**Planet:**
- Planet close-up (large colored circle with surface pattern)
- Stats panel: type, resources, hazard level
- Buttons rendered as colored rects with text: "Scan", "Collect", "Launch"

**Encounter:**
- Two ships, HP bars, "Fight" / "Flee" buttons

### Entity interface for editor
- `getEntities()` — returns stars (galaxy layer) or planets (system layer)
- `addEntity('star', x, y)` — add star at galaxy position
- `addEntity('planet', x, y)` — add planet to current system
- `moveEntity(id, x, y)` — reposition star or planet
- `getConfig()` — export full config

Register: `GameEngine.registerModuleType('space_explorer', ExplorerModule);`

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-module-explorer.js
git commit -m "feat(game-studio): add Space Explorer module — galaxy, system, planet layers"
```

---

## Task 3: Base Builder Module

**Files:**
- Create: `platform_v2/static/js/game-module-builder.js`

- [ ] **Step 1: Write the Base Builder module (~300 lines)**

### Constants
```javascript
var CELL_SIZE = 32;
var TERRAIN = { GRASS: 0, ROCK: 1, WATER: 2, SAND: 3 };
var TERRAIN_COLORS = { 0: '#3a5', 1: '#776', 2: '#36a', 3: '#ca8' };
var BUILDING_DEFS = {
    shelter: { color: '#88f', size: 1, cost: { wood: 20, stone: 10 } },
    farm:    { color: '#6b4', size: 1, cost: { wood: 10 } },
    workshop:{ color: '#a86', size: 1, cost: { wood: 15, stone: 15 } },
    storage: { color: '#aa6', size: 1, cost: { wood: 25 } },
    wall:    { color: '#555', size: 1, cost: { stone: 5 } },
    turret:  { color: '#f44', size: 1, cost: { metal: 10, wood: 5 } },
    well:    { color: '#4af', size: 1, cost: { stone: 15 } },
};
```

### init(engine, config)
Parse terrain grid, buildings, colonists, resource nodes, resources, threats config. Init cycle counter.

### update(engine, dt)

**Cycle timer:** increment `_cycleTimer += dt`. When >= `config.cycleLength`:
- Reset timer, increment `config.cycle`
- Farms produce: for each farm, if adjacent orthogonal cell has water or well → `resources.food += 2`
- Colonist arrival: if any shelter has free capacity (count colonists in shelter's cell < 4) AND `resources.food > 10` → spawn new colonist near shelter
- Threat check: if `config.cycle % config.threats.raidInterval === 0` → spawn raiders from map edge

**Colonist AI (per colonist per frame):**
- If threat active + colonist not in shelter → pathfind to nearest shelter (BFS)
- Else if assigned task 'gather' → move toward nearest resource node, collect when adjacent
- Else if assigned task 'build' → move toward pending build site
- Else → idle (wander near shelter)
- Movement: move 1 cell per 0.5s toward BFS-computed next cell

**Raiders:** move toward nearest building at 1 cell/s. Attack on contact (reduce building HP). Turrets auto-fire at raiders within 5 cells (deal damage per second).

**Resource gathering:** colonist adjacent to resource node → extract 1 unit per second until node depleted.

### render(engine, ctx)

1. Draw terrain grid (colored cells)
2. Draw resource nodes (tree=green triangle, rock=grey pentagon, ore=brown square)
3. Draw buildings (colored squares with icon letter: S=shelter, F=farm, W=workshop, etc.)
4. Draw colonists (small white circles with task indicator color)
5. Draw raiders (red circles with X)
6. Draw selection highlight (if cell selected)
7. Draw day/night overlay: `ctx.fillStyle = 'rgba(0,0,20,' + nightAlpha + ')'`
8. HUD: resources (wood/stone/metal/food counters), cycle number, colonist count, threat timer

### Building placement
- `placeBuilding(type, gridX, gridY)` — check cost, check cell empty, deduct resources, add to buildings array
- Called from editor or from click on grid when build mode active

### BFS pathfinding
```javascript
function bfs(grid, startX, startY, targetX, targetY) {
    // Simple BFS on grid, returns next cell toward target
    // Obstacles: water, rock terrain, buildings (except destination)
}
```

### Entity interface
- `getEntities()` — buildings + colonists + resource nodes
- `addEntity('building_shelter', gridX, gridY)` — place building (type after underscore)
- `addEntity('colonist', gridX, gridY)` — spawn colonist
- `addEntity('resource_tree', gridX, gridY)` — place resource node
- `removeEntity(id)` — remove
- `moveEntity(id, gridX, gridY)` — snap to grid
- `getConfig()` — export full state

Register: `GameEngine.registerModuleType('base_builder', BuilderModule);`

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-module-builder.js
git commit -m "feat(game-studio): add Base Builder module — grid colony, buildings, colonists, raids"
```

---

## Task 4: Scene Editor

**Files:**
- Create: `platform_v2/static/js/scene-editor.js`

- [ ] **Step 1: Write the scene editor (~250 lines)**

### SceneEditor class
```javascript
class SceneEditor {
    constructor(engine) {
        this.engine = engine;
        this.active = false;
        this.selectedEntity = null;
        this.dragging = false;
        this.dragOffset = { x: 0, y: 0 };
        this.gridSnap = engine.config.type === 'base_builder' ? 32 : 1;
        this.showGrid = engine.config.type === 'base_builder';
        this.contextMenu = null;
    }
}
```

**`enable()`:**
- `this.active = true`
- Pause engine: `this.engine.stop()`
- Bind mouse/touch handlers
- Draw initial editor overlay

**`disable()`:**
- `this.active = false`
- Clear selection, hide context menu
- Unbind handlers
- Resume: `this.engine.start()`

**`onMouseDown(e)`:**
- Convert screen coords to world coords via engine camera
- Hit-test entities: find entity closest to click point within selection radius
- If entity found: select it (store ref), start drag
- If no entity: deselect

**`onMouseMove(e)`:**
- If dragging: update entity position (snap to grid if enabled)
- If not dragging: highlight hovered entity

**`onMouseUp(e)`:**
- End drag
- If entity moved: call `module.moveEntity(id, newX, newY)`, sync config
- Send `postMessage({type: 'configUpdated', config: module.getConfig()})` to parent

**`onRightClick(e)`:**
- Prevent default
- Show context menu at click position
- Menu items based on game type:
  - Shooter: Add Enemy (chase), Add Enemy (patrol), Add Enemy (circle), Add Wall
  - Explorer (galaxy): Add Star; Explorer (system): Add Planet
  - Builder: Add Shelter, Add Farm, Add Workshop, Add Wall, Add Turret, Add Tree, Add Rock
- Click menu item → `module.addEntity(type, worldX, worldY)`, sync config, hide menu

**`render(ctx)`:** Called each frame when active:
- Draw grid lines if `showGrid`
- Draw selection outline (blue rect/circle) on selected entity
- Draw resize handles (small squares at corners)
- Draw delete handle (red X at top-right of selection)
- Draw context menu if open

**`deleteSelected()`:**
- `module.removeEntity(selectedEntity.id)`, sync config, deselect

**Config sync:** after every edit operation, call:
```javascript
window.parent.postMessage({type: 'configUpdated', config: this.engine._module.getConfig()}, '*');
```

**Entity selection notification:**
```javascript
window.parent.postMessage({type: 'entitySelected', entity: {...}}, '*');
```

**Init on iframe load (at bottom of file):**
```javascript
window.addEventListener('message', function(e) {
    if (e.data.type === 'loadConfig' && window._engine) {
        window._sceneEditor = new SceneEditor(window._engine);
    }
});
```

Actually, the editor should init AFTER engine starts. Add to the engine's loadConfig handler:
```javascript
// After engine.start():
window._sceneEditor = new SceneEditor(window._engine);
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/scene-editor.js
git commit -m "feat(game-studio): add visual scene editor — select, drag, add, delete entities"
```

---

## Task 5: Frontend Updates — Editor UI + Templates + Backend

**Files:**
- Modify: `platform_v2/static/js/game-studio.js`
- Modify: `platform_v2/templates/tools/game_studio.html`
- Modify: `platform_v2/static/css/game-studio.css`
- Modify: `platform_v2/tools/game_studio/routes.py`

- [ ] **Step 1: Update game-studio.js**

**Update `refreshPreview()`** to load all module files + scene editor:
```javascript
function refreshPreview() {
    var iframe = document.getElementById('gsPreviewFrame');
    var html = '<!DOCTYPE html><html><head><style>*{margin:0;padding:0;}body{overflow:hidden;background:#000;}canvas{display:block;}</style></head><body>';
    html += '<canvas id="gameCanvas"></canvas>';
    html += '<scr' + 'ipt src="/static/js/game-engine.js"></scr' + 'ipt>';
    html += '<scr' + 'ipt src="/static/js/game-module-shooter.js"></scr' + 'ipt>';
    html += '<scr' + 'ipt src="/static/js/game-module-explorer.js"></scr' + 'ipt>';
    html += '<scr' + 'ipt src="/static/js/game-module-builder.js"></scr' + 'ipt>';
    html += '<scr' + 'ipt src="/static/js/scene-editor.js"></scr' + 'ipt>';
    html += '</body></html>';
    iframe.srcdoc = html;
    iframe.onload = function() {
        iframe.contentWindow.postMessage({type: 'loadConfig', config: _gameConfig}, '*');
    };
}
```

**Add Edit Mode toggle:**
```javascript
var _editMode = false;
window.toggleEditMode = function() {
    _editMode = !_editMode;
    var iframe = document.getElementById('gsPreviewFrame');
    iframe.contentWindow.postMessage({type: _editMode ? 'enableEditor' : 'disableEditor'}, '*');
    document.querySelector('[data-action="edit-mode"]').classList.toggle('active', _editMode);
    toast(_editMode ? 'Edit Mode ON — click entities to edit' : 'Edit Mode OFF');
};
```

**Listen for iframe messages:**
```javascript
window.addEventListener('message', function(e) {
    if (e.data.type === 'configUpdated') {
        _gameConfig = e.data.config;
        if (_activeTab === 'config') renderConfigEditor();
        // Sync Monaco if code tab
    }
    if (e.data.type === 'entitySelected') {
        // Update properties panel with entity details
        updateEntityProperties(e.data.entity);
    }
});
```

**Add default configs for new templates:**

`DEFAULT_EXPLORER_CONFIG` — 15 stars with 3-5 planets each, one starbase at home star, player starts with 100 fuel + 500 credits.

`DEFAULT_BUILDER_CONFIG` — 40x30 grid, grass terrain with tree/rock border, one shelter at center, 3 colonists, starting resources (wood:50, stone:30, metal:10, food:20).

**Update `createGame()`** to use the right default config based on template.

**Update template selector** — remove `gs-coming-soon` class from Space Explorer and Base Builder cards, add onclick handlers.

- [ ] **Step 2: Update game_studio.html**

Add to toolbar:
```html
<button class="gs-toolbar-btn" data-action="edit-mode" onclick="toggleEditMode()">Edit Mode</button>
```

Add building palette in right panel (shown for base_builder):
```html
<div id="gsBuildPalette" class="gs-build-palette" style="display:none;">
  <div class="gs-prop-group-title">Buildings</div>
  <!-- Building buttons rendered by JS based on game type -->
  <div id="gsBuildButtons"></div>
</div>
```

Update template cards: remove `gs-coming-soon` from Space Explorer and Base Builder.

- [ ] **Step 3: Update game-studio.css**

Add:
```css
.gs-editor-active { box-shadow: inset 0 0 4px var(--gs-accent, #4f6); }
.gs-context-menu {
    position: absolute; z-index: 100;
    background: var(--gs-bg, #0d0d1a); border: 1px solid var(--gs-accent, #4f6);
    border-radius: 4px; padding: 0.25rem 0; min-width: 150px;
}
.gs-context-menu-item {
    padding: 0.3rem 0.75rem; font-size: 0.7rem; color: var(--gs-text, #aab);
    cursor: pointer;
}
.gs-context-menu-item:hover { background: rgba(68, 255, 102, 0.08); color: var(--gs-accent, #4f6); }
.gs-build-palette { padding: 0.5rem; }
.gs-build-btn {
    display: block; width: 100%; padding: 0.3rem; margin-bottom: 0.25rem;
    border: 1px solid var(--gs-border, #232); background: transparent;
    color: var(--gs-text, #aab); font-size: 0.7rem; cursor: pointer;
    text-align: left; border-radius: 3px;
}
.gs-build-btn:hover { border-color: var(--gs-accent, #4f6); color: var(--gs-accent, #4f6); }
```

- [ ] **Step 4: Update routes.py — add default configs for new templates**

In `create_game()`, after the existing shooter default, add:
```python
elif template == "space_explorer" and game_id:
    default_config = { ... }  # 15 stars, planets, starbase
    cur.execute("INSERT INTO game_scenes ...")
elif template == "base_builder" and game_id:
    default_config = { ... }  # grid, terrain, buildings, colonists
    cur.execute("INSERT INTO game_scenes ...")
```

- [ ] **Step 5: Commit all frontend + backend changes**

```bash
git add platform_v2/static/js/game-studio.js platform_v2/templates/tools/game_studio.html platform_v2/static/css/game-studio.css platform_v2/tools/game_studio/routes.py
git commit -m "feat(game-studio): add edit mode, explorer+builder templates, building palette"
```

---

## Task 6: Integration Test

**Files:**
- Create: `/tmp/test_game_studio_phase2.py`

- [ ] **Step 1: Write integration test**

Test coverage:
- All 5 new/modified JS files exist: game-engine.js, game-module-shooter.js, game-module-explorer.js, game-module-builder.js, scene-editor.js
- game-engine.js has: GameEngine, registerModule, registerModuleType, MODULES
- game-module-shooter.js has: ShooterModule, top_down_shooter
- game-module-explorer.js has: ExplorerModule, space_explorer, galaxy, system, planet
- game-module-builder.js has: BuilderModule, base_builder, BUILDING_DEFS, bfs
- scene-editor.js has: SceneEditor, enable, disable, onMouseDown, onRightClick
- game-studio.js has: toggleEditMode, DEFAULT_EXPLORER_CONFIG, DEFAULT_BUILDER_CONFIG
- HTML has: edit-mode button, gsBuildPalette
- CSS has: .gs-context-menu, .gs-build-palette, .gs-build-btn
- No innerHTML in any new JS files

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_game_studio_phase2.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_game_studio_phase2.py
```

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 7: Deploy + Git Push + Dev HQ

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

- `store_memory` — Game Studio Phase 2 complete
- `log_decision` — plugin module architecture, postMessage editor sync
