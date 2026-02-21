# Bridge Command Redesign — Design Document

**Date**: 2026-02-21
**Project**: #94 — Platform UI Overhaul
**Task**: #634 — Redesign: Bridge Command (Phase 2)
**Status**: Approved

---

## Problem

The Bridge Command module is functionally complete (50+ API endpoints, 10 stations, dispatch, crew, nodes) but visually outdated compared to the Dashboard gold standard. The page is extremely long (~6 screens of vertical scrolling), the Command Station hero wastes vertical space, station cards need polish, and the sidebar content is hidden on mobile.

## Solution

Tab-based redesign with compact status header, applying Dashboard gold standard visual patterns throughout.

---

## Architecture

### Layout Structure

```
┌─────────────────────────────────────────────┐
│ LCARS Framed Header (existing, keep)        │
├─────────────────────────────────────────────┤
│ Compact Status Bar (replaces Command hero)  │
│ [Bridge Online] [Routing: local_cloud]      │
│ [292 interactions/24h] [10 agents] [19:22]  │
├─────────────────────────────────────────────┤
│ Tab Pills: Overview│Stations│Dispatch│Crew│Network │
├─────────────────────────────────────────────┤
│                                             │
│ [Active Tab Content]                        │
│                                             │
└─────────────────────────────────────────────┘
```

### Tab Contents

#### 1. Overview Tab (default)
- **HUD Pods Strip**: 4-5 metric gauges (throughput, agent utilization, model health, IAAE compliance, queue depth)
- **Quick Status Cards** (briefing-card pattern, 3-col grid):
  - AI Bridge Status (online/offline per service, routing mode)
  - Active Stations Summary (10 stations, agent counts, coverage %)
  - IAAE Health Monitor (moved from sidebar)
- **Mini Activity Feed**: Last 5 dispatch items (link to Dispatch tab for full view)

#### 2. Stations Tab
- **Station Grid**: 10 station cards in auto-fill grid (minmax 280px)
- **Each station card**: briefing-card pattern with accent color matching station theme
  - Station name + icon + status indicator
  - Assigned agents list with drag-drop
  - Module coverage chips
  - Quick-assign button
- **Station Assignment Modal** (existing, keep)
- **Station Detail Modal** (existing, keep)

#### 3. Dispatch Tab
- **Active Jobs Panel**: Current running jobs with step progress bars
- **Dispatch Activity Table**: Recent bridge transactions (existing data)
- **Throughput Chart**: Station-by-station bar chart (existing, polish)
- **SSE real-time updates** (existing, keep)

#### 4. Crew Tab
- **Sub-sections** (collapsible or mini-tabs):
  - **Manifest**: All agents with role, station, status — card grid
  - **Training Rooms**: Agents in training, skills catalog, assign training
  - **Lounge**: Agents at rest, return-to-duty actions
- Agent emotional state indicators on each card

#### 5. Network Tab
- **Nodes Grid**: Registered remote nodes with health indicators
- **Pending Approvals**: Nodes awaiting approval (conditionally shown)
- **Model Availability**: Available models across all nodes
- **External Providers**: Cloud model configs (OpenAI, Anthropic, etc.)
- **Node Detail Modal** (existing 5-tab modal, keep)

---

## Visual Design

### Patterns to Apply (from Dashboard Gold Standard)

| Pattern | Usage |
|---------|-------|
| **Briefing cards** | All content sections (backdrop-blur, accent-color headers, `::before` gradient line) |
| **HUD pods** | Overview metrics (SVG ring gauges, monospace labels) |
| **Tab pills** | 5-tab navigation below status bar |
| **Category nav** | Not needed (tabs replace it) |
| **Light mode** | Dual selector: `[data-theme="light"]` + `body.light-mode` |

### Color Accents per Tab
- Overview: `#00ff41` (green — system health)
- Stations: `#ffaa00` (orange — command gold)
- Dispatch: `#00ffff` (cyan — activity)
- Crew: `#8b5cf6` (purple — personnel)
- Network: `#ff6b6b` (red — infrastructure)

### Typography
- Headers: Orbitron (display), uppercase, letter-spacing 2-3px
- Body/Labels: JetBrains Mono, 0.75-0.85rem
- Values: JetBrains Mono, bold

### CSS Token Usage
All styles use `--archie-*` tokens. No hardcoded colors.

---

## Responsive Design

### Desktop (1280px+)
- Full layout, all tabs with multi-column grids
- Status bar in single row
- Station grid: 3-4 columns

### Tablet / Fold5 Open (717px)
- Tab pills scroll horizontally if needed
- Station grid: 2 columns
- Status bar wraps to 2 rows
- Briefing cards stack to single column

### Mobile / Fold5 Closed (374px)
- Tab pills: icon-only mode (tooltips for labels)
- Station grid: 1 column
- Status bar: essential metrics only (hide time, routing label)
- Controls toggle (existing) for routing/escalation

---

## Functional Improvements

1. **Resolve TODO: Skill validation API** (line 5048) — Wire to actual validation or remove
2. **Resolve TODO: Assignment update API** (line 5130) — Connect to PUT endpoint
3. **Fix sidebar content accessibility** — Training/Lounge/IAAE move into proper tabs
4. **Add keyboard navigation** — Tab key cycles through tabs, Enter activates

---

## Data Flow

No backend changes needed. All existing API endpoints serve the redesigned frontend:
- `/api/dashboard/ai-status` — Overview metrics
- `/api/stations` — Stations tab
- `/api/dispatch/activity-history` — Dispatch tab
- `/api/bridge/crew/manifest` — Crew tab
- `/api/nodes` — Network tab
- `/api/dispatch/stream` — SSE for real-time updates (all tabs)

---

## Migration Strategy

1. Restructure HTML into tab panels (preserve all existing content)
2. Apply new CSS (briefing-card patterns, tab pills, responsive)
3. Add tab switching JS (show/hide panels, URL hash routing)
4. Polish each tab's content incrementally
5. Test at all 3 breakpoints with Playwright screenshots

---

## i18n

All new UI strings use `data-i18n` attributes. New keys:
- `bridge.tabs.overview`, `bridge.tabs.stations`, `bridge.tabs.dispatch`, `bridge.tabs.crew`, `bridge.tabs.network`
- `bridge.status.routing_mode`, `bridge.status.interactions_24h`
- Existing keys preserved for all moved content
