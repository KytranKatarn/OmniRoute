# Dashboard Redesign — "Starship Bridge" Design

**Project**: #94 — Platform UI Overhaul
**Task**: #628 — Redesign: Dashboard
**Date**: 2026-02-18
**Approach**: Full rebuild — Starship Bridge (Approach A)
**Responsive**: Equal priority — 374px / 717px / 1280px+

---

## Overview

Full rebuild of `dashboard_dynamic.html` (~2,793 lines) into a layered command center experience. Eight sections stacked top-to-bottom, each with distinct purpose and visual identity. Replaces the current hero+grid layout with a richer, data-driven dashboard.

**Files to modify/create**:
- `platform_v2/templates/dashboard_dynamic.html` — full rewrite
- `platform_v2/dashboard_generator.py` — extend for new data endpoints
- `platform_v2/app.py` — add API endpoints for HUD vitals, mission briefing data

---

## Section 1: Cinematic Boot Sequence (~4s)

Staged starship power-up animation with skip button.

| Phase | Time | Content |
|-------|------|---------|
| 0 | 0-0.3s | Pure black, cursor blink |
| 1 | 0.3-1s | `> INITIALIZING A.R.C.H.I.E. CORE...` types out, screen flicker |
| 2 | 1-2.5s | 6 subsystem checks with progress bars (DATABASE, AI BRIDGE, MODULES, NETWORK, AGENTS, CONSCIOUSNESS) |
| 3 | 2.5-3s | `⚠ THREAT LEVEL: NOMINAL` amber flash, brief screen shake |
| 4 | 3-3.5s | ARCHIE logo materializes with ring pulse, `SYSTEM ONLINE` |
| 5 | 3.5-4s | Overlay splits horizontally revealing dashboard |

- Skip button: bottom-right `SKIP ▸`, appears at 0.5s
- localStorage `archie-boot-skip` remembers preference
- Audio hooks: CSS classes for future sound integration (no actual audio)

## Section 2: Ambient Background

- **Matrix rain**: Slower, opacity 0.15, katakana + binary + "ARCHIE"
- **Nebula gradient**: Animated radial gradient, 60s cycle, deep space colors
- **No scanlines**: Removed for readability
- **Light mode**: No matrix rain, subtle animated gradient mesh (light blues/grays)

## Section 3: Command Bar (Top Navigation)

Fixed 48px bar at top, glassmorphic (`backdrop-filter: blur(20px)`).

- **Left**: User avatar + name + role badge + tier badge
- **Center**: Quick search input (`Ctrl+K` hint)
- **Right**: Notification bell (count badge), theme toggle, Dev HQ link (admin), logout
- On scroll: gains subtle bottom border glow

## Section 4: HUD Vitals Strip

Horizontal strip of 6 glassmorphic stat pods (~120px each on desktop):

| Pod | Data Source | Visual |
|-----|-------------|--------|
| System Health | Aggregate | Animated ring gauge |
| CPU Load | `/api/system-stats` | Mini bar chart |
| Memory | `/api/system-stats` | Ring gauge |
| AI Status | `/api/ai-status` | Pulsing dot + label |
| Active Agents | `/api/module-agents` | Icon stack + count |
| Uptime | `/api/system-stats` | Duration counter |

- **Desktop (1280px+)**: 6 pods in a row
- **Tablet (717px)**: Horizontal scrollable strip
- **Mobile (374px)**: 2x3 grid
- Auto-refresh: 15s interval

## Section 5: Mission Briefing Row

3 full-width cards (stacked on mobile):

1. **Recent Activity**: Last 5 actions with timestamps (logins, module access, AI queries)
2. **System Alerts**: Active warnings, color-coded (green/amber/red)
3. **AI Insights**: Today's AI interaction count, top topics, consciousness status

Each card uses LCARS framed header with category color accent.

## Section 6: Featured Modules

2-3 large pinned module cards (~300px height desktop):

- Module icon, name, full description
- Live mini-stat relevant to module
- Recent activity line ("Last accessed 2h ago")
- Hover: lift + glow matching category color
- Pin/unpin via localStorage (future: DB-backed)
- Default pins: Chat, Bridge Command, Dev HQ

**Responsive**: Single column on mobile, 2-3 columns on desktop.

## Section 7: Category Grid

Collapsible panels per category with LCARS framed headers:

- Header: icon + title + module count + collapse chevron
- Cards: compact (icon + name + status dot)
- **Desktop**: 3-4 columns
- **717px**: 2 columns
- **374px**: 1 column
- Category colors preserved: orange (admin), cyan (dev), purple (SaaS), green (knowledge), pink (media)
- Hover: brief description tooltip

## Section 8: Status Footer

Slim footer bar:

- **Left**: System time (blinking separator), version badge
- **Right**: Connection status dot, "Last refreshed Xs ago"

---

## Color System

Inherits existing `--archie-*` CSS tokens:

| Category | Color |
|----------|-------|
| Admin Operations | `#cc6600` (orange) |
| AI Command | `#cc6600` (orange) |
| Development Tools | `#00808f` (cyan) |
| SaaS Services | `#7c3aed` (purple) |
| Project & Knowledge | `#00aa33` (green) |
| Media & Home | `#db2777` (pink) |
| Coming Soon | `#8b949e` (muted gray) |

## Animation Inventory

| Animation | Duration | Use |
|-----------|----------|-----|
| Boot typing | 0.03s/char | Phase 1 text |
| Progress bar fill | 0.2s each | Phase 2 subsystem checks |
| Screen shake | 0.15s | Phase 3 warning |
| Ring pulse | 0.5s | Phase 4 logo reveal |
| Overlay split | 0.5s | Phase 5 reveal |
| Card materialize | 0.6s | Card entrance |
| Ring gauge fill | 1s | HUD vitals |
| Glow pulse | 3s infinite | Active elements |
| Nebula drift | 60s infinite | Background |
| Matrix rain | continuous | Background |

## API Endpoints Needed

| Endpoint | Data | New? |
|----------|------|------|
| `/api/modules` | Module health status | Existing |
| `/api/module-agents` | Agent assignments | Existing |
| `/api/system-stats` | CPU, RAM, uptime | New |
| `/api/ai-status` | AI bridge status | New |
| `/api/recent-activity` | Last N user actions | New |
| `/api/system-alerts` | Active warnings | New |

## Testing Plan

- Playwright screenshots at 374px, 717px, 1280px
- Boot sequence: capture at 1s, 2.5s, 4s intervals
- Verify all module cards render and link correctly
- Theme toggle: dark and light mode captures
- HUD vitals: verify auto-refresh cycle
