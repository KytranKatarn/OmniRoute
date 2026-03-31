# LCARS Open-Source Framework Review
## Actionable Patterns for A.R.C.H.I.E. Platform

**Date**: 2026-03-31
**Repos Analyzed**:
1. `joernweissenborn/lcars` (360 stars) -- Most complete component set, Stylus-based
2. `louh/lcars` (214 stars) -- Responsive Vue 3 + CSS Grid, lives at lcars.computer
3. `mttaggart/lcars-css` (14 stars, archived) -- Simple Sass library, overlay approach

**Our Current Stack**: lcars-tokens.css (design tokens), lcars-frames.css (structural frames with elbows/sidebars), lcars-panels.css (panel accents), station-ops.css/js (station terminals), bm-* modal classes, sc-live/sc-static glow states, 8 themes, agent cards.

---

## 1. MISSING Component Patterns (High Priority)

### 1.1 LCARS Element Decorators & Indicators (joernweissenborn)
**We don't have this.** Their `lcars-element` system treats blocks as first-class UI atoms with built-in sub-components:
- `lcars-element-addition` -- small indicator pip inside a block (e.g., a colored dot showing status)
- `lcars-element-decorator` -- vertical stripe on the left/right edge of a block

**Adoption value**: Our agent cards, status badges, and sidebar segments would benefit from a standardized decorator/indicator pattern. Currently we use ad-hoc CSS for each module.

**Proposed implementation**:
```css
/* Generic element decorators */
.lcars-element { position: relative; }
.lcars-element-indicator {
    position: absolute;
    top: 4px; right: 8px;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--archie-cyan);
}
.lcars-element-decorator {
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 4px;
    background: var(--archie-accent, var(--archie-cyan));
}
.lcars-element-decorator.right { left: auto; right: 0; }
```

### 1.2 LCARS Accordion (mttaggart)
**We don't have this.** Their `.lcars-accordion` extends the container pattern with collapsible sections:
```
.lcars-accordion (extends .lcars-container with thinner borders)
  .lcars-accordion-heading (clickable, cursor: pointer)
  .lcars-accordion-content (display: none by default, toggled via JS)
```

**Adoption value**: Knowledge base entries, agent profiles, compliance scan results -- anywhere we show expandable detail. Currently we use custom show/hide per module.

**Proposed implementation**: Wrap our existing `lcars-frame` geometry around a details/summary pattern:
```css
.lcars-accordion {
    border: 2px solid var(--frame-color);
    border-radius: var(--frame-radius);
    overflow: hidden;
}
.lcars-accordion summary {
    cursor: pointer;
    padding: 8px 16px;
    background: rgba(var(--frame-rgb), 0.1);
    font-family: var(--archie-font-nav); /* Antonio */
    text-transform: uppercase;
    letter-spacing: 1px;
}
.lcars-accordion[open] summary {
    border-bottom: 2px solid var(--frame-color);
}
```

### 1.3 LCARS Dropdown Nav (mttaggart)
**We don't have this as a reusable component.** Their nav has proper LCARS-styled dropdowns:
```
.lcars-nav.top > .lcars-nav-menu > .lcars-nav-item.dropdown
  > .lcars-dropdown > .lcars-dropdown-item
```
Styled with rounded pill-shape buttons (end-radius on left/right items), context colors (system/alert/info/confirm), and hover lighten.

**Adoption value**: Module category navigation, department floor selectors, any multi-level nav. Our current nav is custom per module.

### 1.4 Inspect Bracket / Focus Frame (louh)
**We don't have this.** A targeting bracket component with animated markers along vertical scale bars. Used for "inspecting" or "scanning" an object:
- Corner brackets (SVG-based, rotatable to all 4 corners)
- Vertical scale bars with numeric readouts (010-090)
- Animated markers that slide up/down randomly via `startAnimation()`
- Content area in center (they show planet views)

**Adoption value**: Agent profile inspection, system diagnostics focus view, node health drill-down. Would give a dramatic "scanning target" aesthetic.

