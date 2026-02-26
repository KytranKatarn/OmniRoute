# Full OKUDAGRAM LCARS Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace thin-accent LCARS with authentic OKUDAGRAM structural frames — thick elbows, 48px sidebars, segmented color blocks, header/footer bars with pips — on Dashboard, Login, and Signup pages via a shared component system.

**Architecture:** New `lcars-frames.css` shared component (promoted from Consciousness modal frame pattern at `consciousness_dashboard.html:1148-1220`). Dashboard uses stacked framed panels. Login/Signup use centered tablet frames. Frame-build boot animation replaces terminal typing. Responsive sidebar scales 48→32→24→16px. Light mode renders frames as muted schematics.

**Tech Stack:** CSS3 (custom properties, backdrop-filter, clip-path, @keyframes), Flask/Jinja2 templates, vanilla JS, Lucide icons

**Design Doc:** `docs/plans/2026-02-26-lcars-okudagram-redesign-design.md`

---

## Task 1: Create shared `lcars-frames.css` structural component

**Files:**
- Create: `platform_v2/static/css/lcars-frames.css`

This is the foundation. All pages will use these structural frame classes.

**Blueprint reference:** `platform_v2/tools/consciousness/templates/consciousness_dashboard.html:1148-1220` (modal frame with elbows, segments, lights)

**Step 1: Create the CSS file with all structural components**

The file must contain these components in order:

1. **CSS Variables** (`:root`)
   - `--frame-color: #00ff41`
   - `--frame-rgb: 0, 255, 65`
   - `--frame-radius: 20px`
   - `--frame-sidebar-w: 48px`
   - `--frame-bar-h: 44px`
   - `--frame-footer-h: 28px`
   - `--frame-elbow-top-h: 52px`
   - `--frame-elbow-bottom-h: 36px`
   - `--frame-seg-h: 28px`
   - `--frame-seg-gap: 4px`

2. **`.lcars-frame`** — Outer container
   - `display: flex; flex-direction: row`
   - Transparent background (content sits on page background)

3. **`.lcars-sidebar`** — Left structural column
   - `width: var(--frame-sidebar-w); flex-shrink: 0`
   - `display: flex; flex-direction: column; gap: var(--frame-seg-gap)`

4. **`.lcars-elbow-top`** — Top sweeping corner
   - `height: var(--frame-elbow-top-h); background: var(--frame-color)`
   - `border-radius: var(--frame-radius) 0 0 0`
   - `position: relative`
   - `::after` — Cutout notch: `position: absolute; bottom: 0; right: 0; width: 18px; height: 18px; background: var(--archie-bg-primary, #010409); border-radius: var(--frame-radius) 0 0 0`

5. **`.lcars-elbow-bottom`** — Bottom sweeping corner
   - `height: var(--frame-elbow-bottom-h); background: var(--frame-color)`
   - `border-radius: 0 0 0 var(--frame-radius)`
   - `position: relative`
   - `::after` — Cutout notch: `position: absolute; top: 0; right: 0; width: 18px; height: 14px; background: var(--archie-bg-primary, #010409); border-radius: 0 0 0 var(--frame-radius)`

6. **`.lcars-seg`** — Sidebar color block
   - `height: var(--frame-seg-h); background: var(--seg-color, var(--frame-color))`
   - `border-radius: 0 8px 8px 0; flex-shrink: 0`

7. **`.lcars-seg-light`** — Indicator light between segments
   - `width: 10px; height: 10px; border-radius: 50%; align-self: center`
   - `background: var(--light-color, var(--frame-color))`
   - `box-shadow: 0 0 8px var(--light-color, var(--frame-color))`
   - `animation: lcarsFramePulse 3s ease-in-out infinite`
   - `margin: 3px 0`

8. **`.lcars-seg-fill`** — Flexible spacer
   - `flex: 1; background: rgba(var(--frame-rgb), 0.15)`
   - `border-radius: 0 8px 8px 0; min-height: 8px`

9. **`.lcars-content`** — Right content column
   - `flex: 1; display: flex; flex-direction: column; min-width: 0`
   - `margin-left: 8px` (gap between sidebar and content)

10. **`.lcars-bar`** — Header bar
    - `height: var(--frame-bar-h); background: var(--frame-color)`
    - `border-radius: 0 var(--frame-radius) var(--frame-radius) 0`
    - `display: flex; align-items: center; padding: 0 16px; gap: 12px`
    - `font-family: 'Antonio', sans-serif; font-size: 0.8rem; font-weight: 600`
    - `color: var(--archie-bg-primary, #010409); text-transform: uppercase; letter-spacing: 1.5px`

11. **`.lcars-bar-title`** — Title text inside header bar
    - `font-family: 'Antonio', sans-serif; white-space: nowrap`

12. **`.lcars-bar-spacer`** — Flexible gap in header bar
    - `flex: 1`

13. **`.lcars-pips`** — Decorative readout group
    - `display: flex; align-items: center; gap: 4px`

