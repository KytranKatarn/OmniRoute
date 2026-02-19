# Full Translation Manager — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the Consciousness Languages tab into a full translation manager with coverage tracking, side-by-side EN/FR browser, smart multi-source discovery, and comprehensive dashboard i18n coverage.

**Architecture:** Enhanced scan discovers translatable strings from 4 sources (HTML templates, JS manifest, module registry, categories). New coverage and browser APIs power an upgraded admin UI. Dashboard gets full `data-i18n` coverage including module names, category names, JS strings via `archieI18n.t()`.

**Tech Stack:** Flask/Jinja2, PostgreSQL, vanilla JS, existing archie-i18n.js engine

**Design Doc:** `docs/plans/2026-02-19-translation-manager-design.md`

---

### Task 1: Add TRANSLATION_KEYS Manifest to archie-i18n.js

Add a JS string registry and expose it so the scan endpoint can discover JS-generated translatable strings.

**Files:**
- Modify: `platform_v2/static/js/archie-i18n.js:8-18` — add TRANSLATION_KEYS constant after `'use strict';`

**Step 1: Add the TRANSLATION_KEYS constant**

After line 12 (`var CACHE_TTL = ...`), insert:

```javascript
    // -- JS String Registry --
    // All translatable strings generated in JavaScript (not in HTML templates).
    // The scan endpoint reads these via getTranslationKeys().
    var TRANSLATION_KEYS = {
        // Boot sequence
        'js.boot.initializing': '> INITIALIZING A.R.C.H.I.E. CORE...',
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
        // Status labels
        'js.status.online': 'ONLINE',
        'js.status.offline': 'OFFLINE',
        'js.status.checking': 'CHECKING...',
        // Time formatting
        'js.time.seconds_ago': 's ago',
        'js.time.minutes_ago': 'm ago',
        'js.time.hours_ago': 'h ago',
        'js.time.days_ago': 'd ago',
        // Mission briefing
        'js.briefing.loading_activity': 'Loading activity...',
        'js.briefing.no_recent_activity': 'No recent activity',
        'js.briefing.checking_alerts': 'Checking alerts...',
        'js.briefing.loading_insights': 'Loading insights...',
        'js.briefing.all_nominal': 'ALL SYSTEMS NOMINAL',
        'js.briefing.unable_load_activity': 'Unable to load activity',
        'js.briefing.unable_load_alerts': 'Unable to load alerts',
        'js.briefing.ai_unavailable': 'AI data unavailable',
        // AI Insights
        'js.insights.interactions_today': 'Interactions Today',
        'js.insights.active_agents': 'Active Agents',
        'js.insights.ai_online': 'AI Systems Online',
        'js.insights.ai_offline': 'AI Systems Offline',
        // Pin actions
        'js.pin.pin_to': 'Pin to Priority Stations',
        'js.pin.unpin_from': 'Unpin from Priority Stations',
        'js.pin.pin_module': 'Pin module',
        'js.pin.unpin_module': 'Unpin module',
        // Footer
        'js.footer.last_refreshed': 'Last refreshed',
        // Badges
        'js.badge.beta': 'BETA',
        'js.badge.coming_soon': 'COMING SOON',
        'js.badge.admin': 'ADMIN',
        // Button titles
        'js.nav.notifications': 'Notifications',
        'js.nav.toggle_theme': 'Toggle Theme',
        'js.nav.language': 'Language',
        'js.nav.dev_hq': 'Dev HQ',
        'js.nav.logout': 'Logout'
    };
```

**Step 2: Expose getTranslationKeys() in the public API**

At line ~258, update the `window.archieI18n` object to add:

```javascript
        getTranslationKeys: function() { return TRANSLATION_KEYS; }
```

**Step 3: Commit**

```bash
git add platform_v2/static/js/archie-i18n.js
git commit -m "feat(linguistics): add TRANSLATION_KEYS manifest to archie-i18n.js"
```

---

### Task 2: Tag Dashboard HTML — Missing Static Elements

