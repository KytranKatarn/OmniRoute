# Dashboard + Login/Signup LCARS Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild Dashboard, Login, and Signup pages using the Consciousness module's LCARS design language with green `#00ff41` accent.

**Architecture:** New shared `lcars-panels.css` component provides reusable LCARS card/panel classes. Login and Signup get full template rewrites (remove matrix rain, add LCARS framed cards). Dashboard gets CSS overhaul of existing sections (command bar, HUD, mission briefing, featured modules, category grid) while preserving all JavaScript logic and API integrations.

**Tech Stack:** Flask/Jinja2 templates, CSS3 (custom properties, backdrop-filter, @keyframes), vanilla JS, Lucide icons

**Design Doc:** `docs/plans/2026-02-25-dashboard-login-overhaul-design.md`

---

## Task 1: Create shared `lcars-panels.css` component

**Files:**
- Create: `platform_v2/static/css/lcars-panels.css`

This is the foundation — all three pages will use these classes.

**Step 1: Create the CSS file**

```css
/* ═══════════════════════════════════════════════════════
   LCARS Panels — Reusable framed card component
   Shared across Dashboard, Login, Signup, and future modules.
   Theme via --lcars-accent (defaults to green #00ff41).
   ═══════════════════════════════════════════════════════ */

:root {
    --lcars-accent: #00ff41;
    --lcars-accent-rgb: 0, 255, 65;
    --lcars-accent-dim: #00cc34;
}

/* ── Panel (Card Container) ─────────────────────────── */
.lcars-panel {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(var(--lcars-accent-rgb), 0.12);
    border-left: 3px solid rgba(var(--lcars-accent-rgb), 0.4);
    border-radius: 0 12px 12px 0;
    padding: 0;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s;
}
.lcars-panel::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: linear-gradient(180deg,
        rgba(var(--lcars-accent-rgb), 0.6) 0%,
        rgba(var(--lcars-accent-rgb), 0.2) 50%,
        rgba(var(--lcars-accent-rgb), 0.4) 100%);
    border-radius: 2px 0 0 2px;
}
.lcars-panel:hover {
    border-color: rgba(var(--lcars-accent-rgb), 0.25);
}

/* ── Panel Header ───────────────────────────────────── */
.lcars-panel-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px 8px;
    margin: 0;
    font-family: 'Orbitron', sans-serif;
    font-size: 0.78rem;
    font-weight: 600;
    color: rgba(var(--lcars-accent-rgb), 0.9);
    text-transform: uppercase;
    letter-spacing: 1.2px;
    background: rgba(var(--lcars-accent-rgb), 0.04);
    border-bottom: 1px solid rgba(var(--lcars-accent-rgb), 0.08);
}

/* ── Cap Bar (6px accent stripe in header) ──────────── */
.lcars-panel-cap {
    width: 6px;
    height: 20px;
    border-radius: 3px;
    background: rgb(var(--lcars-accent-rgb));
    flex-shrink: 0;
}

/* ── Panel Title ────────────────────────────────────── */
.lcars-panel-title {
    font-family: 'Antonio', sans-serif;
    font-size: 0.8rem;
    font-weight: 600;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    flex: 1;
}

/* ── Indicator Light ────────────────────────────────── */
.lcars-panel-light {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: rgb(var(--lcars-accent-rgb));
    box-shadow: 0 0 8px rgba(var(--lcars-accent-rgb), 0.6);
    animation: lcarsPulse 3s ease-in-out infinite;
    flex-shrink: 0;
}

/* ── Panel Body ─────────────────────────────────────── */
.lcars-panel-body {
    padding: 12px 16px;
    max-height: 300px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: rgba(var(--lcars-accent-rgb), 0.3) transparent;
}
.lcars-panel-body::-webkit-scrollbar { width: 6px; }
.lcars-panel-body::-webkit-scrollbar-track { background: transparent; }
.lcars-panel-body::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg,
        rgba(var(--lcars-accent-rgb), 0.4),
        rgba(var(--lcars-accent-rgb), 0.15));
    border-radius: 3px;
}
.lcars-panel-body::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(180deg,
        rgba(var(--lcars-accent-rgb), 0.6),
        rgba(var(--lcars-accent-rgb), 0.3));
}
.lcars-panel-body.no-scroll {
    max-height: none;
    overflow: visible;
}

/* ── Panel Footer ───────────────────────────────────── */
.lcars-panel-footer {
    padding: 8px 16px;
    border-top: 1px solid rgba(var(--lcars-accent-rgb), 0.08);
    font-family: 'Antonio', sans-serif;
    font-size: 0.7rem;
    color: rgba(255,255,255,0.35);
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* ── Accent Variants ────────────────────────────────── */
.lcars-panel.accent-green  { --lcars-accent-rgb: 0, 255, 65; }
.lcars-panel.accent-orange { --lcars-accent-rgb: 245, 158, 11; }
.lcars-panel.accent-cyan   { --lcars-accent-rgb: 0, 255, 255; }
.lcars-panel.accent-purple { --lcars-accent-rgb: 139, 92, 246; }
.lcars-panel.accent-red    { --lcars-accent-rgb: 239, 68, 68; }
.lcars-panel.accent-amber  { --lcars-accent-rgb: 245, 158, 11; }

/* ── Section Label (used above groups of panels) ───── */
.lcars-section-label {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;
}
.lcars-section-cap {
    width: 6px;
    height: 24px;
    border-radius: 3px;
    background: rgb(var(--lcars-accent-rgb));
    flex-shrink: 0;
}
.lcars-section-title {
    font-family: 'Antonio', sans-serif;
    font-size: 0.8rem;
    font-weight: 600;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase;
    letter-spacing: 1.5px;
}

/* ── LCARS Form Controls ────────────────────────────── */
.lcars-input {
    width: 100%;
    padding: 12px 16px;
    background: rgba(var(--lcars-accent-rgb), 0.06);
    border: 1.5px solid rgba(var(--lcars-accent-rgb), 0.2);
    border-radius: 8px;
    color: #fff;
    font-size: 0.9rem;
    font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.lcars-input:focus {
    outline: none;
    border-color: rgb(var(--lcars-accent-rgb));
    box-shadow: 0 0 16px rgba(var(--lcars-accent-rgb), 0.2);
}
.lcars-input::placeholder {
    color: rgba(255,255,255,0.2);
}

.lcars-label {
    display: block;
    font-family: 'Antonio', sans-serif;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: rgba(var(--lcars-accent-rgb), 0.6);
    margin-bottom: 6px;
}

/* ── LCARS Pill Button ──────────────────────────────── */
.lcars-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px 28px;
    background: rgba(var(--lcars-accent-rgb), 0.15);
    border: 1.5px solid rgba(var(--lcars-accent-rgb), 0.4);
    border-radius: 20px;
    color: rgb(var(--lcars-accent-rgb));
    font-family: 'Antonio', sans-serif;
    font-size: 0.88rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.2s, color 0.2s, box-shadow 0.2s;
    position: relative;
    overflow: hidden;
}
.lcars-btn:hover {
    background: rgb(var(--lcars-accent-rgb));
    color: #0a0a1a;
    box-shadow: 0 0 20px rgba(var(--lcars-accent-rgb), 0.3);
}
.lcars-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
/* Energy sweep on hover */
.lcars-btn::after {
    content: '';
    position: absolute;
    top: 0; left: -100%;
    width: 100%; height: 100%;
    background: linear-gradient(90deg,
        transparent,
        rgba(255,255,255,0.15),
        transparent);
    transition: left 0.4s;
}
.lcars-btn:hover::after {
    left: 100%;
}

/* ── LCARS Status Dot ───────────────────────────────── */
.lcars-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    display: inline-block;
}
.lcars-dot.online  { background: #00ff41; box-shadow: 0 0 8px rgba(0,255,65,0.6); }
.lcars-dot.warning { background: #f59e0b; box-shadow: 0 0 8px rgba(245,158,11,0.6); }
.lcars-dot.offline { background: #ef4444; box-shadow: 0 0 8px rgba(239,68,68,0.6); }
.lcars-dot.pulse   { animation: lcarsPulse 3s ease-in-out infinite; }

/* ── Animations ─────────────────────────────────────── */
@keyframes lcarsPulse {
    0%, 100% { opacity: 0.6; box-shadow: 0 0 4px currentColor; }
    50%      { opacity: 1;   box-shadow: 0 0 12px currentColor; }
}

@keyframes lcarsCardIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

@keyframes lcarsFieldIn {
    from { opacity: 0; transform: translateX(-10px); }
    to   { opacity: 1; transform: translateX(0); }
}

@keyframes lcarsSweep {
    from { left: -100%; }
    to   { left: 100%; }
}

/* ── Light Mode ─────────────────────────────────────── */
[data-theme="light"] .lcars-panel,
body.light-mode .lcars-panel {
    background: rgba(0,0,0,0.02);
    border-color: rgba(0,0,0,0.08);
    border-left-color: rgba(var(--lcars-accent-rgb), 0.3);
}
[data-theme="light"] .lcars-panel::before,
body.light-mode .lcars-panel::before {
    background: linear-gradient(180deg,
        rgba(var(--lcars-accent-rgb), 0.4) 0%,
        rgba(var(--lcars-accent-rgb), 0.15) 50%,
        rgba(var(--lcars-accent-rgb), 0.25) 100%);
}
[data-theme="light"] .lcars-panel-header,
body.light-mode .lcars-panel-header {
    background: rgba(var(--lcars-accent-rgb), 0.03);
    border-bottom-color: rgba(0,0,0,0.06);
}
[data-theme="light"] .lcars-panel-title,
body.light-mode .lcars-panel-title {
    color: rgba(0,0,0,0.5);
}
[data-theme="light"] .lcars-panel-light,
body.light-mode .lcars-panel-light {
    box-shadow: none;
    animation: none;
}
[data-theme="light"] .lcars-input,
body.light-mode .lcars-input {
    background: rgba(0,0,0,0.03);
    border-color: rgba(0,0,0,0.12);
    color: #1a1a2e;
}
[data-theme="light"] .lcars-input:focus,
body.light-mode .lcars-input:focus {
    box-shadow: 0 0 8px rgba(var(--lcars-accent-rgb), 0.1);
}
[data-theme="light"] .lcars-label,
body.light-mode .lcars-label {
    color: rgba(0,0,0,0.5);
}
[data-theme="light"] .lcars-btn,
body.light-mode .lcars-btn {
    background: rgba(var(--lcars-accent-rgb), 0.08);
    border-color: rgba(var(--lcars-accent-rgb), 0.25);
    color: var(--lcars-accent-dim, #00cc34);
}
[data-theme="light"] .lcars-btn:hover,
body.light-mode .lcars-btn:hover {
    box-shadow: none;
}
[data-theme="light"] .lcars-dot,
body.light-mode .lcars-dot {
    box-shadow: none;
}

/* ── Reduced Motion ─────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
    .lcars-panel-light,
    .lcars-dot.pulse { animation: none; }
    .lcars-btn::after { display: none; }
}

/* ── Responsive ─────────────────────────────────────── */
@media (max-width: 480px) {
    .lcars-panel-header { padding: 8px 12px 6px; font-size: 0.7rem; }
    .lcars-panel-body { padding: 10px 12px; }
    .lcars-btn { padding: 10px 20px; font-size: 0.8rem; }
}
```