14. **`.lcars-pip`** — Individual pip rectangle
    - `height: 8px; border-radius: 4px; display: block`
    - `background: rgba(var(--archie-bg-primary-rgb, 1,4,9), 0.3)`
    - Widths set inline: 14px, 20px, 35px variants

15. **`.lcars-bar-status`** — Status readout in header bar
    - `font-family: 'Orbitron', sans-serif; font-size: 0.7rem; font-weight: 600`
    - `white-space: nowrap`

16. **`.lcars-body`** — Content area between header and footer
    - `flex: 1; padding: 16px; overflow-y: auto`
    - Custom scrollbar: thin, frame-color themed (matching lcars-panels.css pattern)

17. **`.lcars-footer-bar`** — Bottom bar
    - `height: var(--frame-footer-h); background: rgba(var(--frame-rgb), 0.6)`
    - `border-radius: 0 var(--frame-radius) var(--frame-radius) 0`
    - `display: flex; align-items: center; padding: 0 12px; gap: 8px`
    - `font-family: 'Antonio', sans-serif; font-size: 0.65rem; color: var(--archie-bg-primary, #010409)`
    - `text-transform: uppercase; letter-spacing: 1px`

18. **`.lcars-footer-stardate`** — Stardate/time text
    - `white-space: nowrap; opacity: 0.7`

19. **`.lcars-footer-dots`** — Decorative footer dots
    - `display: flex; gap: 4px; margin-left: auto`

20. **`.lcars-footer-dot`** — Individual dot
    - `width: 6px; height: 6px; border-radius: 50%`

21. **`.lcars-frame--compact`** — Compact variant (no bottom elbow/footer)
    - `.lcars-frame--compact .lcars-elbow-bottom, .lcars-frame--compact .lcars-footer-bar { display: none }`
    - `.lcars-frame--compact .lcars-seg-fill { display: none }`
    - `.lcars-frame--compact .lcars-bar { height: 40px }`

22. **`.lcars-frame--collapsed`** — Collapsed state for collapsible panels
    - `.lcars-frame--collapsed .lcars-sidebar .lcars-seg, .lcars-frame--collapsed .lcars-sidebar .lcars-seg-light, .lcars-frame--collapsed .lcars-sidebar .lcars-seg-fill, .lcars-frame--collapsed .lcars-sidebar .lcars-elbow-bottom { display: none }`
    - `.lcars-frame--collapsed .lcars-body, .lcars-frame--collapsed .lcars-footer-bar { display: none }`
    - Transition on `.lcars-body`: `max-height 0.3s ease`

23. **Animations**
    - `@keyframes lcarsFramePulse` — 3s breathing glow (same as lcarsPulse from panels)
    - `@keyframes lcarsElbowSweep` — `from { transform: scaleX(0); transform-origin: left } to { transform: scaleX(1) }`
    - `@keyframes lcarsBarExtend` — `from { width: 0 } to { width: 100% }` (use clip-path or max-width for smooth extend)
    - `@keyframes lcarsSegFill` — `from { opacity: 0; transform: scaleY(0) } to { opacity: 1; transform: scaleY(1) }`
    - `@keyframes lcarsContentFade` — `from { opacity: 0 } to { opacity: 1 }`

24. **Light mode overrides** — `[data-theme="light"]` and `body.light-mode`
    - Elbows/bars: Same colors at 30% saturation (`filter: saturate(0.3)` or override `--frame-color`)
    - Segments: 20% opacity with 1px inner border
    - Indicator lights: No glow, no animation
    - Header/footer bars: 10% opacity fill, colored border, colored text
    - Body: white bg, subtle gray border
    - Implementation: Use `.light-mode .lcars-frame` selectors per element

25. **Responsive breakpoints**
    - `@media (max-width: 1279px)` — Sidebar 32px, segments 20px, radius 14px, pips hidden
    - `@media (max-width: 767px)` — Sidebar 24px, segments 12px no gaps, radius 8px, no lights, footer hidden
    - `@media (max-width: 479px)` — Sidebar 16px, no segments (just colored bar), radius 4px, minimal
    - `@media (max-width: 479px) .lcars-frame--tablet` — Sidebar hidden, top-bar-only mode

26. **Reduced motion**
    - `@media (prefers-reduced-motion: reduce)` — All animations none, no pulses

**Step 2: Verify file loads**

Add `<link rel="stylesheet" href="{{ url_for('static', filename='css/lcars-frames.css') }}">` temporarily to `base.html` or any template, reload, confirm no CSS errors in dev tools.

**Step 3: Commit**

```bash
git add platform_v2/static/css/lcars-frames.css
git commit -m "feat: add shared lcars-frames.css structural component system"
```

---

## Task 2: Rebuild Login page with LCARS tablet frame

**Files:**
- Modify: `platform_v2/templates/login.html` (1,027 lines — full rewrite of CSS lines 7-769, HTML lines 771-910, JS lines 911-1026)

