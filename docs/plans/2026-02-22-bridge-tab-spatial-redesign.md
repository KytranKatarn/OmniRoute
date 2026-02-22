# Bridge Tab Spatial Redesign — Starship Bridge Layout

**Date**: 2026-02-22
**Status**: Approved
**Module**: Bridge Command (`platform_v2/tools/bridge/`)

---

## Summary

Replace the current card-grid Stations tab with a top-down starship bridge view. Stations are positioned spatially around the bridge perimeter. Agents appear as circular avatar nodes with glowing status halos at their assigned stations. A central viewscreen shows live dispatch activity with animated SVG arcs connecting to active stations.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Visual metaphor | Starship bridge top-down | Fits existing LCARS design language |
| Agent display | Avatar nodes + status halos | Visually striking, shows presence and status |
| Viewscreen content | Live dispatch feed | Most dynamic, shows bridge in action |
| Dispatch animation | SVG bezier arcs | High impact, CSS-only animation, no canvas |
| Mobile strategy | Stack vertically | Pragmatic — spatial layout needs width |
| Backend changes | None (fix one field name) | All APIs already exist |

## Desktop Layout (1280px+)

```
┌──────────────────────────────────────────────────────────┐
│                    ┌─ MAIN VIEWSCREEN ─┐                 │
│                    │ Live dispatch feed │                 │
│                    │ + alerts + stats   │                 │
│                    └───────┬────────────┘                 │
│                            │ (SVG dispatch arcs)         │
│   ┌────────┐    ┌─────────┐    ┌─────────┐   ┌────────┐ │
│   │SCIENCE │    │CONSCIOU.│    │SECURITY │   │CREATIVE│ │
│   │ ◉◉     │    │ ◉◉◉     │    │ ◉       │   │ ◉◉     │ │
│   └────────┘    └─────────┘    └─────────┘   └────────┘ │
│                                                          │
│   ┌────────┐    ┌──────────┐   ┌─────────┐   ┌────────┐ │
│   │  ENG   │    │ ★COMMAND │   │   OPS   │   │   HR   │ │
│   │ ◉      │    │  ◉ Cmdr  │   │ ◉◉◉     │   │ ◉◉     │ │
│   └────────┘    └──────────┘   └─────────┘   └────────┘ │
│                                                          │
│           ┌────────┐    ┌────────┐   ┌────────┐         │
│           │ MEDICAL│    │  COMM  │   │AWAY TM │         │
│           │ ◉      │    │ ◉      │   │ ◉      │         │
│           └────────┘    └────────┘   └────────┘         │
└──────────────────────────────────────────────────────────┘
```

Station arrangement uses CSS Grid with named grid areas. The layout adapts to 9-11 stations dynamically. Stations are arranged in 3 rows:
- **Row 1** (back of bridge): 4 stations — flanking the viewscreen
- **Row 2** (middle): 4 stations — COMMAND prominently centered
- **Row 3** (front of bridge): 3 stations — centered

## Station Zones

Each station is a semi-transparent glass panel:

```css
.bridge-station-zone {
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  /* Station color applied via CSS variable --station-color */
}
```

### Station Zone Contents

- **Header**: Station name (LCARS font, uppercase) + pulsing status dot + module count badge
- **Agent area**: Circular avatar nodes arranged in a flex row
- **Footer line**: `N modules | M nodes` compact text
- **Click behavior**: Opens existing station detail panel (reuse current `showStationDetail()`)

## Agent Avatar Nodes

Each agent at a station is a 40px circular avatar with a glowing ring:

```
  ╭───╮
  │ RH│  ← initials or avatar image
  ╰───╯
   ◉     ← status halo ring
```

### Status Halo States

| State | Ring Style | Animation |
|-------|-----------|-----------|
| Active (dispatching) | Bright station color, 3px | `pulse` 1.5s — bright box-shadow oscillation |
| Idle | Dim station color, 1px | `breathe` 4s — slow opacity cycle |
| Error/overloaded | Red, 2px | `alert-flash` 0.8s — red flicker |
| Commander | Gold ring + star badge | `pulse` 2s with gold |

### Agent Node Interaction

- **Hover**: Tooltip with full name, title, station role (primary/backup), current task
- **Click**: Opens agent detail panel (reuse existing functionality)
- **Drag**: Existing drag-drop reassignment (reuse `cursor: grab` pattern)

## Main Viewscreen

Central rectangular panel at the top, styled as a "display screen":

### Visual Treatment
- Dark background with subtle CSS scanline overlay (`repeating-linear-gradient`)
- Thin LCARS-style border with corner accents
- Faint CRT glow effect via `box-shadow`

### Content
- **Event feed**: Last 5 dispatch events, most recent at top
- **Each event row**: `HH:MM:SS  AgentName → STATION  "task summary"  model | duration | ✓/✗`
- **Bottom status bar**: `● N dispatches/hr | XX.X% success | ⚠ N alerts`
- **Auto-refresh**: 30s interval (matches existing pattern)