**Step 2: Verify the file renders correctly**

Open a browser and manually include it in any page to confirm classes load. Or visually inspect later during Login task.

**Step 3: Commit**

```bash
git add platform_v2/static/css/lcars-panels.css
git commit -m "feat: add shared lcars-panels.css component for LCARS framed cards"
```

---

## Task 2: Rebuild Login page

**Files:**
- Modify: `platform_v2/templates/login.html` (lines 7–1265, full rewrite of CSS + HTML, JS preserved)

This is a full template rewrite. The existing file has 1,267 lines. We will replace the CSS (lines 7–951), restructure the HTML (lines 953–1087), and update the JS (lines 1089–1265) to remove matrix rain.

**Critical preservations:**
- Form action: `POST /login` with fields `username` and `password`
- OAuth: `{{ url_for('oauth.google_login') }}` link
- Theme toggle: `window.toggleTheme()` delegation
- Language menu: `archieI18n` integration, 8 languages, all `data-i18n` keys
- Password toggle: eye icon SVG swap
- Flash messages: handled by `base.html` (no changes needed)
- `{% extends "base.html" %}`, `{% block title %}`, `{% block module_name %}`, `{% block styles %}`, `{% block content %}`, `{% block scripts %}`

**Step 1: Rewrite the full template**

Replace the entire file with the LCARS version. Key changes:

