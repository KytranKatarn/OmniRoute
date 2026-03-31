# A.R.C.H.I.E. LCARS Design System Documentation

**Version:** 1.0
**Last Updated:** March 31, 2026
**Purpose:** Complete design system for the Star Trek LCARS-inspired A.R.C.H.I.E. platform dashboard

---

## Table of Contents

1. [Color Palette](#color-palette)
2. [Typography](#typography)
3. [LCARS Frame Structure](#lcars-frame-structure)
4. [Layout Grids](#layout-grids)
5. [Component Styling](#component-styling)
6. [Command Bar](#command-bar)
7. [HUD Vitals Frame](#hud-vitals-frame)
8. [Briefing Frame](#briefing-frame)
9. [Responsive Design](#responsive-design)
10. [Animations](#animations)
11. [CSS Variables](#css-variables)
12. [Design Principles](#design-principles)

---

## Color Palette

### Primary Colors

These colors define the core visual identity and are used for frame borders, accent bars, and glows.

| Color | Hex Value | RGB | Usage |
|-------|-----------|-----|-------|
| **Green** | `#00FF41` | `0, 255, 65` | Command bar, default frames, online status |
| **Cyan** | `#00FFFF` | `0, 255, 255` | HUD vitals, system info |
| **Orange** | `#FFAA00` | `255, 170, 0` | Featured modules, warnings |

### Category-Specific Colors

Each dashboard category has a unique accent color for visual distinction:

```css
.category-frame--admin_operations  { --frame-color: #ef4444; }      /* Red */
.category-frame--ai_command        { --frame-color: #00ffff; }      /* Cyan */
.category-frame--saas_services     { --frame-color: #f59e0b; }      /* Amber */
.category-frame--project_knowledge { --frame-color: #00ff41; }      /* Lime Green */
.category-frame--media_home        { --frame-color: #0ea5e9; }      /* Sky Blue */
.category-frame--crypto            { --frame-color: #eab308; }      /* Yellow */
.category-frame--applications      { --frame-color: #10b981; }      /* Emerald */
.category-frame--creative_studios  { --frame-color: #ec4899; }      /* Pink */
.category-frame--placeholders      { --frame-color: #6b7280; }      /* Gray */
```

### Background Colors

- **Primary Background:** `#010409` (near-black)
- **Secondary Background:** `#0d1117` (dark blue-gray)
- **Semi-transparent overlays:** `rgba(255, 255, 255, 0.03–0.06)`

### Neon Glow Effects

The characteristic LCARS "glow" is achieved with box-shadow using semi-transparent accent colors:

```css
--archie-glow-green-sm:   0 0 8px rgba(0, 255, 65, 0.3);
--archie-glow-green-md:   0 0 15px rgba(0, 255, 65, 0.5);
--archie-glow-cyan:       0 0 8px rgba(0, 255, 255, 0.3);
--archie-glow-orange:     0 0 8px rgba(255, 170, 0, 0.3);
--archie-glow-red:        0 0 8px rgba(255, 59, 59, 0.6);
--archie-glow-gold:       0 0 20px rgba(251, 191, 36, 0.15);
```

---

## Typography

### Font Families

| Font | Usage |
|------|-------|
| **Antonio** | All LCARS headers, bar titles, labels (uppercase) |
| **JetBrains Mono** / **IBM Plex Mono** | Body text, input fields, UI copy |
| **Orbitron** | Numeric readouts and values (HUD displays) |
| **Courier New** | Fallback monospace |

### Font Sizing & Styling

All text is **UPPERCASE** with tight letter-spacing for the futuristic LCARS aesthetic:

| Element | Size | Weight | Letter-spacing | Example |
|---------|------|--------|-----------------|---------|
| Category Header | `0.78–0.85rem` | 500–600 | `1.5–2px` | "ENGINEERING" |
| LCARS Bar Title | `0.75–0.85rem` | 600 | `0.15–1.5em` | "SYSTEM STATUS" |
| Featured Card Name | `0.95–1.1rem` | 600 | `1px` | "BLUEPRINT" |
| Module Card Name | `0.85rem` | 600 | `0.5px` | "CODERABBIT" |
| HUD Label | `11px` | 600 | `0.15em` | "POWER" |
| HUD Value | `14px` | 700 | `normal` | "87%" |
| Section Title | `0.78rem` | 500 | `1.5px` | "RECENT ACTIVITY" |
| Footer Text | `0.7rem` | normal | `1px` | Small metadata |

---

## LCARS Frame Structure

The characteristic LCARS frame consists of five main components:

### Component Hierarchy

```
.lcars-frame (outer container)
  ├── .lcars-sidebar (left vertical edge, 6–8px wide)
  │   ├── .lcars-elbow-top (rounded corner at top-left)
  │   ├── .lcars-seg (colored segment blocks)
  │   ├── .lcars-seg-light (dimmed/inactive segment)
  │   ├── .lcars-seg-fill (spacer segment)
  │   └── .lcars-elbow-bottom (rounded corner at bottom-left)
  └── .lcars-content (main content area)
      ├── .lcars-bar (header bar with title)
      │   ├── .lcars-bar-title (section name)
      │   ├── .lcars-bar-spacer (flex spacer)
      │   └── .lcars-pips (decorative colored squares)
      └── .lcars-body (content area)
```

### Elbow Corners

The signature LCARS design uses **rounded square corners**:
- **Border-radius:** `16–20px` (typically `20px`)
- **Position:** Top-left and bottom-left of the sidebar
- **Effect:** Creates the distinctive "bent" look at frame corners
- **Applied to:** `.lcars-elbow-top` and `.lcars-elbow-bottom`

### Sidebar

- **Width:** 6–8px (flex-basis adjusted)
- **Contains:** Vertical stack of colored segments
- **Segments** indicate status: lit segments use `background: var(--seg-color)` with `box-shadow: glow`; unlit segments use `rgba(255, 255, 255, 0.06)`
- **Fills** available vertical space

### Bar Header

- **Height:** 14–20px (varies by frame type)
- **Border-radius:** `0 var(--frame-radius, 20px) var(--frame-radius, 20px) 0` (right side only)
- **Contains:** Bar title, spacer, and decorative pips
- **Background:** Inherits `--frame-color`

### Body

- **Padding:** 8–14px (varies by context)
- **Background:** Transparent or very dark
- **Contains:** Cards, readouts, or nested content

---

## Layout Grids

### Featured Cards Row

```css
.featured-cards-row {
  display: flex;
  flex-direction: row;           /* Horizontal on desktop */
  gap: 16px;
  flex-wrap: wrap;
}

.featured-card {
  flex: 1 1 240px;               /* Grow/shrink, min 240px */
  min-height: 180px;
  border-radius: 4px;
}

/* Mobile: Stack vertically */
@media (max-width: 480px) {
  .featured-cards-row {
    flex-direction: column;       /* Stack vertically */
  }
  .featured-card {
    min-width: 0;
    flex: none;
  }
}
```

**Layout:** 3–4 cards per row on desktop; 1 stacked on mobile.

### Module Grid

```css
.module-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);  /* 3-column layout */
  gap: 12px;
}

.module-card {
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(var(--frame-rgb), 0.2);
  border-radius: 4px;
  padding: 16px;
  background: transparent;
  min-height: 160px;
  transition: all 0.3s ease;
}

.module-card:hover {
  border-color: rgba(var(--frame-rgb), 0.5);
  box-shadow: 0 0 20px rgba(var(--frame-rgb), 0.2);
}
```

**Cards:** 3 per row, grow to fill column, flexible height.

### Category Grid

```css
.category-grid {
  display: flex;
  flex-direction: column;      /* Stack categories vertically */
  gap: 24px;
  margin-top: 16px;
}

.category-frame {
  --frame-color: [category-specific color];
  --frame-rgb: [category RGB triplet];
}
```

**Layout:** Vertical stacking; each category is a full-width frame.

---

## Component Styling

### Module Cards (featured and standard)

**Structure:**
- Anchor tag with flex-column layout
- 48×48px icon in top-left
- Title (bold, uppercase)
- Category badge (small colored label)
- Status indicators (optional "coming soon", "external" badges)
- Flex spacer (pushes footer down)
- Footer (optional metadata)

**Styling:**

```css
.module-card, .featured-card {
  border: 1px solid rgba(var(--frame-rgb), 0.2);
  border-radius: 4px;
  padding: 16px;
  background: transparent;
  transition: all 0.3s ease;
}

.module-card:hover {
  border-color: rgba(var(--frame-rgb), 0.5);
  box-shadow: 0 0 20px rgba(var(--frame-rgb), 0.2);
  filter: brightness(1.05);
}

/* External product cards (gold accent) */
.module-card.external-product {
  border-color: rgba(251, 191, 36, 0.4);
}

.module-card.external-product:hover {
  border-color: rgba(251, 191, 36, 0.8);
  box-shadow: 0 0 20px rgba(251, 191, 36, 0.15);
}

/* Coming soon (disabled) */
.module-card.coming-soon {
  opacity: 0.5;
  pointer-events: none;
}
```

### Category Section Header

```css
.category-frame .lcars-bar {
  background: var(--frame-color);
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  border-radius: 0 20px 20px 0;
}

.lcars-bar-title {
  font-family: 'Antonio';
  font-size: 0.85rem;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #010409;           /* Dark text on colored background */
}

.cat-module-count {
  margin-left: auto;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.7rem;
  background: rgba(0, 0, 0, 0.15);
}

.cat-chevron {
  transform: rotate(0deg);
  transition: transform 0.3s ease;
}

.category-frame.lcars-frame--collapsed .cat-chevron {
  transform: rotate(-90deg);
}
```

---

## Command Bar

The sticky top bar with search, language, and user menu.

### Structure

```
.command-bar-frame (sticky top: 0, z-index: 100)
  ├── .lcars-frame (green accent frame)
  │   ├── .lcars-sidebar (green segments)
  │   └── .lcars-content
  │       ├── .lcars-bar (header with pips)
  │       └── .lcars-body
  │           ├── .cb-zone-left (logo)
  │           ├── .cb-zone-center (search)
  │           └── .cb-zone-right (language, user, logout)
```

### Zones

**Left Zone:**
- Logo or branding element

**Center Zone:**
- Search input with magnifying glass icon
- `flex: 1` to grow and fill space
- Placeholder text: "Search..." (i18n)

**Right Zone:**
- Language selector (dropdown on click)
- Username + profile badge
- Logout button (red accent, `data-accent="red"`)

### Responsive Behavior

| Breakpoint | Changes |
|-----------|---------|
| **Desktop** | All elements visible, full spacing |
| **≤ 717px** | Hide username/badge, compress zones |
| **≤ 480px** | Hide search hint, reduce font sizes, minimal padding |

---

## HUD Vitals Frame

Admin-only system status display with segmented bars and status indicators.

### Structure

```
.hud-frame (cyan accent)
  ├── .lcars-frame
  │   ├── .lcars-sidebar (cyan & green segments)
  │   └── .lcars-content
  │       ├── .lcars-bar ("SYSTEM STATUS" title)
  │       └── .lcars-body
  │           ├── .hud-row (bar readout)
  │           ├── .hud-divider (gradient line)
  │           └── .hud-status-row (status readout)
```

### Bar Readouts

Rows with labels, segmented progress bars, and numeric values:

```html
<div class="hud-row">
  <div class="hud-row-label">POWER</div>
  <div class="hud-bar">
    <div class="hud-seg lit"></div>
    <div class="hud-seg lit"></div>
    <div class="hud-seg lit"></div>
    <!-- ... 7–10 segments total -->
  </div>
  <div class="hud-row-value">87%</div>
  <div class="hud-row-sub">125.3 W</div>
</div>
```

**Styling:**
- Label width: `80px` (smaller on mobile: `65px`)
- Bar: `flex: 1`, gap `3px` between segments
- Segment height: `18px`
- Value: `14px`, `font-family: 'Orbitron'`, monospace, right-aligned
- Sub-detail: `10px`, dimmed color

### Status Readouts

Rows with animated status dots, labels, and values:

```html
<div class="hud-status-row">
  <div class="hud-status-dot online"></div>
  <div class="hud-status-label">AGENTS</div>
  <div class="hud-status-value">42</div>
  <div class="hud-status-extra">+3 new</div>
</div>
```

**Styling:**
- Status dot: `10×10px`, `border-radius: 50%`, animates on online
- Label: `11px`, `Antonio`, `0.15em` letter-spacing, right-aligned
- Value: `12px`, `Orbitron`, bold color

### Animations

**Status dot (online):**
```css
.hud-status-dot.online {
  animation: lcarsPulseGreen 3s ease-in-out infinite;
}

@keyframes lcarsPulseGreen {
  0%, 100% {
    opacity: 0.6;
    box-shadow: 0 0 4px rgba(0, 255, 65, 0.2);
  }
  50% {
    opacity: 1;
    box-shadow: 0 0 10px rgba(0, 255, 65, 0.8);
  }
}
```

---

## Briefing Frame

Collapsible sections for activity and alerts.

### Structure

```
.briefing-frame (green accent)
  ├── .lcars-frame
  │   └── .lcars-content
  │       ├── .lcars-bar ("RECENT ACTIVITY" / "SYSTEM ALERTS")
  │       └── .lcars-body
  │           └── .briefing-sections
  │               ├── .briefing-section (activity section)
  │               └── .briefing-section (alerts section)
```

### Collapsible Sections

```html
<div class="briefing-section is-open">
  <div class="briefing-section-header">
    <svg class="briefing-section-chevron"><!-- chevron --></svg>
    <span>RECENT ACTIVITY</span>
    <span class="briefing-badge">3</span>
  </div>
  <div class="briefing-section-body">
    <!-- activity items -->
  </div>
</div>
```

**Header Styling:**
- `border-left: 4px solid var(--col-accent)` (green for activity, orange for alerts)
- `padding: 8px 12px`
- `background: rgba(255, 255, 255, 0.03)` (hover: `0.06`)
- `font-family: 'Antonio'`, `0.72rem`, uppercase
- Chevron: `14×14px`, rotates `90deg` when open

---

## Responsive Design

### Breakpoints

#### Mobile (≤480px)

- Featured cards: **stack vertically** (flex-direction: column)
- Command bar: reduced padding/gap, hide search hint
- HUD labels: width `65px` (vs. `80px`), font `10px` (vs. `11px`)
- HUD values: font `12px` (vs. `14px`)
- Module grid: may compress to 2 columns or stack

#### Tablet (≤717px)

- Command bar: compress zones, hide username/badge
- HUD: tighten spacing slightly
- Featured cards: remain horizontal
- Category grid: maintain 3-column module layout

#### Desktop (>1200px)

- Full layout with maximum spacing
- All elements visible
- 3-column module grids
- Featured cards in 3–4 column row

### Media Query Examples

```css
/* Tablet: 717px and below */
@media (max-width: 717px) {
  .cb-zone-center { flex: 1 1 0; min-width: 0; }
  .cb-username, .cb-badge { display: none; }
  .hud-row-label { width: 65px; font-size: 10px; }
  .hud-row-value { font-size: 12px; width: 44px; }
}

/* Mobile: 480px and below */
@media (max-width: 480px) {
  .featured-cards-row { flex-direction: column; }
  .featured-card { min-width: 0; flex: none; }
  .cb-search-hint { display: none; }
}
```

---

## Animations

### lcarsPulseGreen (Status Dot)

```css
@keyframes lcarsPulseGreen {
  0%, 100% {
    opacity: 0.6;
    box-shadow: 0 0 4px rgba(0, 255, 65, 0.2);
  }
  50% {
    opacity: 1;
    box-shadow: 0 0 10px rgba(0, 255, 65, 0.8);
  }
}

/* Duration: 3s, Timing: ease-in-out, Infinite loop */
```

### lcarsCardIn (Card Entry)

```css
@keyframes lcarsCardIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Duration: 0.3s, Timing: ease-out */
```

### slideIn (Notification Entry)

```css
@keyframes slideIn {
  from {
    transform: translateX(400px);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

/* Duration: 0.3s, Timing: ease */
```

### scanDown (Boot Overlay)

```css
@keyframes scanDown {
  0% { top: 0; opacity: 0.8; }
  100% { top: 100%; opacity: 0; }
}

/* Duration: 2s, Timing: linear, Infinite loop */
```

### lcarsFieldIn (Input Focus)

```css
@keyframes lcarsFieldIn {
  from {
    opacity: 0;
    transform: scaleX(0.95);
  }
  to {
    opacity: 1;
    transform: scaleX(1);
  }
}

/* Duration: 0.3s, Timing: ease-out both */
```

---

## CSS Variables

### Frame Variables

Used to control frame appearance dynamically:

```css
--frame-color:    Hex color (e.g., #00FF41)
--frame-rgb:      RGB triplet for alpha blending (e.g., 0,255,65)
--frame-radius:   Border-radius for elbows (default: 20px)
```

### Segment Variables

```css
--seg-color:      Individual segment color override
```

### Category Variables

```css
--col-accent:     Category accent color
--col-accent-rgb: RGB triplet for category accent
```

### Global Archie Variables

```css
--archie-green:        #00FF41
--archie-cyan:         #00FFFF
--archie-orange:       #FFAA00
--archie-danger:       #FF3B3B
--archie-warning:      #FFAA00
--archie-success:      #00FF00
--archie-info:         #00FFFF

--archie-green-rgb:    0, 255, 65
--archie-cyan-rgb:     0, 255, 255
--archie-orange-rgb:   255, 170, 0

--archie-glow-green-sm:   0 0 8px rgba(0, 255, 65, 0.3)
--archie-glow-green-md:   0 0 15px rgba(0, 255, 65, 0.5)
--archie-glow-cyan:       0 0 8px rgba(0, 255, 255, 0.3)
--archie-glow-orange:     0 0 8px rgba(255, 170, 0, 0.3)

--archie-bg-primary:      #010409
--archie-bg-secondary:    #0d1117

--archie-font-mono:       'JetBrains Mono', monospace
--archie-radius-md:       6px
```

---

## Design Principles

1. **UPPERCASE TEXT EVERYWHERE:** All UI text is uppercase for authenticity and futuristic appeal.

2. **LETTER-SPACING:** 0.5–2px letter-spacing on headings creates the distinctive LCARS typography.

3. **NEON GLOWS:** Box-shadows with semi-transparent accent colors (20–30% opacity) simulate neon lighting.

4. **MONOSPACE NUMBERS:** Use `Orbitron` or monospace fonts for numeric readouts and HUD values to emphasize technical data.

5. **DARK THEME:** `#010409` primary background with dark gray (`#0d1117`) secondary; minimal color saturation.

6. **COLORED ACCENTS:** Each section/category has a unique accent color for visual hierarchy and quick scanning.

7. **ROUNDED CORNERS:** Subtle 4–8px border-radius on cards, large 20px on frame elbows to maintain LCARS shape.

8. **SEGMENTED INDICATORS:** The sidebar segments show status at a glance; lit segments are brighter, unlit are dimmed.

9. **FLEX LAYOUT:** Flexbox and CSS Grid enable responsive, fluid composition without fixed pixel widths.

10. **HOVER EFFECTS:** Borders brighten, glows intensify on interaction; all transitions are 0.3s ease.

11. **ANIMATION RESTRAINT:** Only status dots and notifications animate; subtle, not distracting—no more than 3s loops.

12. **ACCESSIBILITY:** Sufficient contrast, semantic HTML, focus states on interactive elements.

---

## File References

- **HTML Template:** `/platform_v2/templates/dashboard_dynamic.html`
- **Dashboard CSS:** `/platform_v2/static/css/dashboard.css`
- **Base CSS:** `/platform_v2/static/css/base.css`
- **LCARS Panels CSS:** `/platform_v2/static/css/lcars-panels.css`
- **LCARS Frames CSS:** `/platform_v2/static/css/lcars-frames.css`

---

## Usage Examples

### Creating a New Category Frame

```html
<div class="category-frame lcars-frame category-frame--my_category" style="--frame-color: #AB00FF; --frame-rgb: 171,0,255">
  <div class="lcars-sidebar">
    <div class="lcars-elbow-top"></div>
    <div class="lcars-seg" style="--seg-color: #AB00FF"></div>
    <div class="lcars-seg-fill"></div>
    <div class="lcars-elbow-bottom"></div>
  </div>
  <div class="lcars-content">
    <div class="lcars-bar">
      <span class="lcars-bar-title">MY CATEGORY</span>
      <div class="lcars-bar-spacer"></div>
      <div class="lcars-pips">
        <span class="lcars-pip"></span>
        <span class="lcars-pip"></span>
      </div>
    </div>
    <div class="lcars-body">
      <div class="module-grid">
        <!-- module cards here -->
      </div>
    </div>
  </div>
</div>
```

### Creating a Module Card

```html
<a href="/module-link" class="module-card">
  <img src="/icon.svg" class="module-card-icon" />
  <div class="module-card-name">Module Title</div>
  <div class="module-card-category">Category</div>
  <div class="flex-spacer"></div>
  <div class="module-card-footer">v1.2.0</div>
</a>
```

### Styling a Custom Frame

```css
.my-custom-frame {
  --frame-color: #AB00FF;
  --frame-rgb: 171, 0, 255;
  --frame-radius: 24px;  /* Optional: larger elbows */
}
```

---

## Maintenance & Future Expansion

- **Color Palette:** Add new category colors via `.category-frame--[name] { --frame-color: ... }`
- **Typography:** Adjust font sizes in `dashboard.css` or base styles; all use rem units for scalability.
- **Animations:** Add new keyframes in dashboard.css; keep durations ≤ 3s for performance.
- **Responsive:** Update breakpoints in `@media` queries; test on real devices.
- **Accessibility:** Maintain WCAG 2.1 AA contrast ratios; test with screen readers.
