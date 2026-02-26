# Full OKUDAGRAM LCARS Redesign — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current thin-accent "fake LCARS" with authentic OKUDAGRAM structural frames — thick sweeping elbows, 48px sidebars with segmented color blocks, bold header/footer bars with decorative pips. Applied to Dashboard (stacked framed panels), Login/Signup (tablet frame), built as a shared component system.

**Status:** Approved 2026-02-26

**Replaces:** `docs/plans/2026-02-25-dashboard-login-overhaul-design.md` (thin accent line approach)

**i18n Requirement:** ALL visible text in LCARS frames MUST use `data-i18n` keys for translation via the Consciousness Languages tab. This includes header bar titles, footer stardates, status readouts, button labels, section titles, and any new text introduced. Preserve all existing `data-i18n` keys from current templates. Use the existing `archieI18n` system.

---

## Architecture

### What We're Building

The current `lcars-panels.css` provides thin 3px left-border accent lines on glass cards. That's a theme, not LCARS. Real LCARS (OKUDAGRAM) panels have **structural geometry** — thick bars that form the interface skeleton, sweeping elbow corners, chunky segmented color blocks.

The Consciousness module already has this pattern built (modal tablet frames with 48px sidebars, elbows, segments). This redesign promotes that pattern into a shared component system and applies it to Dashboard, Login, and Signup.

### Shared Assets (reuse)

- `theme.css` — 150+ CSS custom properties (colors, spacing, typography, glows)
- `animations.css` — shared keyframes
- `category-nav.css` — category accent colors
- Consciousness modal frame pattern — the blueprint we're promoting

### New Shared Component

- `static/css/lcars-frames.css` — replaces `lcars-panels.css` with structural frame system

### Existing `lcars-panels.css`

Kept for backward compatibility in modules not yet upgraded. New pages use `lcars-frames.css`. Over time, modules migrate from panels → frames.

---

## Section 1: Shared LCARS Structural Component System

New file: `static/css/lcars-frames.css`

### Core Components

**1. LCARS Frame (`lcars-frame`)** — The master structural container

```
┌──────────────────────────────────────────────┐
│ ╭━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮ │
│ ┃  ELBOW   ┃  HEADER BAR  [pips] [status] ┃ │
│ ┃  corner  ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛ │
│ ┃          ┃                                 │
│ ┃ SIDEBAR  ┃      CONTENT AREA              │
│ ┃ segments ┃                                 │
│ ┃ [color]  ┃                                 │
│ ┃ [color]  ┃                                 │
│ ┃ [color]  ┃                                 │
│ ┃          ┃                                 │
│ ┃  ELBOW   ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╗ │
│ ╰━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╝ │
└──────────────────────────────────────────────┘
```

- Display: flex (sidebar + content columns)
- Left sidebar: **48px wide**, solid color, houses elbows + segments
- Content area: flex-1, houses header bar + body + footer bar

**2. LCARS Elbow (`lcars-elbow-top`, `lcars-elbow-bottom`)** — Sweeping corner pieces
- Top elbow: **52px tall**, solid `--frame-color`, `border-radius: 20px 0 0 0`
- Cutout notch: `::after` pseudo-element, 18×18px, bottom-right corner (creates the classic LCARS elbow shape)
- Bottom elbow: **36px tall**, solid `--frame-color`, `border-radius: 0 0 0 20px`
- Cutout notch: `::after`, 18×14px, top-right corner

**3. LCARS Segments (`lcars-seg`)** — Stacked color blocks in sidebar
- Each segment: **28px tall**, solid color via `--seg-color`, `border-radius: 4px`
- Gap: **4px** between segments
- Flexible spacer: `lcars-seg-fill` (flex: 1, fills remaining height with dim frame color)

**4. LCARS Indicator Lights (`lcars-seg-light`)** — Between segments
- **10×10px** dots, solid color, `border-radius: 50%`
- `box-shadow` glow in matching color
- `lcarsPulse` animation (3s ease-in-out infinite)
- Centered in sidebar with 6px vertical margin

