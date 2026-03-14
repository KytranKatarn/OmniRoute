# Game Studio Phase 1: Core UI + Engine + Template — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Game Studio frontend with a standalone HTML5 Canvas game engine, playable top-down shooter template, three-panel LCARS editor with config/code/preview modes, and AI chat builder via Bridge.

**Architecture:** `game-engine.js` is a standalone Canvas engine loaded in a preview iframe — reads JSON config from `game_scenes.scene_data`. `game-studio.js` handles the editor UI (dashboard, config editor, Monaco, AI chat). `game_studio.html` provides the three-panel LCARS layout. Routes.py upgraded with Bridge AI chat and template defaults.

**Tech Stack:** Flask (existing), HTML5 Canvas, Monaco Editor 0.45.0 (CDN), vanilla JS

**Key patterns from existing backend:**
- Blueprint: `game_studio_bp`, prefix `/tools/game-studio`
- Template: `platform_v2/templates/tools/game_studio.html` (doesn't exist yet)
- No `static_folder` on blueprint — JS/CSS in `platform_v2/static/`
- Project API: `GET/POST /api/games`, `GET/PUT/DELETE /api/games/<id>`
- Scene API: `GET/POST /api/games/<id>/scenes`
- `game_projects`: user_id, title, engine_type, template, status, progress, settings (JSONB)
- `game_scenes`: game_id, name, scene_order, scene_data (JSONB — stores game config)
- AI chat: currently uses v2 REST (broken) — must upgrade to `archie_bridge` direct import
- Bridge call: `import sys; sys.path.insert(0, "/mnt/archie_brain/ai_bridge"); from archie_bridge import archie_bridge as ai_bridge; result = ai_bridge(prompt, system_prompt, user_id, enable_memory=False)`
- Module category: `PLACEHOLDERS_FUTURE` → needs changing to `CREATIVE_TOOLS`
- Base template blocks: `extra_css`, `content`, `extra_js`
- IMPORTANT: All DOM construction must use createElement/textContent — no innerHTML

---

## Task 1: Migration + Module Activation

**Files:**
- Create: `database/migrations/159_game_studio_phase1.sql`
- Modify: `platform_v2/module_registry.py`

- [ ] **Step 1: Write migration**

```sql
-- Migration 159: Game Studio Phase 1 — chat history
-- Idempotent: safe to run multiple times

ALTER TABLE game_projects
ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/159_game_studio_phase1.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/159_game_studio_phase1.sql
```

- [ ] **Step 3: Update module_registry.py**

Change Game Studio's category from `ModuleCategory.PLACEHOLDERS_FUTURE` to `ModuleCategory.CREATIVE_TOOLS`. Remove `"placeholder"` from tags.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/159_game_studio_phase1.sql platform_v2/module_registry.py
git commit -m "feat(game-studio): add migration 159 + activate module in CREATIVE_TOOLS"
```

---

## Task 2: Game Engine

**Files:**
- Create: `platform_v2/static/js/game-engine.js`

- [ ] **Step 1: Write the standalone game engine (~300 lines)**

This file runs INSIDE the preview iframe. It has zero dependencies on the editor. The iframe HTML loads it via a script tag.

Key components:

**`GameEngine` class:**
```javascript
class GameEngine {
    constructor(canvas, config) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.config = config;
        this.entities = { player: null, enemies: [], bullets: [], walls: [] };
        this.score = 0;
        this.wave = 1;
        this.gameOver = false;
        this.keys = {};
        this.mouse = { x: 0, y: 0, down: false };
        this.touch = { active: false, moveX: 0, moveY: 0, aimX: 0, aimY: 0 };
        this.lastTime = 0;
        this.lastShot = 0;
    }
}
```

**`start()`** — set canvas size to config.map dimensions, init player/enemies/walls from config, bind input listeners, start `requestAnimationFrame` loop.

**`update(dt)`** — called each frame with delta time in seconds:
1. Update player position from input (WASD or touch joystick) × player.speed × dt
2. Clamp player to map bounds and wall collisions
3. Handle shooting: if mouse down or touch aim, create bullet every `player.fireRate` seconds
4. Update bullets: move in direction × bullet.speed × dt, remove if off-screen
5. Update enemies by AI type:
   - `chase`: move toward player at enemy.speed × dt
   - `patrol`: move between waypoints, chase if player within 200px
   - `circle`: orbit spawn point, shoot at player every 2s
6. Check collisions:
   - Bullet→enemy: reduce enemy health, remove bullet, if health ≤ 0 → remove enemy + score
   - Enemy→player: reduce player health by contact (once per second cooldown)
   - Entity→wall: push entity out of wall
7. Check wave complete: if no enemies → increment wave, spawn more enemies
8. Check game over: player health ≤ 0

**`render()`** — called each frame:
1. Clear canvas with map.backgroundColor
2. Draw walls as rects
3. Draw enemies as circles (color from config, size from config)
4. Draw bullets as small circles
5. Draw player as circle
6. Draw HUD: score (top-left), health bar (top-left below score), wave number (top-right)
7. If gameOver: draw "GAME OVER" + score + "Click to Restart" overlay

**Input handlers:**
- `keydown`/`keyup` → `this.keys[e.key] = true/false`
- `mousemove` → `this.mouse.x/y` (relative to canvas)
- `mousedown`/`mouseup` → `this.mouse.down`
- `touchstart`/`touchmove`/`touchend` — left 40% = movement joystick, right 60% = aim+shoot

**Virtual joystick rendering (mobile):**
When touch is active, draw a subtle circle at touch origin + line to current touch position on the movement side.

**`spawnWave(waveNum)`** — create enemies based on wave: `count = 3 + waveNum * 2`, speed increases slightly per wave, mix of AI types.

**`restart()`** — reset score, health, wave, respawn player + enemies.

**Initialization (at bottom of file):**
```javascript
// Auto-init when loaded in iframe
window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'loadConfig') {
        var canvas = document.getElementById('gameCanvas');
        if (!canvas) {
            canvas = document.createElement('canvas');
            canvas.id = 'gameCanvas';
            document.body.appendChild(canvas);
            document.body.style.margin = '0';
            document.body.style.overflow = 'hidden';
            document.body.style.background = '#000';
        }
        window._engine = new GameEngine(canvas, e.data.config);
        window._engine.start();
    }
});
```

The editor sends config to the iframe via `postMessage`. The engine receives it and starts.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-engine.js
git commit -m "feat(game-studio): add standalone Canvas game engine with top-down shooter"
```

