# Bridge Tab Spatial Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the card-grid Stations tab with a top-down starship bridge spatial layout featuring avatar nodes, a central viewscreen, and animated SVG dispatch arcs.

**Architecture:** Pure frontend change to `bridge.html` — new CSS for spatial layout + viewscreen + agent nodes, rewritten JS render functions, SVG overlay for dispatch arcs. No backend changes. All existing API endpoints reused as-is.

**Tech Stack:** HTML/CSS Grid, SVG path animations, vanilla JS, existing Lucide icons, existing LCARS design tokens.

**Design doc:** `docs/plans/2026-02-22-bridge-tab-spatial-redesign.md`

**Security note:** This template uses innerHTML for rendering station zones and viewscreen events. All dynamic data originates from authenticated API endpoints (own platform DB), not user-submitted content. Agent names, station codes, and module names are all server-controlled values from the `agents` and `bridge_stations` tables. The existing bridge.html template already uses this same innerHTML pattern throughout (~40 instances across all tabs). `escapeHtml()` is applied to any user-facing text.

---

## Task 1: Fix Critical Bug — Traffic Counter Field Name

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:5728`

**Step 1: Fix the field name mismatch**

In `loadStatusBarStats()` at line 5728, change `data.total_today` to `data.total_24h`. The API returns `total_24h` but the JS reads `total_today`, causing the counter to always show 0.

```javascript
// BEFORE (line 5728):
if (el) el.textContent = data.total_today || 0;

// AFTER:
if (el) el.textContent = data.total_24h || 0;
```

**Step 2: Verify**

Load `/tools/bridge` in browser, check the status bar "24h" counter shows a real number instead of 0.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "fix(bridge): traffic counter reads correct total_24h field"
```

---

## Task 2: Add Spatial Layout CSS

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (CSS style block, insert after line ~430 before `.bridge-station-card`)

**Step 1: Add the spatial bridge layout CSS**

Insert a comprehensive CSS block covering:
- `.bridge-spatial-layout` — CSS Grid container
- `.bridge-viewscreen` — CRT-styled central screen with scanline effect
- `.bridge-viewscreen-header`, `.bridge-viewscreen-feed`, `.bridge-viewscreen-event` — feed styling
- `.bridge-viewscreen-statusbar` — bottom stats
- `.bridge-station-zone` — glass panel station containers with hover glow
- `.bridge-station-zone.dispatch-active` — enhanced glow when receiving dispatch
- `.bridge-zone-header`, `.bridge-zone-agents`, `.bridge-zone-footer` — zone internals
- `.bridge-agent-node` — circular avatar container with hover scale
- `.agent-node-avatar-wrap`, `.agent-node-initials`, `.agent-node-halo` — avatar + ring
- Halo states: `.idle` (breathe 4s), `.active` (pulse 1.5s), `.error` (alert 0.8s), `.commander` (gold 2s)
- `.agent-node-commander-star` — gold star badge
- `.agent-node-tooltip` — hover tooltip
- `.bridge-dispatch-overlay` — SVG overlay layer
- `.bridge-dispatch-arc` — SVG path animation with `arc-draw` keyframes
- `@keyframes agent-pulse`, `agent-breathe`, `agent-alert`, `arc-draw`
- Mobile responsive (< 768px): single column, smaller avatars, no arcs, no labels
- Light mode overrides for viewscreen, station zones, tooltips

Refer to design doc CSS section for exact values. Keep existing station card CSS intact until Task 7 cleanup.

**Step 2: Verify CSS loads without breaking existing tabs**

Restart platform and load `/tools/bridge` — the Overview tab should look identical.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add spatial layout CSS for starship bridge view"
```

---

## Task 3: Replace Stations Tab HTML Structure

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:4297-4324` (Stations tab panel HTML)

**Step 1: Replace the stations panel HTML**