Add `data-i18n` attributes to all remaining untagged static text on the dashboard.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html`

**Step 1: Tag loading states in briefing cards**

Find and tag these 3 loading messages (lines ~2250, 2260, 2270):

```html
<!-- Before -->
<span class="briefing-muted">Loading activity...</span>
<!-- After -->
<span class="briefing-muted" data-i18n="js.briefing.loading_activity">Loading activity...</span>
```

Same for:
- `Checking alerts...` -> `data-i18n="js.briefing.checking_alerts"`
- `Loading insights...` -> `data-i18n="js.briefing.loading_insights"`

**Step 2: Tag module/category elements in Jinja2 loops**

Featured cards section (line ~2294):
```html
<!-- Before -->
<div class="featured-card-name">{{ module.name }}</div>
<div class="featured-card-desc">{{ module.description | striptags }}</div>
<!-- After -->
<div class="featured-card-name" data-i18n="module.{{ module.id }}.name">{{ module.name }}</div>
<div class="featured-card-desc" data-i18n="module.{{ module.id }}.desc">{{ module.description | striptags }}</div>
```

Category grid section (line ~2320):
```html
<!-- Before -->
<span class="cat-header-title">{{ cat_info.name }}</span>
<!-- After -->
<span class="cat-header-title" data-i18n="cat.{{ cat_key }}">{{ cat_info.name }}</span>
```

Module cards in category grid (line ~2342):
```html
<!-- Before -->
<div class="module-card-name">{{ module.name }}</div>
<!-- After -->
<div class="module-card-name" data-i18n="module.{{ module.id }}.name">{{ module.name }}</div>
```

**Step 3: Tag button titles**

Command bar buttons (lines ~2136-2161) - add `data-i18n-title` attributes:
- Notifications button: `data-i18n-title="js.nav.notifications"`
- Theme toggle: `data-i18n-title="js.nav.toggle_theme"`
- Language button: `data-i18n-title="js.nav.language"`
- Dev HQ link: `data-i18n-title="js.nav.dev_hq"`
- Logout link: `data-i18n-title="js.nav.logout"`

**Step 4: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(linguistics): tag all remaining dashboard elements with data-i18n"
```

---

### Task 3: Update Dashboard JS to Use archieI18n.t()

Replace hardcoded English strings in the dashboard script block with `archieI18n.t()` calls.

**Files:**
- Modify: `platform_v2/templates/dashboard_dynamic.html` (JS section, lines ~2382+)

**Step 1: Boot sequence subsystems (lines ~2585-2590)**

```javascript
// Before
{label: 'DATABASE', val: 'CONNECTED'},
// After
{label: archieI18n.t('js.boot.database','DATABASE'), val: archieI18n.t('js.boot.connected','CONNECTED')},
```

Apply same pattern to all 6 subsystems: DATABASE/CONNECTED, AI BRIDGE/ONLINE, MODULES/LOADED, NETWORK/SECURE, AGENTS/ACTIVE, CONSCIOUSNESS/AWARE.

Also the initialization message (~line 2546):
```javascript
// Before
'> INITIALIZING A.R.C.H.I.E. CORE...'
// After
archieI18n.t('js.boot.initializing', '> INITIALIZING A.R.C.H.I.E. CORE...')
```

**Step 2: Status text (lines ~2975-2993)**

Replace ONLINE/OFFLINE/CHECKING strings with `archieI18n.t('js.status.online', 'ONLINE')` etc. in AI status and ARCHIE status sections.

**Step 3: Time formatting (lines ~3075-3078)**

```javascript
// Before
if (secs < 60) return secs + 's ago';
// After
if (secs < 60) return secs + archieI18n.t('js.time.seconds_ago', 's ago');
```

Same for minutes_ago, hours_ago, days_ago.

**Step 4: Mission briefing text**

- `'No recent activity'` -> `archieI18n.t('js.briefing.no_recent_activity', 'No recent activity')`
- `'ALL SYSTEMS NOMINAL'` -> `archieI18n.t('js.briefing.all_nominal', 'ALL SYSTEMS NOMINAL')`
- `'Unable to load activity'` -> `archieI18n.t('js.briefing.unable_load_activity', ...)`
- `'Unable to load alerts'` -> `archieI18n.t('js.briefing.unable_load_alerts', ...)`
- `'AI data unavailable'` -> `archieI18n.t('js.briefing.ai_unavailable', ...)`

**Step 5: AI Insights labels**

- `'Interactions Today'` -> `archieI18n.t('js.insights.interactions_today', ...)`
- `'Active Agents'` -> `archieI18n.t('js.insights.active_agents', ...)`
- `'AI Systems Online'` / `'AI Systems Offline'` -> `archieI18n.t('js.insights.ai_online', ...)` etc.

**Step 6: Pin button titles and featured status**