### 1.5 Forward Scanner Animation (louh)
**We don't have this.** Expanding bracket animation that pulses outward:
- Three staggered `.scanner` layers with 2s delay offsets
- `embiggen` keyframe: scales from 10% to 95% width/height
- Select-bracket borders on left/right edges with rounded corners
- Uses `cubic-bezier(0, 0, 0.9, 1.0)` for near-linear but slightly eased timing

**Adoption value**: Loading/scanning states, fleet health checks, compliance scan in-progress. Far more on-brand than a spinner.

### 1.6 SVG Special Elements (joernweissenborn)
**We don't have these.** Pre-packaged SVG widgets:
- `lcars_xy_circle_widget` -- classic circular X/Y control
- `lcars_rectangular_array_ctl` -- grid array control
- Can be used as `<img>` (static) or inline SVG (interactive + audio)
- Color class definitions embedded in SVG via `<defs><style>`

**Adoption value**: Dashboard widgets, fleet map controls, system resource monitors. These are iconic LCARS elements we're missing entirely.

---

## 2. MISSING Component Patterns (Medium Priority)

### 2.1 Divider Content Grid (louh)
Randomized data-decorative dividers between layout sections:
- 3 types (`data-type="1|2|3"`) with different grid column layouts
- Small colored blocks with cutouts (pseudo-elements creating notches)
- Uses CSS Grid with `grid-template-columns` varying per type
- Purely decorative, adds visual complexity between sections

**Adoption value**: Between tab sections, between header and content. Adds authenticity.

### 2.2 LCARS Unit Grid System (joernweissenborn)
Strict multiplier-based sizing: `lcars-u-X` (width = X * unit), `lcars-vu-X` (height = X * unit), `lcars-u-X-Y` (both). X,Y = 0..16.

**Adoption value**: We use ad-hoc widths. A unit grid would enforce visual consistency across all modules. However, retrofitting is expensive -- better for new components only.

### 2.3 LCARS Form Controls (mttaggart)
Styled form elements within LCARS containers:
- Text inputs, checkboxes, radio buttons, range sliders, select dropdowns
- `.lcars-form-label` and `.lcars-select-label` wrappers
- `.lcars-radio-group` (block display container with thin borders)
- Context colors apply to form elements (system/alert/info/confirm)

**Adoption value**: Our forms are mostly default browser-styled. LCARS form controls would unify CRM, Account Center, agent creation forms.

### 2.4 Audio Feedback System (joernweissenborn)
Semantic audio events tied to UI interactions:
- `TactileInputAcknowledge()` -- button press confirmed
- `TactileInputNegativeAcknowledge()` -- action denied
- `Alert()` -- attention required
- Auto-detected file format (m4a/ogg/webm fallback)
- Applied via `.button` class automatically, or via `onclick` attribute

**Adoption value**: Optional but highly immersive. Could be gated behind a user preference toggle. Low priority but high "wow factor."

---

## 3. Color & Typography Differences

### 3.1 Color Palettes

