# Theme Layout Families — Design Document

**Date:** 2026-02-28
**Status:** Approved
**Author:** Kytran + Claude
**Depends on:** SaaS Theme System (ADR-068, complete)

---

## Problem

The current theme system only swaps colors and fonts — all 8 themes render with the same LCARS structural layout (pill shapes, sidebar segments, glow borders). SaaS customers need visual layouts that match their chosen theme's identity, not just recolored LCARS.

## Decision

**Approach A: Theme-Dispatching Jinja2 Macros** — group 8 themes into 4 layout families. Each family provides its own Jinja2 macro file that renders the same data with different HTML structure. A dispatcher macro file auto-imports the correct family based on the user's theme. Modules call theme-agnostic macros and never know which family is active.

## Layout Families (4)

| Family | Themes | Visual Identity |
|--------|--------|----------------|
| **LCARS** | `lcars-classic` | Pill shapes, sidebar segments, glow borders, scanlines, asymmetric radius, footer bars |
| **Corporate** | `corporate-blue`, `slate-pro` | Clean rectangles, subtle box-shadows, standard nav with underline active, no accent bars |
| **Minimal** | `warm-minimal`, `arctic-light` | Maximum whitespace, hairline borders, no frames, flat cards, text-only tabs |
| **Elegant** | `midnight-purple`, `rose-gold`, `forest` | Floating rounded cards, gradient accents, glass effects, decorative borders |

## Theme-to-Family Mapping

```python
THEME_TO_FAMILY = {
    'lcars-classic': 'lcars',
    'corporate-blue': 'corporate',
    'slate-pro': 'corporate',
    'warm-minimal': 'minimal',
    'arctic-light': 'minimal',
    'midnight-purple': 'elegant',
    'rose-gold': 'elegant',
    'forest': 'elegant',
}
```

## Architecture

### Macro Dispatcher

`theme_macros.html` imports the correct family based on `layout_family` from context processor:

```jinja2
{% if layout_family == 'corporate' %}
  {% from 'layouts/corporate.html' import page_header, stat_card,
     tab_nav, panel, data_table, card_grid, filter_bar, modal %}
{% elif layout_family == 'minimal' %}
  {% from 'layouts/minimal.html' import page_header, stat_card,
     tab_nav, panel, data_table, card_grid, filter_bar, modal %}
{% elif layout_family == 'elegant' %}
  {% from 'layouts/elegant.html' import page_header, stat_card,
     tab_nav, panel, data_table, card_grid, filter_bar, modal %}
{% else %}
  {% from 'layouts/lcars.html' import page_header, stat_card,
     tab_nav, panel, data_table, card_grid, filter_bar, modal %}
{% endif %}
```

### Module Usage

Modules become data-driven — they describe *what* to show, families decide *how*:

```jinja2
{% from 'theme_macros.html' import page_header, stat_card,
   tab_nav, panel, filter_bar, data_table, modal %}

{{ page_header('CUSTOMER RELATIONS', subtitle='Management System') }}

<div class="stat-grid">
  {{ stat_card(icon='users', value=stats.total, label='Total', variant='default') }}
  {{ stat_card(icon='crown', value=stats.subs, label='Subscribers', variant='success') }}
</div>

{{ tab_nav(tabs=[
  {id: 'customers', icon: 'users', label: 'Customers'},
  {id: 'segments', icon: 'layers', label: 'Segments'}
]) }}

{% call panel(title='All Customers', icon='users') %}
  {{ filter_bar(search='Search customers...', filters=[...]) }}
  {{ data_table(headers=['Name','Email','Status'], rows=customers) }}
{% endcall %}
```

### Context Processor

`app.py` maps theme → family and injects both into templates:

```python
THEME_TO_FAMILY = { ... }

@app.context_processor
def inject_theme_context():
    # existing theme resolution (user → org → fallback)
    layout_family = THEME_TO_FAMILY.get(theme_name, 'lcars')
    return {
        'theme_name': theme_name,
        'layout_family': layout_family,
        'is_admin_module': is_admin_module,
    }
```

## 8 Core Macros (Uniform Signatures)

All 4 families export these macros with identical signatures:

### 1. `page_header(title, subtitle='', actions='')`
- LCARS: Glow bar, scanline overlay, Orbitron font
- Corporate: Clean h1, subtle bottom border, Inter font
- Minimal: Large bold text, no decoration
- Elegant: Gradient underline, slight text shadow

