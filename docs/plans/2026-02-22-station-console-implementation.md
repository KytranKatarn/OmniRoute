# LCARS Station Console Panel — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the basic station info modal with a slide-in LCARS console panel featuring tabbed navigation (Crew/Dispatch/Nodes/Metrics), module icon rail with previews, and reorder Bridge tabs so the isometric bridge is the default landing tab.

**Architecture:** The console panel is a new HTML element in bridge.html that slides in from the right when clicking an isometric zone. It replaces `showZoneInfo()`. CSS uses `.lcars-console-*` classes extending existing isometric styling. Two new backend endpoints provide station metrics and module previews. The tab reorder swaps Stations to position 1 and Overview to position 2.

**Tech Stack:** HTML/CSS/JS (vanilla, no framework), Flask/Python backend, PostgreSQL queries via `get_db_cursor()`, Lucide icons, Orbitron font.

**Design doc:** `docs/plans/2026-02-22-station-console-design.md`

---

### Task 1: Reorder Bridge Tabs — Stations First

Swap the Stations tab to be the default landing tab, move Overview to second position.

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:5145-5166` (tab nav HTML)
- Modify: `platform_v2/templates/tools/bridge.html:6549-6556` (hash restore IIFE)

**Step 1: Swap tab button order in HTML**

Move the `data-tab="stations"` button to first position with `active` class, remove `active` from overview button.

**Step 2: Swap the default tab panel active state**

Find the stations panel `data-panel="stations"` and add `active` class. Remove `active` from `data-panel="overview"`.

**Step 3: Update hash restore to default to stations**

In the IIFE at line ~6549, add an `else` branch that calls `switchBridgeTab('stations')` when no hash is present. Update validTabs array to put 'stations' first.

**Step 4: Verify**

- Reload Bridge Command page — should land on Stations (isometric view) with warp-in animation
- Click Overview tab — should show the report/stats view
- URL hash `#overview` should still work correctly
- Other tabs (Dispatch, Crew, Network) unaffected

**Step 5: Commit**

```
feat(bridge): make Stations the default landing tab
```

---

### Task 2: LCARS Console Panel — CSS

Add all `.lcars-console-*` CSS classes for the slide-in panel, LCARS frame, tab rail, and content area.

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (add CSS block after existing `.iso-*` styles)

**Step 1: Add LCARS console panel CSS**

Insert before the light mode section. Include classes for:
- `.lcars-console-backdrop` — fixed overlay, opacity transition
- `.lcars-console` — fixed right panel, 420px wide, translateX animation
- `.lcars-console-header` — station name with LCARS elbow bracket
- `.lcars-console-elbow` — border-radius trick for LCARS rounded corner
- `.lcars-module-rail` — horizontal scrollable icon row
- `.lcars-module-icon` — 38px icon buttons with hover/active states
- `.lcars-module-tooltip` — absolute positioned tooltip on hover
- `.lcars-console-body` — flex container for tab rail + content
- `.lcars-tab-rail` — vertical tab pills column
- `.lcars-tab-pill` — vertical text, Orbitron font, active = station color fill
- `.lcars-tab-content` — scrollable content area
- `.lcars-crew-row` — agent rows with avatar, name, role badge
- `.lcars-dispatch-row` — dispatch entries with time, status, model, latency
- `.lcars-node-card` — node cards with hostname, specs, load bar
- `.lcars-metrics-grid` — 2x2 stat card grid
- `.lcars-metric-card` — stat card with Orbitron value + label
- `.lcars-module-preview` — module preview card with header, description, open button
- `.lcars-back-link` — "back to station" link
- `.lcars-section-label` — section headers (uppercase, muted)
- `.lcars-empty` — empty state text

Responsive breakpoints:
- 768px: 360px panel width, smaller fonts
- 480px: 100vw width, horizontal tab pills instead of vertical

Light mode overrides for panel background and card backgrounds.

**Step 2: Verify** — CSS only, no visual changes yet. Reload page, check no syntax errors.

**Step 3: Commit**

```
feat(bridge): add LCARS station console CSS classes
```

---

### Task 3: LCARS Console Panel — HTML Skeleton

