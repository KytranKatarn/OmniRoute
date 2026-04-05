# Consciousness Module UX Overhaul — Design Spec

**Date:** 2026-04-05
**Project:** #222 — Consciousness Module UX Overhaul
**Task:** #1642 — Nav bar integration + category color theming (Phase 1)
**Status:** Approved design, pending implementation

---

## Problem

The Consciousness module has visual disconnects: teal category nav bar transitions to purple content panels. Nav bar, glass nav, and ops alert bar are 3 separate components eating vertical space. Responsive breakpoints are inconsistent (480px/768px only). Modals don't use the platform-standard LCARS tablet system. The design doesn't scale to other modules.

## Goals

1. **Seamless LCARS header** — elbow + gradient bar + tabs as one integrated component
2. **CSS variable theming** — `--cat-accent` auto-inherits from module category, matching dashboard.js colors exactly
3. **Adaptive responsive** — 6 breakpoints covering Fold 5, Android, tablet, desktop
4. **LCARS alert strip** — elbow color = system status (teal/orange/red)
5. **bm- modal standard** — all popups use LCARS tablet frames
6. **Platform scalability** — one `{% include %}` gives any module the full treatment

---

## 1. Color System

### Single Source of Truth: `dashboard.js` Category Colors

| Category | Slug | Primary | Dark (20%) | RGB |
|----------|------|---------|------------|-----|
| AI Command | `ai_command` | `#00ffff` | `#00cccc` | `0,255,255` |
| Admin Operations | `admin_operations` | `#ef4444` | `#dc2626` | `239,68,68` |
| SaaS Services | `saas_services` | `#f59e0b` | `#d97706` | `245,158,11` |
| Project & Knowledge | `project_knowledge` | `#00ff41` | `#00cc34` | `0,255,65` |
| Media Home | `media_home` | `#0ea5e9` | `#0284c7` | `14,165,233` |
| Crypto | `crypto` | `#eab308` | `#ca8a04` | `234,179,8` |
| Applications | `applications` | `#10b981` | `#059669` | `16,185,129` |
| Creative Studios | `creative_studios` | `#ec4899` | `#db2777` | `236,72,153` |
| Core Services | `core_services` | `#00808f` | `#006670` | `0,128,143` |

### CSS Variables (Set by base.html from category)

```css
:root {
  --cat-accent: #00ffff;           /* Primary category color */
  --cat-accent-dark: #00cccc;      /* 20% darker, for gradients */
  --cat-accent-rgb: 0,255,255;     /* For rgba() usage */
}
```

Template sets these via inline style on `<body>` based on module's registered category. Every CSS rule in the module uses `var(--cat-accent)` instead of hardcoded colors.

### Implementation

- New file: `platform_v2/static/css/archie-colors.css` — central color registry with category mappings
- Modify: `base.html` — set `--cat-accent*` variables from module registry category
- Modify: `consciousness-dashboard-v2.css` — replace ~50 purple `#8b5cf6` hardcodes with `var(--cat-accent)`
- Modify: `consciousness.js` — update any JS color references

---

## 2. LCARS Integrated Header

### Desktop Layout (1024px+)

```
┌──────────┬──────────────────────────────────────────────────┐
│ ← (back) │  CONSCIOUSNESS    AI COMMAND         SD 78924.7  │  ← gradient bar
│          ├──────────────────────────────────────────────────┤
│  ☾  EN   │  [Dashboard] [Intelligence] [Knowledge] [GitHub] │  ← tab row
│  (elbow) │  [Languages] [Code Health]                       │
└──────────┴──────────────────────────────────────────────────┘
     64px                        flex: 1
```

**Elbow (left):**
- Top section: back arrow (navigates to dashboard), uses `--cat-accent` gradient
- Bottom section: theme toggle icon + language code, uses `--cat-accent-dark`
- Corner radii: 14px top-left, 14px bottom-left (matches bm- modal elbows)

