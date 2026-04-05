# Consciousness UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the disconnected nav + glass-nav with a unified LCARS header component, convert all hardcoded purple to CSS variable theming, implement 6-tier responsive breakpoints, add LCARS alert strip and toast notifications — all as a reusable shared component for the entire platform.

**Architecture:** New shared LCARS header include (`lcars-header.html`) + CSS (`lcars-header.css`) + JS (`lcars-header.js`). Breakpoints in `archie-breakpoints.css`. Consciousness module is first adopter. Category colors flow from `module_registry.py` through template variables to CSS custom properties.

**Tech Stack:** HTML/Jinja2, CSS (custom properties), vanilla JS, Flask.

**Spec:** `docs/superpowers/specs/2026-04-05-consciousness-ux-overhaul-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `platform_v2/static/css/archie-breakpoints.css` | Platform-standard breakpoint variables |
| Create | `platform_v2/static/css/lcars-header.css` | LCARS header component + responsive + alert states + toasts |
| Create | `platform_v2/static/js/lcars-header.js` | Header tab switching, alert state management, toast system |
| Create | `platform_v2/templates/includes/lcars-header.html` | Shared Jinja2 include for LCARS header |
| Modify | `platform_v2/templates/base.html` | Add breakpoints CSS link |
| Modify | `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` | Replace category_nav + glass-nav with lcars-header, convert inline purple |
| Modify | `platform_v2/static/css/consciousness-dashboard-v2.css` | Replace ~50 purple hardcodes with var(--cat-accent) |
| Modify | `platform_v2/static/js/consciousness.js` | Wire new header tab switching, remove glass-nav init |

---

### Task 1: Platform Breakpoints CSS

**Files:**
- Create: `platform_v2/static/css/archie-breakpoints.css`
- Modify: `platform_v2/templates/base.html`

- [ ] **Step 1: Create the breakpoints file**

Create `platform_v2/static/css/archie-breakpoints.css`:

```css
/* archie-breakpoints.css -- Platform-Standard Responsive Breakpoints
   ALL modules MUST use these. No ad-hoc values.
   xs:360 sm:480 fold:717 md:768 lg:1024 xl:1440
*/
:root {
  --bp-xs: 360px;
  --bp-sm: 480px;
  --bp-fold: 717px;
  --bp-md: 768px;
  --bp-lg: 1024px;
  --bp-xl: 1440px;
}
```

- [ ] **Step 2: Add to base.html**

In `platform_v2/templates/base.html`, find the CSS links section (around line 20-42). Add after `animations.css`:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/archie-breakpoints.css') }}">
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/static/css/archie-breakpoints.css platform_v2/templates/base.html
git commit -m "feat: add platform-standard responsive breakpoints (360/480/717/768/1024/1440)"
```

---

### Task 2: LCARS Header HTML Template

**Files:**
- Create: `platform_v2/templates/includes/lcars-header.html`

- [ ] **Step 1: Create the shared include**

Create `platform_v2/templates/includes/lcars-header.html`. This is the reusable component that any module includes with one line.

Parameters it reads from the including template:
- `cat_accent` (hex color), `cat_accent_rgb` (r,g,b), `cat_accent_dark` (darker hex)
- `cat_label` (category name), `module_title` (module name)
- `module_back_url` (back button target, defaults to /dashboard)
- `header_tabs` (list of (id, label, icon) tuples)

Structure:
- Left: `.lcars-header-elbow` with back arrow (top) and theme toggle + lang (bottom)
- Right top: `.lcars-header-bar` with module name, category, stardate
- Right bottom: `.lcars-header-tabs` with tab buttons
- Short tab labels (`.lcars-header-tab-short`) hidden on desktop, shown on mobile
- Toast container at the bottom