**Critical preservations:**
- Form action: `POST /login` with fields `username` and `password`
- OAuth: `{{ url_for('oauth.google_login') }}` link
- Theme toggle: `window.toggleTheme()` delegation
- Language menu: `archieI18n` integration, 8 languages, all `data-i18n` keys
- Password toggle: eye icon SVG swap
- Flash messages: handled by `base.html`
- Template blocks: `{% extends "base.html" %}`, all standard blocks

**Step 1: Rewrite the full template**

**CSS block changes (replace lines 7-769):**
- Remove: All 15+ old animation @keyframes, matrix rain styles, breathing border styles, old corner decoration styles, old card styles
- Add: `<link rel="stylesheet" href="{{ url_for('static', filename='css/lcars-frames.css') }}">`
- Add: Page-level styles only:
  - `.login-page` background: dark gradient (`#0a0a1a → #0f0f2a`) + radial green glow
  - `.login-frame` centering: `max-width: 560px; margin: auto; margin-top: 15vh`
  - `.login-frame .lcars-body` padding overrides for form spacing
  - `.login-subtitle` styling (Antonio, uppercase, letter-spacing)
  - Form group spacing
  - Boot animation classes (`.boot-phase-*` for staggered frame construction)
  - Login-specific light mode overrides (background gradient → off-white)
  - Login-specific responsive overrides (frame → top-bar mode at 479px)

**HTML block changes (replace lines 771-910):**
- Remove: `<canvas id="matrix-bg">`, `<div class="grid-overlay">`, `<div class="scan-line">`, old corner decorations, old card structure
- New structure:

```html
<div class="login-page">
  <div class="login-frame lcars-frame lcars-frame--tablet"
       style="--frame-color: #00ff41; --frame-rgb: 0,255,65">
    <div class="lcars-sidebar">
      <div class="lcars-elbow-top"></div>
      <div class="lcars-seg" style="--seg-color: #00ff41"></div>
      <div class="lcars-seg-light" style="--light-color: #00ff41"></div>
      <div class="lcars-seg" style="--seg-color: #00ffff"></div>
      <div class="lcars-seg" style="--seg-color: #f59e0b"></div>
      <div class="lcars-seg-fill"></div>
      <div class="lcars-seg" style="--seg-color: #00ff41"></div>
      <div class="lcars-elbow-bottom"></div>
    </div>
    <div class="lcars-content">
      <div class="lcars-bar">
        <span class="lcars-bar-title">A.R.C.H.I.E.</span>
        <div class="lcars-bar-spacer"></div>
        <div class="lcars-pips">
          <span class="lcars-pip" style="width:20px; background:#00ff41"></span>
          <span class="lcars-pip" style="width:14px; background:#00ff41"></span>
          <span class="lcars-pip" style="width:14px; background:#00ff41"></span>
        </div>
      </div>
      <div class="lcars-body">
        <p class="login-subtitle" data-i18n="login_subtitle">AUTHENTIFICATION REQUISE</p>
        <!-- form groups: username, password, submit button -->
        <!-- forgot password link -->
        <!-- OR divider + Google OAuth -->
        <!-- signup link -->
      </div>
      <div class="lcars-footer-bar">
        <span class="lcars-footer-stardate" id="loginStardate">SD 79145.7</span>
        <button class="login-theme-toggle" onclick="window.toggleTheme()">...</button>
        <button class="login-lang-btn">...</button>
        <div class="lcars-footer-dots">
          <span class="lcars-footer-dot" style="background:#00ff41"></span>
          <span class="lcars-footer-dot" style="background:#00ffff"></span>
          <span class="lcars-footer-dot" style="background:#f59e0b"></span>
        </div>
      </div>
    </div>
  </div>
  <!-- System status indicators below frame -->
  <div class="login-status-strip">...</div>
</div>
```

**JS block changes (replace lines 911-1026):**
- Remove: Matrix rain IIFE (canvas setup, draw loop, resize handler)
- Remove: `document.getElementById('matrix-bg')` references
- Keep: Form submit handler (loading state), password toggle, forgot password toggle, language menu
- Update: Theme toggle (remove canvas references)
- Add: Boot animation JS — staggered class additions:
  1. Add `.boot-elbow` class to elbow-top (triggers sweep)
  2. Add `.boot-bar` to header bar (triggers extend)
  3. Add `.boot-seg` to each segment (staggered 0.15s each)
  4. Add `.boot-light` to indicator light
  5. Add `.boot-elbow-bottom` to bottom elbow
  6. Add `.boot-footer` to footer bar — briefly set text to "THREAT LEVEL MIDNIGHT" then swap to stardate after 0.5s
  7. Add `.boot-content` to body (fade in)
- Add: `sessionStorage` skip check (same as current)