**Bar (top right):**
- Full-width gradient: `linear-gradient(90deg, var(--cat-accent), var(--cat-accent-dark) 50%, transparent)`
- Module name in Antonio font, bold, dark text on accent background
- Category label (dimmed), stardate (right-aligned, monospace)

**Tab row (bottom right):**
- Translucent accent background at 3% opacity
- Active tab: accent bg at 20% + accent border + accent text
- Inactive: muted gray text, hover shows accent at 10%
- Bottom border: 2px solid accent at 20% opacity

### Alert Status (Elbow Color Changes)

| Status | Elbow Color | Animation | Trigger |
|--------|------------|-----------|---------|
| Normal | `--cat-accent` (teal for AI Command) | None | Default state |
| Warning | `#ff9f43` (orange) | Slow pulse (2s) | Ops alerts pending |
| Critical | `#ef4444` (red) | Fast pulse (1s) | System critical alerts |

Click elbow → opens LCARS tablet modal (`bm-` system) showing all notifications grouped by severity. Module-level alerts appear as auto-dismissing toast messages.

### HTML Structure

New shared include: `platform_v2/templates/includes/lcars-header.html`

```html
{% set tabs = tabs|default([]) %}
<div class="lcars-header" style="--cat-accent:{{ cat_accent }}; --cat-accent-dark:{{ cat_accent_dark|default(cat_accent) }}; --cat-accent-rgb:{{ cat_accent_rgb }};">
  <div class="lcars-header-elbow" id="lcarsHeaderElbow" data-alert-state="normal">
    <div class="lcars-header-elbow-top">
      <a href="/dashboard" class="lcars-header-back">←</a>
    </div>
    <div class="lcars-header-elbow-bottom">
      <button class="lcars-header-theme" onclick="toggleTheme()">☾</button>
      <span class="lcars-header-lang">EN</span>
    </div>
  </div>
  <div class="lcars-header-main">
    <div class="lcars-header-bar">
      <span class="lcars-header-title">{{ module_name|upper }}</span>
      <span class="lcars-header-category">{{ cat_label }}</span>
      <span class="lcars-header-stardate"></span>
    </div>
    <div class="lcars-header-tabs" id="lcarsHeaderTabs">
      {% for tab_id, tab_label, tab_icon in tabs %}
      <button class="lcars-header-tab{% if loop.first %} active{% endif %}" data-tab="{{ tab_id }}">
        <i data-lucide="{{ tab_icon }}"></i>
        <span>{{ tab_label }}</span>
      </button>
      {% endfor %}
    </div>
  </div>
</div>
```

Module template usage:
```html
{% set tabs = [
  ("dashboard", "Dashboard", "layout-dashboard"),
  ("intelligence", "Intelligence", "brain-circuit"),
  ("knowledge", "Knowledge", "book-open"),
  ("github", "GitHub", "github"),
  ("languages", "Languages", "languages"),
  ("codehealth", "Code Health", "activity")
] %}
{% include 'includes/lcars-header.html' %}
```

---

## 3. Responsive Breakpoints

### Standard Breakpoints (Platform-Wide)

| Name | Width | Target | Elbow | Tabs |
|------|-------|--------|-------|------|
| `xs` | 360px | Fold 5 folded, small phones | 3px top accent strip | 2-3 letter labels, horizontal scroll |
| `sm` | 480px | Standard Android phones | 3px top accent strip | Short labels, horizontal scroll |
| `fold` | 717px | Galaxy Fold 5 unfolded | 40px mini elbow | Scroll with fade edges |
| `md` | 768px | iPad Mini, small tablets | 40px mini elbow | Full labels, may wrap |
| `lg` | 1024px | iPad, laptops | 56px elbow | Full labels in row |
| `xl` | 1440px | Desktop, large screens | 64px elbow | Full labels with spacing |

### New File: `archie-breakpoints.css`

```css
/* Platform-standard breakpoints — use these everywhere */
:root {
  --bp-xs: 360px;
  --bp-sm: 480px;
  --bp-fold: 717px;
  --bp-md: 768px;
  --bp-lg: 1024px;
  --bp-xl: 1440px;
}
```

