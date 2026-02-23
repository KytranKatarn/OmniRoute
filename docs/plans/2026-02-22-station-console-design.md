# Bridge Command — LCARS Station Console Panel

**Date:** 2026-02-22
**Status:** Approved
**Project:** #94 — Platform UI Overhaul

---

## Overview

When a user clicks an isometric station zone on the Bridge Command tab, a slide-in LCARS console panel opens from the right. It replaces the current `showZoneInfo()` modal with a rich, tabbed interface showing station crew, live dispatch activity, compute nodes, performance metrics, and module quick-launch icons with inline previews.

## Trigger

Click any isometric station zone → `showZoneInfo()` replaced by `openStationConsole(zoneName, zoneInfo, zoneData)`.

## Panel Layout

### Dimensions & Responsive Behavior

| Breakpoint | Width | Behavior |
|---|---|---|
| Desktop (1280px+) | 420px | Slides from right edge, full viewport height minus header |
| Fold5 open (717px) | 360px | Slides from right, bridge shrinks |
| Fold5 closed (374px) | 100vw | Full-width overlay, swipe-down to dismiss |

### Animation

- Slide-in: `transform: translateX(100%) → translateX(0)` over 300ms ease-out
- Backdrop: subtle dim overlay on bridge area (rgba(0,0,0,0.3))
- Close: reverse slide + fade

### LCARS Frame Structure

```
╔══════════════════════════════════════╗
║  ┌─────────────────┐                ║
║  │ ENGINEERING      │ ═══════╗      ║
║  │ STATION     [✕]  │        ║      ║
║  └─────────────────┘        ║      ║
║                              ║      ║
║  ┌──┐ ┌──┐ ┌──┐ ┌──┐       ║      ║
║  │📧│ │🔧│ │📊│ │🤖│  ...  ║      ║
║  └──┘ └──┘ └──┘ └──┘       ║      ║
║  ─────────────────────────── ║      ║
║  ╔═══╗                       ║      ║
║  ║CRW║  Agent 1 • Primary    ║      ║
║  ╠═══╣  Agent 2 • Backup     ║      ║
║  ║DSP║                       ║      ║
║  ╠═══╣  [Tab Content Area]   ║      ║
║  ║NOD║                       ║      ║
║  ╠═══╣                       ║      ║
║  ║MET║                       ║      ║
║  ╚═══╝                       ║      ║
╚══════════════════════════════════════╝
```

**Top → Bottom:**

1. **Station Header** — Station icon + name + close button. LCARS rounded elbow bracket at top-left in station color. Orbitron font, station-colored text-shadow glow.
2. **Module Icon Rail** — Horizontal row of Lucide module icons from module_registry. Scrollable if > 6 modules. Active module highlighted with station-color underline. Hover tooltip with module name.
3. **Content Area** — Two-column layout:
   - **Left: LCARS Tab Rail** — 4 vertical pills (CREW / DISPATCH / NODES / METRICS) in station color. Active = filled, others = outlined.
   - **Right: Tab Content** — Scrollable content for selected tab OR module preview card.

## Tab Contents

### CREW Tab (Default Active)

Shows assigned agents for this station.

- **Agent row:** avatar (40px circle) | name (FirstName LastName) | role badge (PRIMARY/BACKUP pill in station color) | model name (muted)
- Commander agent gets gold star badge
- Status dot: green pulse = active, gray = idle
- **Empty state:** "No crew assigned" muted text
- **Data source:** Already loaded in `allStations` array — no API call needed

### DISPATCH Tab

Live activity feed filtered to this station.

- Fetches from existing `/api/dispatch/activity-history` with station filter
- Each entry: timestamp | model used | status icon (✓/✗) | response time (ms)
- Auto-refreshes every 15s while tab is active
- Shows last 20 dispatches
- Mini sparkline at top: throughput over last hour
- **Data source:** `GET /api/dispatch/activity-history?station={code}`

### NODES Tab

Compute resources assigned to this station.

- Summary header from inlined `node_coverage` data (total/primary/backup counts)
- Detailed node cards fetched on tab open from `/api/stations/{id}/nodes`
- Each node card: hostname | status dot | CPU/RAM/GPU specs | current load progress bar
- Grouped by role: Primary → Backup → Relief
- **Data source:** `GET /api/stations/{id}/nodes` (fetch on tab open, cache result)

### METRICS Tab

Station performance mini-dashboard.

- 4 stat cards in 2×2 grid:
  - **Requests (24h)** — total dispatches to this station
  - **Avg Response** — mean response time in ms
  - **Tokens Used** — total tokens consumed
  - **Success Rate** — percentage of successful completions
- Values animate with counting-up effect
- Station color accent border on each card
- **Data source:** New endpoint `GET /api/stations/{code}/metrics`

## Module Preview Cards

When a module icon is clicked in the rail:

1. Tab content area swaps to a **module preview card**
2. Card structure:
   - Module name + Lucide icon header
   - 2-3 key stats (module-specific, from preview endpoint)
   - **"Open Module →"** button navigating to module route (e.g., `/tools/email-manager`)
3. If no preview data available: module description + direct link
4. LCARS tab pills show deselected state with "← Back to Station" link
5. **Data source:** New endpoint `GET /api/stations/{code}/module-preview/{module_id}`

## Data Flow Summary

| Feature | Endpoint | Fetch Strategy |
|---|---|---|
| Crew | In-memory (`allStations`) | No fetch |
| Dispatch | `/api/dispatch/activity-history?station={code}` | On tab open, refresh 15s |
| Nodes | `/api/stations/{id}/nodes` | On tab open, cache |
| Metrics | New: `GET /api/stations/{code}/metrics` | On tab open |
| Module Preview | New: `GET /api/stations/{code}/module-preview/{module_id}` | On icon click |

## New Backend Endpoints

### `GET /api/stations/{code}/metrics`

Returns aggregated station performance data:
- Query `bridge_transactions` for the station's models within last 24h
- Return: total_requests, avg_response_ms, total_tokens, success_rate

### `GET /api/stations/{code}/module-preview/{module_id}`

Returns preview data for a module within a station context:
- Lookup module in `module_registry` for metadata (name, icon, description, route)
- Query module-specific tables for 2-3 key stats (e.g., email count, backup count, agent count)
- Extensible: each module can register a `preview_data()` callback, falling back to metadata-only

## CSS Architecture

- New CSS block: `.lcars-console-*` classes (panel, header, elbow, tab-rail, tab-pill, content)
- Station color applied via `--station-color` CSS custom property (already exists)
- LCARS elbow bracket: `border-radius` trick — large radius on top-left corner only
- Glass morphism backdrop on panel body (existing pattern from `.bridge-station-zone`)
- Dark theme only (inherits bridge dark background)
- Light theme: adjust to `rgba(255,255,255,0.9)` panel background

## Files Modified

| File | Changes |
|---|---|
| `platform_v2/templates/tools/bridge.html` | New CSS (.lcars-console-*), new HTML panel, new JS (openStationConsole, tab switching, module previews) |
| `platform_v2/tools/bridge/routes.py` | New endpoints: station metrics + module preview |

## Verification

1. Click each of 6 isometric zones → console opens with correct station data and color
2. All 4 tabs load data correctly (Crew from memory, others via API)
3. Module icons match station's module list from registry
4. Module preview cards show data + "Open Module" navigates correctly
5. Close button / click outside / Escape key all dismiss the panel
6. Responsive: test at 1280px, 717px, 374px
7. Animation smooth (no jank on slide-in/out)
8. No JS errors in console on any interaction
