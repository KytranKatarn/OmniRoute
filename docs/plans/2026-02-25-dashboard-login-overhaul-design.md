# Dashboard + Login/Signup Full Visual Overhaul — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild Dashboard, Login, and Signup pages using the Consciousness module's LCARS design language — framed headers, glassmorphism cards, indicator lights, Antonio/Orbitron fonts — while keeping green `#00ff41` as the accent color.

**Status:** Approved 2026-02-25

---

## Architecture

### Shared Assets (already built, reuse)
- `theme.css` — 150+ CSS custom properties
- `glass-nav.css` + `glass-nav.js` — frosted tab navigation (available but not used here)
- `category-nav.css` — LCARS strip navigation
- `animations.css` — shared keyframes

### New Shared Component
- `static/css/lcars-panels.css` — reusable LCARS framed panel component

### No HoloSphere on Dashboard or Login
Dashboard is operational (module access), Login is a gateway. HoloSphere stays Consciousness-only.

---

## Section 1: Login Page (Full Rebuild)

### Background
- Replace matrix rain canvas with LCARS-style background
- Dark gradient (`#0a0a1a` → `#0f0f2a`) with soft radial glow (green-tinted) centered behind card
- Optional: slow-drifting CSS-only particle dust (no canvas)

### Card
- LCARS framed card replacing current glassmorphic card
- Framed header with colored cap bar (6px green accent, left side)
- `backdrop-filter: blur(16px)` glass body
- Indicator lights in header (3 dots: green pulse sequence)
- Corner bracket decorations (simplified, 2 corners only)
- Orbitron logo, Antonio labels, IBM Plex Mono form inputs

### Boot Sequence
- Keep staggered reveal but simplify
- Card fades in (0.8s), header slides (0.4s), fields stagger (0.2s each), button powers up
- Total: ~2.5s (down from ~5s)
- No scanning beam, no matrix rain

### Form Controls
- LCARS-styled inputs with bottom accent border (green glow on focus)
- Pill-shaped submit button with energy sweep hover
- Status indicators below form (SYSTEM ONLINE / AI CORE / SECURITY — LCARS dot indicators)

### Light Mode
- Muted green accent on white/light gray
- No glows, simplified shadows

### Responsive
- 5 breakpoints: 1280/768/717/480/374px
- Corner decorations hide at 480px

---

## Section 2: Signup Page

### Same Design Language as Login
- Shared LCARS framed card, same background, same boot sequence timing

### Differences
- Wider card (max 520px vs 440px)
- Multi-step form with LCARS step indicator at top
  - Pill-shaped segments showing progress (Step 1/3 green filled, 2/3 and 3/3 dim)
  - Steps: Account → Profile → Confirm
- Each step transition: current panel slides left + fades, next slides in from right (0.3s)
- Terms checkbox gets LCARS-styled toggle
- Same form controls, fonts, button style as Login

---

## Section 3: Dashboard

### Overall Layout (top to bottom)

#### 1. Command Bar (sticky, 56px)
- Keep current structure, restyle with glassmorphism
- `backdrop-filter: blur(16px)` background
- LCARS framed left edge (green accent bar)
- User avatar, search, notification bell, theme toggle, logout
- Notification dropdown gets LCARS card styling (framed header, accent cap)

#### 2. HUD Vitals Strip
- Glassmorphism strip below command bar
- LCARS framed section label ("SYSTEM STATUS" in Antonio, letter-spaced)
- Ring gauges get green glow treatment
- Status pods use `holo-hud-item` pattern (label + value, Orbitron numbers)

#### 3. Mission Briefing (3-column grid)
- Each card becomes an LCARS tablet panel:
  - Framed header with colored cap (6px left accent bar)
  - Antonio title, indicator light in header
  - Glassmorphism body with `backdrop-filter`
  - Scrollable content area
- **Activity Feed** card: green accent cap
- **Alerts** card: orange/amber accent cap
- **Quick Insights** card: cyan accent cap
- Responsive: 3-col → 2-col at 768px → 1-col at 480px

#### 4. Featured Modules
- Horizontal scroll strip
- LCARS pill-shaped module buttons (not cards)
- Green glow on hover, status dot indicator
- Antonio labels, compact layout

#### 5. Category Panels (module grid)
- Each category gets a collapsible LCARS framed section
- Header: colored cap bar + Antonio title + expand/collapse chevron + indicator light
- Module cards inside: glassmorphism tiles in responsive grid (4-col → 2-col → 1-col)
- Each module card: small colored cap at top, icon, name (Orbitron), description (IBM Plex Mono), status dot, glow hover
- Category accent colors preserved (AI Command = cyan, Dev Tools = purple, SaaS = orange, etc.)

#### 6. Boot Sequence
- Keep cinematic startup, align with LCARS
- Same phased reveal (typing → subsystems → logo → split)
- Replace non-LCARS styling with Antonio/Orbitron fonts
- Green accent throughout

### CSS Approach
- All styles use `--archie-*` design tokens from theme.css
- LCARS framed headers use shared `.lcars-panel` classes from `lcars-panels.css`
- Inline CSS in template (matching current pattern)

---

## Section 4: Shared LCARS Panel Component

**New file: `static/css/lcars-panels.css`**

```
.lcars-panel          — glass card with border + backdrop blur
.lcars-panel-header   — flex header with cap bar + title + indicator
.lcars-panel-cap      — 6px colored accent bar (left or top)
.lcars-panel-title    — Antonio font, letter-spaced, uppercase
.lcars-panel-light    — 5px indicator dot with glow pulse
.lcars-panel-body     — scrollable content area
.lcars-panel-footer   — optional bottom bar
```

Colors via CSS variable `--lcars-accent` (defaults to green, overridable per instance). No JavaScript needed — pure CSS.

Replaces one-off `.cs-card`, `.mission-card`, `.category-panel` patterns with single consistent component.

---

## Section 5: What Stays, What Goes

| Element | Login | Signup | Dashboard |
|---------|-------|--------|-----------|
| Matrix rain canvas | Remove | Remove | Keep boot overlay, remove rain |
| Breathing borders | Replace with LCARS frame | Same | N/A |
| Corner decorations | Simplify (2 corners) | Same | N/A |
| Glassmorphism | Keep (in LCARS panels) | Same | Add to all cards |
| Boot sequence | Shorten to ~2.5s | Same | Keep existing phases |
| HoloSphere | No | No | No |
| GlassNav | No | No | No (command bar serves as nav) |
| LCARS framed headers | New | New | New |
| Indicator lights | New | New | New |
| Pill buttons | New | New | Update existing |
| Fonts (Antonio/Orbitron/IBM Plex) | Update | Update | Complete coverage |

---

## Testing

- Playwright visual baseline at 5 breakpoints (374/480/717/768/1280px)
- Light/dark mode for all three pages
- Boot sequence timing verification
- `prefers-reduced-motion` respected (disable all animations)

---

## Color Reference

- **Dashboard/Login accent:** Green `#00ff41`
- **Alerts:** Orange/amber `#f59e0b`
- **Info/Insights:** Cyan `#00ffff`
- **Per-category module colors:** Preserved from current system

## Font Stack

- **Titles/Values:** Orbitron 400-800
- **Labels/Nav:** Antonio 400-700
- **Body/Code:** IBM Plex Mono 300-500
- **Forms:** JetBrains Mono (inputs)