### 2. `stat_card(icon, value, label, variant='default')`
- LCARS: Centered icon with neon glow, large value, scanline
- Corporate: Horizontal layout (icon left, value right), subtle shadow
- Minimal: Large centered number, small label, no icon container
- Elegant: Centered with gradient background, decorative top border

Variants: `default`, `success`, `warning`, `info`, `danger`

### 3. `tab_nav(tabs)`
Each tab: `{id, icon, label, badge_count?}`
- LCARS: Bubble groups, terminal-block icon buttons
- Corporate: Horizontal with underline active indicator
- Minimal: Text-only, underline active, no icons
- Elegant: Pill-shaped buttons with hover fill

### 4. `panel(title, icon='', compact=False)` (callable)
- LCARS: Frame with 48px sidebar, colored segments, elbow corners
- Corporate: Header bar with bottom border, clean body
- Minimal: Bold text label + thin separator, no visible chrome
- Elegant: Gradient header bar, rounded body with glass effect

### 5. `data_table(headers, rows, row_id_field='id')` (callable)
- LCARS: Dark table with glow row hover, accent header
- Corporate: Clean alternating rows, subtle borders
- Minimal: Borderless with wide spacing, hairline separators
- Elegant: Rounded container, hover glow, no visible header border

### 6. `card_grid(items, empty_message='')` (callable)
- LCARS: Asymmetric pill cards with left accent bar
- Corporate: Rectangle cards with subtle shadow
- Minimal: Hairline border cards with generous padding
- Elegant: Floating rounded cards with gradient border

### 7. `filter_bar(search='', filters=[])`
Each filter: `{id, type, placeholder?, options?}`
- LCARS: Inline group with glow inputs
- Corporate: Row grid with form-control inputs
- Minimal: Simple inline with thin borders
- Elegant: Rounded inputs with accent focus ring

### 8. `modal(modal_id, title, icon='', size='medium')` (callable)
- LCARS: Tablet style — left frame sidebar with segments
- Corporate: Standard centered dialog, rounded, subtle shadow
- Minimal: Slim dialog, lots of whitespace
- Elegant: Glass morphism backdrop, gradient header strip

## CSS Architecture

### Separation: Layout CSS vs Theme CSS

```
platform_v2/static/css/
  layouts/                    ← NEW: structural styles per family
    corporate-layout.css
    minimal-layout.css
    elegant-layout.css
  themes/                     ← EXISTING: color-only overrides
    corporate-blue.css
    slate-pro.css
    midnight-purple.css
    ...
```

LCARS layout uses existing `theme.css` + `lcars-frames.css` + `lcars-panels.css` — no new file needed.

### Loading Order (base.html)

```html
<!-- 1. Base theme variables (always) -->
<link rel="stylesheet" href="/static/css/theme.css">

<!-- 2. Layout family CSS (structural) -->
{% if layout_family != 'lcars' and not is_admin_module %}
<link rel="stylesheet" href="/static/css/layouts/{{ layout_family }}-layout.css">
{% endif %}

<!-- 3. Theme color CSS (palette) -->
{% if theme_name != 'lcars-classic' and not is_admin_module %}
<link rel="stylesheet" href="/static/css/themes/{{ theme_name }}.css">
{% endif %}

<!-- 4. Light mode (layers on top of anything) -->
<link rel="stylesheet" href="/static/css/light-mode.css">
```

### What Goes Where

| Layout CSS (structural) | Theme CSS (colors) |
|---|---|
| `border-radius` values | `--archie-accent` color |
| `padding` / `margin` / `gap` | `--archie-bg-primary` |
| `box-shadow` shape (spread, blur) | Shadow color values |
| `display` / `flex-direction` | `--archie-text-primary` |
| `backdrop-filter` presence | Glow colors |
| Font stack (`Inter` vs `Orbitron`) | Font colors |
| Element visibility (scanlines on/off) | Border colors |

## Family Visual Details

### LCARS
- Cards: `border-radius: 0 12px 12px 0`, 3px left accent bar with gradient, glow borders
- Panels: 48px sidebar, colored segments, elbow corners, footer bar
- Nav: Bubble groups, icon buttons with left accent bars
- Stat cards: Centered icons with neon glow, scanline overlay
- Modals: Tablet with left frame sidebar + indicator lights

### Corporate
- Cards: `border-radius: 8px`, `box-shadow: 0 1px 3px`, no accent bars
- Panels: Simple header bar + bottom border, no sidebar
- Nav: Horizontal with underline active indicator
- Stat cards: Horizontal layout (icon left, value right), `display: flex`
- Modals: Centered dialog, rounded corners, subtle shadow