**CSS (block styles):**
- Remove all 15 animation @keyframes (cardMaterialize, borderBreathe, scanSweep, cornerDrawH/V, headerReveal, shimmerPass, logoGlow, logoReveal, subtitleType, fieldMaterialize, btnPowerUp, statusPulse, spin, fadeIn, fadeInUp)
- Add `lcars-panels.css` link: `<link rel="stylesheet" href="{{ url_for('static', filename='css/lcars-panels.css') }}">`
- New simplified animations: `lcarsCardIn` (0.8s), `lcarsFieldIn` (0.2s stagger), `lcarsBtnPowerUp` (0.4s)
- Background: dark gradient with radial green glow — CSS only (no canvas)
- Login card uses `.lcars-panel` + custom overrides for centered card layout
- Form inputs use `.lcars-input` + `.lcars-label` from shared CSS
- Submit button uses `.lcars-btn` from shared CSS
- Corner decorations: 2 corners only (top-left, bottom-right), simpler CSS
- Status indicators: `.lcars-dot.online.pulse` from shared CSS
- Light mode: override dark theme selectors with `body.light-mode`
- 5 responsive breakpoints preserved (1280/768/717/480/374)

**HTML (block content):**
- Remove: `<canvas id="matrix-bg">`, `<div class="grid-overlay">`, `<div class="scan-line">`
- Remove: 2 corner decorations (keep top-left + bottom-right only)
- Card becomes: `.login-card.lcars-panel` with custom centered layout
- Header becomes: `.lcars-panel-header` with cap + logo + indicator lights
- Form groups use `.lcars-label` + `.lcars-input`
- Submit button uses `.lcars-btn`
- System status uses `.lcars-dot.online.pulse`
- OAuth, language menu, theme toggle structure preserved