**Step 2: Test in browser**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/login` and verify:
- LCARS tablet frame renders with left sidebar (48px), elbows, 4 segments, indicator light
- Green frame color throughout
- Header bar shows "A.R.C.H.I.E." with 3 green pips
- Footer bar shows stardate, theme toggle, language button, 3 dots
- Form submits correctly (POST /login)
- Password toggle works (eye icon)
- Theme toggle switches light/dark
- Language menu works (8 languages, i18n keys)
- OAuth button links to Google
- Boot animation plays (~2.5s) — frame constructs, "THREAT LEVEL MIDNIGHT" flashes in footer
- Boot skip works (click/key + sessionStorage)
- Light mode: muted frame, no glows
- Responsive: 768px (32px sidebar), 480px (24px sidebar), 374px (top-bar mode, sidebar hidden)

**Step 3: Commit**

```bash
git add platform_v2/templates/login.html
git commit -m "feat: rebuild Login page with LCARS OKUDAGRAM tablet frame"
```

---

## Task 3: Rebuild Signup page with LCARS tablet frame

**Files:**
- Modify: `platform_v2/templates/signup.html` (1,601 lines — full rewrite)

**Same tablet frame as Login, with these differences:**
- Max-width: 640px (wider)
- Header bar: Step indicator pills replace pips (3 pills: ACCOUNT → SECURITY → CONFIRM)
- Step transitions: Content slides inside frame body, frame stays static
- Form steps: Step 1 (Username + Email), Step 2 (Password + Confirm + Strength), Step 3 (Review + Terms)

**Critical preservations:**
- Form action: `POST /signup` with fields `username`, `email`, `password`, `confirm_password`
- OAuth: `{{ url_for('oauth.google_login') }}` link
- Password strength: `strengthFill`, `strengthNote` JS logic
- Theme toggle + language menu
- Back link: `{{ url_for('login') }}`
- Approval notice section
- All `data-i18n` keys

**Step 1: Rewrite the full template**

Follow Login pattern with wider frame. Header bar replaces pips with:

```html
<div class="lcars-bar">
  <div class="signup-steps">
    <div class="signup-step active" data-step="1">
      <span class="signup-step-num">1</span>
      <span class="signup-step-label">ACCOUNT</span>
    </div>
    <div class="signup-step" data-step="2">
      <span class="signup-step-num">2</span>
      <span class="signup-step-label">SECURITY</span>
    </div>
    <div class="signup-step" data-step="3">
      <span class="signup-step-num">3</span>
      <span class="signup-step-label">CONFIRM</span>
    </div>
  </div>
</div>
```

Step pills: Active = solid green pill with glow. Future = dim border. Completed = solid green + checkmark.

**Step 2: Test in browser**

Navigate to `http://192.168.1.200:3000/signup` and verify:
- LCARS tablet frame, wider than Login (640px)
- Step indicator in header bar (3 pills)
- Step 1→2→3 transitions animate content only (frame static)
- Password strength bar works
- Form submits correctly
- All same checks as Login (theme, language, OAuth, responsive)

**Step 3: Commit**

```bash
git add platform_v2/templates/signup.html
git commit -m "feat: rebuild Signup page with LCARS tablet frame + step indicator"
```

---

## Task 4: Dashboard — Command Bar LCARS frame

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
  - CSS: Replace lines 598-1340 (command bar CSS)
  - HTML: Replace lines 3121-3204 (command bar HTML)

This replaces the command bar with a compact LCARS frame (no bottom elbow/footer).

**Step 1: Add lcars-frames.css import**

At the top of the CSS block (after existing `<link>` tags), add:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/lcars-frames.css') }}">
```

**Step 2: Replace command bar CSS**

Remove all existing `.command-bar`, `.cb-*` CSS (lines 598-1340). Replace with:
- `.command-bar-frame` — `position: sticky; top: 0; z-index: 100`
- Override `--frame-color: #00ff41; --frame-rgb: 0,255,65`
- `.lcars-bar` content styling for avatar, search, notification, theme, etc.
- Search popover (`.cb-search-popover`) — LCARS-styled: glass bg, green accent border, rounded corners
- Notification popover (`.cb-notif-popover`) — same LCARS treatment
- Notification detail modal (`.cb-notif-modal`) — LCARS framed modal
- Keep all existing popover/modal JS event handler class names

**Step 3: Replace command bar HTML**

Wrap existing command bar content in LCARS compact frame:
```html
<div class="command-bar-frame lcars-frame lcars-frame--compact"
     style="--frame-color: #00ff41; --frame-rgb: 0,255,65">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: #00ff41"></div>
    <div class="lcars-seg" style="--seg-color: #00ffff"></div>
    <div class="lcars-seg" style="--seg-color: #f59e0b"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar" id="command-bar">
      <!-- existing command bar content: avatar, search, notifications, theme, logout -->
    </div>
  </div>
</div>
```

Preserve ALL element IDs: `command-bar`, `cbSearchInput`, `cbNotifBtn`, `cbNotifPopover`, `cbNotifModal`, etc.

**Step 4: Test**

```bash
docker compose restart archie_platform
```

- Command bar renders with left sidebar (green/cyan/amber segments) + thick header bar
- Search popover opens (Ctrl+K) with LCARS styling
- Notification bell opens popover, click item opens modal
- Theme toggle, language, logout all work
- Sticky positioning works on scroll
- Responsive: sidebar scales at breakpoints

