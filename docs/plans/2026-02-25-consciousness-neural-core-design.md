# Consciousness Module — Neural Core Redesign

**Date**: 2026-02-25
**Project**: UI Overhaul (#94)
**Status**: Approved
**Author**: Claude + Kytran

---

## Vision

Transform the Consciousness module from a tabbed data viewer into ARCHIE's visible, living brain. The centerpiece is a **Neural Core visualization** — concentric orbital rings with circuit-trace pathways showing knowledge flowing through ARCHIE's mind in real time. This is the Consciousness equivalent of the Bridge Command module's isometric starship room.

## Design System (LCARS Neural)

### Color Palette
- **Primary accent**: `#8b5cf6` (purple — consciousness identity)
- **Secondary**: `#3b82f6` (blue — data/files), `#22c55e` (green — healthy/embedded), `#f59e0b` (amber — processing/warning), `#00ffff` (cyan — active/online)
- **Mood-reactive center**: Purple (focused), Cyan (curious), Green (happy), Amber (processing), Rose (empathetic)
- **Surfaces**: `rgba(255,255,255,0.02)` base, `0.04` elevated, `0.06` borders
- **Glow effects**: `box-shadow: 0 0 Npx color` with 0.3 opacity

### Typography
- **Labels/Nav**: Antonio (uppercase, letter-spacing 1.2px)
- **Values/Titles**: Orbitron (bold, tabular numbers)
- **Body/Code**: IBM Plex Mono (light/regular)

### Animations (GPU-only)
- All animations use `transform` and `opacity` only
- Duration: 150-300ms for interactions, 8-20s for ambient loops
- All wrapped in `@media (prefers-reduced-motion: no-preference)`
- Particle effects via CSS (small count) or lightweight Canvas (larger count)

---

## Part 1: Dashboard Tab — The Neural Core

### Hero Visualization

A full-width interactive visualization (~500px height on desktop, ~350px mobile) rendered with a `<canvas>` overlay on styled HTML.

#### Structure

```
┌──────────────────────────────────────────────────┐
│                   NEURAL CORE                     │
│                                                   │
│              ╭─── outer ring ───╮                 │
│           ╭──┤  repo  conv  gh  ├──╮              │
│        ╭──┤  ╰─── ─── ─── ───╯  ├──╮            │
│     ╭──┤  │   inner ring nodes   │  ├──╮         │
│     │  │  │    ┌───────────┐     │  │  │         │
│     │  │  │    │  A.R.C.H. │     │  │  │         │
│     │  │  │    │  I.E.     │     │  │  │         │
│     │  │  │    │  ♥ mood   │     │  │  │         │
│     │  │  │    └───────────┘     │  │  │         │
│     ╰──┤  │  circuit pathways    │  ├──╯         │
│        ╰──┤  ·····particles····  ├──╯            │
│           ╰──────────────────────╯               │
│                                                   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐ │
│  │ 14,349  │ │  9,144  │ │  87%    │ │ 10/10  │ │
│  │Knowledge│ │ GitHub  │ │Embedded │ │ Agents │ │
│  └─────────┘ └─────────┘ └─────────┘ └────────┘ │
└──────────────────────────────────────────────────┘
```

#### Center Node
- Hexagonal shape with pulsing glow ring
- Shows: ARCHIE name, current mood emoji-free icon, mood label
- Glow color shifts based on emotional state from `/brain-state` API
- Pulse speed: faster when jobs are active, slow ambient when idle

#### Inner Ring (6 Knowledge Cluster Nodes)
- **Conversations** (blue) — `conversation_memory` count
- **Code** (green) — `code_snippet` + `github_file` count
- **Vault Notes** (purple) — `vault_note` count
- **Repos** (amber) — `github_repositories` count
- **Learned** (cyan) — `mistake_learned` + `improvement` count
- **Sessions** (rose) — `conversation_sessions` count

Each node:
- Sized proportionally to entry count (min 30px, max 60px radius)
- Positioned evenly around center at ~120px radius
- Gentle orbital drift (CSS `rotate` on parent, counter-rotate on labels to keep text upright)
- Hover: expand slightly, show tooltip with exact count
- Click: switch to relevant tab (Knowledge, GitHub, Insights, etc.)

#### Outer Ring (Active Sources)
- Individual dots for recent entries (last 50), color-coded by source
- Positioned at ~220px radius, slowly orbiting
- New entries animate inward from edge with a particle trail
- Each dot: hover shows title, click opens detail

#### Circuit Pathways
- SVG `<path>` elements connecting inner ring nodes through center
- Curved Bézier paths (not straight lines)
- Base: `stroke: rgba(139,92,246,0.08)`, `stroke-width: 1`
- Active: brighter stroke + animated dashes (`stroke-dasharray` + `stroke-dashoffset` animation)
- When a bridge job runs, the pathway between relevant nodes lights up

#### Particle Flow
- CSS-animated small circles (4-6px) that travel along pathways
- 10-20 particles max (performance budget)
- Speed increases during active processing
- Each particle: slight glow trail via `box-shadow`

#### Stats HUD (Below Visualization)
- 4 LCARS readout strips (same pattern as current GitHub strips)
- Total Knowledge | GitHub Files | Embed Coverage % | Active Agents
- Values update on tab load, animate number transitions

### Data Sources
```
GET /brain-state              → mood, emotion, top memories
GET /api/dashboard/summary    → knowledge counts, agent status, activity
GET /api/github/repos         → repo list for outer ring
GET /github/stats             → embed coverage
GET /emotional-state          → mood color
```

### Responsive Behavior
- **≥1024px**: Full visualization, 500px height
- **768-1023px**: Reduced to inner ring + center, 350px height, outer ring hidden
- **<768px**: Center node + stats strips only, 200px height, no orbital animation

---

## Part 2: GitHub Tab — Knowledge Intake

### Layout (Top to Bottom)

#### Zone 1: Intake Port
```
┌──────────────────────────────────────────────────┐
│ ╭─ KNOWLEDGE INTAKE ────────────────────────────╮ │
│ │                                                │ │
│ │  🔗 Paste a GitHub repository URL              │ │
│ │  ┌──────────────────────────────┐  ┌────────┐ │ │
│ │  │ https://github.com/owner/rep │  │ INGEST │ │ │
│ │  └──────────────────────────────┘  └────────┘ │ │
│ │                                                │ │
│ │  Type: [Auto-detect ▼]  Max: [2000]           │ │
│ │                                                │ │
│ ╰────────────────────────────────────────────────╯ │
│                                                    │
│  ┌─ INDEXING: anthropics/courses ─────────────┐   │
│  │ ████████████░░░░ 847/1,200 files  71%      │   │
│  │ Agent: DataMind • ANALYTICS station         │   │
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

- URL input: full-width, large (48px height), glowing purple border on focus
- Inline options row: Type dropdown + Max files input (collapsed by default, "Options" toggle)
- Submit: LCARS-style pill button "INGEST" (purple accent)
- No modal — the intake is directly on the page, always visible
- Active job: progress bar appears inline below input with file counter ticking up
- On completion: success notification bar slides in (LCARS `lcarsMsg` pattern)

#### Zone 2: Repository Intelligence Cards
```
┌──────────────────────────────────────────────────┐
│ ╭─ INDEXED REPOSITORIES (7) ─────── [search] ──╮ │
│ │                                                │ │
│ │ ┌──────────────────┐  ┌──────────────────┐    │ │
│ │ │ anthropics/cours  │  │ langchain/langch  │    │ │
│ │ │ ┌──┐              │  │ ┌──┐              │    │ │
│ │ │ │87│% embedded    │  │ │62│% embedded    │    │ │
│ │ │ └──┘              │  │ └──┘              │    │ │
│ │ │ 1,247 files       │  │ 892 files         │    │ │
│ │ │ Indexed 2d ago    │  │ Indexed 5d ago    │    │ │
│ │ │ AI Agents • py    │  │ Python • py       │    │ │
│ │ │ [↻][🗑][↗]       │  │ [↻][🗑][↗]       │    │ │
│ │ └──────────────────┘  └──────────────────┘    │ │
│ │                                                │ │
│ ╰────────────────────────────────────────────────╯ │
└──────────────────────────────────────────────────┘
```

- Grid layout: 2 columns desktop, 1 column mobile
- Each card:
  - Repo name (truncated with title tooltip)
  - Circular SVG progress ring showing embed coverage %
  - File count + last indexed age
  - Repo type badge + primary language
  - Action buttons: Re-index, Delete (with confirm), Open on GitHub
  - LCARS left-cap color bar (color-coded: green >80%, amber 40-80%, red <40% embedded)
- Card expand (click): shows file tree sample, top languages, dependency count
- Empty state: "No repositories indexed yet. Paste a URL above to begin learning." with arrow pointing up

#### Zone 3: Discovery Console
```
┌──────────────────────────────────────────────────┐
│ ╭─ DISCOVERY ───────────────────────────────────╮ │
│ │                                                │ │
│ │  Search ARCHIE's indexed knowledge...          │ │
│ │  ┌──────────────────────────────────────────┐ │ │
│ │  │ How does the embedding service work?      │ │ │
│ │  └──────────────────────────────────────────┘ │ │
│ │                                                │ │
│ │  ┌─ Results (12 matches) ──────────────────┐  │ │
│ │  │ embedding_service.py          98% match  │  │ │
│ │  │ archie/ai_bridge                         │  │ │
│ │  │ > def generate_embedding(text):          │  │ │
│ │  │ >     """Generate vector embedding..."""  │  │ │
│ │  ├──────────────────────────────────────────┤  │ │
│ │  │ knowledge_analyzer.py         89% match  │  │ │
│ │  │ archie/ai_bridge                         │  │ │
│ │  │ > embedding = generate_embedding(...)     │  │ │
│ │  └─────────────────────────────────────────┘  │ │
│ ╰────────────────────────────────────────────────╯ │
└──────────────────────────────────────────────────┘
```

- Large search input (44px height), full-width
- Placeholder: "Ask ARCHIE's knowledge..." (emphasizes semantic, not just keyword)
- Results: card-style with file path, repo name, relevance score bar, code snippet preview
- Syntax highlighting in snippets (basic — keywords colored)
- "No results" state: suggests trying different terms or indexing more repos

### LCARS Operations Terminal (Retained, Moved)
- The existing ops terminal (crew, jobs, commands) moves to a collapsible sidebar or footer
- REINDEX ALL and EMBED FILES remain as ops commands
- VERIFY opens the existing modal (already well-built)

---

## Part 3: Cross-Tab Navigation & Shared Elements

### Tab Bar Enhancement
- Current tab pills are functional but static
- Add: subtle glow on active tab, count badges (e.g., "GitHub (7)"), micro-animation on switch

### Mini Neural Core
- A small (80px) version of the center node + inner ring appears in the top-right corner of non-Dashboard tabs
- Shows current mood + processing state
- Click: returns to Dashboard
- Provides visual continuity — "the brain is always visible"

### LCARS Notification Bar
- Already exists as `lcarsMsg()` — extend to all tabs
- Consistent feedback for: indexing started, indexing complete, embedding done, errors

---

## Part 4: Implementation Sequence

### Phase 1: Neural Core Dashboard (Priority)
1. Build the Canvas/SVG neural core visualization component
2. Wire to real data APIs (dashboard/summary, brain-state, emotional-state)
3. Add orbital animation + particle flow
4. Implement click-to-navigate (node → tab)
5. Stats HUD strips below
6. Responsive breakpoints

### Phase 2: GitHub Tab Restructure
1. Replace modal with inline Intake Port
2. Build repo intelligence cards with progress rings
3. Add delete repo functionality (backend exists)
4. Build Discovery Console with semantic search
5. Wire progress feedback to active jobs
6. Move ops terminal to collapsible section

### Phase 3: Polish & Cross-Tab
1. Tab bar enhancements (badges, glow)
2. Mini neural core component
3. Entry animations (new knowledge flows in)
4. Mood-reactive color system
5. Performance audit (animation budget)
6. Mobile responsive pass

### Phase 4: Other Tabs (Future)
- Apply same LCARS Neural patterns to Knowledge, Team, Insights, Languages tabs
- Each tab gets its own character while sharing the design system
- Dashboard nodes link to their respective tabs

---

## Technical Notes

### Performance Budget
- Canvas particles: max 20 elements, requestAnimationFrame with throttle
- CSS animations: transform/opacity only, `will-change` on animated elements
- SVG pathways: static paths, animated via CSS `stroke-dashoffset`
- Orbital rotation: single parent transform, counter-rotate children
- Target: 60fps on mid-range devices, graceful degradation to static on low-end

### Data Refresh
- Dashboard visualization: load once on tab switch, refresh on manual action
- GitHub stats: cache 60s, refresh on indexing complete
- Mood/emotion: poll every 30s while Dashboard tab is active
- Active jobs: existing polling mechanism (already implemented)

### File Structure
- `consciousness_dashboard.html` — template with visualization markup
- `consciousness.js` — add neural core rendering functions
- CSS stays inline in template (existing pattern)
- No external chart libraries — pure SVG + Canvas + CSS

### Accessibility
- All interactive nodes: `role="button"`, `aria-label`, `tabindex`
- Animation: `prefers-reduced-motion` disables particles, orbital drift, scanline
- Color: all status indicators have icon + label (not color-only)
- Screen reader: hidden canvas, visible stat strips carry the data