| Framework | Approach | Key Difference from Ours |
|-----------|----------|--------------------------|
| **joernweissenborn** | 33 named colors (pale-canary, golden-tanoi, neon-carrot, eggplant, anakiwa, mariner, etc.) via `.lcars-COLORNAME-bg` / `.lcars-COLORNAME-color` | Warm oranges/golds as primary, purples as secondary. Much broader palette than our 7-color system. |
| **louh** | Doug Drexler reference palette: 9 colors (a1-a9) all warm oranges/roses/purples. `--lcars-color-a1: #ec943a` through `--lcars-color-a9: #8b72aa` | Screen-accurate TNG palette. Warm-toned, no cyans/greens. |
| **mttaggart** | 4 context colors: system (#C3A94B gold), alert (#B4463C red), info (#2F7B8E teal), confirm (#37A456 green). Default #5E5BC8 purple. | Minimal semantic palette. |
| **Ours** | 7 primary colors (green, cyan, orange, red, purple, blue, pink) + gold, with dim/bright/alpha variants per color. Semantic status colors. | Most comprehensive token system, but missing warm orange LCARS "authenticity" tones. |

**Actionable finding**: Add a "Classic LCARS" warm palette as optional theme variables:
```css
:root[data-theme="classic-lcars"] {
    --archie-primary: #ec943a;      /* warm orange */
    --archie-secondary: #c47d69;    /* dusty rose */
    --archie-tertiary: #8b72aa;     /* muted purple */
    --archie-surface: #090909;      /* near-black */
    --archie-accent: #faa41b;       /* golden amber */
}
```

### 3.2 Typography

| Framework | Font | Usage |
|-----------|------|-------|
| **joernweissenborn** | Not specified in CSS (relies on system + Stylus config) | -- |
| **louh** | `HelveticaLTStd-UltraComp` (custom @font-face, woff/woff2) | Screen-accurate. Ultra-compressed Helvetica is THE canonical LCARS font. |
| **mttaggart** | `Oswald` (nav/headings) + `Roboto` (body) via Google Fonts | Good free alternative. |
| **Ours** | `Antonio` (nav) + `Orbitron` (titles) + `IBM Plex Mono` (code) | Unique sci-fi feel but NOT canon LCARS. |

**Actionable finding**: Our fonts are intentionally different (A.R.C.H.I.E. is inspired-by, not replica). No change needed, but if we ever want a "Classic LCARS" theme, we'd need a condensed sans-serif like Oswald or Antonio Ultra-Condensed.

---

## 4. Responsive Techniques

### 4.1 louh -- ResizeObserver + Data Attributes (Best Approach)
```html
<div data-observe-resizes data-breakpoints='{"XS": 0, "SM": 708, "MD": 1280, "LG": 1600, "XL": 1900, "XXL": 3000}'>
```
- Uses ResizeObserver (not media queries) for container-based responsiveness
- Breakpoint classes added to container element (`.screen.SM`, `.screen.MD`, etc.)
- CSS Grid template changes per breakpoint class
- 6 breakpoints: XS (0), SM (708), MD (1280), LG (1600), XL (1900), XXL (3000)

**Adoption value**: HIGH. This is container queries before container queries existed. We currently use media queries at 480/768/1024px. Switching to ResizeObserver-based breakpoints would let panels inside modals or sidebars respond to THEIR container width, not the viewport. Modern browsers now support native `@container` queries which is even better.

### 4.2 louh -- CSS Grid Named Areas
```css
grid-template-areas:
    "sidebar-top title"
    "sidebar-top meta-content"
    "sidebar-top divider"
    "sidebar-bottom divider"
    "sidebar-bottom main-content";
```
Complete layout restructuring per breakpoint via named grid areas. Sidebar collapses at small sizes.

**Adoption value**: Our lcars-frame uses flexbox. Grid with named areas would be more powerful for complex layouts but requires significant refactoring. Best for NEW module layouts.

### 4.3 louh -- Touch Action Lock
```css
body { touch-action: none; }
```
Prevents iPad Safari pinch-zoom which deforms the LCARS layout.

**Adoption value**: Quick win for tablet users. Should be applied conditionally (only in fullscreen/kiosk mode).

---

## 5. Animation Patterns Worth Adopting

### 5.1 Stepped Color Pulse (louh)
```css
.shift1 {
    animation-name: pulse;
    animation-duration: 6s;
    animation-timing-function: steps(1, start); /* KEY: discrete steps, not smooth */
    animation-iteration-count: infinite;
    animation-direction: alternate;
}
@keyframes pulse {
    0%   { background-color: #36c; }
    33%  { background-color: #36c; }
    66%  { background-color: #9cf; }
    100% { background-color: #9cf; }
}
```
**Key insight**: `steps(1, start)` creates LCARS-authentic discrete color shifts (not smooth transitions). The real LCARS panels don't fade -- they snap between states.

**Adoption value**: Our `sc-live` glow uses smooth pulsing. Adding a `sc-live-stepped` variant with discrete steps would be more authentic for status indicators.

### 5.2 Staggered Scanner Sweep (louh)
Three layers with 0s/2s/4s delays, each expanding from 10% to 95% over 6s. Creates a radar-like sweep effect.

**Adoption value**: Replace loading spinners in scanning/analysis views.

### 5.3 Animated Scale Markers (louh -- InspectBracket)
```js
startAnimation(markerRef, minPercent, maxPercent, minDuration, maxDuration)
```
Markers slide along a vertical track at random intervals, creating a "sensor reading" effect.

**Adoption value**: System monitoring panels, resource meters. Much more LCARS than progress bars.

---

## 6. Implementation Priority Ranking

| # | Pattern | Effort | Impact | Priority |
|---|---------|--------|--------|----------|
| 1 | LCARS Accordion (`<details>` based) | Low (CSS only) | High -- used everywhere | **P1** |
| 2 | Element Decorators/Indicators | Low (CSS only) | High -- standardizes badges | **P1** |
| 3 | Stepped Color Pulse animation | Low (CSS only) | Medium -- more authentic | **P1** |
| 4 | Scanner Sweep loading animation | Medium (CSS+JS) | Medium -- replaces spinners | **P2** |
| 5 | Container-based breakpoints (`@container`) | Medium (CSS refactor) | High -- fixes panel responsiveness | **P2** |
| 6 | LCARS Form Controls | Medium (CSS) | High -- unifies all forms | **P2** |
| 7 | Inspect Bracket component | High (SVG+JS+CSS) | Medium -- dramatic but niche | **P3** |
| 8 | SVG XY Circle Widget | High (SVG) | Low -- decorative | **P3** |
| 9 | Audio Feedback | Medium (JS+assets) | Low -- optional | **P3** |
| 10 | Classic LCARS warm color theme | Low (CSS vars) | Low -- niche preference | **P3** |
| 11 | Divider Content Grid | Medium (CSS Grid) | Low -- decorative | **P3** |
| 12 | LCARS Dropdown Nav | Medium (CSS+JS) | Medium -- replaces custom navs | **P2** |

---

## 7. Quick Wins (Can Ship This Week)

### 7.1 Add to lcars-frames.css
```css
/* Accordion (native <details>) */
.lcars-accordion { /* see section 1.2 */ }

/* Element decorators */
.lcars-element-indicator { /* see section 1.1 */ }
.lcars-element-decorator { /* see section 1.1 */ }

/* Stepped pulse for status blocks */
.sc-live-stepped {
    animation: lcars-step-pulse 4s steps(1, start) infinite alternate;
}
@keyframes lcars-step-pulse {
    0%, 40%  { opacity: 1; }
    50%, 90% { opacity: 0.5; }
}
```

### 7.2 Add to station-ops.css
```css
/* Scanner sweep for loading states */
.lcars-scanner-sweep {
    position: relative;
    overflow: hidden;
}
.lcars-scanner-sweep::after {
    content: '';
    position: absolute;
    top: 0; left: -100%;
    width: 100%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(var(--frame-rgb), 0.15), transparent);
    animation: lcars-sweep 2s ease-in-out infinite;
}
@keyframes lcars-sweep {
    to { left: 100%; }
}
```

---

## 8. What We Already Do Better

For completeness, areas where our system exceeds all three repos:

| Feature | Our Advantage |
|---------|---------------|
| **Design token system** | Most comprehensive: 7 colors x 4 variants + alpha + semantic + per-module overrides. None of the repos have this level of token architecture. |
| **Theme switching** | 8 themes with 4 layout families. No repo supports theming at all. |
| **Modal system** | Full bm-* modal hierarchy (overlay > shell > frame > content). mttaggart has basic accordion, others have nothing. |
| **Frame geometry** | Our lcars-frames.css has proper structural sidebars with segmented color blocks, pip decorators, elbow math. joernweissenborn has elbows but no sidebar segments. |
| **Glow system** | sc-live/sc-static with per-module accent colors. No repo has data-aware glow states. |
| **i18n ready** | All our components support data-i18n. No repo considers internationalization. |
| **Agent cards** | Domain-specific component. No equivalent in any repo. |
| **Responsive breakpoints** | We have 3 breakpoints working. louh has 6 but via custom JS, not native CSS. |

---

*Review complete. P1 items (accordion, decorators, stepped pulse) can be added to lcars-frames.css with zero breaking changes.*