Replace lines 4297-4324 (the entire `data-panel="stations"` div) with new structure containing:
- `.bridge-spatial-layout` wrapper with id `bridgeSpatialLayout`
- `.bridge-viewscreen` with header ("Main Viewscreen"), feed container (`viewscreenFeed`), statusbar
- `.bridge-spatial-stations` grid container (`bridgeSpatialStations`)
- SVG `.bridge-dispatch-overlay` (`dispatchArcOverlay`)
- All text uses `data-i18n` attributes with English fallbacks

Remove the old command team badges (`#commandTeamRow`, `#commanderBadge`, etc.) — commander info now lives inside the COMMAND station zone.

**Step 2: Verify the HTML is valid**

Load the page — stations tab should show viewscreen header + empty grid area. No JS errors.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): replace stations grid HTML with spatial layout structure"
```

---

## Task 4: Rewrite Station Rendering JS — Spatial Layout + Agent Nodes

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (JS section, lines ~5839-6049)

**Step 1: Replace rendering functions**

Replace `renderStations()`, `createStationCard()`, `renderAgentChip()`, `renderCommandTeamBadges()`, `renderCommandStation()`, `toggleExpand()`, and `updateStationStats()` with:

- **`STATION_LAYOUT_ORDER`** — array defining spatial position order (Row 1: CONSCIOUSNESS, RND, SECURITY, CREATIVE; Row 2: ENGINEERING, COMMAND, OPERATIONS, HR; Row 3: MEDICAL, AWAY_TEAM, QA)
- **`renderStations(stations)`** — sorts by layout order, creates zones, positions in grid (centers last row if < 4 items)
- **`createStationZone(station)`** — builds zone with header (icon, name, status dot, badge), agent node area, footer (module count + node count)
- **`renderAgentNode(agent, stationCode)`** — returns HTML for circular avatar node with:
  - Initials circle (background tinted with station color via `color-mix`)
  - Halo ring (commander/active/idle classes)
  - Commander star badge for COMMAND station primary agents
  - First-name label below
  - Hover tooltip with full name, title, assignment type
- **`getInitials(name)`** — extracts 2-letter initials from full name
- **`updateStationStats(stations)`** — updates viewscreen statusbar agent count

Keep `loadStations()` (lines 5794-5837) intact.

**Step 2: Verify stations render as spatial zones**

Load `/tools/bridge#stations` — should see station zones in a grid with agent avatar circles and glowing halos.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): spatial station zones with avatar node rendering"
```

---

## Task 5: Add Viewscreen Data Loading and Rendering

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (JS section)

**Step 1: Add viewscreen functions**

- **`loadViewscreenData()`** — fetches `/api/dispatch/activity-history` + `/api/traffic` in parallel, calls `renderViewscreen()`
- **`renderViewscreen(events, trafficData)`** — renders last 5 events in viewscreen feed. Each event row shows: timestamp, agent name, arrow, station code (colored), model name, success/fail icon. Updates statusbar with req/min + success rate + agent count
- **`getStationForModule(moduleName)`** — maps module names to station codes by checking `allStations[].modules`, with fallback heuristics

**Step 2: Hook into loadStations**

After `renderStations()` call in `loadStations()`, add `loadViewscreenData()` call.

**Step 3: Add viewscreen refresh interval**

In `DOMContentLoaded` handler, add `setInterval(loadViewscreenData, 30000)`.

**Step 4: Verify viewscreen shows dispatch events**

Load `/tools/bridge#stations` — viewscreen should show recent events with timestamps, agent names, station labels.

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): viewscreen with live dispatch feed and traffic stats"
```

---

## Task 6: Add SVG Dispatch Arc Animations

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (JS section)

**Step 1: Add arc animation system**

- **`MAX_ACTIVE_ARCS = 3`** and `activeArcs = []` state
- **`createDispatchArc(stationCode)`** — calculates DOM positions (viewscreen center to station zone center, relative to layout container), creates SVG quadratic bezier path, applies `stroke-dasharray`/`stroke-dashoffset` animation, adds station `.dispatch-active` glow, fades arc after 2.8s, removes from DOM after 4s. Skips on mobile (< 768px). Evicts oldest arc if at max.
- **`triggerArcsFromViewscreen()`** — checks newest viewscreen event, fires arc if event is new (tracks `_lastViewscreenEventId`)
- **Resize handler** — debounced 250ms, clears all arcs on resize (positions are stale)

**Step 2: Hook into viewscreen render**

At end of `renderViewscreen()`, call `setTimeout(triggerArcsFromViewscreen, 100)`.

**Step 3: Verify arcs animate**

Load `/tools/bridge#stations`, wait for data — SVG arc from viewscreen to station, station glows.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): animated SVG dispatch arcs from viewscreen to stations"
```

---

## Task 7: Clean Up Dead Code and Remove Legacy CSS/JS

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Remove legacy JS functions**

- `renderCommandTeamBadges()` — replaced by COMMAND zone
- `renderCommandStation()` — was already a no-op
- `renderAgentChip()` — replaced by `renderAgentNode()`
- `toggleExpand()` — zones don't use expand/collapse
- `showNotification()` console.log stub — redirect callers to `showToast()` if it exists

**Step 2: Remove old station card CSS (lines ~432-680)**

Remove selectors no longer used: `.bridge-station-card`, `.bridge-station-header`, `.bridge-station-icon`, `.bridge-station-status`, `.bridge-station-name`, `.bridge-station-badge`, `.bridge-station-modules`, `.bridge-module-btn`, `.bridge-station-team`, `.bridge-station-team-label`, `.bridge-station-nodes`, `.station-node-chip`, `.bridge-agent-chip`, `.bridge-agent-avatar`, `.bridge-agent-info`, `.bridge-agent-skill-badge`, `.bridge-hidden-agents`, `.bridge-expand-btn`, `.bridge-station-empty`, `.bridge-command-team`, `.command-team-badge`, and associated sub-selectors.

**Before deleting any CSS selector, grep the template to confirm it's not used by other tabs.**

**Step 3: Verify no console errors on all 5 tabs**

Load Overview, Stations, Dispatch, Crew, Network — confirm no JS errors, no visual regressions.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "refactor(bridge): remove legacy station card code replaced by spatial layout"
```

