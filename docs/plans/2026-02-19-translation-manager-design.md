# Full Translation Manager — Design Document

**Date:** 2026-02-19
**Project:** Platform UI Overhaul (#94) — Linguistics Extension
**Status:** Approved

---

## Goal

Upgrade the Consciousness > Languages tab into a full translation management center with coverage tracking, side-by-side EN/FR browsing, smart source discovery, and one-click generation workflows. Also tag the dashboard (and future modules) comprehensively with `data-i18n` attributes covering all static HTML, JS-generated strings, and module registry data.

## Current State

- 20 English strings seeded, 20 French translations approved
- 18 `data-i18n` attributes on dashboard (boot, HUD pods, section headers, footer)
- ~75+ untranslated strings identified: ~15 static HTML, ~45 JS-generated, ~7 categories + ~34 module names + ~34 module descriptions
- Languages tab has 3 sub-tabs: Dashboard (basic stats), Review (table), Glossary (CRUD)
- Scan Templates button only finds `data-i18n` attributes in HTML files

## Architecture

### String Sources (4 types)

1. **HTML Templates** — `data-i18n` attributes, discovered by regex scanning `templates/` directory
2. **JS Strings** — hardcoded English in `<script>` blocks. Defined in a `TRANSLATION_KEYS` manifest inside `archie-i18n.js`. Referenced via `archieI18n.t('key', 'fallback')` calls.
3. **Module Registry** — module names + descriptions from `module_registry.py`. Keys: `module.{id}.name`, `module.{id}.desc`
4. **Category Names** — category display names from `module_registry.py`. Keys: `cat.{key}`

### Key Naming Convention

```
# HTML template strings (existing pattern)
boot.skip, hud.system, section.recent_activity, status.online, ...

# JS-generated strings (new)
js.boot.initializing, js.boot.database, js.boot.connected, ...
js.status.online, js.status.offline, js.status.checking, ...
js.time.seconds_ago, js.time.minutes_ago, js.time.hours_ago, js.time.days_ago
js.briefing.loading_activity, js.briefing.no_recent_activity, ...
js.briefing.all_nominal, js.briefing.unable_to_load, ...
js.insights.interactions_today, js.insights.active_agents, ...
js.pin.pin_to_stations, js.pin.unpin_from_stations, ...
js.footer.last_refreshed

# Module registry (new)
module.backup_manager.name, module.backup_manager.desc
module.crm.name, module.crm.desc
... (34 modules × 2 = 68 keys)

# Categories (new)
cat.admin_operations, cat.ai_command, cat.development_tools, ...
cat.saas_services, cat.project_knowledge, cat.media_home, cat.placeholders_future
```

### Translation Flow

```
Scan All Sources → Discover keys from HTML + JS manifest + module registry
        ↓
Seed Missing English → Create EN rows in translations table for new keys
        ↓
Generate French → Batch translate all EN keys missing FR via qwen3-coder-cpu
        ↓
Review & Approve → Admin reviews in side-by-side browser or bulk approves
        ↓
Live → archie-i18n.js applies translations on language switch
```

## UI Changes — Consciousness Languages Tab

### Sub-tab 1: Coverage Dashboard (upgrade)

**Stats cards** (6 total):
- Total Keys | Approved | Pending Review | Human Edited | Discovered | Missing

**Per-source coverage bars:**
```
Dashboard HTML    ████████████░░░░  20/32  (63%)
Module Names      ░░░░░░░░░░░░░░░░   0/34  (0%)
Module Descs      ░░░░░░░░░░░░░░░░   0/34  (0%)
Categories        ░░░░░░░░░░░░░░░░   0/7   (0%)
JS Strings        ░░░░░░░░░░░░░░░░   0/45  (0%)
```

**Action buttons:**
- "Scan All Sources" — discovers from all 4 sources
- "Seed Missing English" — auto-creates EN entries
- "Generate All French" — batch translates missing FR
- "Approve All Pending" — bulk approve

### Sub-tab 2: Side-by-Side Browser (new)

Table with columns: Key | English | French | Status | Source
- Filter by: source type, status (all/missing/pending/approved), text search
- Inline edit French column
- Per-row approve/reject buttons
- "Missing" rows highlighted with empty French cell

### Sub-tab 3: Review (keep existing)

### Sub-tab 4: Glossary (keep existing)

## Backend Changes

### Enhanced Scan Endpoint
`POST /tools/consciousness/api/translations/scan`

Currently: regex scans `templates/` for `data-i18n` attributes.
New: also scans:
- Module registry via `get_all_modules()` → generates `module.{id}.name` and `module.{id}.desc` keys
- Category definitions → generates `cat.{key}` keys
- JS string manifest from `archie-i18n.js` → `TRANSLATION_KEYS` constant (returned via a new API or hardcoded in scan logic)

Returns: `{ keys: { "key": { source: "template|module|category|js", file: "...", english: "..." } }, total: N }`

### Auto-Seed Endpoint
`POST /tools/consciousness/api/translations/seed`

Takes the scan results, creates English `translations` rows for any keys not yet in DB.
Returns: `{ seeded: N, skipped: N }`

### Coverage API
`GET /tools/consciousness/api/translations/coverage`

Returns per-source stats:
```json
{
  "sources": {
    "template": { "total": 32, "translated": 20, "approved": 20 },
    "module_name": { "total": 34, "translated": 0, "approved": 0 },
    "module_desc": { "total": 34, "translated": 0, "approved": 0 },
    "category": { "total": 7, "translated": 0, "approved": 0 },
    "js": { "total": 45, "translated": 0, "approved": 0 }
  },
  "overall": { "total": 152, "translated": 20, "approved": 20 }
}
```

### Side-by-Side API
`GET /tools/consciousness/api/translations/browser?source=all&status=all&search=&language=fr`

Returns paired EN/FR translations with source metadata:
```json
{
  "translations": [
    { "key": "hud.system", "english": "SYSTEM", "french": "SYSTÈME", "status": "approved", "source": "template", "file": "dashboard_dynamic.html", "fr_id": 42 },
    { "key": "module.crm.name", "english": "CRM", "french": null, "status": "missing", "source": "module_name", "file": "module_registry.py", "fr_id": null }
  ]
}
```

## Frontend Changes

### archie-i18n.js — TRANSLATION_KEYS Manifest

Add a `TRANSLATION_KEYS` constant defining all JS-generated translatable strings:

```javascript
var TRANSLATION_KEYS = {
    'js.boot.initializing': 'INITIALIZING A.R.C.H.I.E. CORE...',
    'js.boot.database': 'DATABASE',
    'js.boot.connected': 'CONNECTED',
    'js.boot.ai_bridge': 'AI BRIDGE',
    'js.boot.online': 'ONLINE',
    'js.boot.modules': 'MODULES',
    'js.boot.loaded': 'LOADED',
    'js.boot.network': 'NETWORK',
    'js.boot.secure': 'SECURE',
    'js.boot.agents': 'AGENTS',
    'js.boot.active': 'ACTIVE',
    'js.boot.consciousness': 'CONSCIOUSNESS',
    'js.boot.aware': 'AWARE',
    'js.status.online': 'ONLINE',
    'js.status.offline': 'OFFLINE',
    'js.status.checking': 'CHECKING...',
    'js.time.seconds_ago': 's ago',
    'js.time.minutes_ago': 'm ago',
    'js.time.hours_ago': 'h ago',
    'js.time.days_ago': 'd ago',
    'js.briefing.loading_activity': 'Loading activity...',
    'js.briefing.no_recent_activity': 'No recent activity',
    'js.briefing.checking_alerts': 'Checking alerts...',
    'js.briefing.loading_insights': 'Loading insights...',
    'js.briefing.all_nominal': 'ALL SYSTEMS NOMINAL',
    'js.briefing.unable_load_activity': 'Unable to load activity',
    'js.briefing.unable_load_alerts': 'Unable to load alerts',
    'js.briefing.ai_unavailable': 'AI data unavailable',
    'js.insights.interactions_today': 'Interactions Today',
    'js.insights.active_agents': 'Active Agents',
    'js.insights.ai_online': 'AI Systems Online',
    'js.insights.ai_offline': 'AI Systems Offline',
    'js.pin.pin_to': 'Pin to Priority Stations',
    'js.pin.unpin_from': 'Unpin from Priority Stations',
    'js.pin.pin_module': 'Pin module',
    'js.pin.unpin_module': 'Unpin module',
    'js.footer.last_refreshed': 'Last refreshed',
    'js.badge.beta': 'BETA',
    'js.badge.coming_soon': 'COMING SOON',
    'js.badge.admin': 'ADMIN'
};
```

Add `getTranslationKeys()` method to expose the manifest for the scan endpoint.

### Dashboard Template — Additional data-i18n Tags

Tag remaining static HTML strings:
- Loading states: `data-i18n="briefing.loading_activity"` etc.
- Button titles: `data-i18n-title="nav.notifications"` etc.
- Pin button titles
- Badge text (BETA, COMING SOON, ADMIN)

### Dashboard Template — Module/Category Translation

For server-rendered module names in Jinja2 loops:
```html
<div class="featured-card-name" data-i18n="module.{{ module.id }}.name">{{ module.name }}</div>
<div class="featured-card-desc" data-i18n="module.{{ module.id }}.desc">{{ module.description | striptags }}</div>
<span class="cat-header-title" data-i18n="cat.{{ cat_key }}">{{ cat_info.name }}</span>
```

The English text renders as default, `archie-i18n.js` swaps it on language switch.

### Dashboard JS — Use archieI18n.t() for Dynamic Content

Replace hardcoded strings in JS with `archieI18n.t()` calls:
```javascript
// Before
subsystems[0] = { label: 'DATABASE', val: 'CONNECTED' };
// After
subsystems[0] = { label: archieI18n.t('js.boot.database', 'DATABASE'), val: archieI18n.t('js.boot.connected', 'CONNECTED') };
```

## Summary

| Component | Changes |
|-----------|---------|
| `archie-i18n.js` | Add `TRANSLATION_KEYS` manifest + `getTranslationKeys()` |
| `consciousness/routes.py` | New endpoints: `/coverage`, `/browser`, `/seed`. Enhanced `/scan` |
| `consciousness_dashboard.html` | Upgraded Coverage sub-tab, new Side-by-Side Browser sub-tab |
| `dashboard_dynamic.html` | Tag ~15 more HTML elements, add `data-i18n` to module/category loops, replace ~45 JS strings with `t()` calls |
| `translation_service.py` | No changes (batch translate already handles any keys) |