**5. LCARS Header Bar (`lcars-bar`)** — Top strip extending from elbow
- **44px tall**, solid `--frame-color`
- Right end: `border-radius: 0 20px 20px 0`
- Layout: flex with `gap: 12px`
- Contains: title (Antonio uppercase, letter-spacing 1.5px) + pips + status readout
- 8px gap between sidebar and content (creates visual separation from elbow)

**6. LCARS Footer Bar (`lcars-footer-bar`)** — Bottom strip
- **28px tall**, solid `--frame-color` at 60% opacity
- Right end: `border-radius: 0 20px 20px 0`
- Contains: stardate/timestamp text + decorative dots
- Font: Antonio 0.65rem, letter-spacing 1px

**7. LCARS Pips (`lcars-pip`)** — Decorative readout rectangles
- Small colored blocks: **8px height**, widths of 14px / 20px / 35px
- `border-radius: 4px`, spaced 4px apart
- Colors: mix of frame color and accent variants
- Placed in header bar, right-aligned before status

**8. LCARS Footer Dots (`lcars-footer-dot`)** — Decorative footer accents
- **6×6px** circles, 3-4 per footer, different colors
- No glow, no animation — purely decorative

### HTML Structure Pattern

```html
<div class="lcars-frame" style="--frame-color: #00ff41; --frame-rgb: 0,255,65">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: #00ff41"></div>
    <div class="lcars-seg-light"></div>
    <div class="lcars-seg" style="--seg-color: #f59e0b"></div>
    <div class="lcars-seg" style="--seg-color: #00ffff"></div>
    <div class="lcars-seg-fill"></div>
    <div class="lcars-elbow-bottom"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar">
      <span class="lcars-bar-title">SECTION TITLE</span>
      <div class="lcars-pips">
        <span class="lcars-pip" style="width:20px"></span>
        <span class="lcars-pip" style="width:35px"></span>
        <span class="lcars-pip" style="width:14px"></span>
      </div>
      <span class="lcars-bar-status">ONLINE</span>
    </div>
    <div class="lcars-body">
      <!-- actual content here -->
    </div>
    <div class="lcars-footer-bar">
      <span class="lcars-footer-stardate">SD 79145.7</span>
      <div class="lcars-footer-dots">
        <span class="lcars-footer-dot" style="background:#00ff41"></span>
        <span class="lcars-footer-dot" style="background:#00ffff"></span>
        <span class="lcars-footer-dot" style="background:#f59e0b"></span>
      </div>
    </div>
  </div>
</div>
```

### CSS Variable API

```css
--frame-color       /* Primary frame color (elbows + bars) */
--frame-rgb         /* RGB triplet for rgba() blending */
--seg-color         /* Per-segment color override */
--frame-radius      /* Elbow corner radius, default 20px */
--frame-sidebar-w   /* Sidebar width, default 48px */
```

### Compact Frame Variant

For panels that need minimal frame overhead (e.g., command bar):

```html
<div class="lcars-frame lcars-frame--compact">
```

- No bottom elbow or footer bar
- Sidebar: 2 segments max, no fill spacer
- Header bar only, reduced to 40px
- Total frame overhead: ~52px vertical

---

## Section 2: Dashboard Layout — Stacked OKUDAGRAM Panels

The dashboard becomes a vertical stack of independent LCARS framed panels with 24px gaps. Each panel has its own frame, elbows, sidebar segments, and header bar. Background: dark nebula gradient behind everything.

### Panel 1: Command Bar (sticky)

- **Frame variant:** `lcars-frame--compact` (no bottom elbow, no footer)
- **Frame color:** Green `#00ff41`
- **Sidebar segments:** Green, cyan, amber
- **Position:** `position: sticky; top: 0; z-index: 100`
- **Total height:** ~56px
- **Header bar contains:** Avatar + username badge, search input (Ctrl+K), notification bell (badge count), theme toggle, language, Dev HQ link, logout icon
- **Pips:** 3 decorative blocks on right side (green, cyan, amber)
- **Search popover:** Drops below as LCARS-styled panel (glass bg, frame-color border)
- **Notification popover:** Same LCARS panel treatment