---

## Task 8: Visual Polish and Final Verification

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (if any tweaks needed)

**Step 1: Test at all breakpoints**

- **1280px desktop**: Full spatial bridge layout with viewscreen, station zones in grid, arcs
- **717px tablet**: Stations in 2-column grid, smaller viewscreen
- **374px mobile (Fold5)**: Single column, compact viewscreen, no arcs

**Step 2: Test light mode**

Toggle theme — viewscreen and station zones should adapt correctly.

**Step 3: Test with real data**

Navigate to `/tools/bridge#stations` with admin account (`admin` / `Kyt$13ran2025`). Verify:
- All stations appear with correct colors
- Agents show as circular avatar nodes with initials
- Commander has gold star badge
- Viewscreen shows recent dispatch events
- Hovering agent node shows tooltip
- Arc fires on viewscreen refresh

**Step 4: Run visual baseline**

```bash
node platform_v2/tests/visual_baseline.mjs --username admin --password 'Kyt$13ran2025'
```

**Step 5: Final commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): spatial bridge tab — final polish and verification"
```

---

## Summary

| Task | Description | Steps |
|------|-------------|-------|
| 1 | Fix traffic counter bug | 3 |
| 2 | Add spatial layout CSS | 3 |
| 3 | Replace stations HTML structure | 3 |
| 4 | Rewrite station rendering JS | 3 |
| 5 | Add viewscreen data loading | 5 |
| 6 | Add SVG dispatch arc animations | 4 |
| 7 | Clean up dead code | 4 |
| 8 | Visual polish and verification | 5 |
| **Total** | | **30 steps** |
