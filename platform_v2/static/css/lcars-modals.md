# LCARS Modal System -- Platform Design Standard

## Overview

The LCARS tablet modal system provides a sci-fi themed modal dialog
used throughout the A.R.C.H.I.E. platform. Originally built for
Starbase Command, this is now the standard modal pattern for all modules.

The modal resembles a handheld LCARS tablet device: a dark shell with
a left-side decorative frame (elbows, segments, status lights) and a
content area with header, body, and footer strips.

---

## HTML Structure

```html
<div class="bm-overlay" id="my-modal"
     style="--bm-accent:#00ffff; --bm-accent-rgb:0,255,255;">
    <div class="bm-shell" style="max-width:500px;">

        <!-- Left decorative frame -->
        <div class="bm-frame">
            <div class="bm-frame-elbow-top"></div>
            <div class="bm-frame-seg"></div>
            <div class="bm-frame-seg dim"></div>
            <div class="bm-frame-light on"></div>
            <div class="bm-frame-light amber"></div>
            <div class="bm-frame-seg cyan"></div>
            <div class="bm-frame-fill"></div>
            <div class="bm-frame-elbow-bottom"></div>
        </div>

        <!-- Main content area -->
        <div class="bm-content">

            <!-- Header bar with title, pips, close button -->
            <div class="bm-header">
                <span class="bm-header-title">MODAL TITLE</span>
                <div class="bm-header-strip">
                    <span class="bm-header-pip w1"></span>
                    <span class="bm-header-pip w2"></span>
                    <span class="bm-header-pip w3"></span>
                    <button class="bm-close" onclick="closeMyModal()">&times;</button>
                </div>
            </div>

            <!-- Scrollable body -->
            <div class="bm-body">
                <!-- Your form fields, text, or content here -->
            </div>

            <!-- Action buttons (optional) -->
            <div class="bm-actions">
                <button class="btn-cancel" onclick="closeMyModal()">Cancel</button>
                <button class="btn-submit" onclick="submitMyModal()">Confirm</button>
            </div>

            <!-- Footer strip with decorative dots -->
            <div class="bm-footer">
                <div class="bm-footer-strip">
                    <span class="bm-footer-dot cyan"></span>
                    <span class="bm-footer-dot gold"></span>
                    <span class="bm-footer-dot green"></span>
                </div>
            </div>

        </div>
    </div>
</div>
```

---

## CSS Classes

### Container

| Class | Purpose |
|-------|---------|
| `.bm-overlay` | Full-screen fixed backdrop (`rgba(0,0,0,0.8)`). Hidden by default; add `.active` to show. Centers the shell with flexbox. |
| `.bm-shell` | The tablet device body. Dark background (`#06060c`), rounded corners (24px), max-width configurable via inline style. Contains frame + content side by side. |

### Left Frame (Decorative)

| Class | Purpose |
|-------|---------|
| `.bm-frame` | 48px-wide vertical strip on the left. Flex column layout. |
| `.bm-frame-elbow-top` | Top corner piece (52px tall). Uses `--bm-accent` color with a rounded top-left corner (20px radius). Has a `::after` pseudo-element for the inner cutout. |
| `.bm-frame-elbow-bottom` | Bottom corner piece (36px tall). Mirrors top elbow with bottom-left radius. |
| `.bm-frame-seg` | Horizontal segment bars (28px tall). Accepts color modifiers: `.dim` (0.6 opacity), `.dimmer` (0.3 opacity), `.amber`, `.cyan`, `.green`, `.red`, `.purple`. |
| `.bm-frame-light` | Small circular indicator (10px). Pulses via `bmLightPulse` animation. Variants: `.on` (green), `.amber`, `.cyan`. Each has a glow box-shadow and staggered animation delay. |
| `.bm-frame-fill` | Flexible spacer that fills remaining height. Uses accent color at 25% opacity. |

### Content Area