### Data Source
- `GET /api/dispatch/recent` — existing endpoint
- `GET /api/traffic` — fix field name `total_today` → `total_24h`

## Animated Dispatch Arcs

SVG overlay layer (`position: absolute; pointer-events: none`) covering the entire bridge layout.

### How It Works
1. Dispatch event arrives (via SSE or poll refresh)
2. JS calculates DOM positions: viewscreen center → target station zone center
3. Creates SVG `<path>` with quadratic bezier curve between the two points
4. Path styled with `stroke: var(--station-color)`, `stroke-width: 2px`
5. `stroke-dasharray` + `stroke-dashoffset` animation draws the arc over 0.8s
6. Arc holds for 2s, then fades via `opacity` transition over 1.2s
7. Station zone simultaneously gets a `box-shadow` intensity bump (4s duration)
8. SVG path element removed from DOM after fade completes

### Constraints
- Max 3 concurrent arcs (older ones removed on overflow)
- Arcs disabled on mobile (< 768px)
- `requestAnimationFrame` for position calculations
- Recalculate positions on window resize (debounced 250ms)

## Mobile Layout (< 768px)

### Viewscreen
Compact card at top, showing only the 2 most recent dispatch events in a condensed format:
```
┌───── VIEWSCREEN ─────┐
│ ▶ Nova → ENG  1.2s ✓ │
│ ▶ Kai → SCI   3.4s ✓ │
└──────────────────────┘
```

### Stations
Stack vertically as condensed horizontal rows:
```
┌──────────────────────┐
│ ◉ ENG  ●●  3mod 2nd │  ← station color left border
└──────────────────────┘
```
- Station color as left border accent
- Agent dots (filled = active, hollow = idle) instead of full avatars
- Tap to expand inline with agent details
- No SVG arcs

## CSS Architecture

All new CSS added within the existing `<style>` block in `bridge.html`. Key new selectors:

| Selector | Purpose |
|----------|---------|
| `.bridge-spatial-layout` | CSS Grid container for the whole bridge |
| `.bridge-viewscreen` | Central screen panel |
| `.bridge-viewscreen-feed` | Scrolling event list inside viewscreen |
| `.bridge-viewscreen-statusbar` | Bottom stats bar |
| `.bridge-station-zone` | Positioned station container |
| `.bridge-station-zone.active` | Glowing state when dispatching |
| `.bridge-agent-node` | 40px circular avatar |
| `.bridge-agent-node .halo` | Status ring around avatar |
| `.bridge-dispatch-overlay` | SVG layer for arcs |
| `.bridge-dispatch-arc` | SVG path animation |

### Animations

```css
@keyframes agent-pulse { /* Active agent halo */ }
@keyframes agent-breathe { /* Idle agent halo */ }
@keyframes agent-alert { /* Error agent halo */ }
@keyframes arc-draw { /* SVG stroke-dashoffset */ }
@keyframes scanline { /* Viewscreen CRT effect */ }
```

## JavaScript Changes

### Modified Functions
- `loadStations()` → add viewscreen data fetch, trigger arc animations
- `renderStations()` → replace grid render with spatial layout render
- `createStationCard()` → becomes `createStationZone()` (positioned in grid area)
- `renderAgentChip()` → becomes `renderAgentNode()` (circular avatar with halo)
- `updateStationStats()` → feeds viewscreen status bar instead

### New Functions
- `renderViewscreen(dispatchEvents, trafficStats)` — populate the central screen
- `renderSpatialLayout(stations)` — position station zones in bridge layout
- `createDispatchArc(fromEl, toEl, color)` — SVG arc animation
- `getStationGridArea(stationCode, totalStations)` — dynamic grid-area assignment
- `recalculateArcPositions()` — debounced resize handler

### Removed Functions
- `renderCommandTeamBadges()` — commander info now integrated into COMMAND station zone

## Data Sources (No Backend Changes)

| Endpoint | Use | Notes |
|----------|-----|-------|
| `GET /api/stations` | Station list + agents + modules | Existing |
| `GET /api/stations/coverage` | Node counts per station | Existing |
| `GET /api/dispatch/recent` | Viewscreen feed | Existing |
| `GET /api/traffic` | Throughput stats | Fix `total_today` → `total_24h` in JS |

## What Stays vs. Changes

| Stays | Changes |
|-------|---------|
| All backend API endpoints | Card grid → spatial bridge layout |
| Station data model + colors | Agent chips → circular avatar nodes with halos |
| Agent drag-drop reassignment | No animation → animated dispatch arcs |
| Module links from station | Separate card sections → compact zone footer |
| Station detail panel on click | Same panel, triggered from zone click |
| Expand/collapse for many agents | Same pattern, within zone |
| 30s auto-refresh interval | Same interval, also updates viewscreen |
| i18n keys + translations | All existing keys reused |

## Scope Exclusions

- No 3D/WebGL — pure CSS + SVG
- No new database tables or columns
- No new API endpoints
- No changes to other tabs (Overview, Dispatch, Crew, Network)
- No changes to agent data model