All modules MUST use these breakpoints. No more ad-hoc 500px or 767px values.

### Phone Behavior (xs + sm: ≤480px)

- Elbow hidden, replaced by 3px accent strip at top of header
- Module name + back arrow in slim bar
- Tabs become swipeable pill row (horizontal scroll, no wrap)
- Tab labels: shortened (Dashboard→DASH, Intelligence→INTEL, Knowledge→KB)
- Utilities (theme/lang) accessible via 3-dot menu or hidden in header tap

### Fold 5 Behavior (fold: 481-717px)

- Mini elbow (40px wide) with back arrow only
- Tabs scroll horizontally with fade edges on overflow
- Full tab labels (no abbreviation)
- Theme/lang icons in elbow bottom section

### Tablet Behavior (md: 718-1024px)

- Mini elbow (40px) with back arrow + theme toggle
- Full tab labels, may wrap to second row if needed
- Content panels stack vertically

### Desktop Behavior (lg+: 1025px+)

- Full elbow (56-64px) with all controls
- All tabs visible in single row
- Content panels may use side-by-side layout where appropriate

---

## 4. Modals — bm- LCARS Tablet System

All consciousness module popups/modals MUST use the existing `bm-` LCARS tablet modal system (documented in `static/css/lcars-modals.md`).

### Modals needed:

| Modal | Purpose | Accent |
|-------|---------|--------|
| Notification Panel | All alerts grouped by severity | `--cat-accent` |
| Generate Report | Confirm D.A.R.W.I.N. doc generation | `--cat-accent` |
| Knowledge Link | Manual link KB entry to project | `--cat-accent` |

### Implementation

- Set `--bm-accent: var(--cat-accent)` and `--bm-accent-rgb: var(--cat-accent-rgb)` on overlays
- Modals auto-inherit the module's category color
- Responsive: already handled at 768px in bm- system, extend to 480px/360px

---

## 5. Notification Toast System

Module-level alerts (not system/ops) appear as toast messages:

```html
<div class="lcars-toast" data-severity="info|warning|error|success">
  <div class="lcars-toast-accent"></div>
  <div class="lcars-toast-content">
    <span class="lcars-toast-title">Title</span>
    <span class="lcars-toast-message">Message text</span>
  </div>
  <button class="lcars-toast-close">&times;</button>
</div>
```

- Position: top-right, stacked
- Auto-dismiss: 5s (info), 10s (warning), manual (error)
- Accent bar color matches severity (teal/orange/red/green)
- Slide-in animation from right

---

## 6. File Summary

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/static/css/lcars-header.css` | LCARS header component styles + responsive |
| Create | `platform_v2/static/js/lcars-header.js` | Header behavior, alert states, tab switching, toast system |
| Create | `platform_v2/static/css/archie-breakpoints.css` | Platform-standard breakpoint variables |
| Create | `platform_v2/templates/includes/lcars-header.html` | Shared Jinja2 include for LCARS header |
| Modify | `platform_v2/templates/base.html` | Add breakpoints CSS, set --cat-accent from category |
| Modify | `consciousness_dashboard.html` | Replace glass-nav with lcars-header include |
| Modify | `consciousness-dashboard-v2.css` | Replace ~50 purple hardcodes with var(--cat-accent) |
| Modify | `consciousness.js` | Wire new header tab switching, remove glass-nav init |
| Modify | `module_registry.py` | Add color fields to category enum (primary, dark, rgb) |
| Keep | `glass-nav.css` + `glass-nav.js` | Retained as fallback for modules not yet migrated |

### Migration Path for Other Modules

After consciousness proves the pattern:
1. Module template: replace glass-nav with `{% include 'includes/lcars-header.html' %}`
2. Module CSS: replace hardcoded colors with `var(--cat-accent)`
3. Module JS: update tab switching to use `lcars-header.js` API
4. Test at all 6 breakpoints
5. One module at a time — no big-bang migration