**Step 5: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS OKUDAGRAM command bar frame"
```

---

## Task 5: Dashboard — System Vitals HUD frame

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
  - CSS: Replace lines 1342-1538 (HUD vitals CSS)
  - HTML: Replace lines 3205-3278 (HUD HTML)

**Step 1: Replace HUD CSS**

Remove existing `.hud-vitals-strip`, `.hud-pod-*`, `.hud-ring-*` CSS. Replace with:
- LCARS frame overrides: `--frame-color: #00ffff; --frame-rgb: 0,255,255`
- HUD content styling inside `.lcars-body`: flex row layout for ring gauges + status pods
- Ring gauge SVGs: keep structure, add cyan glow filter (`filter: drop-shadow(0 0 4px rgba(0,255,255,0.4))`)
- Pod styling: Orbitron numbers, Antonio labels
- Status dots: `.lcars-dot` reuse from lcars-panels.css (or inline equivalent)

**Step 2: Replace HUD HTML**

```html
<div class="hud-frame lcars-frame" style="--frame-color: #00ffff; --frame-rgb: 0,255,255">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: #00ffff"></div>
    <div class="lcars-seg-light" style="--light-color: #00ff41"></div>
    <div class="lcars-seg" style="--seg-color: #00ff41"></div>
    <div class="lcars-seg" style="--seg-color: #00ff41"></div>
    <div class="lcars-seg-light" style="--light-color: #00ffff"></div>
    <div class="lcars-seg" style="--seg-color: #0ea5e9"></div>
    <div class="lcars-seg-fill"></div>
    <div class="lcars-elbow-bottom"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar">
      <span class="lcars-bar-title">SYSTEM STATUS</span>
      <div class="lcars-bar-spacer"></div>
      <div class="lcars-pips">...</div>
      <span class="lcars-bar-status" id="hudUptime">10h 8m 23s</span>
    </div>
    <div class="lcars-body" id="hud-vitals">
      <!-- ring gauges + status pods flex row (preserve existing IDs) -->
    </div>
    <div class="lcars-footer-bar">
      <span class="lcars-footer-stardate" id="hudStardate">SD 79145.7</span>
      <span>v{{ config.get('VERSION','5.32.0') }}</span>
      <div class="lcars-footer-dots">...</div>
    </div>
  </div>
</div>
```

Preserve all HUD element IDs for JS data binding.

**Step 3: Test**

- Cyan LCARS frame wraps HUD strip
- Ring gauges display and animate (System, CPU, Memory percentages)
- AI Status, Agent count, ARCHIE status, uptime all show
- Auto-refresh updates values
- Footer shows stardate + version

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS OKUDAGRAM system vitals HUD frame"
```

---

## Task 6: Dashboard — Mission Briefing frame

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
  - CSS: Replace lines 1897-2342 (mission briefing CSS)
  - HTML: Replace lines 3279-3320 (mission briefing HTML)

**Step 1: Replace Mission Briefing CSS**

Remove existing `.briefing-card*` CSS. Replace with:
- LCARS frame overrides: `--frame-color: #00ff41; --frame-rgb: 0,255,65`
- 3-column grid inside `.lcars-body`: `display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px`
- Column accent header strips (thin 4px top bar, NOT nested frames):
  - `.briefing-col-header` — 4px top border in accent color, Antonio uppercase label, colored dot
  - Activity column: green accent
  - Alerts column: orange accent
  - AI Insights column: cyan accent
- Activity list items, alert items, AI stat numbers — restyle with LCARS typography (Orbitron numbers, Antonio labels)
- Responsive: 3-col → 2-col at 1024px → 1-col at 768px

**Step 2: Replace Mission Briefing HTML**

```html
<div class="briefing-frame lcars-frame" style="--frame-color: #00ff41; --frame-rgb: 0,255,65">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: #00ff41"></div>
    <div class="lcars-seg" style="--seg-color: #f59e0b"></div>
    <div class="lcars-seg-light" style="--light-color: #00ffff"></div>
    <div class="lcars-seg" style="--seg-color: #00ffff"></div>
    <div class="lcars-seg" style="--seg-color: #8b5cf6"></div>
    <div class="lcars-seg-fill"></div>
    <div class="lcars-elbow-bottom"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar">
      <span class="lcars-bar-title">MISSION BRIEFING</span>
      <div class="lcars-bar-spacer"></div>
      <div class="lcars-pips">...</div>
    </div>
    <div class="lcars-body">
      <div class="briefing-grid">
        <div class="briefing-col briefing-col--activity">
          <div class="briefing-col-header" style="--col-accent: #00ff41">
            <span>ACTIVITÉ RÉCENTE</span>
          </div>
          <ul id="activityList">...</ul>
        </div>
        <div class="briefing-col briefing-col--alerts">
          <div class="briefing-col-header" style="--col-accent: #f59e0b">
            <span>ALERTES SYSTÈME</span>
          </div>
          <div id="alertsList">...</div>
        </div>
        <div class="briefing-col briefing-col--ai">
          <div class="briefing-col-header" style="--col-accent: #00ffff">
            <span>INSIGHTS DE L'IA</span>
          </div>
          <div id="aiInsights">...</div>
        </div>
      </div>
    </div>
    <div class="lcars-footer-bar">
      <span class="lcars-footer-stardate" id="briefingTimestamp"></span>
      <div class="lcars-footer-dots">...</div>
    </div>
  </div>
</div>
```