Full HTML provided in the spec. Use Lucide icons (`data-lucide` attributes). Tab buttons call `lcarsHeaderSwitchTab(tabId)` on click.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/templates/includes/lcars-header.html
git commit -m "feat: create shared LCARS header Jinja2 include"
```

---

### Task 3: LCARS Header CSS

**Files:**
- Create: `platform_v2/static/css/lcars-header.css`

- [ ] **Step 1: Create the full CSS file**

This file contains ALL styles for the LCARS header component:

**Base layout:** `.lcars-header` (sticky, flex row), `.lcars-header-elbow` (64px column), `.lcars-header-main` (flex-1).

**Elbow:** Top section (gradient, back arrow, 32px h, rounded top-left 16px). Bottom section (darker gradient, theme/lang icons, rounded bottom-left 16px).

**Alert states:** `[data-alert-state="warning"]` turns elbow orange with 2s pulse. `[data-alert-state="critical"]` turns elbow red with 1s pulse. Animation: `lcarsElbowPulse` opacity 1->0.6->1.

**Title bar:** `.lcars-header-bar` full gradient left-to-right (accent->accent-dark->transparent). Title in Antonio bold, dark text on accent bg. Category label dimmed. Stardate right-aligned monospace.

**Tabs:** `.lcars-header-tabs` flex row, scrollable, no scrollbar. Active tab: accent bg 15%, accent text, glow shadow. Hover: accent bg 8%. Short labels (`.lcars-header-tab-short`) hidden by default.

**Toasts:** `.lcars-toast-container` fixed top-right z-10000. `.lcars-toast` flex row with accent strip (4px left), content area, close button. Severity variants change accent strip color. Slide-in/out animations.

**Responsive (6 breakpoints):**
- 1024px: Elbow 56px, slightly smaller
- 768px: Elbow 44px, hide category/stardate, smaller tabs
- 717px: Elbow 40px, hide lang label
- 480px: Header becomes column layout. Elbow becomes 3px top accent strip. Back arrow moves to title bar. Tab labels switch to short form (4 chars). Tab icons shrink.
- 360px: No tab icons, tighter padding, smaller title.

All colors use `var(--cat-accent)`, `var(--cat-accent-dark)`, `rgba(var(--cat-accent-rgb), ...)`.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/css/lcars-header.css
git commit -m "feat: LCARS header CSS with 6-tier responsive + alert states + toasts"
```

---

### Task 4: LCARS Header JavaScript

**Files:**
- Create: `platform_v2/static/js/lcars-header.js`

- [ ] **Step 1: Create the JS file**

IIFE with these functions:

**`window.lcarsHeaderSwitchTab(tabId)`** — toggles `.active` class on tab buttons matching `data-tab`. Calls `window.onLcarsTabSwitch(tabId)` if defined (module hook).

**`window.lcarsSetAlertState(state)`** — sets `data-alert-state` attribute on `#lcarsHeader`. Values: "normal", "warning", "critical".

**`window.lcarsToast(title, message, severity, durationMs)`** — creates toast DOM element in `#lcarsToastContainer`. Uses safe DOM methods only (createElement, textContent). Close button uses textContent = "\u00d7" (multiplication sign character, NOT innerHTML). Auto-dismiss: info=5s, warning=10s, error=manual (0). Removal: adds `.removing` class, waits 300ms, removes from DOM.

**`_updateStardate()`** — computes stardate from current date (year + day-of-year + fraction), updates `#lcarsStardate`. Runs on DOMContentLoaded + every 60s.

**DOMContentLoaded handler:** calls `_updateStardate()`, sets interval, calls `lucide.createIcons()` if available.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/lcars-header.js
git commit -m "feat: LCARS header JS -- tab switching, alert states, toast system, stardate"
```

---

### Task 5: Wire Consciousness Module to LCARS Header

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`
- Modify: `platform_v2/static/js/consciousness.js`

- [ ] **Step 1: Replace category_nav with lcars-header in the template**

Find lines 20-31 (cat_accent setup + category_nav include). Replace with:

```html
{% set cat_accent = '#00ffff' %}
{% set cat_accent_rgb = '0,255,255' %}
{% set cat_accent_dark = '#00cccc' %}
{% set cat_label = 'AI COMMAND' %}
{% set module_title = 'CONSCIOUSNESS' %}
{% set header_tabs = [
    ("dashboard", "Dashboard", "layout-dashboard"),
    ("intelligence", "Intelligence", "brain-circuit"),
    ("knowledge", "Knowledge", "book-open"),
    ("github", "GitHub", "github"),
    ("languages", "Languages", "languages"),
    ("codehealth", "Code Health", "activity")
] %}
{% include 'includes/lcars-header.html' %}
```

- [ ] **Step 2: Remove the glass-nav HTML block**

Delete the entire `<nav class="glass-nav" id="csNav">...</nav>` block (around line 2475-2500, approximately 25 lines).

- [ ] **Step 3: Add CSS and JS links**

Add to the `{% block extra_css %}` section:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/lcars-header.css') }}">
```

Add BEFORE the `consciousness.js` script tag at the bottom:
```html
<script src="{{ url_for('static', filename='js/lcars-header.js') }}"></script>
```

- [ ] **Step 4: Wire tab switching in consciousness.js**

Replace the GlassNav initialization (around line 2146-2152):
```javascript
  var navEl = document.getElementById("csNav");
  if (navEl) {
    _glassNav = new GlassNav(navEl, {
      onSwitch: function(tab) { switchConsciousnessTab(tab); }
    });
  }
```

With:
```javascript
  // Wire LCARS header tab switching
  window.onLcarsTabSwitch = function(tab) {
    switchConsciousnessTab(tab);
  };
```

Remove the `_glassNav.setActive(tab)` call from `switchConsciousnessTab` (around line 108).

Update `validTabs` to include all 6 tabs:
```javascript
  var validTabs = ["dashboard", "intelligence", "knowledge", "github", "languages", "codehealth"];
