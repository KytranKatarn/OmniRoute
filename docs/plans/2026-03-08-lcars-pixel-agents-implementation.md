# LCARS Pixel Agents Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Canvas 2D station deck with pixel art crew characters below the WebGL Neural Core sphere on the Consciousness Dashboard.

**Architecture:** Single `pixel-crew.js` file containing `PixelSpriteFactory` (programmatic 32x32 sprite generation), `PixelCrew` class (deck renderer, character state machine, BFS pathfinding, event bus integration). CSS file for deck positioning. Template and JS wiring changes are minimal — hooks into existing `_neuralEvents` bus and crew manifest API.

**Tech Stack:** Canvas 2D, vanilla JS, existing `_neuralEvents` event bus, existing crew manifest API

---

## Task Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Create pixel-crew.css (deck canvas positioning + glow) | Create: `static/css/pixel-crew.css` |
| 2 | Create pixel-crew.js — sprite factory | Create: `static/js/pixel-crew.js` |
| 3 | Create pixel-crew.js — deck renderer + consoles | Modify: `static/js/pixel-crew.js` |
| 4 | Create pixel-crew.js — character state machine + pathfinding | Modify: `static/js/pixel-crew.js` |
| 5 | Create pixel-crew.js — event integration + public API | Modify: `static/js/pixel-crew.js` |
| 6 | Update template (deck canvas + script/css refs) | Modify: `consciousness_dashboard.html` |
| 7 | Update consciousness.js (PixelCrew wiring) | Modify: `consciousness.js` |
| 8 | Visual testing + polish | Possibly modify: JS/CSS tuning |
| 9 | Final commit + deploy + Dev HQ update | Push + restart |

---

### Task 1: Create pixel-crew.css

**Files:**
- Create: `platform_v2/static/css/pixel-crew.css`

The CSS positions the deck canvas inside `.nc-hero`, handles the glow bridge between sphere and deck, and provides responsive/reduced-motion overrides.

```css
/* ============================================================
   Pixel Crew — Station deck Canvas 2D overlay
   Positioned below the WebGL Neural Core sphere in .nc-hero
   ============================================================ */

/* ---- Deck canvas ---- */
.pc-deck {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 40%;
  z-index: 3;
  pointer-events: none;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
}

/* ---- Glow bridge — sphere bloom bleeds into deck ---- */
.pc-glow-bridge {
  position: absolute;
  left: 0;
  right: 0;
  height: 80px;
  bottom: 40%;
  z-index: 2;
  background: radial-gradient(
    ellipse at 50% 100%,
    rgba(139, 92, 246, 0.15) 0%,
    transparent 70%
  );
  pointer-events: none;
}

/* ---- Responsive ---- */
@media (max-width: 767px) {
  .pc-deck {
    height: 35%;
  }
  .pc-glow-bridge {
    height: 40px;
  }
}

@media (max-width: 500px) {
  .pc-deck {
    height: 30%;
  }
}

/* ---- Reduced motion ---- */
@media (prefers-reduced-motion: reduce) {
  .pc-glow-bridge {
    display: none;
  }
}
```

---

### Task 2: Create pixel-crew.js — Sprite Factory

**Files:**
- Create: `platform_v2/static/js/pixel-crew.js`

This task creates the IIFE module shell and the `PixelSpriteFactory` that programmatically draws 32x32 pixel art characters. Each agent gets a sprite sheet with all animation frames.

The factory must:
- Accept agent config (name, station, skinTone, hairStyle, hairColor)
- Derive visual traits deterministically from agent name hash when not specified
- Draw each frame onto an offscreen canvas
- Return an ImageBitmap or canvas with all frames in a horizontal strip
- Support these animation rows: idle (4 frames), walk (6 frames), working (4 frames), beam-in (4 frames), beam-out (4 frames), celebrate (3 frames) = 25 frames total per agent

Station colors (must match `neural-core.js` `STATION_COLORS`):
```javascript
var STATION_COLORS = {
  COMMAND: "#8b5cf6", ANALYTICS: "#06b6d4", CREATIVE: "#ec4899",
  ENGINEERING: "#f59e0b", COMMUNICATIONS: "#3b82f6", RESEARCH: "#22c55e",
  SECURITY: "#ef4444", LOGISTICS: "#f97316", DIPLOMATIC: "#a78bfa",
  OPERATIONS: "#14b8a6"
};
```