Preserve IDs: `activityList`, `alertsList`, `aiInsights` (used by JS renderers).

**Step 3: Test**

- Green LCARS frame wraps 3-column briefing grid
- Sidebar segments: green, orange, cyan light, cyan, purple
- Activity feed populates and scrolls
- Alerts show with severity colors
- AI Insights big numbers display
- Responsive column collapsing works

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS OKUDAGRAM mission briefing frame"
```

---

## Task 7: Dashboard — Priority Stations frame

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
  - CSS: Replace lines 1672-1896 (featured modules CSS — note: this section is ABOVE briefing in CSS order)
  - HTML: Replace lines 3321-3352 (featured modules HTML)

**Step 1: Replace Featured Modules CSS**

Remove existing `.featured-*`, `.section-header` CSS. Replace with:
- LCARS frame overrides: `--frame-color: #f59e0b; --frame-rgb: 245,158,11`
- Featured card styling inside `.lcars-body`: flex row wrap, glass tiles
- `.featured-card` — glass tile: `backdrop-filter: blur(8px)`, thin border, icon + name + desc + status dot, pin button
- Hover: border glow in category accent color

**Step 2: Replace Featured Modules HTML**

```html
<div class="featured-frame lcars-frame" style="--frame-color: #f59e0b; --frame-rgb: 245,158,11">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: #f59e0b"></div>
    <div class="lcars-seg" style="--seg-color: #00ff41"></div>
    <div class="lcars-seg" style="--seg-color: #00ffff"></div>
    <div class="lcars-seg-fill"></div>
    <div class="lcars-seg" style="--seg-color: #8b5cf6"></div>
    <div class="lcars-elbow-bottom"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar">
      <span class="lcars-bar-title">PRIORITY STATIONS</span>
      <div class="lcars-bar-spacer"></div>
      <div class="lcars-pips">...</div>
    </div>
    <div class="lcars-body" id="featured-modules">
      <div class="featured-cards-row" id="featuredCardsRow">
        <!-- JS-populated featured module cards -->
      </div>
    </div>
    <div class="lcars-footer-bar">
      <span class="lcars-footer-stardate" id="featuredPinCount"></span>
      <div class="lcars-footer-dots">...</div>
    </div>
  </div>
</div>
```

Preserve IDs: `featured-modules`, `featuredCardsRow`.

**Step 3: Test**