### Panel 2: System Vitals HUD

- **Frame color:** Cyan `#00ffff`
- **Sidebar segments:** Cyan, green, green, blue
- **Indicator lights:** 2 lights (between seg 1-2 and seg 3-4)
- **Header bar:** "SYSTEM STATUS" title + pips + uptime readout (Orbitron)
- **Content (lcars-body):** Flex row containing:
  - Ring gauges (System %, CPU %, Memory %) — SVG circles with glow filter
  - AI Status pod (label + "EN LIGNE" status)
  - Agent count pod (icon + count in Orbitron)
  - A.R.C.H.I.E. status pod (label + status + uptime)
- **Footer bar:** Stardate + version (`v5.32.0`) + 3 decorative dots

### Panel 3: Mission Briefing

- **Frame color:** Green `#00ff41`
- **Sidebar segments:** Green, orange, cyan, purple (maps to: activity, alerts, insights, general)
- **Indicator lights:** 1 light between segments 2-3
- **Header bar:** "MISSION BRIEFING" title + pips
- **Content (lcars-body):** 3-column CSS grid (`1fr 1fr 1fr`, gap 16px)
  - **Column 1 — Activity Feed:** Green accent header strip (thin 4px top bar), scrollable list of activity items
  - **Column 2 — System Alerts:** Orange accent header strip, alert items with severity colors
  - **Column 3 — AI Insights:** Cyan accent header strip, big numbers (Orbitron) + metric labels
  - Each column header: Antonio uppercase label + colored dot
  - Columns are NOT nested frames (too heavy) — thin accent header strips only
- **Footer bar:** Timestamp + dots
- **Responsive:** 3-col → 2-col at 1024px → 1-col at 768px

### Panel 4: Priority Stations (Featured Modules)

- **Frame color:** Amber `#f59e0b`
- **Sidebar segments:** Amber, green, cyan, purple
- **Header bar:** "PRIORITY STATIONS" title + module count in pip
- **Content:** Horizontal flex row (wrap), each featured module = glass tile card:
  - Icon (Lucide), module name (Orbitron 0.8rem), description (Antonio), status dot
  - Pin/unpin star button
  - Hover: border glow in module category color
- **Footer bar:** Pin count + dots

### Panel 5–N: Category Panels (one per category, collapsible)

- **Frame color:** Per-category accent
  - Admin Operations: Red `#ef4444`
  - AI Command: Cyan `#00ffff`
  - Dev Tools: Purple `#8b5cf6`
  - SaaS Services: Orange `#f59e0b`
  - Project Knowledge: Green `#00ff41`
  - Media Home: Blue `#0ea5e9`
  - Upcoming: Amber `#ffaa00`
- **Sidebar segments:** 3-4 blocks in shades/variants of the category color
- **Header bar:** Category name (Antonio) + ADMIN badge + module count pip + collapse chevron
- **Content:** CSS grid of module cards (3-col → 2-col → 1-col)
  - Module card: Glass tile, 4px top accent bar in category color, icon, name (Orbitron), status dot, pin button
- **Footer bar:** Category status + dots
- **Collapse behavior:**
  - Collapsed: Only top elbow + header bar visible (sidebar segments, content, footer all hide)
  - Smooth `max-height` transition (0.3s ease)
  - Chevron rotates 180° on toggle
  - Default: All expanded (matching current behavior)

### Panel Spacing

- **24px vertical gap** between each panel
- Command bar sticky at top, remaining panels scroll below

---

## Section 3: Login Page — LCARS Tablet Frame

The login page is a centered LCARS tablet terminal.

### Layout