---

## Task 3: CSS File

**Files:**
- Create: `platform_v2/static/css/game-studio.css`

- [ ] **Step 1: Write CSS (~180 lines)**

`gs-` prefix. Green accent `var(--gs-accent, #4f6)`. Same three-panel pattern as Website Designer but with green theme.

Key classes:
- `.gs-layout` — CSS Grid `grid-template-columns: 250px 1fr 280px`
- `.gs-panel`, `.gs-panel-header`, `.gs-panel-body`
- `.gs-scene-list`, `.gs-scene-item`
- `.gs-tabs`, `.gs-tab`, `.gs-tab.active`
- `.gs-toolbar`, `.gs-toolbar-btn`, `.gs-toolbar-btn.active`
- `.gs-config-editor` — form container
- `.gs-config-section` — collapsible section with title
- `.gs-config-section-title` — Antonio font, green accent, clickable to collapse
- `.gs-entity-card` — enemy/wall card with remove button
- `.gs-preview-container`, `.gs-preview-container iframe`
- `.gs-ai-bar`, `.gs-ai-input`, `.gs-ai-send`
- `.gs-dashboard`, `.gs-project-card`, `.gs-template-card`, `.gs-coming-soon`
- `.gs-modal`, `.gs-modal-content`, `.gs-modal-title`
- `.gs-toast`
- `.gs-prop-group`, `.gs-prop-group-title`, `.gs-prop-row`, `.gs-prop-input`

Design tokens: `--gs-bg: #0d0d1a`, `--gs-border: #232`, `--gs-accent: #4f6`, `--gs-text: #aab`

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/css/game-studio.css
git commit -m "feat(game-studio): add LCARS game studio CSS with gs- prefix"
```

---

## Task 4: HTML Template

**Files:**
- Create: `platform_v2/templates/tools/game_studio.html`

- [ ] **Step 1: Read base.html to confirm block names**

Confirm: `extra_css`, `content`, `extra_js`.

- [ ] **Step 2: Write the template (~250 lines)**

Extends `base.html`. Structure:

**Dashboard view (`#gsDashboard`):**
- Title "Game Studio"
- Project grid with "New Game" card
- Template gallery: Top-Down Shooter (active), Blank Canvas (active), Space Explorer (coming soon), Base Builder (coming soon)

**Builder view (`#gsBuilder`, display:none):**

Left panel:
- Project selector dropdown + New Scene button
- Scene list container (`#gsSceneList`)

Center panel:
- Tab bar: Config | Code | Preview
- Toolbar: play/stop for preview, save button
- Config tab (`#gsConfigTab`): scrollable config editor form
- Code tab (`#gsCodeTab`, display:none): Monaco container
- Preview tab (`#gsPreviewTab`, display:none): iframe for game engine
- AI chat bar at bottom: input + send button