Skin tone presets (6): `["#f5d0a9", "#e8b88a", "#d4956b", "#b8764e", "#8d5c3a", "#5c3a21"]`
Hair color presets (6): `["#2c1810", "#5c3317", "#8b6914", "#c4a35a", "#d4d4d4", "#4a90d9"]`

The sprite drawing approach:
- Use a 32x32 pixel grid
- Draw body (torso, legs) as rectangular pixel blocks
- Station-colored shoulders/chest panel (4-6px wide band across upper torso)
- Small bright pixel for comm badge on chest
- Head with skin tone, simple eyes (2px), hair on top
- Boots (dark, 2px tall at bottom)
- For walking frames: alternate leg positions
- For working frames: seated pose with arms forward
- For beam effects: vertical sparkle lines with increasing/decreasing opacity
- For celebrate: arms raised position

Key implementation detail: use `ctx.fillRect()` for individual pixels at the sprite's native 32x32 resolution. The deck renderer handles scaling up with `imageSmoothingEnabled = false`.

**IIFE structure:**
```javascript
(function() {
"use strict";

// Constants, station colors, presets...

// PixelSpriteFactory
var PixelSpriteFactory = { /* ... */ };

// (Tasks 3-5 add more here)

// Expose
window.PixelCrew = PixelCrew;      // added in Task 5
window.PixelSpriteFactory = PixelSpriteFactory;  // for debugging
})();
```

---

### Task 3: Create pixel-crew.js — Deck Renderer + Consoles

**Files:**
- Modify: `platform_v2/static/js/pixel-crew.js`

Add the deck renderer inside the IIFE. This handles:

**Tile grid:** 20 columns × 8 rows. Each tile is 32×32 at base resolution. The canvas is sized to fill the `.pc-deck` container and the grid is centered and scaled to fit.

**Floor rendering:**
- Fill with dark background `rgba(10, 10, 30, 0.7)`
- Draw subtle hex grid pattern in dim cyan `rgba(10, 42, 58, 0.4)` — hexagonal outlines every 2 tiles
- Radial glow from top-center `rgba(139, 92, 246, 0.12)` fading outward (sphere light bleeding down)

**6 station consoles** arranged in semicircle. Each console:
- Position: predefined tile coords in semicircle layout:
  ```javascript
  var CONSOLE_LAYOUT = [
    { id: "conversations", label: "CONV",     col: 5,  row: 2 },
    { id: "code",          label: "CODE",     col: 14, row: 2 },
    { id: "vault",         label: "VAULT",    col: 2,  row: 4 },
    { id: "repos",         label: "REPOS",    col: 17, row: 4 },
    { id: "learned",       label: "LEARN",    col: 5,  row: 6 },
    { id: "sessions",      label: "SESSIONS", col: 14, row: 6 }
  ];
  ```
- Draw as 2×2 tile pixel art desk: dark base with lighter screen panel on top, station-colored glow border
- Small text label below each console (LCARS font style, drawn via fillText)

**Core pad:** Center tile (col 10, row 1) — a glowing circular pad where agents beam in/out. Drawn as concentric circles with pulsing opacity.

**Render loop:**
- `requestAnimationFrame` with frame skip targeting 30fps
- Clear canvas → draw floor → draw consoles → draw core pad → draw characters (Task 4)
- Pause on `document.hidden` (visibilitychange)

**Resize handling:**
- Listen for `resize` event on window
- Recalculate canvas dimensions and scale factor
- Canvas resolution = container size × devicePixelRatio (capped at 2)

---

### Task 4: Create pixel-crew.js — Character State Machine + Pathfinding

**Files:**
- Modify: `platform_v2/static/js/pixel-crew.js`

**Character object:**
```javascript
{
  name: "nexus",
  displayName: "Jin Park",
  station: "COMMAND",
  sprite: null,           // ImageBitmap from factory (set on creation)
  state: "idle",          // idle | walking | working | beam_in | beam_out | celebrate
  tileCol: 10,            // current tile position
  tileRow: 1,
  targetCol: null,        // walking destination
  targetRow: null,
  path: [],               // BFS path (array of {col, row})
  pathIndex: 0,
  moveProgress: 0,        // 0-1 interpolation between tiles
  frame: 0,               // current animation frame index
  frameTimer: 0,          // accumulator for frame timing
  facing: 1,              // 1 = right, -1 = left
  homeConsole: null,      // assigned console id (e.g. "conversations")
  opacity: 1.0
}
```