**JS (block scripts):**
- Remove: entire Matrix rain IIFE (canvas setup, draw loop, resize handler)
- Remove: `document.getElementById('matrix-bg')` references
- Keep: form submit handler (loading state)
- Keep: password toggle
- Keep: forgot password toggle
- Keep: theme toggle (remove canvas clear on theme change)
- Keep: language menu
- Add: simplified boot animation (card + field stagger via CSS classes)

**Step 2: Test in browser**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/login` and verify:
- LCARS framed card renders with green accent
- Form submits correctly (POST /login)
- Password toggle works
- Theme toggle works (light/dark)
- Language menu works
- OAuth button links correctly
- Boot animation plays (~2.5s)
- All 5 breakpoints look correct (resize browser)

**Step 3: Commit**

```bash
git add platform_v2/templates/login.html
git commit -m "feat: rebuild Login page with LCARS design language"
```

---

## Task 3: Rebuild Signup page

**Files:**
- Modify: `platform_v2/templates/signup.html` (full rewrite matching Login pattern)

Same approach as Login — rewrite CSS + HTML, preserve form logic.

**Critical preservations:**
- Form action: `POST /signup` with fields `username`, `email`, `password`, `confirm_password`
- OAuth: `{{ url_for('oauth.google_login') }}` link
- Password strength bar: `strengthFill`, `strengthNote` — JS logic preserved
- Theme toggle + language menu: same as Login
- Back link: `{{ url_for('login') }}`
- Approval notice section: preserved
- All `data-i18n` keys preserved

**Step 1: Rewrite the full template**

Follow Login pattern exactly, with these differences:
- Card max-width: 520px (wider than Login's 440px)
- Add LCARS step indicator at top (Account → Profile → Confirm)
  - 3 pill segments in a flex row
  - Active step: green fill + glow
  - Future steps: dim border only
  - Step transitions: CSS `translateX` + opacity (0.3s)
- Step 1: Username + Email fields
- Step 2: Password + Confirm Password + Strength bar
- Step 3: Approval notice (review + terms)
- Navigation: "NEXT" / "BACK" pill buttons between steps
- Final submit on Step 3
- Password strength bar: thin progress bar with green gradient fill (same JS logic)

**Step 2: Test in browser**

Navigate to `http://192.168.1.200:3000/signup` and verify:
- LCARS card renders, matches Login aesthetic
- Step indicator shows 3 steps
- Step transitions animate smoothly
- Password strength updates live
- Form submits correctly
- Theme/language/OAuth all work
- Responsive at all 5 breakpoints

