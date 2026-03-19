# A.R.C.H.I.E. Responsive Design Standard

**Version**: 1.0 | **Date**: 2026-03-19 | **Status**: Active

---

## Breakpoints

| Token | Width | Device | CSS Variable |
|-------|-------|--------|--------------|
| `fold` | `max-width: 374px` | Samsung Fold5 front screen (360px logical) | `--bp-fold` |
| `phone` | `max-width: 480px` | Small phones, narrow portrait | `--bp-phone` |
| `tablet` | `max-width: 768px` | Fold5 unfolded (730px), iPad mini | `--bp-tablet` |
| `desktop` | `min-width: 1024px` | Laptops, monitors | `--bp-desktop` |

**Primary test device**: Samsung Galaxy Fold5
- Folded front screen: **360 x 748 px** (20:9)
- Unfolded inner screen: **730 x 652 px** (approx 6:5)
- Both orientations must be usable

### Breakpoint Usage (mobile-first discouraged)

ARCHIE uses **desktop-first** because the LCARS UI was designed for large screens.
Write base styles for desktop, then override downward:

```css
/* Desktop: base styles (no media query) */
.my-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.5rem; }

/* Tablet / Fold unfolded */
@media (max-width: 768px) {
    .my-grid { grid-template-columns: repeat(2, 1fr); gap: 1rem; }
}

/* Small phone */
@media (max-width: 480px) {
    .my-grid { grid-template-columns: 1fr; gap: 0.75rem; }
}

/* Fold front screen */
@media (max-width: 374px) {
    .my-grid { padding: 0.5rem; font-size: 0.85rem; }
}
```

---

## Layout Rules

### 1. Touch Targets
- Minimum **44x44 px** on `max-width: 768px`
- Minimum **48x48 px** on `(hover: none) and (pointer: coarse)` (pure touch devices)
- Already enforced globally in `static/css/mobile.css`

### 2. Tab Navigation
- Horizontal scroll (`overflow-x: auto`) below 768px — never wrap tabs
- Hide scrollbar with `-webkit-overflow-scrolling: touch` + `scrollbar-width: none`
- Pattern already in `mobile.css` section 2

### 3. Navigation
- Desktop: full sidebar/top nav
- Below 768px: hamburger toggle, slide-from-right drawer
- Pattern already in `mobile.css` section 3

### 4. Grid Layouts
| Breakpoint | Columns | Padding |
|------------|---------|---------|
| Desktop (1024px+) | 3-4 columns | 1.5-2rem |
| Tablet (768px) | 2 columns | 1rem |
| Phone (480px) | 1 column | 0.75rem |
| Fold (374px) | 1 column, reduced font | 0.5rem |

### 5. Typography Scaling
| Element | Desktop | Tablet | Phone/Fold |
|---------|---------|--------|------------|
| H1 (Orbitron) | 2rem | 1.5rem | 1.2rem |
| H2 | 1.5rem | 1.25rem | 1rem |
| Body | 1rem | 0.95rem | 0.85rem |
| Mono/code | 0.875rem | 0.8rem | 0.75rem |

### 6. LCARS Panels
- Station ops panels stack vertically below 768px
- Modal overlays (`bm-shell`) go full-width below 480px
- LCARS frame borders reduce thickness on mobile (2px -> 1px)

### 7. Images & Media
- Use `max-width: 100%` and `height: auto` on all images
- Limit `max-height: 50vh` for media in modals
- Agent avatars: 48px desktop, 36px tablet, 32px phone

---

## Shared CSS Files

| File | Purpose |
|------|---------|
| `static/css/mobile.css` | Global responsive overrides (touch targets, tabs, nav drawer) |
| `static/css/base.css` | Flash messages, profile modal (no media queries yet) |
| `static/css/station-ops.css` | Station panels — has own responsive rules |
| `static/css/lcars-panels.css` | LCARS frame components — has own media queries |

**All module CSS files** should handle their own content-specific breakpoints using
the standard breakpoint values above (374/480/768/1024).

---

## Testing Checklist

Before merging any UI change, verify on these viewports:

- [ ] **Desktop** 1920x1080 (Chrome DevTools)
- [ ] **Laptop** 1366x768
- [ ] **Tablet landscape** 1024x768 (iPad)
- [ ] **Fold5 unfolded** 730x652 (Chrome DevTools custom device)
- [ ] **Tablet portrait** 768x1024
- [ ] **Phone** 480x844 (Pixel 7)
- [ ] **Fold5 folded** 360x748 (Chrome DevTools custom device)
- [ ] **Small phone** 320x568 (iPhone SE)

### Chrome DevTools Custom Devices

Add these custom devices in DevTools > Settings > Devices:

| Name | Width | Height | DPR | UA |
|------|-------|--------|-----|-----|
| Fold5 Front | 360 | 748 | 3 | Mobile |
| Fold5 Inner | 730 | 652 | 3 | Mobile |

### Quick Smoke Test

1. Open page at full desktop width
2. Drag browser to ~768px — layout should adapt (2-col, scroll tabs)
3. Drag to ~480px — single column, hamburger nav visible
4. Drag to ~360px — still usable, no overflow, no clipped text

---

## Anti-Patterns (Do NOT Do)

- **Fixed pixel widths** on containers — use `max-width` + `width: 100%`
- **`display: none` on mobile** for important content — restructure instead
- **Viewport-height modals** without `max-height` — keyboard pushes content off screen
- **Horizontal scroll on body** — always caused by an element wider than viewport
- **`!important` in responsive rules** — specificity issues compound; fix the cascade instead
- **Separate mobile templates** — one template with responsive CSS, not `/mobile/page.html`

---

*Reference: `mobile.css` (global), MEMORY.md (Samsung Fold5 primary device), ADR-068/069 (theme system)*
