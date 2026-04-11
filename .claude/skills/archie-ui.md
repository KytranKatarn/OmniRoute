---
name: archie-ui
description: LCARS UI reference for A.R.C.H.I.E. platform — design tokens, modal patterns, CSS classes, breakpoints, station colors. Use when building or modifying any platform UI component.
---

# ARCHIE LCARS UI Reference

Platform-specific UI patterns. Use this when building or modifying any A.R.C.H.I.E. module UI.

## Refactoring Protocol

**One component at a time. Screenshot before and after. CSS-only when possible.**

```
1. SCREENSHOT — Capture current state (Playwright or P.R.O.B.E.)
2. EDIT CSS   — ONE focused change (just tabs OR just buttons, never both)
3. DEPLOY     — docker compose restart archie_platform
4. SCREENSHOT — Capture same view again
5. COMPARE    — Verify no regression
6. COMMIT     — Only if verified. Revert if broken.
```

Prohibited:
- Never 50+ edits to a template in one shot
- Never use `!important` to fix display issues
- Never add inline `display:none` as a fix
- Never claim "done" without a screenshot

## Design Tokens

Import `lcars-tokens.css` FIRST in any module. All colors via `var(--archie-*)`.

### Primary Colors
| Token | Hex | Use |
|-------|-----|-----|
| `--archie-green` | #00ff41 | Success, active states |
| `--archie-cyan` | #00ffff | Primary accent, links |
| `--archie-orange` | #ffaa00 | Warnings, attention |
| `--archie-red` | #ff6b6b | Danger, errors |
| `--archie-purple` | #8b5cf6 | Analytics, Consciousness |
| `--archie-blue` | #0ea5e9 | Info, secondary accent |
| `--archie-pink` | #f472b6 | Creative |
| `--archie-gold` | #fbbf24 | Engineering |

### Alpha Variants
Each primary has `-alpha-10`, `-alpha-20`, `-alpha-30` for rgba overlays.

### Semantic
`--archie-success`, `--archie-warning`, `--archie-danger`, `--archie-info` (each with `-bg` and `-border` variants).

### Legacy
`--lcars-accent` (#00ff41), `--lcars-accent-rgb`, `--lcars-accent-dim` (#00cc34).

### Modal Accent
Set `--bm-accent` on `.bm-shell` for per-modal theming.

## Font Stack

| Font | Use | CSS |
|------|-----|-----|
| Antonio | Navigation, UI labels | `font-family: 'Antonio', sans-serif` |
| Orbitron | Titles, headers | `font-family: 'Orbitron', sans-serif` |
| IBM Plex Mono | Code, data, monospace | `font-family: 'IBM Plex Mono', monospace` |

## LCARS Modal Pattern

```html
<div class="bm-overlay" id="my-modal">
  <div class="bm-shell" style="--bm-accent: var(--archie-cyan)">
    <div class="bm-frame">
      <div class="bm-content">
        <div class="bm-header">Title</div>
        <div class="bm-body">Content here</div>
        <div class="bm-footer">
          <button class="bm-btn">Action</button>
        </div>
      </div>
    </div>
  </div>
</div>
```

Show: add `.active` to `.bm-overlay`
Theming: cyan (info/load), red (danger/unload/alert)
Reference: `bridge.html` lines 9209-9249

## LCARS Panel Component

```html
<div class="lcars-panel">
  <div class="lcars-panel-header">
    <span class="lcars-panel-title">Section Title</span>
    <span class="lcars-panel-light"></span>
  </div>
  <div class="lcars-panel-body">Content</div>
  <div class="lcars-panel-cap"></div>
</div>
```

Shared stylesheet: `static/css/lcars-panels.css`

## CSS Class Prefixes by Module

| Prefix | Module |
|--------|--------|
| `sn-` | Security Network |
| `ac-` | Account Center |
| `bm-` | Backup Manager / Modals |
| `sc-` | StationOps / Crew |
| `cs-` | Consciousness |
| `devhq-` | Dev HQ |
| `lcars-` | Shared panel components |

Pattern: `{prefix}-{component}-{modifier}` (e.g., `sn-tab-active`, `bm-modal-danger`)

New modules: pick a 2-3 letter prefix, add to this list.

## Live Data Indicators

| Class | Effect |
|-------|--------|
| `sc-live` | Pulsing teal glow (real-time data) |
| `sc-static` | Dim, no animation (stale data) |

## 10 Station Colors

| Station | Hex | CSS |
|---------|-----|-----|
| COMMAND | #00e5ff | `var(--archie-cyan)` approx |
| ANALYTICS | #8b5cf6 | `var(--archie-purple)` |
| CREATIVE | #f472b6 | `var(--archie-pink)` |
| ENGINEERING | #fbbf24 | `var(--archie-gold)` |
| COMMUNICATIONS | #22d3ee | — |
| RESEARCH | #10b981 | — |
| SECURITY | #ef4444 | `var(--archie-red)` approx |
| LOGISTICS | #f97316 | `var(--archie-orange)` approx |
| DIPLOMATIC | #818cf8 | — |
| OPERATIONS | #a3e635 | — |

## Responsive Breakpoints

```css
@media (max-width: 480px)  { /* Mobile phone */ }
@media (max-width: 768px)  { /* Tablet / large phone */ }
@media (max-width: 1024px) { /* Small desktop / tablet landscape */ }
```

## Shared Components

| File | Purpose |
|------|---------|
| `static/css/lcars-tokens.css` | Central CSS variables — import FIRST |
| `static/css/lcars-panels.css` | Reusable framed card component |
| `static/css/station-ops.css` | LCARS station terminal |
| `static/js/station-ops.js` | StationOps JS (crew, jobs, commands) |
| `static/js/archie-time.js` | Global timezone formatter |
| `static/js/archie-i18n.js` | i18n with `data-i18n` + `t()` |

## Agent Cards

Use `_renderUnifiedAgentCard()` for all agent cards (hub + node).
Profile: `openAgentProfileFromBridge(hubAgentId)` — always fetch from Starbase endpoint.
Single status badge: ON DUTY / DEPLOYED / WORKING / BARRACKED / OFF DUTY.

## Before You Start

1. **Check `lcars-tokens.css`** — your color probably already has a token
2. **Check `base.html` shared CSS** — your class might already exist
3. **Use `bm-overlay.active`** for modals — don't invent new modal patterns
4. **Grep existing CSS** before writing new rules — avoid duplication
5. **Read the component** you're modifying — understand HTML structure first