**Step 3: Commit**

```bash
git add platform_v2/templates/signup.html
git commit -m "feat: rebuild Signup page with LCARS multi-step form"
```

---

## Task 4: Dashboard — Command Bar + HUD Vitals LCARS overhaul

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (CSS lines 563–1557)

This task only touches the **CSS** for the command bar and HUD vitals strip. No HTML structure changes, no JS changes.

**Critical preservations:**
- All element IDs (command-bar, cbSearchInput, cbNotifBtn, etc.)
- All JavaScript event handlers
- All API endpoint calls
- HUD ring gauge SVG structure
- Notification popover + detail modal structure

**Step 1: Restyle Command Bar CSS (lines 563–1296)**

Replace command bar CSS with LCARS treatment:
- `.command-bar`: Add `backdrop-filter: blur(16px)`, remove old gradient, add glass bg `rgba(10,10,26,0.8)`
- Add green accent bar on left edge (6px, via `::before` pseudo-element)
- `.cb-search-input`: Use `.lcars-input` styling (green focus glow)
- `.cb-search-popover`: Use `.lcars-panel` styling (glass card with green accent)
- `.cb-notif-popover`: Use `.lcars-panel` styling
- `.cb-notif-item.unread`: Green left border (was generic)
- `.cb-notif-modal`: Use `.lcars-panel` styling for modal body
- `.cb-icon-btn`: Add hover glow (`box-shadow: 0 0 12px rgba(0,255,65,0.2)`)
- `.cb-avatar`: Keep gradient, add subtle green glow ring
- Fonts: Ensure Antonio for labels, Orbitron for any numeric values

**Step 2: Restyle HUD Vitals CSS (lines 1300–1557)**