Right panel:
- Properties header + collapse button
- Game settings (title, engine_type)
- Entity quick-add buttons (+ Enemy, + Wall)
- Preview controls (restart button)

**Modals:** New Game (name + template select), New Scene (name)

**Toast div**

**Scripts:** Monaco CDN loader + game-studio.js (NOT game-engine.js — that loads inside the iframe)

- [ ] **Step 3: Commit**

```bash
git add platform_v2/templates/tools/game_studio.html
git commit -m "feat(game-studio): add three-panel LCARS builder HTML template"
```

---

## Task 5: Editor JavaScript — Core + Dashboard + Scenes

**Files:**
- Create: `platform_v2/static/js/game-studio.js`

- [ ] **Step 1: Write core state, API helper, dashboard, scene management (~200 lines)**

IIFE wrapping all code. `API_BASE = '/tools/game-studio'`.

**State:** `_currentGameId`, `_currentGame`, `_scenes`, `_sceneMap`, `_currentScene`, `_gameConfig`, `_monacoEditor`, `_editorTab`, `_aiHistory`

**Dashboard:** `loadDashboard()` — fetch `GET /api/games`, render project cards. Template cards with onclick for Top-Down Shooter + Blank Canvas. Coming soon cards grayed out.

**Create game:** `window.createGame()` — read modal inputs, POST `/api/games` with title + template. If template is `top_down_shooter`, create a default scene with the shooter config JSON. Open project.

**Open project:** `openProject(gameId)` — hide dashboard, show builder. Load game + scenes. Auto-open first scene.

**Scene list:** `renderSceneList()` — list scenes in left panel. Click loads scene config.

**Load scene:** `loadScene(sceneId)` — set `_gameConfig` from `scene.scene_data`. Render config editor. If Monaco open, update model. Refresh preview.

**Default shooter config:** A constant `DEFAULT_SHOOTER_CONFIG` with the full JSON from the spec (player, 5 enemies, bullets, walls, UI settings).

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-studio.js
git commit -m "feat(game-studio): add JS core — dashboard, project CRUD, scene management"
```

---

## Task 6: Editor JavaScript — Config Editor + Monaco + Preview

**Files:**
- Modify: `platform_v2/static/js/game-studio.js` (append inside IIFE)

- [ ] **Step 1: Append config editor, Monaco, preview, tabs (~200 lines)**

**Config editor:** `renderConfigEditor()` — read `_gameConfig` and build form sections using createElement:
- Player section: speed (range 50-500), health (number), size (range 5-50), color (input type=color), fireRate (range 0.05-1.0)
- Enemies section: list of enemy cards. Each: x, y (number), speed, health, size, color, AI type (select: chase/patrol/circle). Remove button per card. "Add Enemy" button.
- Map section: width, height (number), backgroundColor (color)
- Walls section: list of wall cards. Each: x, y, width, height, color. Remove/add.
- UI section: showScore, showHealth, showMinimap (checkboxes)

All inputs have `onchange`/`oninput` handlers that update `_gameConfig` directly and call `debouncePreviewRefresh()`.

**Add/remove entities:**
- `addEnemy()` — push default enemy to `_gameConfig.enemies`, re-render section
- `removeEnemy(index)` — splice, re-render
- Same for walls

**Monaco (Code tab):** `initMonaco(callback)` — same CDN pattern as Website Designer. Create editor in `#gsCodeContainer`. When Code tab active, set model to `JSON.stringify(_gameConfig, null, 2)`. On model change, parse JSON and update `_gameConfig` + refresh preview.

**Preview (Preview tab):** The iframe loads a minimal HTML page that includes `game-engine.js`. The editor sends config to the iframe via `postMessage`:

```javascript
function refreshPreview() {
    var iframe = document.getElementById('gsPreviewFrame');
    // Build iframe content with game-engine.js
    var html = '<!DOCTYPE html><html><head><style>body{margin:0;overflow:hidden;background:#000;}</style></head><body>';
    html += '<canvas id="gameCanvas"></canvas>';
    html += '<script src="/static/js/game-engine.js"><\/script>';
    html += '</body></html>';
    iframe.srcdoc = html;
    // After iframe loads, send config
    iframe.onload = function() {
        iframe.contentWindow.postMessage({type: 'loadConfig', config: _gameConfig}, '*');
    };
}
```

**Tab switching:** `setTab(tab)` — show/hide Config/Code/Preview containers. When switching to Code, sync Monaco model. When switching to Preview, refresh.

**Save:** `saveScene()` — PUT `/api/games/<id>/scenes` doesn't exist (only POST). Need to use the existing update pattern. Actually, check: the spec says scene_data is stored on scenes, but update scene endpoint may not exist. If not, save to `game_projects.settings` JSONB as fallback, or use create_scene to replace.