| Class | Purpose |
|-------|---------|
| `.bm-content` | Right side of the shell. Flex column, fills remaining width. |
| `.bm-header` | Top bar with title and strip. Flex row, min-height 42px. |
| `.bm-header-title` | Title text. Antonio font, uppercase, letter-spaced. Accent-colored background at 25% opacity. |
| `.bm-header-strip` | Flexible strip next to title. Contains decorative pips and close button. |
| `.bm-header-pip` | Small decorative bars inside the header strip. Three widths: `.w1` (20px, accent), `.w2` (35px, amber), `.w3` (14px, cyan). |
| `.bm-close` | Close button. Semi-transparent accent background with border. Glows on hover. |
| `.bm-body` | Scrollable content area. Padding 20px 24px. Antonio font for labels, IBM Plex Mono for code. Custom thin scrollbar styled with accent color. Auto-styles form inputs (text, number, password, select, textarea) with accent-tinted borders and backgrounds. |
| `.bm-actions` | Button row (not part of the bm- prefix but used inside bm-content). Contains cancel/submit/delete buttons. |
| `.bm-footer` | Bottom decorative bar (14px min-height). |
| `.bm-footer-strip` | Rounded strip with decorative dots. |
| `.bm-footer-dot` | Small circles (6px). Color variants: `.cyan`, `.gold`, `.green`, `.purple`, `.red`. |

---

## Theming

Set `--bm-accent` (hex color) and `--bm-accent-rgb` (comma-separated RGB values)
on the `.bm-overlay` element for per-module theming:

| Module | Accent | Hex | RGB |
|--------|--------|-----|-----|
| Starbase Command | Cyan | `#00ffff` | `0,255,255` |
| Department HQ | Purple | `#8b5cf6` | `139,92,246` |
| Autonomy | Emerald | `#10b981` | `16,185,129` |
| Consciousness | Purple | `#8b5cf6` | `139,92,246` |
| Security Network | Red | `#ef4444` | `239,68,68` |
| Media Studio | Pink | `#f472b6` | `244,114,182` |
| Dev HQ | Blue | `#3b82f6` | `59,130,246` |

Both variables are required. `--bm-accent` is used for solid colors
(elbows, segments, borders). `--bm-accent-rgb` is used inside `rgba()`
for translucent fills, glows, and scrollbar styling.

---

## Opening and Closing

```javascript
// Open
function openMyModal() {
    document.getElementById('my-modal').classList.add('active');
}

// Close
function closeMyModal() {
    document.getElementById('my-modal').classList.remove('active');
}
```

The `.bm-overlay` is `display: none` by default. Adding `.active` sets
it to `display: flex`, centering the shell on screen.

---

## Wider Modals

For modals that need more horizontal space (e.g., node detail panels),
add a modifier class to `.bm-shell`:

```css
.bm-shell.node-detail-modal {
    width: 800px;
    max-width: 95vw;
}
```

Or use an inline `max-width` style on `.bm-shell`.

---

## Responsive Behavior

At `max-width: 768px` the system automatically adjusts:

- Shell: 95% width, 90vh max-height, 16px border-radius
- Frame: 32px wide (down from 48px)
- Elbows: smaller radii (14px)
- Segments: 20px tall (down from 28px)
- Header: 36px min-height, smaller title font
- Header pip `.w2`: hidden
- Body padding: 16px (down from 20px 24px)

---

## Form Inputs Inside `.bm-body`

All standard form elements are automatically styled when placed inside
`.bm-body`:

- Labels: Antonio font, uppercase, letter-spaced, accent-colored
- Inputs/selects/textareas: Dark translucent background, accent-tinted
  border, white text, rounded corners (6px)
- Focus state: Accent border glow with `box-shadow`

No additional classes needed -- just use standard HTML form elements.

---

## Light Mode

The modal retains its dark appearance even in light mode themes.
`.bm-shell` stays `#0a0a14` and form inputs keep white text on dark
backgrounds. This is intentional -- the LCARS tablet aesthetic is
inherently dark.

---

## Reference Implementation

- **CSS**: `static/css/starbase.css` lines 4808-5121
- **HTML**: `tools/starbase/templates/starbase.html` lines 1011-1084 (Station Assignment Modal)
- **Pattern origin**: Starbase Command module (ADR-045 route splitting)
- **CLAUDE.md reference**: "LCARS Modals -> bm- Classes" in project root CLAUDE.md

---

## Checklist for Adding a New Modal

1. Copy the HTML structure above into your template
2. Set `--bm-accent` and `--bm-accent-rgb` to your module's color
3. Give the overlay a unique `id`
4. Write open/close functions that toggle `.active` on the overlay
5. Place form content inside `.bm-body` -- inputs auto-style
6. Add action buttons inside `.bm-actions`
7. Test at 768px breakpoint for responsive behavior