```

Update the initial tab switch to also sync the LCARS header:
```javascript
  if (hash && validTabs.indexOf(hash) !== -1) {
    lcarsHeaderSwitchTab(hash);
    switchConsciousnessTab(hash);
  } else {
    switchConsciousnessTab("dashboard");
  }
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat: wire consciousness module to LCARS header, remove glass-nav"
```

---

### Task 6: Convert Purple Hardcodes to CSS Variables

**Files:**
- Modify: `platform_v2/static/css/consciousness-dashboard-v2.css`
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

- [ ] **Step 1: Replace in consciousness-dashboard-v2.css**

Global find-and-replace across the file:
- `#8b5cf6` -> `var(--cat-accent)` (approximately 30+ occurrences)
- `rgba(139, 92, 246,` -> `rgba(var(--cat-accent-rgb),` (approximately 20+ occurrences)
- `#6d28d9` -> `var(--cat-accent-dark)` (a few occurrences in sidebar styles)

**Do NOT replace:** `#ef4444` (red), `#10b981` (green), `#fbbf24` (gold), `#00e5ff` (cyan skill chips), `#fb923c` (orange drafts). These are semantic status colors, not accent colors.

- [ ] **Step 2: Replace in template inline styles**

In `consciousness_dashboard.html`, find all LCARS frame `<div>` elements with inline purple styles:

Replace `--frame-color: #8b5cf6` with `--frame-color: var(--cat-accent)`
Replace `--frame-rgb: 139,92,246` with `--frame-rgb: var(--cat-accent-rgb)`
Replace `background:#8b5cf6` with `background:var(--cat-accent)`
Replace `background:#6d28d9` with `background:var(--cat-accent-dark)`

These appear in all 5 Intelligence tab panels and other LCARS frames throughout the template.

- [ ] **Step 3: Replace in the large inline style block**

The template has a `<style>` block starting around line 33 with comment `Purple/violet accent #8b5cf6`. Apply the same replacements inside that block.

- [ ] **Step 4: Update the knowledge graph canvas JS**

In `consciousness-dashboard-v2.js`, find the `renderKnowledgeGraph` function. Node colors reference `139, 92, 246` (purple). Replace with reading from CSS:

Find all `rgba(139, 92, 246,` in that file and replace with `rgba(var(--cat-accent-rgb),` where possible. For canvas ctx operations that need literal values, read the CSS variable at render time:

```javascript
var accentColor = getComputedStyle(document.documentElement).getPropertyValue('--cat-accent').trim() || '#00ffff';
```

Use this for canvas `ctx.strokeStyle` and `ctx.fillStyle` calls instead of hardcoded purple.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/css/consciousness-dashboard-v2.css platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness-dashboard-v2.js
git commit -m "feat: convert all purple hardcodes to var(--cat-accent) CSS variables"
```

---

### Task 7: Deploy, Test, Verify

**Files:** None (verification only)

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify LCARS header renders at http://192.168.1.200:3000/tools/consciousness**

Check:
1. LCARS elbow visible on left (teal gradient, 64px wide on desktop)
2. Module title "CONSCIOUSNESS" in gradient bar
3. "AI COMMAND" category label visible
4. 6 tab buttons visible and clickable
5. Active tab highlighted in teal
6. Back arrow links to /dashboard
7. Stardate displayed

- [ ] **Step 3: Verify all 6 tabs switch correctly**

Click each tab. Verify panel content loads, URL hash updates, no JS errors in console.

- [ ] **Step 4: Verify teal theming — zero purple remaining**

Check all Intelligence panels: frame headers, completeness rings, gap chips, expertise tabs, knowledge graph nodes all teal.

- [ ] **Step 5: Test toast system**

Browser console:
```javascript
lcarsToast("Test", "Info toast", "info");
lcarsToast("Warning", "Warning toast", "warning");
lcarsToast("Error", "Error toast - manual dismiss", "error");
```

- [ ] **Step 6: Test alert states**

Browser console:
```javascript
lcarsSetAlertState("warning");
// Observe: elbow turns orange, pulses
lcarsSetAlertState("critical");
// Observe: elbow turns red, fast pulse
lcarsSetAlertState("normal");
// Observe: elbow returns to teal
```

- [ ] **Step 7: Test responsive breakpoints**

Resize browser to: 1440px, 1024px, 768px, 717px, 480px, 360px. Verify elbow adapts (full -> shrink -> strip), tabs adapt (full labels -> short labels -> icons only), content reflows.

- [ ] **Step 8: Complete MCP task**

```
mcp complete_task 1642 "LCARS integrated header: shared component with elbow + gradient bar + tabs. CSS variable theming matching dashboard.js category colors. 6-tier responsive breakpoints (360/480/717/768/1024/1440). Alert strip (elbow = status). Toast notifications. All purple converted to var(--cat-accent). Platform-scalable: any module uses one include."
```