Add the panel HTML and backdrop elements.

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` — add after `iso-zone-info-modal` div (~line 5738)

**Step 1: Add console panel HTML**

Structure:
- `#lcarsConsoleBackdrop` — dim overlay div
- `#lcarsConsole` — main panel with:
  - `.lcars-console-header` containing elbow, title, subtitle, close button
  - `#lcarsModuleRail` — empty div, populated by JS
  - `.lcars-console-body` containing:
    - `#lcarsTabRail` with 4 `lcars-tab-pill` buttons (CREW/DSPCH/NODES/STATS)
    - `#lcarsTabContent` with 5 tab panels (crew/dispatch/nodes/metrics/module-preview)

**Step 2: Commit**

```
feat(bridge): add LCARS console panel HTML skeleton
```

---

### Task 4: Console Panel JS — Open/Close + Tab Switching

Wire up open/close behavior and internal tab switching.

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` — add JS after `showZoneInfo()`

**Step 1: Add core console JS**

Functions to add:
- `openStationConsole(zoneName, zoneInfo, zd)` — sets station color, title, builds module rail, renders crew tab, opens panel with animation
- `closeStationConsole()` — removes open class, clears dispatch timer, removes event listeners
- `_consoleEscHandler(e)` — Escape key handler
- `switchConsoleTab(tabName)` — toggles pills/panels, triggers data load per tab
- Event delegation on `#lcarsTabRail` for pill clicks

State variables: `_consoleCurrentZone`, `_consoleDispatchTimer`, `_consoleNodeCache`

**Step 2: Update zone click handler**

In `createIsometricZone()`, replace `showZoneInfo(zoneName, zoneInfo, zd)` with `openStationConsole(zoneName, zoneInfo, zd)`.

**Step 3: Verify** — Click zone, panel slides in. Close via X/backdrop/Escape. Tab pills switch content.

**Step 4: Commit**

```
feat(bridge): wire LCARS console open/close and tab switching
```

---

### Task 5: Module Icon Rail + Backend Metadata Endpoint

Build the horizontal module icon rail with Lucide icons.

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — new `POST /api/modules/metadata` endpoint
- Modify: `platform_v2/templates/tools/bridge.html` (JS)

**Step 1: Add backend endpoint**

`POST /api/modules/metadata` accepts `{ "modules": ["name1", "name2"] }`, returns module metadata (id, name, icon, route, description, category) from `module_registry.get_enabled_modules()`. Uses fuzzy matching by id, name, and tags.

**Step 2: Add JS `buildModuleRail()` function**

Fetches metadata (with `_moduleMetadataCache`), creates icon elements with Lucide icons and tooltips, wires click to `showModulePreview()`. Calls `lucide.createIcons()` after building.

**Step 3: Verify** — Module icons appear with correct icons and tooltips.

**Step 4: Commit**

```
feat(bridge): module icon rail with metadata lookup
```

---

### Task 6: Crew Tab Content

Render assigned agents using DOM construction (no innerHTML for security).

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (JS)

**Step 1: Add `renderCrewTab(agents, stationColor)` function**

Builds agent rows using DOM methods:
- Avatar img (40px, DiceBear fallback)
- Name (first_name + last_name or name)
- Title (if present)
- Model name (monospace, muted)
- Role badge (PRIMARY/BACKUP pill)
- Empty state if no agents

All content set via `textContent` (no innerHTML with user data).

**Step 2: Verify** — Crew tab shows agents correctly.

**Step 3: Commit**

```
feat(bridge): crew tab content in LCARS console
```

---

### Task 7: Dispatch Tab Content + Station Filter

Render live dispatch activity filtered to station's agents.

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — add station filter param to activity-history
- Modify: `platform_v2/templates/tools/bridge.html` (JS)

**Step 1: Add station filter to activity-history endpoint**

Accept `?station=CODE` query params. Add WHERE clause filtering by agent_id IN (SELECT from station_assignments JOIN bridge_stations). Apply filter to both UNION branches (task_execution_log and bridge_interaction_log). Also add `duration_ms` / `execution_time_ms` to the SELECT for latency display.