```
        ╭━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮
        ┃  ELBOW   ┃  A.R.C.H.I.E.  [●][●][●]   ┃
        ┃  (green) ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
        ┃          ┃
        ┃ ████████ ┃  AUTHENTIFICATION REQUISE
        ┃ (green)  ┃
        ┃          ┃  ┌─────────────────────────┐
        ┃ ████████ ┃  │  Username               │
        ┃ (cyan)   ┃  └─────────────────────────┘
        ┃          ┃
        ┃    ●     ┃  ┌─────────────────────────┐
        ┃          ┃  │  Password            👁  │
        ┃ ████████ ┃  └─────────────────────────┘
        ┃ (amber)  ┃
        ┃          ┃  ╭─────────────────────────╮
        ┃ ████████ ┃  │    ACCÉDER AU SYSTÈME   │
        ┃ (green)  ┃  ╰─────────────────────────╯
        ┃          ┃
        ┃          ┃  ── OR ──────────────────────
        ┃          ┃  [ G  Continue with Google  ]
        ┃          ┃
        ┃  ELBOW   ┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╗
        ╰━━━━━━━━━━┻━━━━━━━ SD 79145.7 ━[●●●]━━━╝
```

### Specifications

- **Uses:** `lcars-frame` shared component (same HTML structure as dashboard panels)
- **Frame color:** Green `#00ff41`
- **Sidebar segments:** Green, cyan, amber, green (4 segments + 1 indicator light between seg 2-3)
- **Max width:** 560px (sidebar 48px + content 512px)
- **Centered** on page vertically and horizontally
- **Background:** Dark gradient (`#0a0a1a → #0f0f2a`) with subtle radial green glow (600px, 0.06 opacity) behind frame
- **Header bar:** "A.R.C.H.I.E." in Orbitron + 3 indicator pips (green pulse)
- **Footer bar:** Stardate + theme toggle + language button + 3 decorative dots
- **System status readouts:** Integrated into sidebar segment labels — each segment has tiny rotated text: "SYS", "AI", "SEC"
- **Form inputs:** LCARS input style (green border, focus glow) inside frame body
- **Submit button:** Full-width LCARS pill button with energy sweep animation
- **OAuth:** Google button below divider, inside frame body
- **Corner decorations:** Removed — elbows replace them

### Critical Preservations (from current login.html)

- Form action: `POST /login` with fields `username` and `password`
- OAuth: `{{ url_for('oauth.google_login') }}` link
- Theme toggle: `window.toggleTheme()` delegation
- Language menu: `archieI18n` integration, 8 languages, all `data-i18n` keys
- Password toggle: eye icon SVG swap
- Flash messages: handled by `base.html`
- Template blocks: `{% extends "base.html" %}`, `{% block styles %}`, `{% block content %}`, `{% block scripts %}`

---

## Section 4: Signup Page — LCARS Tablet Frame Variant

Same tablet frame as Login, wider, with multi-step form.

### Differences from Login

- **Max width:** 640px (sidebar 48px + content 592px)
- **Header bar:** Step indicator pills replace pips
  - 3 pill-shaped segments in flex row: `① ACCOUNT` → `② SECURITY` → `③ CONFIRM`
  - Active step: solid green fill + glow
  - Future steps: dim border only
  - Completed steps: solid green, checkmark
- **Step transitions:** Content inside `lcars-body` slides (current panel slides left + fades, next slides right, 0.3s). Frame stays completely static.
- **Sidebar segments:** Same as Login (green, cyan, amber, green) — don't change per step
- **Form steps:**
  - Step 1 (Account): Username + Email fields
  - Step 2 (Security): Password + Confirm Password + Strength bar
  - Step 3 (Confirm): Review + Approval notice + Terms
- **Navigation:** "NEXT" / "BACK" pill buttons between steps, final submit on Step 3
- **Password strength bar:** Thin progress bar inside frame body, green gradient fill

### Critical Preservations