- Amber LCARS frame wraps featured modules
- Featured cards render with glass tile styling
- Pin/unpin works (localStorage)
- Hover glow effects

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS OKUDAGRAM priority stations frame"
```

---

## Task 8: Dashboard — Category Panels frames

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
  - CSS: Replace lines 2427-3052 (category grid CSS)
  - HTML: Replace lines 3354-3406 (category grid HTML)

This is the largest section — each category becomes its own LCARS frame with per-category accent colors.

**Step 1: Replace Category Grid CSS**

Remove existing `.category-grid`, `.category-panel`, `.cat-header`, `.module-card` CSS. Replace with:
- `.category-grid` — flex column, 24px gap
- Each `.category-frame` uses `.lcars-frame` with per-category `--frame-color`
- Category color map (via CSS classes or inline styles):
  - `.category-frame--admin_operations { --frame-color: #ef4444; --frame-rgb: 239,68,68 }`
  - `.category-frame--ai_command { --frame-color: #00ffff; --frame-rgb: 0,255,255 }`
  - `.category-frame--dev_tools { --frame-color: #8b5cf6; --frame-rgb: 139,92,246 }`
  - `.category-frame--saas_services { --frame-color: #f59e0b; --frame-rgb: 245,158,11 }`
  - `.category-frame--project_knowledge { --frame-color: #00ff41; --frame-rgb: 0,255,65 }`
  - `.category-frame--media_home { --frame-color: #0ea5e9; --frame-rgb: 14,165,233 }`
  - `.category-frame--upcoming_placeholders { --frame-color: #ffaa00; --frame-rgb: 255,170,0 }`
- Collapse behavior: `.lcars-frame--collapsed` class toggle
- Module card grid: `display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px` inside `.lcars-body`
- `.module-card` — glass tile with 4px top accent bar in category color
- Responsive: 3→2→1 col

**Step 2: Replace Category Grid HTML (Jinja2 loop)**

Each category panel becomes:
```html
{% for category in categories %}
<div class="category-frame lcars-frame category-frame--{{ category.key }}"
     style="--frame-color: {{ category.color }}; --frame-rgb: {{ category.rgb }}">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: {{ category.seg1 }}"></div>
    <div class="lcars-seg" style="--seg-color: {{ category.seg2 }}"></div>
    <div class="lcars-seg" style="--seg-color: {{ category.seg3 }}"></div>
    <div class="lcars-seg-fill"></div>
    <div class="lcars-elbow-bottom"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar" onclick="toggleCategory(this)">
      <span class="lcars-bar-title">{{ category.name }}</span>
      {% if category.admin %}<span class="cat-admin-badge">ADMIN</span>{% endif %}
      <div class="lcars-bar-spacer"></div>
      <span class="cat-module-count">{{ category.count }}</span>
      <span class="cat-chevron">▼</span>
    </div>
    <div class="lcars-body">
      <div class="module-grid">
        {% for module in category.modules %}
        <a href="{{ module.url }}" class="module-card">...</a>
        {% endfor %}
      </div>
    </div>
    <div class="lcars-footer-bar">
      <span class="lcars-footer-stardate">{{ category.name | upper }}</span>
      <div class="lcars-footer-dots">...</div>
    </div>
  </div>
</div>
{% endfor %}
```

Note: The Jinja2 loop structure must match the existing category data flow. Check the current template's category iteration pattern and replicate it exactly with the new frame markup. Preserve `data-category` attributes and any JS hooks.

**Step 3: Test**

- Each category renders as its own LCARS frame with distinct color
- Collapse/expand works smoothly (header bar click)
- Module cards display with glass tile styling + 4px accent bars
- Module status dots update from API
- Pin/unpin buttons work
- Client-side search still finds modules
- Responsive grid: 3→2→1 col
- Light mode: all category frames render as muted schematics
- ADMIN badges display correctly

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS OKUDAGRAM category panel frames with per-category colors"
```

---

## Task 9: Dashboard — Frame-build boot sequence

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`
  - CSS: Replace lines 117-412 (boot sequence CSS)
  - HTML: Replace lines 3071-3110 (boot overlay HTML)
  - JS: Replace boot sequence IIFE in JS block (~lines 3432-3500+)

**Step 1: Replace boot CSS**

Remove: All old boot overlay, terminal, typing, logo, split reveal CSS. Replace with:
- `.boot-overlay` — full-screen black, z-index 9999, flex center
- `.boot-scanline` — faint green horizontal line sweep (CSS animation)
- `.boot-threat-flash` — "THREAT LEVEL MIDNIGHT" centered text, dim red, Antonio font, opacity 0→0.4→0 over 0.3s
- Frame build animation classes (applied per-frame via JS):
  - `.frame-build .lcars-elbow-top` — `animation: lcarsElbowSweep 0.2s ease-out forwards`
  - `.frame-build .lcars-bar` — `animation: lcarsBarExtend 0.3s ease-out forwards`
  - `.frame-build .lcars-seg` — `animation: lcarsSegFill 0.15s ease-out forwards` with stagger via `animation-delay`
  - `.frame-build .lcars-seg-light` — `animation: lcarsFramePulse 0.3s ease-out forwards`
  - `.frame-build .lcars-elbow-bottom` — same as top elbow
  - `.frame-build .lcars-footer-bar` — same as header bar
  - `.frame-build .lcars-body` — `animation: lcarsContentFade 0.3s ease-out forwards`
- Initially all frame elements hidden: `.boot-hidden { opacity: 0 }`
- `.boot-complete` removes boot-hidden

**Step 2: Replace boot HTML**

Remove: matrix rain canvas, boot-overlay with terminal phases. Replace with:
```html
<div class="boot-overlay" id="bootOverlay">
  <div class="boot-scanline"></div>
  <div class="boot-threat-flash" id="bootThreatFlash">THREAT LEVEL MIDNIGHT</div>
</div>
```

All dashboard panel frames get class `boot-hidden` initially (added/removed by JS).

**Step 3: Replace boot JS**

Remove: Matrix rain IIFE, terminal typing sequence. Replace with:

```javascript
(function initFrameBoot() {
  if (sessionStorage.getItem('archie-booted')) {
    // Skip boot — show everything immediately
    document.getElementById('bootOverlay')?.remove();
    return;
  }

  const overlay = document.getElementById('bootOverlay');
  const threatFlash = document.getElementById('bootThreatFlash');
  const frames = document.querySelectorAll('.lcars-frame');

  // All frames start hidden
  frames.forEach(f => f.classList.add('boot-hidden'));

  // Phase 1: Darkness + Threat Level Midnight flash (0-500ms)
  setTimeout(() => {
    threatFlash.classList.add('flash');
  }, 100);

  // Phase 2-5: Build frames sequentially with accelerating timing
  const frameDelays = [500, 1200, 2000, 2800]; // first 4 frames get individual timing
  const cascadeStart = 2800; // remaining frames cascade rapidly

  frames.forEach((frame, i) => {
    const delay = i < 4 ? frameDelays[i] : cascadeStart + (i - 4) * 200;
    setTimeout(() => {
      frame.classList.remove('boot-hidden');
      frame.classList.add('frame-build');
    }, delay);
  });

  // Phase 6: System online pulse + remove overlay
  const totalTime = cascadeStart + Math.max(0, frames.length - 4) * 200 + 400;
  setTimeout(() => {
    overlay.classList.add('fade-out');
    sessionStorage.setItem('archie-booted', '1');
    setTimeout(() => overlay.remove(), 300);
  }, totalTime);

  // Skip on click or keypress
  function skipBoot() {
    frames.forEach(f => {
      f.classList.remove('boot-hidden');
      f.classList.remove('frame-build');
    });
    overlay.remove();
    sessionStorage.setItem('archie-booted', '1');
    document.removeEventListener('click', skipBoot);
    document.removeEventListener('keydown', skipBoot);
  }
  document.addEventListener('click', skipBoot);
  document.addEventListener('keydown', skipBoot);
})();
```

**Step 4: Test**

- Full boot sequence plays (~4s): darkness → threat flash → frames build sequentially
- Frame construction animation visible: elbows sweep, bars extend, segments fill
- "THREAT LEVEL MIDNIGHT" flashes briefly in Phase 1
- Skip works (click/key)
- sessionStorage bypass works on second visit
- `prefers-reduced-motion`: everything appears instantly with 0.3s fade

**Step 5: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(dashboard): LCARS frame-build boot sequence with Threat Level Midnight"
```

---

## Task 10: Clean up removed CSS + consolidate

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (CSS block)

**Step 1: Remove dead CSS**

After Tasks 4-9, scan the CSS block for any orphaned styles from the old design that are no longer referenced:
- Old `.command-bar` styles (replaced by frame)
- Old `.hud-vitals-strip` styles (replaced by frame)
- Old `.briefing-card` styles (replaced by frame)
- Old `.featured-*` styles not already removed
- Old `.category-panel`, `.cat-header` styles (replaced by frame)
- Old boot overlay styles (replaced)
- Old matrix rain styles

**Step 2: Verify no visual regressions**

Reload dashboard, check all sections render correctly. Check light mode. Check mobile.

**Step 3: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "refactor(dashboard): remove orphaned CSS from pre-OKUDAGRAM layout"
```

---

## Task 11: Visual baseline + final verification

**Files:**
- No code changes

**Step 1: Take Playwright screenshots**

Use Playwright to capture screenshots at all breakpoints for all pages:

```bash
# Or use manual Playwright navigation
# Login: dark + light at 1280, 768, 480, 374
# Signup: dark + light at 1280, 768, 480, 374
# Dashboard: dark + light at 1280, 768, 480, 374
# Dashboard boot sequence (if video capture possible)
```

**Step 2: Manual verification checklist**

- [ ] Login: Full LCARS tablet frame (elbows, 48px sidebar, segments, header/footer bars)
- [ ] Login: Boot animation ~2.5s — frame constructs, "THREAT LEVEL MIDNIGHT" footer flash
- [ ] Login: Form submits, password toggle, theme, language, OAuth all work
- [ ] Login light mode: Muted schematic rendering
- [ ] Login 374px: Top-bar mode (sidebar hidden)
- [ ] Signup: Same tablet frame, wider, step indicator pills in header bar
- [ ] Signup: Step transitions animate inside frame (frame stays static)
- [ ] Signup: Password strength, form submit, all controls work
- [ ] Dashboard: All panels render as independent LCARS frames
- [ ] Dashboard: Command bar compact frame, sticky, search/notification popovers
- [ ] Dashboard: System Vitals cyan frame, ring gauges, live data
- [ ] Dashboard: Mission Briefing green frame, 3-column grid
- [ ] Dashboard: Priority Stations amber frame, featured module cards
- [ ] Dashboard: Category panels with per-category frame colors
- [ ] Dashboard: Category collapse/expand works
- [ ] Dashboard: Module cards, pin/unpin, status dots functional
- [ ] Dashboard: Boot sequence ~4s — frame-build cascade, Threat Level Midnight flash
- [ ] Dashboard: Boot skip (click/key + sessionStorage)
- [ ] Dashboard light mode: All frames as muted schematics
- [ ] Dashboard 768px: 32px sidebars, 2-col grids
- [ ] Dashboard 480px: 24px sidebars, 1-col
- [ ] Dashboard 374px: 16px edge bars, simplified
- [ ] `prefers-reduced-motion`: No animations, 0.3s fade only
- [ ] All existing JS: search, notifications, HUD refresh, module status, i18n

**Step 3: Fix any issues found, commit**

```bash
git add -A
git commit -m "fix: visual polish after OKUDAGRAM baseline review"
```

---

## Task 12: Push + Update Dev HQ

**Step 1: Push all commits**

```bash
git push
```

**Step 2: Update Dev HQ**

- `mcp store_memory` — vault note documenting OKUDAGRAM redesign (shared component, frame patterns, segment color mapping)
- `mcp update_project_understanding` — update project #94 awareness
- `mcp log_decision` — ADR for LCARS structural frame system replacing thin accent panels
- `mcp complete_task` — if there are relevant tasks in project #94

**Step 3: Restart platform**

```bash
docker compose restart archie_platform
```

Verify live site at `http://192.168.1.200:3000`.
