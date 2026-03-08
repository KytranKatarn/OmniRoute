# LCARS Pixel Agents Design

## Overview

Add pixel art agent characters to the Consciousness Dashboard. A 2D Canvas station deck renders below the existing WebGL Neural Core sphere, showing LCARS-themed crew members walking between station consoles, working on jobs, and reacting to real-time events. The sphere stays untouched — pixel characters ground the abstract 3D visuals with personality.

## Goals

1. **Crew presence** — See which agents are active, idle, or working as pixel characters on a station deck
2. **Event-driven animation** — Characters react to the same events as the Neural Core (job starts/completions, knowledge additions, agent dispatches)
3. **LCARS space aesthetic** — Star Trek-inspired uniforms, transporter beam effects, station consoles, hex grid floor
4. **Reusable sprite system** — Sprite factory designed for future use in Bridge Command and other modules
5. **Zero new dependencies** — Pure Canvas 2D, no libraries

## Architecture

### Hero Container Split

The existing `.nc-hero` (65vh) is split visually:
- **Top ~60%**: WebGL Neural Core sphere (existing, untouched)
- **Bottom ~40%**: Canvas 2D station deck (new layer)
- Sphere's bloom glow bleeds down via radial gradient connecting the two

### Files

- **Create**: `static/js/pixel-crew.js` — Sprite factory, character state machine, deck renderer, pathfinding
- **Create**: `static/css/pixel-crew.css` — Deck canvas positioning, glow effects
- **Modify**: `consciousness_dashboard.html` — Add deck canvas inside `.nc-hero`, load new JS/CSS
- **Modify**: `consciousness.js` — Wire crew manifest into pixel-crew, sync events

### Data Flow (No New APIs)

```
Crew Manifest API (15s poll, already exists)
    ↓
consciousness.js (diff detection, already exists)
    ↓
_neuralEvents.emit("job:started", {agent, node})
    ↓                          ↓
pixel-crew.js                 neural-core.js
(walk to console,             (stream fires,
 working animation)            agent orb brightens)
    ↓
[job completes]
    ↓
_neuralEvents.emit("job:completed", {agent})
    ↓                          ↓
pixel-crew.js                 neural-core.js
(celebrate animation)         (pulse flash)
```

## Sprite Factory

### `PixelSpriteFactory`

Programmatic Canvas 2D sprite generation. Draws each agent's sprite sheet onto an offscreen canvas at runtime. No external image assets.

### Character Template (32x32 per frame)

- LCARS space crew uniform: fitted jumpsuit with station-colored shoulder/chest panels
- Comm badge on chest (bright pixel)
- Boots, belt line, rank pips on collar (1-3 pixels)
- Unique per agent: skin tone (6 presets), hair style (8 presets), hair color (6 presets)
- Identity derived from deterministic hash of agent name → consistent visuals

### Animation States

| State | Frames | Description |
|-------|--------|-------------|
| Idle | 4 | Breathing + occasional blink, standing at ease |
| Walking | 6 | Left/right walk cycle (flip for direction) |
| Working | 4 | Seated at console, hands on keyboard, screen glow |
| Dispatched-in | 4 | Transporter beam-in sparkle effect |
| Dispatched-out | 4 | Transporter beam-out dissolve |
| Celebrate | 3 | Fist pump / arms up (job completion) |

~25 frames per agent, each 32x32. One sprite sheet ~800x32px per agent.

### Station-Colored Uniforms

| Station | Shoulder Color |
|---------|---------------|
| COMMAND | Gold #FFD700 |
| ANALYTICS | Cyan #06b6d4 |
| CREATIVE | Pink #ec4899 |
| ENGINEERING | Amber #f59e0b |
| COMMUNICATIONS | Blue #3b82f6 |
| RESEARCH | Green #22c55e |
| SECURITY | Red #ef4444 |
| LOGISTICS | Orange #f97316 |
| DIPLOMATIC | Purple-light #a78bfa |
| OPERATIONS | Teal #14b8a6 |

## Station Deck

### Tile Grid

~20x8 tiles (640x256px base), scaled to fill hero width. Each tile 32x32.

### Floor

- Dark translucent background (rgba(10, 10, 30, 0.7))
- Subtle hex grid lines in dim cyan (#0a2a3a) — LCARS scanner aesthetic
- Soft radial glow from center-top where sphere sits above

### Console Layout

6 station consoles in semicircle, mapped 1:1 to knowledge nodes:

```
         [sphere glow]
              ◉ CORE PAD
        ◉CONV          ◉CODE
     ◉VAULT                ◉REPOS
        ◉LEARN          ◉SESSIONS
```

Each console: pixel art desk with screen (2x2 tiles), station-colored glow, small label.

### Character Behavior

| Trigger | Action |
|---------|--------|
| Page load | Agents beam in at assigned station console |
| Idle | Stand/sit at station, breathing animation |
| `job:started` | Walk to relevant console, sit, working animation |
| `job:completed` | Stand, celebrate (1s), walk back to home station |
| `job:failed` | Stand, brief red flash, walk back |
| `knowledge:added` | Nearest idle agent looks up (head tilt toward sphere) |
| `agent:dispatched` | Beam-in at core pad, walk to assigned station |
| Agent removed | Walk to core pad, beam-out |

### Pathfinding

Simple BFS on 20x8 = 160 tiles. <1ms per path. Characters avoid overlapping (wait or reroute).

## 3D Orb Coexistence

Agent orbs in the Neural Core **stay**. They represent abstract AI presence in the knowledge sphere. Pixel characters below represent the "physical crew" on the station deck. Both react to the same events simultaneously — orb brightens above while character works below.

## Event Mapping

| Event | Pixel Crew | Neural Core (existing) |
|-------|-----------|----------------------|
| `job:started` | Walk to console, work | Stream fires, orb brightens |
| `job:completed` | Celebrate | Pulse flash |
| `job:failed` | Red flash | Red ripple |
| `knowledge:added` | Head tilt up | Node burst |
| `agent:dispatched` | Beam-in effect | New orb appears |

## Performance

- Canvas 2D at 30fps (pixel art sweet spot, `requestAnimationFrame` with frame skip)
- Max 13 characters (matches MAX_LOADED_MODELS)
- Sprite sheets generated once, cached as ImageBitmap
- BFS on 160 tiles = <1ms
- Deck render per frame: ~2ms
- Combined with WebGL: well within 16ms budget
- Pauses on `visibilitychange`

## Fallbacks

| Scenario | Behavior |
|----------|----------|
| WebGL + Canvas 2D work | Full experience |
| WebGL fails | Deck renders standalone with static starfield bg |
| Canvas 2D fails | No deck, existing crew cards suffice |
| `prefers-reduced-motion` | Static poses, no animation, no beam effects |

## Mobile (<768px)

- Deck shrinks with hero (50vh)
- Max 6 characters shown (hide barracked/swap)
- Console labels hidden, just glowing dots
- Sprites stay 32px (crisp at 1x)

## Cleanup

`PixelCrew.destroy()` called alongside `NeuralCore.destroy()` on tab switch. Releases ImageBitmap sheets, stops animation loop, removes canvas.

## Future Reuse

This sprite system is designed for expansion:
- **Bridge Command station map** — same sprites on a bridge deck layout
- **Other modules** — any view that shows agent activity
- **New animation states** — easy to add frames to the factory