### Minimal
- Cards: `border-radius: 4px`, hairline 1px border, 24px padding
- Panels: Bold text label + thin separator, no visible header bar
- Nav: Text-only tabs, underline active state
- Stat cards: Large centered number, small label, no icon container
- Modals: Slim dialog, maximum whitespace

### Elegant
- Cards: `border-radius: 16px`, `box-shadow: 0 8px 32px`, `backdrop-filter: blur(8px)`, gradient border
- Panels: Gradient header (left-to-right), rounded body with glass effect
- Nav: Pill-shaped buttons with hover fill, smooth transitions
- Stat cards: Centered with gradient background, decorative 3px top border
- Modals: Glass morphism backdrop, gradient header strip

## Migration Strategy

### Phase 1: Build Foundation (no module changes)
1. Create 4 macro files + dispatcher
2. Create 3 layout CSS files
3. Extract LCARS patterns into `lcars.html` macros
4. Add `layout_family` to context processor
5. Add layout CSS loading to `base.html`

Everything works exactly as before after Phase 1 — no visual changes.

### Phase 2: Migrate Modules (one at a time)

| Order | Module | Complexity | Notes |
|-------|--------|-----------|-------|
| 1 | HR Management | Low | Inline CSS, simple structure, good pilot |
| 2 | Scheduler | Low | Clean tabs + calendar (FullCalendar untouched) |
| 3 | Invoicing | Low | Already uses Bootstrap patterns |
| 4 | CRM | Medium | 4 tabs, stat cards, tables — covers most macros |
| 5 | Email Manager | Medium | 5 tabs, SMTP banner stays as-is |
| 6 | Store Manager | Medium | Product cards + grid |
| 7 | SaaS Manager | Medium | Settings panels |
| 8 | Training System | Medium | Course cards + progress |
| 9 | Autonomy | Medium | Dashboard-style panels |
| 10 | Dashboard | High | 5,200 lines, heavy JS — partial macro adoption |

Each migration: extract → wrap in macros → test LCARS → test other families → commit.

### What Stays Untouched
- Admin modules (Bridge, Consciousness, Dev HQ, Account Center, System Ops, Security, Backup) — always LCARS
- Module-specific JS — macros only change HTML, JS binds by ID
- Module-specific one-offs (FullCalendar, SMTP banner) — outside macro system

## File Map

### New Files (8)

```
# Macro system (5)
platform_v2/templates/theme_macros.html
platform_v2/templates/layouts/lcars.html
platform_v2/templates/layouts/corporate.html
platform_v2/templates/layouts/minimal.html
platform_v2/templates/layouts/elegant.html

# Layout CSS (3)
platform_v2/static/css/layouts/corporate-layout.css
platform_v2/static/css/layouts/minimal-layout.css
platform_v2/static/css/layouts/elegant-layout.css
```

### Modified Files (12)

```
# Foundation (2)
platform_v2/app.py                              — THEME_TO_FAMILY + layout_family context
platform_v2/templates/base.html                 — layout CSS conditional loading

# Module migrations (10 — Phase 2, one per commit)
platform_v2/templates/tools/hr.html
platform_v2/templates/tools/scheduler.html
platform_v2/templates/tools/invoicing.html
platform_v2/templates/tools/crm.html
platform_v2/templates/tools/email_manager.html
platform_v2/templates/tools/store_manager.html
platform_v2/templates/tools/saas_manager.html
platform_v2/templates/tools/training_system.html
platform_v2/templates/tools/autonomy.html
platform_v2/templates/tools/dashboard_dynamic.html
```

### Untouched (admin — always LCARS)

```
platform_v2/templates/tools/bridge.html
platform_v2/templates/tools/consciousness.html
platform_v2/templates/tools/dev_hq.html
platform_v2/templates/tools/account_center.html
platform_v2/templates/tools/system_operations.html
platform_v2/templates/tools/security_network.html
platform_v2/templates/tools/backup_manager.html
```

## What Does NOT Change

- Existing color theme CSS files (`themes/*.css`) — unchanged
- `theme.css` (LCARS base variables) — unchanged
- `lcars-frames.css` / `lcars-panels.css` — unchanged (LCARS family references them)
- `light-mode.css` — unchanged (layers on top)
- Admin module templates — never see layout families
- Theme resolution logic (user → org → fallback) — unchanged
- My Profile theme selector — unchanged
- Account Center org default dropdown — unchanged