- Form action: `POST /signup` with fields `username`, `email`, `password`, `confirm_password`
- OAuth: `{{ url_for('oauth.google_login') }}` link
- Password strength: `strengthFill`, `strengthNote` JS logic
- Theme toggle + language menu: same as Login
- Back link: `{{ url_for('login') }}`
- Approval notice section
- All `data-i18n` keys

---

## Section 5: Frame-Build Boot Sequence (Dashboard)

Replaces the current terminal-typing boot overlay. The LCARS frames construct themselves.

### Sequence Timeline (~4s total)

**Phase 1: Darkness + Flicker (0–0.5s)**
- Screen dark, faint green scanline flicker across viewport
- Brief text flash in center: `THREAT LEVEL MIDNIGHT` in dim red (#ff4444 at 0.4 opacity), Antonio font, gone in 0.3s
- Single green cursor blink at bottom-left

**Phase 2: Command Bar Frame Build (0.5–1.2s)**
- Top elbow sweeps in from left edge (0.2s, ease-out)
- Header bar extends right across the screen (0.3s, ease-out)
- Sidebar segments fill top-to-bottom (3 segments, 0.1s each staggered)
- Command bar content fades in (search, avatar, icons) — 0.2s
- Indicator lights pulse on

**Phase 3: System Vitals Frame Build (1.2–2.0s)**
- Second panel's elbow sweeps in (0.2s) — offset 24px below command bar
- Cyan header bar extends right (0.3s)
- Sidebar segments fill (0.1s each)
- Ring gauges animate from 0% to actual values (0.4s, ease-out)
- Status readouts type in character by character: "EN LIGNE"

**Phase 4: Mission Briefing Frame Build (2.0–2.8s)**
- Third panel frame constructs (elbow → bar → segments, 0.5s)
- 3-column content fades in left-to-right (0.1s stagger per column)
- Activity items populate top-to-bottom
- Alert severity colors pulse once on appear

**Phase 5: Remaining Panels Cascade (2.8–3.8s)**
- Priority Stations + all Category panels build in rapid cascade
- Each panel: elbow → bar → segments in 0.3s (overlapping with previous, not sequential)
- Creates accelerating cascade effect — gets faster as it goes
- Module cards pop in with subtle scale transition (0.95 → 1.0)

**Phase 6: System Online (3.8–4.0s)**
- All indicator lights across all panels sync-pulse once (green flash)
- All footer bars display stardates simultaneously
- Brief full-page green glow pulse (very subtle box-shadow on body, 0.2s)

### Skip Behavior
- Click anywhere or press any key → all frames jump to final state instantly
- `sessionStorage.setItem('archie-booted', '1')` skips entire boot on subsequent page loads within session

### Easter Egg: Threat Level Midnight
- Phase 1 flash: `THREAT LEVEL MIDNIGHT` appears for 0.3s in dim red
- Login footer: Stardate area briefly shows "THREAT LEVEL MIDNIGHT" for 0.5s before settling to actual stardate during boot animation
- Subtle enough to miss on first view, delightful on re-watch

---

## Section 6: Login Boot Animation

Simpler than Dashboard — single tablet frame constructs.

### Sequence (~2.5s)

1. **Top elbow** sweeps in from left (0.3s)
2. **Header bar** extends right (0.3s)
3. **Sidebar segments** fill top-to-bottom (0.15s each, 4 segments = 0.6s)
4. **Indicator light** pulses on
5. **Bottom elbow** sweeps in from left (0.2s)
6. **Footer bar** extends right (0.2s) — briefly flashes "THREAT LEVEL MIDNIGHT" before showing stardate
7. **Form content** fades in (0.4s) — subtitle, fields, button stagger

### Skip
Same as Dashboard — click/key to skip, sessionStorage bypass.

---

## Section 7: Responsive Behavior

### Breakpoints

**Desktop 1280px+** — Full LCARS frames
- 48px sidebars, full elbows (20px radius), all segments visible
- Mission Briefing: 3-column grid
- Category modules: 3-col grid
- All pips, lights, footer bars visible

**Tablet 768–1279px**
- Sidebar: **32px** wide
- Segments: **20px** tall
- Elbows: **14px** corner radius
- Mission Briefing: 2-column (AI Insights below)
- Category modules: 2-col grid
- Header bar pips: hidden
- Footer bar dots: hidden (stardate/version only)

**Mobile Large 480–767px**
- Sidebar: **24px** wide
- Segments: **12px** tall, no gaps (tight color strips)
- Elbows: **8px** corner radius, simplified (no cutout notch)
- No indicator lights
- Header bars: **36px** tall
- Footer bars: hidden entirely
- Mission Briefing: 1-column stack
- Category modules: 1-col stack
- Command bar search: collapses to icon-only

**Mobile Small 374–479px**
- Sidebar: **16px** wide — just colored edge bars, no individual segments
- Elbows: **4px** border-radius (simple rounded corners)
- Header bars: title + status only, no pips
- Everything single column
- Login/Signup: Sidebar hidden, becomes top-bar-only frame (horizontal bar across top with elbow at top-left, content below)

### Key Rule
The structural frame **never fully disappears**. Even at 374px, colored edge bars and rounded corners preserve LCARS identity. The design scales gracefully rather than collapsing to generic cards.

### Collapsible Category Panels (all viewports)
- Collapsed: Top elbow + header bar visible only (sidebar, content, footer hide)
- Transition: `max-height` with 0.3s ease
- Chevron: rotates 180° on toggle
- Default state: all expanded

---

## Section 8: Light Mode

### Principle
Same structural shapes, rendered as a **schematic** (architectural drawing) rather than a **live terminal** (powered console).

### Color Transformations

**Frame bars and elbows:**
- Dark: Solid bold colors (`#00ff41`, `#00ffff`, etc.)
- Light: **Muted pastels at 30% saturation** — green → soft sage, cyan → light teal, amber → warm sand
- Frame outline: 1px solid border at 15% opacity defining the shape

**Sidebar segments:**
- Dark: Solid bold color blocks
- Light: Same colors at **20% opacity** with subtle 1px inner border

**Indicator lights:**
- Dark: Glowing dots with box-shadow
- Light: Solid dots, no glow, no pulse animation

**Header/footer bars:**
- Dark: Solid color fill
- Light: **10% opacity** fill with colored text, shape defined by subtle border

**Content areas:**
- Dark: Near-black glass (`rgba(255,255,255,0.02)`)
- Light: White with very subtle warm gray border (`rgba(0,0,0,0.06)`)

**Background:**
- Dark: Dark nebula gradient (`#0a0a1a → #0f0f2a`)
- Light: Clean off-white (`#f8f9fa`) with faint radial tint of page accent color

**Boot animation:**
- Dark: Full animation with glows
- Light: Frames appear at reduced opacity, fade to final state (0.5s). No glow pulses.

### Reduced Motion (`prefers-reduced-motion: reduce`)
- All frames appear instantly
- No sweep/extend/fill animations
- Simple 0.3s fade-in of complete page
- No boot sequence

---

## Section 9: What Stays, What Goes, What's New

| Element | Current | After Redesign |
|---------|---------|----------------|
| `lcars-panels.css` | Thin accent lines | Kept for other modules, Dashboard/Login/Signup migrate to `lcars-frames.css` |
| 3px left borders | Everywhere | Gone from Dashboard/Login/Signup |
| 6px cap bars | Section headers | Replaced by 44px header bars |
| Glass cards | Mission briefing, modules | Content inside LCARS frames (glass tiles for module cards only) |
| Elbow corners | Consciousness only | Shared component, all pages |
| 48px sidebar | Consciousness modals only | Shared component, all pages |
| Segmented color blocks | Consciousness modals only | All LCARS frames |
| Indicator lights | Consciousness only | All LCARS frames |
| Header/footer bars with pips | Consciousness only | All LCARS frames |
| Matrix rain canvas | Dashboard boot | Removed |
| Terminal typing boot | Dashboard | Replaced by frame-build animation |
| Corner bracket decorations | Login/Signup | Removed (elbows replace them) |
| Boot sequence (~5s) | Dashboard | Frame-build (~4s) |
| Boot sequence (~2.5s) | Login | Frame-build (~2.5s) |
| Threat Level Midnight | Nowhere | Easter egg in boot sequence |
| Nebula gradient bg | Dashboard | Kept (frames float on top) |
| Ring gauges | HUD strip | Kept (inside System Vitals frame) |

---

## Section 10: Font Stack (unchanged)

- **Titles/Status values:** Orbitron 400-800
- **Labels/Nav/Section titles:** Antonio 400-700
- **Body/Code:** IBM Plex Mono 300-500
- **Form inputs:** JetBrains Mono

---

## Section 11: Color Reference

### Frame Colors (per panel)
- Command Bar: Green `#00ff41`
- System Vitals: Cyan `#00ffff`
- Mission Briefing: Green `#00ff41`
- Priority Stations: Amber `#f59e0b`
- Admin Operations: Red `#ef4444`
- AI Command: Cyan `#00ffff`
- Dev Tools: Purple `#8b5cf6`
- SaaS Services: Orange `#f59e0b`
- Project Knowledge: Green `#00ff41`
- Media Home: Blue `#0ea5e9`
- Upcoming: Amber `#ffaa00`
- Login/Signup: Green `#00ff41`

### Segment Color Mapping (sidebar blocks per panel)
- Command Bar: green, cyan, amber
- System Vitals: cyan, green, green, blue
- Mission Briefing: green, orange, cyan, purple
- Priority Stations: amber, green, cyan, purple
- Category panels: 3-4 shades/variants of category color
- Login: green, cyan, amber, green
- Signup: same as Login

---

## Section 12: Testing

### Visual Baseline
- Playwright screenshots at 5 breakpoints: 374 / 480 / 768 / 1024 / 1280px
- Dark mode + light mode for all pages
- Boot sequence recording (if Playwright supports video)

### Manual Checklist
- [ ] Dashboard: All 6+ panels render with full LCARS frames (elbows, sidebars, segments)
- [ ] Dashboard: Command bar sticky, glass search/notification popovers
- [ ] Dashboard: System Vitals ring gauges animate, status readouts live
- [ ] Dashboard: Mission Briefing 3-col grid, scrollable activity/alerts
- [ ] Dashboard: Category panels collapse/expand with smooth transition
- [ ] Dashboard: Module cards, pin/unpin, status dots all functional
- [ ] Dashboard: Boot sequence plays — frame-build animation ~4s
- [ ] Dashboard: "Threat Level Midnight" easter egg visible during boot
- [ ] Dashboard: Boot skip works (click/key + sessionStorage)
- [ ] Login: Tablet frame renders with full elbows + sidebar
- [ ] Login: Form submits correctly (POST /login)
- [ ] Login: Password toggle, theme toggle, language menu all work
- [ ] Login: OAuth button links correctly
- [ ] Login: Boot animation ~2.5s, "Threat Level Midnight" footer flash
- [ ] Signup: Tablet frame, wider, step indicator in header
- [ ] Signup: Step transitions animate inside frame (frame stays static)
- [ ] Signup: Password strength bar works
- [ ] Signup: Form submits correctly (POST /signup)
- [ ] Light mode: All pages — muted schematic rendering, no glows
- [ ] Responsive 1280px: Full frames, 3-col grids
- [ ] Responsive 768px: 32px sidebars, 2-col grids
- [ ] Responsive 480px: 24px sidebars, 1-col, no lights
- [ ] Responsive 374px: 16px edge bars, simplified corners
- [ ] `prefers-reduced-motion`: No animations, 0.3s fade-in only
- [ ] All existing JS functionality preserved (search, notifications, HUD refresh, module status)