**BFS pathfinding:**
- Grid: 20×8 boolean walkability map
- Console tiles (2×2 each) are NOT walkable
- Core pad (1 tile) IS walkable (beam point)
- Standard 4-directional BFS (up/down/left/right)
- Returns array of `{col, row}` from start to end
- If no path found, character teleports (shouldn't happen on 20×8 with few obstacles)

**Character movement:**
- Walk speed: 3 tiles/second
- Each frame: advance `moveProgress` by `dt * 3`
- When `moveProgress >= 1`: snap to next tile in path, reset progress
- Set `facing` based on horizontal direction of movement
- When path complete: transition to target state (idle at home, working at console, etc.)

**Animation timing:**
- Idle: 250ms per frame (4 frames, loop)
- Walking: 120ms per frame (6 frames, loop while moving)
- Working: 300ms per frame (4 frames, loop)
- Beam-in: 150ms per frame (4 frames, play once then switch to idle/walking)
- Beam-out: 150ms per frame (4 frames, play once then remove character)
- Celebrate: 200ms per frame (3 frames, play once then switch to idle)

**State transitions:**
```
beam_in → idle (at home console) or walking (to assigned console)
idle → walking (when job starts, needs to move to console)
walking → working (arrived at console)
working → celebrate (job completed) → idle or walking (back to home)
working → idle (job failed, with red flash)
idle → beam_out (agent removed)
```

**Drawing characters:**
- For each character: calculate pixel position from tile + moveProgress interpolation
- Source rect from sprite sheet based on state + frame
- Draw with `ctx.drawImage()` at scaled position
- Flip horizontally if `facing === -1` (use `ctx.scale(-1, 1)`)
- Apply opacity for beam effects
- Draw name label above character head (small, station-colored text)

**Anti-overlap:** When assigning a walk target, check if another character is already at that tile. If so, offset to an adjacent walkable tile.

---

### Task 5: Create pixel-crew.js — Event Integration + Public API

**Files:**
- Modify: `platform_v2/static/js/pixel-crew.js`

**PixelCrew class public API:**

```javascript
var PixelCrew = {
  create: function(container, opts) { /* returns PixelCrew instance or null */ },
  // Instance methods:
  addAgent: function(agent) { /* agent = {name, display_name, station, status} */ },
  removeAgent: function(name) { /* beam-out then remove */ },
  setAgentWorking: function(name, nodeId) { /* walk to console, work animation */ },
  setAgentIdle: function(name) { /* stop working, walk home */ },
  celebrateAgent: function(name) { /* celebrate animation */ },
  updateAgentCount: function(count) { /* update internal count for HUD */ },
  destroy: function() { /* cleanup everything */ }
};
```

**`create(container, opts)`:**
- `container` = the `.nc-hero` element (deck canvas appended inside it)
- `opts.consoles` = array of `{id, label, color}` matching knowledge nodes (optional, defaults to CONSOLE_LAYOUT)
- Creates `<canvas class="pc-deck">` and `<div class="pc-glow-bridge">`, appends to container
- Initializes tile grid, console positions, render loop
- Returns instance object with methods above
- If Canvas 2D not supported, returns null

**Event bus integration (`_neuralEvents`):**
When PixelCrew is created, it subscribes to events on `window._neuralEvents`:

| Event | Handler |
|-------|---------|
| `job:started` | `setAgentWorking(data.agent, data.nodeId)` |
| `job:completed` | `celebrateAgent(data.agent)` then `setAgentIdle(data.agent)` |
| `job:failed` | Flash character red, `setAgentIdle(data.agent)` |
| `knowledge:added` | Nearest idle character does head-tilt animation (reuse idle frames with Y offset) |
| `agent:dispatched` | `addAgent(data.agent)` |

**Event bus subscription pattern:**
```javascript
if (window._neuralEvents) {
  window._neuralEvents.on("job:started", function(data) {
    if (data.agent) instance.setAgentWorking(data.agent, data.nodeId);
  });
  // ... etc
}
```

**Cleanup (`destroy()`):**
- Cancel animation frame
- Remove canvas and glow-bridge elements
- Unsubscribe from all `_neuralEvents` listeners
- Null out all sprite references (allow GC)
- Clear character array

---

### Task 6: Update consciousness_dashboard.html

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Change 1 — Line 8:** Add `pixel-crew.css` link after `neural-core.css`:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/pixel-crew.css') }}">
```

**Change 2 — Line 2594:** Add `pixel-crew.js` script after `neural-core.js`:
```html
<script src="{{ url_for('static', filename='js/pixel-crew.js') }}"></script>
```

That's it for the template — the deck canvas is created dynamically by `PixelCrew.create()` in JavaScript, not in the HTML.

---

### Task 7: Update consciousness.js

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Change 1 — Line 11:** Add `_pixelCrew` global after `_knowledgePollTimer`:
```javascript
var _pixelCrew = null;
```

**Change 2 — Inside `loadNeuralCore()`, after `_neuralCore = core;` (line 260):**
Add pixel crew initialization:
```javascript
        _neuralCore = core;
        // Initialize pixel crew deck
        if (typeof PixelCrew !== "undefined") {
          _pixelCrew = PixelCrew.create(document.getElementById("neuralCoreHero"));
        }
        _loadAgentsIntoCore();
```

**Change 3 — Inside `_loadAgentsIntoCore()` (line 313-329):**
After adding agents to Neural Core, also add them to Pixel Crew:
```javascript
function _loadAgentsIntoCore() {
  if (!_neuralCore) return;
  fetch("/tools/bridge/api/bridge/crew-manifest").then(function(r) { return r.json(); }).then(function(data) {
    if (!data.success) return;
    var manifest = data.manifest || [];
    manifest.forEach(function(agent) {
      if (agent.status === "active" || agent.status === "paused") {
        _neuralCore.addAgent({
          name: agent.name,
          display_name: agent.display_name || agent.name,
          station: agent.home_station || agent.station || "COMMAND",
          status: agent.status
        });
        if (_pixelCrew) {
          _pixelCrew.addAgent({
            name: agent.name,
            display_name: agent.display_name || agent.name,
            station: agent.home_station || agent.station || "COMMAND",
            status: agent.status
          });
        }
      }
    });
  }).catch(function() {});
}
```

**Change 4 — Inside `loadTabData()` cleanup block (line 122-126):**
Add pixel crew destruction alongside Neural Core:
```javascript
  if (tab !== "dashboard" && _neuralCore) {
    _neuralCore.destroy();
    _neuralCore = null;
    if (_pixelCrew) { _pixelCrew.destroy(); _pixelCrew = null; }
    if (_knowledgePollTimer) { clearInterval(_knowledgePollTimer); _knowledgePollTimer = null; }
  }
```

The event-driven updates (job:started, job:completed, etc.) are handled automatically via the `_neuralEvents` bus subscription inside `pixel-crew.js` — no changes needed to `checkActiveJobs()`.

---

### Task 8: Visual Testing + Polish

Load `http://192.168.1.200:3000/tools/consciousness` (login: `admin` / `Kyt$13ran2025`).

**Checklist:**
- [ ] Deck canvas renders in bottom 40% of hero section
- [ ] Glow bridge gradient visible between sphere and deck
- [ ] Dark floor with hex grid pattern visible
- [ ] 6 station consoles visible in semicircle with correct labels and colors
- [ ] Core pad visible at top-center with pulsing glow
- [ ] Pixel characters rendered with station-colored uniforms
- [ ] Characters are at their assigned consoles (idle animation)
- [ ] Pixel art is crisp (no anti-aliasing blur)
- [ ] Characters face correct direction
- [ ] Name labels above character heads
- [ ] Start a job → character walks to relevant console, plays working animation
- [ ] Meanwhile Neural Core stream fires above (existing behavior)
- [ ] Job completes → character celebrates, sphere pulses, character walks back
- [ ] Canvas pauses when tab hidden (check with console.log in render loop)
- [ ] Switch to Knowledge tab → deck canvas removed (no memory leak)
- [ ] Switch back to Dashboard → deck recreated with characters
- [ ] Mobile (<768px) → deck shrinks, max 6 characters
- [ ] Fallback: if `PixelCrew` undefined, Neural Core still works alone

**Common tuning knobs:**
- Deck height: `.pc-deck { height: 40% }` (try 35-45%)
- Floor opacity: `rgba(10, 10, 30, 0.7)` alpha value
- Glow bridge intensity: `rgba(139, 92, 246, 0.15)` alpha
- Walk speed: `WALK_SPEED = 3` tiles/sec (try 2-4)
- Character scale: draw at 2x or 3x native 32px
- Console glow radius: radius of station-colored shadow
- Hex grid line opacity: `rgba(10, 42, 58, 0.4)` alpha

---

### Task 9: Final Commit + Deploy

1. `git push`
2. `docker compose restart archie_platform`
3. MCP: `complete_task`, `update_project_understanding`, `log_decision`
4. Final verification in browser