Actually, re-check: the backend has `game_scenes` CRUD but only GET list + POST create. No PUT/DELETE for scenes. So either:
1. Save config by updating game_projects.settings JSONB via `PUT /api/games/<id>`
2. Or delete+recreate the scene

Use option 1: save `_gameConfig` to `game_projects.settings` via `PUT /api/games/<id>` with `{settings: _gameConfig}`. The scene's `scene_data` is set on creation only.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-studio.js
git commit -m "feat(game-studio): add config editor, Monaco code mode, Canvas preview"
```

---

## Task 7: Editor JavaScript — AI Chat + Init

**Files:**
- Modify: `platform_v2/static/js/game-studio.js` (append + close IIFE)

- [ ] **Step 1: Append AI chat, toast, properties, init (~100 lines)**

**AI Chat:** `sendAiChat()`:
1. Read input value
2. Add to history display
3. POST `/api/ai/chat` with `{message, game_id: _currentGameId, context: {current_config: JSON.stringify(_gameConfig)}}`
4. On response: try to parse `config_patch` from response. If found, deep-merge into `_gameConfig`. Else try to extract JSON from code block in response text. Else show response as text.
5. Re-render config editor + refresh preview
6. Add AI response to history

**Config merge:** `mergeConfig(base, patch)` — for each key in patch, if both are objects recurse, if patch value is array replace entirely, else overwrite.

**Toast, properties panel, init:** Same patterns as Website Designer.

**Init:** `DOMContentLoaded` → `initMonaco()` → `loadDashboard()`

Close the IIFE.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/game-studio.js
git commit -m "feat(game-studio): add AI chat, config merge, init"
```

---

## Task 8: Backend — Upgrade AI Chat + Template Defaults

**Files:**
- Modify: `platform_v2/tools/game_studio/routes.py`

- [ ] **Step 1: Read routes.py to find ai_chat() and create_game()**

- [ ] **Step 2: Upgrade ai_chat() to use direct Bridge**

Replace the `requests.post("http://localhost:3000/...")` call with:
```python
import sys
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
from archie_bridge import archie_bridge as ai_bridge

# Build game-dev system prompt
system_prompt = (
    "You are a game development AI assistant. The user is building a game.\n"
    "When asked to modify the game, respond with a JSON object containing a 'config_patch' key.\n"
    "The config_patch should contain only the fields to change/add.\n"
    "For adding enemies, include the full enemy object in an 'enemies' array.\n"
    "Current game config:\n" + context_config
)
result = ai_bridge(prompt=message, system_prompt=system_prompt, user_id=current_user.id, enable_memory=False)
response_text = result.get("response", "") if isinstance(result, dict) else str(result)
```

Also add chat history persistence (same pattern as Website Designer):
```python
# After successful response, save history
game_id = data.get("game_id")
if game_id:
    # Load existing, append, save (last 50)
```

- [ ] **Step 3: Update create_game() to set default template config**

When `template == "top_down_shooter"`, after creating the game project, also create a default scene with the shooter config JSON in `scene_data`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/game_studio/routes.py
git commit -m "feat(game-studio): upgrade AI chat to Bridge + add template defaults"
```

---

## Task 9: Integration Test

**Files:**
- Create: `/tmp/test_game_studio.py`

- [ ] **Step 1: Write integration test**

Test coverage:
- Module loads (routes registered, >10 routes)
- Template file exists and not empty
- HTML has key IDs: gsDashboard, gsBuilder, gsSceneList, gsConfigTab, gsCodeTab, gsPreviewTab, gsPreviewFrame, gsAiInput, gsProjectGrid, gsNewGameModal
- Monaco CDN in HTML
- game-studio.js and game-studio.css referenced
- game-engine.js exists with GameEngine class
- JS has key functions: loadDashboard, openProject, renderConfigEditor, refreshPreview, sendAiChat, setTab, saveScene
- CSS has key classes: .gs-layout, .gs-panel, .gs-config-editor, .gs-tabs, .gs-preview-container, .gs-ai-bar, .gs-dashboard, .gs-project-card
- DB: game_projects has chat_history column
- DB: game_projects, game_scenes, game_objects tables exist
- Module category is not PLACEHOLDERS_FUTURE

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_game_studio.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_game_studio.py
```

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 10: Deploy + Git Push + Dev HQ Update

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

Use MCP tools:
- `create_project` for Game Studio
- `store_memory` — Game Studio Phase 1 complete
- `log_decision` — config-driven engine, postMessage for iframe communication, module activated as CREATIVE_TOOLS
