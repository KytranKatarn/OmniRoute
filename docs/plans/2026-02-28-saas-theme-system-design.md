# SaaS Theme System — Design Document

**Date:** 2026-02-28
**Status:** Approved
**Author:** Kytran + Claude

---

## Problem

All A.R.C.H.I.E. modules use the same LCARS sci-fi aesthetic. SaaS customers running business tools (CRM, Invoicing, Scheduler, etc.) need visual options that match their brand or preference. Admin tools should stay LCARS.

## Decision

**Approach A: CSS Variable Theme Sheets** — each theme is a standalone CSS file overriding `:root` variables plus a `body.theme-*` class for structural style changes.

## Theme Scope

| Category | Themed? | Reason |
|----------|---------|--------|
| SaaS Services (9 modules) | Yes | Customer-facing business tools |
| Dashboard | Yes | User's home page |
| Admin Operations | No | LCARS always — internal admin |
| AI Command | No | LCARS always — internal admin |
| Development Tools | No | LCARS always — internal admin |
| Consciousness | No | LCARS always — core identity |

## Themes (8 total)

| # | ID | Name | Style | Accent | Font |
|---|-----|------|-------|--------|------|
| 1 | `lcars-classic` | LCARS Classic | Sci-fi LCARS | `#00ff41` green | Orbitron/Antonio |
| 2 | `corporate-blue` | Corporate Blue | Clean, professional | `#3b82f6` | Inter |
| 3 | `midnight-purple` | Midnight Purple | Modern dark | `#8b5cf6` | Inter |
| 4 | `warm-minimal` | Warm Minimal | Soft, earthy | `#f59e0b` | Inter |
| 5 | `arctic-light` | Arctic Light | Bright, clinical | `#06b6d4` | Inter |
| 6 | `rose-gold` | Rose Gold | Elegant, warm | `#f43f5e` | Inter |
| 7 | `forest` | Forest | Natural, calm | `#22c55e` | Inter |
| 8 | `slate-pro` | Slate Pro | Neutral, business | `#64748b` | Inter |

## Architecture

### Theme File Pattern

Each theme file (~100-150 lines) in `static/css/themes/<id>.css`:

```css
body.theme-corporate-blue {
    /* Color overrides */
    --archie-text-primary: #e2e8f0;
    --archie-accent: #3b82f6;
    --archie-bg-primary: #0f172a;
    /* ~50 variable overrides */

    /* Structural overrides */
    --archie-radius-md: 8px;
    --archie-font-heading: 'Inter', sans-serif;
}
```

### Theme Resolution Order

1. User's `theme_preference` column (if set)
2. Organization's `default_theme` column (if user belongs to org)
3. Fallback: `lcars-classic`

### Database Changes

```sql
ALTER TABLE users ADD COLUMN theme_preference VARCHAR(50) DEFAULT 'lcars-classic';
ALTER TABLE organizations ADD COLUMN default_theme VARCHAR(50) DEFAULT 'lcars-classic';
```

### Template Loading (base.html)

```html
{% if theme_name != 'lcars-classic' and not is_admin_module %}
<link rel="stylesheet" href="/static/css/themes/{{ theme_name }}.css">
{% endif %}
<body class="theme-{{ theme_name }}">
```

Server-side: `app.py` resolves theme from user → org → default and injects `theme_name` + `is_admin_module` into template context.

### Admin Module Detection

`app.py` checks module category. If `ADMIN_OPERATIONS`, `AI_COMMAND`, or `DEVELOPMENT_TOOLS` → `is_admin_module = True` → theme CSS never loaded.

### Light/Dark Mode

Independent of themes. The existing `light-mode.css` layers on top of any theme. `archie-theme.js` toggle works unchanged.

## UI: Theme Selector

### My Profile — Appearance Section

Grid of 8 theme preview cards (4x2). Each card:
- Color swatch bars (3-4 bars showing accent, bg, text)
- Theme name
- Checkmark on active theme
- Hover: live preview (swap theme CSS instantly)
- Click: save via `PUT /api/user/theme`, applies immediately

### Account Center — Organization Tab

"Default Theme" dropdown for org admins. Sets fallback for all org users who haven't chosen their own.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/user/theme` | Returns resolved theme name |
| `PUT` | `/api/user/theme` | Sets user preference |

## New Files

- `static/css/themes/corporate-blue.css`
- `static/css/themes/midnight-purple.css`
- `static/css/themes/warm-minimal.css`
- `static/css/themes/arctic-light.css`
- `static/css/themes/rose-gold.css`
- `static/css/themes/forest.css`
- `static/css/themes/slate-pro.css`
- `database/migrations/XXX_user_theme_preference.sql`

## Modified Files

- `app.py` — theme resolution + `is_admin_module` context injection
- `templates/base.html` — conditional theme CSS + body class
- `templates/tools/user_profile.html` — Appearance section
- `templates/tools/account_center.html` — Default Theme in Org tab

## What Does NOT Change

- `static/css/theme.css` (stays as LCARS Classic base)
- `static/css/light-mode.css` (layers on any theme)
- `static/js/archie-theme.js` (light/dark toggle independent)
- Admin module templates (never see themes)
- All existing JS functionality
