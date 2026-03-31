# Canonical Module Template Structure

**Date**: 2026-03-31
**Project**: #212 LCARS Navigation & Layout Standardization
**Status**: Reference spec — all new modules and refactored modules MUST follow this structure.

---

## Template Skeleton

Every module template MUST follow this structure:

```html
{% extends "base.html" %}
{% block title %}Module Name{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/category-nav.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/module-name.css') }}">
{% endblock %}

{% block content %}

{# ── Category Navigation ── #}
{% set cat_accent = "#f97316" %}
{% set cat_accent_rgb = "249,115,22" %}
{% set cat_accent_light = "#ea580c" %}
{% set cat_label = "CATEGORY NAME" %}
{% set cat_icon = "icon-name" %}
{% set cat_modules = [
    {'url': url_for('module_a.index'), 'endpoint_prefix': 'module_a', 'icon': 'icon', 'label': 'Module A', 'title': 'Full Name'},
    {'url': url_for('module_b.index'), 'endpoint_prefix': 'module_b', 'icon': 'icon', 'label': 'Module B', 'title': 'Full Name'}
] %}
{% include "includes/category_nav.html" %}

{# ── Module Content ── #}
<div class="category-container">
    <div class="category-content">

        {# Module Header #}
        <div class="category-header">
            <i data-lucide="icon-name" style="color: var(--cat-accent);"></i>
            <div class="category-header-text">
                <h1>Module Name</h1>
                <p>Brief description</p>
            </div>
        </div>

        {# Tab Navigation (if multi-tab) #}
        {% include "tools/module_name/tabs.html" %}

        {# Tab Content Panels #}
        {% include "tools/module_name/tab_overview.html" %}
        {% include "tools/module_name/tab_settings.html" %}

    </div>
</div>

{# ── Modals ── #}
{% include "tools/module_name/modals.html" %}

{% endblock %}

{% block extra_js %}
<script src="{{ url_for('static', filename='js/module-name.js') }}"></script>
{% endblock %}
```

---

## Category Accent Colors (9 Categories)

| Category | Accent | RGB | Icon |
|----------|--------|-----|------|
| Admin Operations | `#ef4444` | `239,68,68` | `shield-alert` |
| Admin Tools | `#f97316` | `249,115,22` | `settings-2` |
| AI Command | `#00ffff` | `0,255,255` | `brain` |
| SaaS Services | `#f59e0b` | `245,158,11` | `briefcase` |
| Project & Knowledge | `#00ff41` | `0,255,65` | `folder-kanban` |
| Media & Home | `#0ea5e9` | `14,165,233` | `tv` |
| Crypto | `#eab308` | `234,179,8` | `bitcoin` |
| Applications | `#10b981` | `16,185,129` | `app-window` |
| Creative Studios | `#ec4899` | `236,72,153` | `palette` |

---

## Tab Pattern (Standard)

All modules with tabs MUST use this pattern:

```html
<!-- tabs.html -->
<div class="mod-tabs" role="tablist">
    <button class="tab-btn active" data-tab="overview" role="tab" aria-selected="true"
            onclick="switchTab('overview')">
        <i data-lucide="layout-dashboard"></i> Overview
    </button>
    <button class="tab-btn" data-tab="settings" role="tab" aria-selected="false"
            onclick="switchTab('settings')">
        <i data-lucide="settings"></i> Settings
    </button>
</div>
```

```html
<!-- tab_overview.html -->
<div class="tab-panel active" id="tab-overview" role="tabpanel">
    <!-- content -->
</div>
```

```javascript
// Standard tab switching (in module JS file)
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tabId);
        b.setAttribute('aria-selected', b.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(p => {
        p.classList.toggle('active', p.id === 'tab-' + tabId);
    });
}
```

**Prohibited tab patterns:**
- Bootstrap `nav-tabs` (violates LCARS convention)
- Custom per-module tab classes (fragments the codebase)
- Jinja2 `tab_nav` macro (deprecated — use includes)

---

## File Organization

```
templates/tools/module_name.html          ← Skeleton (< 100 lines ideally)
templates/tools/module_name/
    tabs.html                              ← Tab buttons
    tab_overview.html                      ← Overview tab content
    tab_settings.html                      ← Settings tab content
    modals.html                            ← All modals for this module

static/css/module-name.css                 ← All module CSS (no inline <style>)
static/js/module-name.js                   ← All module JS (no inline <script>)
```

**Rules:**
- **Zero inline CSS** — all styles in external `.css` file
- **Zero inline JS** — all scripts in external `.js` file (except tiny `{% block extra_js %}` config)
- **CSS class prefix** — unique per module (e.g., `sn-` for Security Network, `ac-` for Account Center)
- **Design tokens** — use `var(--archie-*)` from `lcars-tokens.css`, never hardcode colors/spacing
- **Template < 200 lines** — if larger, split into includes

---

## Category Nav Migration Checklist

To migrate a module from its old per-category nav to the generic `category_nav.html`:

1. Replace `{% include "includes/admin_tools_nav.html" %}` (or equivalent) with the parameterized block above
2. Remove any inline `<style>` blocks that duplicate `cn-*` classes (now in `category-nav.css`)
3. Ensure `category-nav.css` is linked in `{% block extra_css %}`
4. Test: nav renders, transitions work, active state highlights correctly, mobile responsive
5. Screenshot compare against baseline in `static/baselines/`

**Old nav includes to replace:**
- `admin_tools_nav.html` → used by: account_center, backup_manager, security_network, system_operations
- `admin_ops_nav.html` → used by: archie_chat, autonomy, repair_bay
- `standalone_apps_nav.html` → used by: archie_pool, doc, fitness, media_hub, pool_management, therapy
- `business_tools_nav.html` → used by: google_work_suite, social_media
- `dev_tools_nav.html` → used by: repair_bay code_editor only

**Dead includes to delete** (unused in any template):
- `creation_tools_nav.html`
- `creative_studios_nav.html`
- `crypto_nav.html`
- `applications_nav.html`

---

## Responsive Breakpoints

All modules must render correctly at:
- **Desktop**: 1024px+ (full nav with labels)
- **Tablet**: 768px (module labels hidden, icons only)
- **Mobile**: 480px (back button text hidden, compact icons)

These breakpoints are already handled in `category-nav.css` responsive section.