- `'Pin to Priority Stations'` / `'Unpin from Priority Stations'` -> `archieI18n.t('js.pin.pin_to', ...)` / `archieI18n.t('js.pin.unpin_from', ...)`
- `'Pin module'` / `'Unpin module'` -> similar
- `'ONLINE'` / `'OFFLINE'` in featured and category grid status -> `archieI18n.t('js.status.online', 'ONLINE')` etc.

**Step 7: Footer refresh text (line ~3684)**

```javascript
// Before
footerRefresh.textContent = 'Last refreshed ' + refreshSecs + 's ago';
// After
footerRefresh.textContent = archieI18n.t('js.footer.last_refreshed', 'Last refreshed') + ' ' + refreshSecs + archieI18n.t('js.time.seconds_ago', 's ago');
```

**Step 8: Commit**

```bash
git add platform_v2/templates/dashboard_dynamic.html
git commit -m "feat(linguistics): replace hardcoded JS strings with archieI18n.t() calls"
```

---

### Task 4: Backend — Enhanced Scan + Seed + Coverage + Browser Endpoints

Add 3 new endpoints and enhance the scan to discover all 4 sources.

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py:8955-8988` — enhance scan endpoint
- Add 3 new endpoints after scan

**Step 1: Enhance the scan endpoint**

Replace the existing `translation_scan()` function (lines 8958-8988) with an expanded version that:

1. Scans HTML templates for `data-i18n` attributes (existing logic) including `tools/*/templates/` subdirectories
2. Reads module registry via `get_all_modules()` and `ModuleCategory` to generate `module.{id}.name`, `module.{id}.desc`, and `cat.{key}` keys
3. Reads the JS translation manifest from `static/js/archie-i18n.js` by regex extracting key-value pairs from the TRANSLATION_KEYS block

Import at top of routes.py:
```python
from module_registry import get_all_modules, ModuleCategory
```

Returns enhanced structure:
```json
{
  "success": true,
  "keys": {
    "hud.system": {"source": "template", "file": "dashboard_dynamic.html", "english": "SYSTEM"},
    "module.crm.name": {"source": "module_name", "file": "module_registry.py", "english": "CRM"},
    "cat.admin_operations": {"source": "category", "file": "module_registry.py", "english": "Admin Operations"},
    "js.boot.database": {"source": "js", "file": "archie-i18n.js", "english": "DATABASE"}
  },
  "total": 152,
  "by_source": {"template": 32, "module_name": 34, "module_desc": 34, "category": 7, "js": 45}
}
```

**Step 2: Add the seed endpoint**

```python
@consciousness_bp.route("/api/translations/seed", methods=["POST"])
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def translation_seed():
    """Seed English source strings for all discovered keys not yet in DB."""
```

Takes `{ keys: { "key": { "english": "text", "source": "..." } } }` from the scan result.

For each key where no English row exists in `translations`, insert with ON CONFLICT DO NOTHING.

Returns: `{ "success": true, "seeded": N, "skipped": N }`

**Step 3: Add the coverage endpoint**

```python
@consciousness_bp.route("/api/translations/coverage")
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def translation_coverage():
    """Per-source coverage stats for French translations."""
```

1. Run scan logic to get all discoverable keys by source
2. Query DB for French translation status per key
3. Return per-source stats: total, translated, approved, pending, missing

**Step 4: Add the browser endpoint**

```python
@consciousness_bp.route("/api/translations/browser")
@login_required
@require_permission(Permission.ADMIN_ACCESS)
def translation_browser():
    """Side-by-side EN/FR translation browser with filtering."""
```

Query params: `source`, `status`, `search`, `language` (default fr).

1. Run scan to get all keys
2. Left-join with English and French translations from DB
3. Apply filters (source, status, search)
4. Return paired EN/FR translations with source metadata

**Step 5: Restart and test**

```bash
docker restart archie_platform && sleep 15
# Test scan
curl -s -b cookies.txt http://192.168.1.200:3000/tools/consciousness/api/translations/scan -X POST | python3 -m json.tool | head -20
# Test coverage
curl -s -b cookies.txt http://192.168.1.200:3000/tools/consciousness/api/translations/coverage | python3 -m json.tool
```

**Step 6: Commit**

```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "feat(linguistics): enhanced scan, seed, coverage, and browser API endpoints"
```

---

### Task 5: Upgrade Languages Dashboard Sub-tab

Replace the basic stats view with the full coverage dashboard.

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html:1687-1715` — dashboard sub-tab HTML
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html:5873-5913` — dashboard JS functions

**Step 1: Replace Dashboard HTML (lines 1688-1715)**

Replace `<div id="lang-sub-dashboard">` content with:

- **6 stat cards**: Total Keys, Approved, Pending Review, Human Edited, Discovered, Missing
- **Per-source coverage section**: rendered by JS into `#ls-coverage-bars` div. Each row has source label, progress bar, and fraction text.
- **Enhanced action buttons**: "Scan All Sources", "Seed Missing English", "Generate All French", "Approve All Pending"
- **Action status text area** (keep existing `ls-action-status`)

**Step 2: Replace loadLangStats() JS function**

Call `/api/translations/coverage` instead of `/api/translations/stats`. Render:
- Update all 6 stat cards
- Build per-source coverage bars using safe DOM methods (createElement, textContent)

**Step 3: Update scanTemplates() JS function**

Rename to `scanAllSources()`. After scan completes:
1. Show count by source in status text
2. Store scan result in module-level variable for seed button

**Step 4: Add seedMissingEnglish() JS function**

1. POST stored scan keys to `/api/translations/seed`
2. Show seeded count
3. Refresh coverage stats

**Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(linguistics): upgraded Languages dashboard with coverage bars and multi-source scan"
```

---

### Task 6: Add Side-by-Side Browser Sub-tab

Add a new sub-tab between Dashboard and Review for browsing all translations.

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Step 1: Add browser sub-tab button (line ~1683)**

Insert after Dashboard button:
```html
<button class="voice-subtab-btn" onclick="switchLangTab('browser')">Side-by-Side</button>
```

**Step 2: Add browser HTML after the dashboard sub-tab**

Structure:
- Filter row: Source dropdown, Status dropdown, Search input
- Table container div (`#ls-browser-table`)

**Step 3: Add loadBrowser() JS function**

Fetches `/api/translations/browser` with filter params. Renders table with:
- Key (monospace)
- English text
- French text (editable input if exists, highlighted empty cell if missing)
- Status badge (color-coded)
- Source label
- Action buttons (approve/save/reject) for existing translations

Uses safe DOM construction methods: `document.createElement`, `textContent` for user data, entity-escaped values in admin-only contexts following the same pattern as the existing Review tab.

**Step 4: Update switchLangTab() to handle browser tab**

```javascript
if (tabId === 'browser') loadBrowser();
```

**Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(linguistics): side-by-side EN/FR translation browser sub-tab"
```

---

### Task 7: Deploy, Seed, Generate, and Verify

Full integration test with the new system.

**Step 1: Restart platform**

```bash
docker restart archie_platform && sleep 15
```

**Step 2: Test enhanced scan**

Navigate to Consciousness > Languages > Dashboard.
Click "Scan All Sources". Verify it discovers ~150+ keys from all 4 sources.

**Step 3: Seed missing English**

Click "Seed Missing English". Verify it creates ~130 new English entries.

**Step 4: Generate French translations**

Click "Generate All French". Batch-translates missing strings via qwen3-coder-cpu.

**Step 5: Review in Browser tab**

Switch to Browser sub-tab. Filter by "Missing" to see gaps. Filter by "Pending" to review new translations.

**Step 6: Bulk approve**

Back on Dashboard tab, click "Approve All Pending".

**Step 7: Test language switch on dashboard**

Go to Dashboard. Click language button > Francais (QC). Verify:
- HUD labels switch to French
- Section headers switch
- Module names switch
- Category names switch
- Boot sequence labels show French (if retriggered)

**Step 8: Push**

```bash
git push origin main
```

**Step 9: Update Dev HQ**

- Log decision: "Enhanced scan discovers from 4 sources: templates, JS manifest, module registry, categories"
- Update project understanding for Project #94
- Update roadmap with translation manager completion

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | JS TRANSLATION_KEYS manifest | `archie-i18n.js` |
| 2 | Tag remaining dashboard HTML | `dashboard_dynamic.html` |
| 3 | Replace JS hardcoded strings with t() | `dashboard_dynamic.html` (JS section) |
| 4 | Backend: enhanced scan + seed + coverage + browser APIs | `consciousness/routes.py` |
| 5 | Upgrade Languages Dashboard sub-tab | `consciousness_dashboard.html` |
| 6 | Add Side-by-Side Browser sub-tab | `consciousness_dashboard.html` |
| 7 | Deploy + seed + generate + verify | (all files) |