Replace HUD strip CSS with LCARS treatment:
- `.hud-vitals-strip`: Add `backdrop-filter: blur(12px)`, glass bg, green accent border-left
- `.hud-pod-label`: Antonio font, letter-spacing 0.12em, uppercase
- `.hud-pod-value`: Orbitron font, green color (#00ff41)
- `.hud-ring-fg`: Green stroke with glow filter (`filter: drop-shadow(0 0 4px rgba(0,255,65,0.4))`)
- `.hud-ring-center`: Orbitron font
- `.hud-ai-dot`, `.hud-archie-dot`: Use `.lcars-dot.online.pulse` pattern
- Add section label above strip: "SYSTEM STATUS" with cap bar (`.lcars-section-label`)
- Light mode: mute glows, lighter backgrounds

**Step 3: Test**

```bash
docker compose restart archie_platform
```

Navigate to Dashboard, verify:
- Command bar has glass effect + green accent
- Search popover has LCARS styling
- Notification popover + modal have LCARS styling
- HUD pods show Orbitron numbers with green glow
- Ring gauges have green glow filter
- All interactions still work (search, notifications, theme, language)
- Light mode renders correctly

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS overhaul — command bar + HUD vitals"
```

---

## Task 5: Dashboard — Mission Briefing LCARS overhaul

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (CSS lines 1782–2134, minor HTML adjustments)

**Step 1: Restyle Mission Briefing CSS**

Replace mission briefing card CSS:
- `.briefing-card`: Use `.lcars-panel` base pattern (glass bg, left accent border, `::before` gradient)
- `.briefing-card-header`: Use `.lcars-panel-header` pattern (Orbitron, letter-spacing, accent bg)
- `.briefing-card-body`: Use `.lcars-panel-body` pattern (scrollable, custom scrollbar)
- Color variants:
  - `.briefing-card--activity`: `--lcars-accent-rgb: 0, 255, 65` (green)
  - `.briefing-card--alerts`: `--lcars-accent-rgb: 245, 158, 11` (orange)
  - `.briefing-card--ai`: `--lcars-accent-rgb: 0, 255, 255` (cyan)
- Add indicator light (`.lcars-panel-light`) to each card header
- `.briefing-activity-item`: Subtle bottom border, Antonio font for labels
- `.briefing-alert-item`: Keep severity colors, add left accent bar per severity
- `.briefing-ai-big-number`: Orbitron font, cyan color with subtle glow
- Light mode overrides for all card variants

**Step 2: Update Mission Briefing HTML (lines 3015–3048)**

Add LCARS panel structure to each card:
- Wrap each card header in `.lcars-panel-header` with `.lcars-panel-cap` + `.lcars-panel-light`
- Wrap content in `.lcars-panel-body`
- Add accent variant class to each card div

**Step 3: Test**

Verify:
- 3 mission cards render as LCARS panels with colored accents
- Activity feed scrolls correctly
- Alerts render with severity colors
- AI insights show big numbers in Orbitron
- Responsive: 3-col → 2-col → 1-col works
- JS rendering functions (`renderRecentActivity`, `renderAlerts`, `renderAiInsights`) still populate correctly

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS mission briefing cards with colored accents"
```

---

## Task 6: Dashboard — Featured Modules + Category Grid LCARS overhaul

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (CSS lines 2140–2673, minor HTML)

**Step 1: Restyle Featured Modules CSS (lines 2140–2421)**

- `.section-header`: Use `.lcars-section-label` pattern (cap bar + Antonio title)
- `.featured-card`: LCARS pill card — `border-radius: 12px`, glass bg, green left accent (3px border), Orbitron for name, Antonio for description
- `.featured-card:hover`: Green glow `box-shadow: 0 0 16px rgba(0,255,65,0.15)`
- `.featured-status-dot`: Use `.lcars-dot` patterns (online/offline/warning)
- `.featured-pin-btn`: Subtle, Antonio font, pill shape

**Step 2: Restyle Category Grid CSS (lines 2428–2673)**

- `.cat-header`: LCARS framed header — glass bg, `::before` gradient accent bar (using `--cat-accent`), Antonio title, chevron
- `.cat-header::before`: 4px top gradient bar in `--cat-accent` color
- `.module-card`: LCARS glass tile — `backdrop-filter: blur(8px)`, thin border, small colored cap (4px top bar in category accent), rounded corners
- `.module-card:hover`: Border glow in category accent color
- `.module-card-icon`: Keep current icon with category accent color
- `.module-card-name`: Orbitron font, 0.75rem
- `.module-card-status`: Use `.lcars-dot` pattern
- `.module-badge`: LCARS pill badge (Antonio, letter-spacing)
- `.module-pin-btn`: Match featured pin btn styling
- Preserve category accent color classes (`.category-admin_operations` etc.)
- Light mode overrides

**Step 3: Update HTML (minor)**

- Featured section header: add cap bar div
- Module cards: add 4px top accent bar div (or via `::before` pseudo-element)

**Step 4: Test**

Verify:
- Featured modules row renders with LCARS styling
- Pin/unpin still works (localStorage)
- Category panels expand/collapse
- Module cards have glass effect + colored caps
- Category accent colors preserved per group
- Module status dots update from API
- Client-side search still finds modules
- Responsive grid: 4-col → 2-col → 1-col
- Light mode

**Step 5: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS featured modules + category grid overhaul"
```

---

## Task 7: Dashboard — Boot Sequence LCARS alignment

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (CSS lines 117–555, JS lines 3235–3497)

**Step 1: Restyle Boot Sequence CSS**

- `.boot-overlay`: Keep full-screen black
- `.boot-terminal`: Add faint green glow to text (`text-shadow`)
- `.boot-line`: Antonio font (was monospace), green color
- `.boot-cursor`: Green blinking cursor
- `.boot-typing-line`: Orbitron font for "INITIALIZING A.R.C.H.I.E. CORE..."
- `.boot-threat`/`.midnight-text`: Keep red/orange flash (dramatic)
- `.boot-logo-text`: Orbitron, green glow (align with login logo)
- `.boot-logo-ring`: Green expanding rings (was generic)
- `.boot-system-online`: Antonio, letter-spacing
- `.boot-scanlines`: Keep CRT effect (subtle)
- `.boot-skip-btn`: LCARS pill button style (Antonio, green border)

**Step 2: Update Boot JS fonts**

The boot sequence JS creates elements dynamically. Ensure:
- Text created in JS uses Antonio/Orbitron class names
- Subsystem check labels use Antonio
- Progress bar uses green gradient fill
- Status text uses green/orange/red colors

**Step 3: Test**

- Full boot sequence plays with LCARS fonts
- Skip button works
- Session skip (sessionStorage) still bypasses boot
- Split reveal animation works
- i18n boot messages still display

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS boot sequence with Orbitron/Antonio fonts"
```

---

## Task 8: Dashboard — Notification Modal + Search Popover polish

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (CSS within command bar section)

**Step 1: Polish Notification Detail Modal**

- `.cb-notif-modal`: Add LCARS panel styling (glass bg, green accent border)
- `.cb-notif-modal-header`: LCARS panel header (cap bar + Orbitron title + indicator light)
- `.cb-notif-modal-body`: Glass body, Antonio font
- `.cb-notif-modal-meta`: Antonio font, dim color, letter-spacing
- `.cb-notif-modal-footer .btn`: Use `.lcars-btn` styling
- Add entrance animation: `lcarsCardIn` (slide up + fade)

**Step 2: Polish Search Popover**

- `.cb-search-popover`: LCARS panel glass bg, green accent border
- `.cb-search-result`: Hover glow in accent color, Antonio font for category
- `.cb-search-result-name`: Orbitron font
- `.cb-search-empty`: Antonio font, dim color

**Step 3: Test**

- Click notification bell → popover has LCARS styling
- Click notification → detail modal slides in with LCARS styling
- Mark as read works
- Ctrl+K → search popover has LCARS styling
- Arrow key navigation works
- Enter selects result
- Responsive at all breakpoints

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS notification modal + search popover polish"
```

---

## Task 9: Visual baseline + final verification

**Files:**
- No code changes

**Step 1: Run Playwright visual baseline**

```bash
node platform_v2/tests/visual_baseline.mjs --username admin --password 'Kyt$13ran2025'
```

This captures screenshots at all breakpoints for Login, Signup, Dashboard.

**Step 2: Manual verification checklist**

- [ ] Login: LCARS card, no matrix rain, boot animation ~2.5s, form works, OAuth works
- [ ] Login light mode: clean, no glows
- [ ] Login 374px: corner decorations hidden, card fits
- [ ] Signup: LCARS card, step indicator, step transitions, form submits
- [ ] Signup light mode: clean
- [ ] Dashboard: Command bar glass effect, HUD green glows, mission cards with accents
- [ ] Dashboard: Featured modules LCARS pills, category grid with colored caps
- [ ] Dashboard: Boot sequence with LCARS fonts
- [ ] Dashboard: Notifications + search popovers with LCARS styling
- [ ] Dashboard light mode: all sections clean
- [ ] Dashboard 374px: mobile layout, cards stack, module grid 1-col
- [ ] All pages: `prefers-reduced-motion` disables animations

**Step 3: Commit (if any fixups needed)**

```bash
git add -A
git commit -m "fix: visual polish after baseline review"
```

---

## Task 10: Push + Update Dev HQ

**Step 1: Push all commits**

```bash
git push
```

**Step 2: Update Dev HQ**

- `mcp store_memory` — vault note documenting the LCARS overhaul (what changed, patterns used)
- `mcp update_project_understanding` — update project #94 awareness
- `mcp log_decision` — ADR for LCARS panel shared component
- `mcp complete_task` — if there are relevant tasks in project #94

**Step 3: Restart platform**

```bash
docker compose restart archie_platform
```

Verify live site at `http://192.168.1.200:3000`.