**Step 2: Add `loadConsoleDispatch(stationCodes)` JS function**

Builds URL with station params, fetches events, renders dispatch rows (time, status icon, model + task type, latency). Sets 15s auto-refresh interval. Clears interval on panel close.

All content via DOM methods and `textContent`.

**Step 3: Verify** — DSPCH tab shows filtered events with auto-refresh.

**Step 4: Commit**

```
feat(bridge): dispatch tab with station-filtered activity feed
```

---

### Task 8: Nodes Tab Content

Render compute node details using the batch-nodes endpoint.

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (JS)

**Step 1: Add `loadConsoleNodes(zd, stationColor)` and `renderNodeCards()` functions**

`loadConsoleNodes`: finds station IDs from `allStations`, checks `_consoleNodeCache`, calls `POST /api/stations/batch-nodes`, flattens results, caches.

`renderNodeCards`: groups nodes by role (primary/backup/relief/worker), renders cards with status dot, hostname, CPU/RAM/GPU specs, and load progress bar.

All content via DOM methods.

**Step 2: Verify** — NODES tab shows cards grouped by role.

**Step 3: Commit**

```
feat(bridge): nodes tab with batch-fetched compute resources
```

---

### Task 9: Metrics Tab + Backend Endpoint

Add station metrics endpoint and 2x2 stat card grid.

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — new `GET /api/stations/{code}/metrics`
- Modify: `platform_v2/templates/tools/bridge.html` (JS)

**Step 1: Add metrics endpoint**

Queries `bridge_interaction_log` for agents assigned to station (via station_assignments JOIN). Returns: requests_24h, avg_response_ms, tokens_24h, success_rate.

**Step 2: Add `loadConsoleMetrics(stationCodes)` JS function**

Fetches metrics per station code, aggregates totals (avg for response time and success rate). Builds 4 metric cards in a 2x2 grid. All DOM construction.

**Step 3: Verify** — STATS tab shows 4 metric cards.

**Step 4: Commit**

```
feat(bridge): station metrics tab with 24h performance stats
```

---

### Task 10: Module Preview Cards + Backend Endpoint

Module preview with stats and "Open Module" link.

**Files:**
- Modify: `platform_v2/tools/bridge/routes.py` — new `GET /api/stations/{code}/module-preview/{module_id}`
- Modify: `platform_v2/templates/tools/bridge.html` (JS)

**Step 1: Add module preview endpoint**

Returns module metadata from `get_module_by_id()` plus optional stats queries for known modules (email count, backup count, bridge interactions). Stats are best-effort — silently skip if table doesn't exist.

**Step 2: Add `showModulePreview(mod)` JS function**

Switches to module-preview panel. Builds: back link, preview card with icon + name header, description (stripped of HTML via regex on textContent), stat pills (from API), and "Open Module" link. All DOM construction.

**Step 3: Verify** — Click module icon, preview appears. "Open Module" navigates. "Back" returns to crew.

**Step 4: Commit**

```
feat(bridge): module preview cards with inline stats
```

---

### Task 11: Final Integration + Verification

End-to-end testing and cleanup.

**Step 1: Full verification checklist**

1. Reload Bridge Command — lands on Stations tab with warp-in animation
2. Click Overview tab — shows report/stats, URL changes to `#overview`
3. Click each of 6 isometric zones — LCARS console slides in with correct station name, color, elbow bracket
4. Module icons in rail have correct Lucide icons and tooltips
5. Crew tab — agents with avatars, roles, models
6. DSPCH tab — dispatch activity loads, filtered to station
7. NODES tab — node cards grouped by role with load bars
8. STATS tab — 2x2 metric cards with 24h data
9. Module icon click — preview card with stats + "Open Module" link
10. "Back to Station" — returns to crew tab
11. Close: X button, backdrop click, Escape key all work
12. Responsive: 1280px, 717px, 374px
13. No JS errors in browser console
14. Light mode: panel readable

**Step 2: Restart container and check logs**

```bash
docker compose restart archie_platform
docker logs --tail 30 archie_platform
```

**Step 3: Final commit**

```
feat(bridge): LCARS station console panel — complete integration
```
