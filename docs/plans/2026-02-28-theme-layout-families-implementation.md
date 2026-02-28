# Theme Layout Families — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 layout families (LCARS, Corporate, Minimal, Elegant) that give each theme its own HTML structure via Jinja2 macro dispatching, so themes change layout — not just colors.

**Architecture:** 8 themes grouped into 4 layout families. A Jinja2 dispatcher (`theme_macros.html`) auto-imports the correct family's macros based on `layout_family` from the context processor. Each family exports 8 macros with identical signatures but different HTML output. Modules call theme-agnostic macros and never know which family is active.

**Tech Stack:** Flask (Python), Jinja2 macros, CSS custom properties, vanilla JS

**Design doc:** `docs/plans/2026-02-28-theme-layout-families-design.md`

---

## Phase 1: Foundation (no visual changes)

### Task 1: Backend — Add THEME_TO_FAMILY Mapping + layout_family to Context Processor

**Files:**
- Modify: `platform_v2/app.py:2225-2281`

**Step 1: Add THEME_TO_FAMILY dict**

In `platform_v2/app.py`, after the `VALID_THEMES` closing brace (line 2225), add:

```python
THEME_TO_FAMILY = {
    "lcars-classic": "lcars",
    "corporate-blue": "corporate",
    "slate-pro": "corporate",
    "warm-minimal": "minimal",
    "arctic-light": "minimal",
    "midnight-purple": "elegant",
    "rose-gold": "elegant",
    "forest": "elegant",
}
```

**Step 2: Add layout_family resolution to inject_theme_context()**

Inside `inject_theme_context()`, before the return statement (line ~2277), add:

```python
        # Resolve layout family from theme
        layout_family = THEME_TO_FAMILY.get(theme_name, "lcars")

        # Admin modules always use LCARS layout
        if is_admin_module:
            layout_family = "lcars"
```

**Step 3: Add layout_family to return dict**

Update the return dict (line ~2278) to include `layout_family`:

```python
    return {
        "theme_name": theme_name,
        "layout_family": layout_family,
        "is_admin_module": is_admin_module,
    }
```

**Step 4: Verify**

```bash
docker compose restart archie_platform
docker logs --tail 20 archie_platform
```

Expected: Clean startup, no errors. Browse any page — no visual changes.

**Step 5: Commit**

```bash
git add platform_v2/app.py
git commit -m "feat(theme): add THEME_TO_FAMILY mapping + layout_family to context processor"
```

---

### Task 2: Template — Add Layout CSS Conditional Loading to base.html

**Files:**
- Modify: `platform_v2/templates/base.html:30-34`

**Step 1: Add layout CSS loading block**

After the existing SaaS theme override block (after line 32 `{% endif %}`) and before `mobile.css` (line 34), insert:

```html
<!-- Layout Family CSS (structural overrides for non-LCARS families) -->
{% if layout_family is defined and layout_family != 'lcars' and not is_admin_module %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/layouts/' + layout_family + '-layout.css') }}">
{% endif %}
```

The full CSS section should now be (in order):
1. `theme.css` (base variables)
2. `animations.css`, `components.css`, `category-nav.css`, `lcars-frames.css`, `admin-ops.css`
3. `light-mode.css`
4. SaaS Theme Override (color CSS — existing)
5. **Layout Family CSS (structural — NEW)**
6. `mobile.css`
7. `agent-badge.css`

**Step 2: Verify**

```bash
docker compose restart archie_platform
```

Browse any page. View page source — no layout CSS `<link>` should appear (since default is LCARS). No visual changes.

**Step 3: Commit**

```bash
git add platform_v2/templates/base.html
git commit -m "feat(theme): add layout family CSS conditional loading to base.html"
```

---

### Task 3: Create Directory Structure + Macro Dispatcher

**Files:**
- Create: `platform_v2/templates/layouts/` (directory)
- Create: `platform_v2/static/css/layouts/` (directory)
- Create: `platform_v2/templates/theme_macros.html`

**Step 1: Create directories**

```bash
mkdir -p platform_v2/templates/layouts
mkdir -p platform_v2/static/css/layouts
```

**Step 2: Create theme_macros.html dispatcher**

Create `platform_v2/templates/theme_macros.html`:

```jinja2
{#
  Theme Macro Dispatcher
  ----------------------
  Auto-imports the correct layout family's macros based on layout_family
  from the context processor. Modules import from this file and never
  know which family is active.

  Usage in module templates:
    {% from 'theme_macros.html' import page_header, stat_card,
       tab_nav, panel, data_table, card_grid, filter_bar, modal with context %}
#}

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

**Step 3: Commit**

```bash
git add platform_v2/templates/theme_macros.html
git commit -m "feat(theme): create macro dispatcher + layout directory structure"
```

---

### Task 4: Create LCARS Family Macros

**Files:**
- Create: `platform_v2/templates/layouts/lcars.html`

This wraps the existing LCARS HTML patterns from modules (`.lcars-panel`, `.lcars-frame`, stat cards, tabs, etc.) into callable macros. The goal: when modules migrate to macros, the LCARS family renders **exactly the same HTML** as before.

**Step 1: Write LCARS macro file**

Create `platform_v2/templates/layouts/lcars.html`:

```jinja2
{#
  LCARS Layout Family
  --------------------
  Sci-fi aesthetic: pill shapes, sidebar segments, glow borders,
  scanlines, asymmetric border-radius, footer bars.

  Uses existing CSS from: theme.css, lcars-panels.css, lcars-frames.css
#}


{# ── Page Header ── #}
{% macro page_header(title, subtitle='', icon='', actions='') %}
<header class="lcars-page-header" style="margin-bottom: 24px;">
    <div class="lcars-header-glow" style="position: absolute; top: 0; left: 50%; transform: translateX(-50%); width: 200px; height: 2px; background: var(--archie-accent, #00ff41); box-shadow: var(--archie-glow-green-lg); border-radius: 1px;"></div>
    <h1 style="font-family: var(--archie-font-display, 'Orbitron', sans-serif); font-size: 1.8rem; color: var(--archie-accent, #00ff41); text-transform: uppercase; letter-spacing: 2px; margin: 0; text-shadow: var(--archie-text-glow-green);">
        {% if icon %}<i data-lucide="{{ icon }}" style="width: 24px; height: 24px; margin-right: 8px;"></i>{% endif %}
        {{ title }}
    </h1>
    {% if subtitle %}
    <p style="color: var(--archie-text-secondary, #8b949e); font-size: 0.85rem; margin: 6px 0 0 0; letter-spacing: 1px;">{{ subtitle }}</p>
    {% endif %}
    {% if actions %}
    <div class="lcars-header-actions" style="display: flex; gap: 8px; margin-top: 12px;">
        {{ actions }}
    </div>
    {% endif %}
</header>
{% endmacro %}


{# ── Stat Card ── #}
{% macro stat_card(icon, value, label, variant='default', id='') %}
{% set variant_colors = {
    'default': '--archie-accent',
    'success': '--archie-success',
    'warning': '--archie-warning',
    'danger': '--archie-danger',
    'info': '--archie-cyan'
} %}
{% set color_var = variant_colors.get(variant, '--archie-accent') %}
<div class="lcars-stat-card" {% if id %}id="{{ id }}"{% endif %} style="background: var(--archie-bg-secondary, #0d1117); border: 1px solid var(--archie-border-default); border-radius: 0 12px 12px 0; padding: 20px; text-align: center; position: relative; overflow: hidden;">
    <div style="position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: linear-gradient(180deg, var({{ color_var }}), transparent);"></div>
    <div style="width: 48px; height: 48px; border-radius: 50%; background: rgba(var(--archie-green-rgb, 0,255,65), 0.1); display: flex; align-items: center; justify-content: center; margin: 0 auto 12px;">
        <i data-lucide="{{ icon }}" style="width: 24px; height: 24px; color: var({{ color_var }});"></i>
    </div>
    <div class="lcars-stat-value" style="font-family: var(--archie-font-display, 'Orbitron', sans-serif); font-size: 2rem; font-weight: 700; color: var({{ color_var }}); text-shadow: 0 0 8px rgba(var(--archie-green-rgb, 0,255,65), 0.3);">{{ value }}</div>
    <div class="lcars-stat-label" style="color: var(--archie-text-secondary, #8b949e); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px;">{{ label }}</div>
</div>
{% endmacro %}


{# ── Tab Navigation ── #}
{% macro tab_nav(tabs, active_id='', onswitch='') %}
<div class="lcars-tab-nav" style="display: flex; gap: 4px; margin-bottom: 20px; flex-wrap: wrap;">
    {% for tab in tabs %}
    <button class="lcars-tab-btn{% if (loop.first and not active_id) or tab.id == active_id %} active{% endif %}"
            data-tab="{{ tab.id }}"
            {% if onswitch %}onclick="{{ onswitch }}('{{ tab.id }}')"{% endif %}
            style="padding: 10px 20px; border: 1px solid var(--archie-border-default); background: var(--archie-bg-secondary); color: var(--archie-text-secondary); border-radius: 0 10px 10px 0; cursor: pointer; font-family: var(--archie-font-heading, 'Antonio', sans-serif); font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px; transition: all 0.2s ease; display: flex; align-items: center; gap: 8px;">
        {% if tab.icon %}<i data-lucide="{{ tab.icon }}" style="width: 16px; height: 16px;"></i>{% endif %}
        <span>{{ tab.label }}</span>
        {% if tab.badge_id %}
        <span class="lcars-tab-badge" id="{{ tab.badge_id }}" style="display: none; background: var(--archie-accent); color: var(--archie-bg-primary); border-radius: 10px; padding: 1px 8px; font-size: 0.75rem; font-weight: 700;">0</span>
        {% endif %}
    </button>
    {% endfor %}
</div>
<style>
    .lcars-tab-btn.active {
        background: rgba(var(--archie-green-rgb, 0,255,65), 0.15) !important;
        border-color: var(--archie-accent, #00ff41) !important;
        color: var(--archie-accent, #00ff41) !important;
        box-shadow: var(--archie-glow-green-sm);
    }
    .lcars-tab-btn:hover:not(.active) {
        background: var(--archie-bg-hover) !important;
        border-color: var(--archie-border-emphasis) !important;
        color: var(--archie-text-primary) !important;
    }
</style>
{% endmacro %}


{# ── Panel (callable — content goes in caller()) ── #}
{% macro panel(title, icon='', accent='green', compact=false, id='') %}
<div class="lcars-panel {% if accent != 'green' %}accent-{{ accent }}{% endif %}" {% if id %}id="{{ id }}"{% endif %} style="{% if compact %}padding: 10px;{% endif %}">
    <div class="lcars-panel-header">
        <div class="lcars-panel-cap"></div>
        <h2 class="lcars-panel-title">
            {% if icon %}<i data-lucide="{{ icon }}" style="width: 16px; height: 16px;"></i>{% endif %}
            {{ title }}
        </h2>
        <div class="lcars-panel-light"></div>
    </div>
    <div class="lcars-panel-body">
        {{ caller() }}
    </div>
</div>
{% endmacro %}


{# ── Data Table ── #}
{% macro data_table(headers, tbody_id='', table_class='') %}
<div class="lcars-table-wrapper" style="overflow-x: auto;">
    <table class="lcars-data-table {{ table_class }}" style="width: 100%; border-collapse: collapse;">
        <thead>
            <tr>
                {% for h in headers %}
                <th style="padding: 10px 12px; text-align: left; font-family: var(--archie-font-heading, 'Antonio', sans-serif); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: var(--archie-text-secondary); border-bottom: 1px solid var(--archie-border-default);">{{ h }}</th>
                {% endfor %}
            </tr>
        </thead>
        <tbody {% if tbody_id %}id="{{ tbody_id }}"{% endif %}>
            {{ caller() }}
        </tbody>
    </table>
</div>
{% endmacro %}


{# ── Card Grid (callable — each item rendered by caller()) ── #}
{% macro card_grid(columns='repeat(auto-fit, minmax(280px, 1fr))', gap='16px', id='') %}
<div class="lcars-card-grid" {% if id %}id="{{ id }}"{% endif %} style="display: grid; grid-template-columns: {{ columns }}; gap: {{ gap }};">
    {{ caller() }}
</div>
{% endmacro %}


{# ── Filter Bar ── #}
{% macro filter_bar(search_placeholder='', search_id='', filters=[], oninput='') %}
<div class="lcars-filter-bar" style="display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; align-items: center;">
    {% if search_placeholder %}
    <div style="flex: 1; min-width: 200px; position: relative;">
        <i data-lucide="search" style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; color: var(--archie-text-tertiary);"></i>
        <input type="text" {% if search_id %}id="{{ search_id }}"{% endif %} class="lcars-input" placeholder="{{ search_placeholder }}" {% if oninput %}oninput="{{ oninput }}()"{% endif %} style="width: 100%; padding-left: 36px;">
    </div>
    {% endif %}
    {% for f in filters %}
    <select {% if f.id %}id="{{ f.id }}"{% endif %} class="lcars-input" {% if oninput %}onchange="{{ oninput }}()"{% endif %} style="min-width: 140px;">
        {% for opt in f.options %}
        <option value="{{ opt.value }}">{{ opt.label }}</option>
        {% endfor %}
    </select>
    {% endfor %}
</div>
{% endmacro %}


{# ── Modal (callable — body + actions in caller()) ── #}
{% macro modal(modal_id, title, icon='', size='medium') %}
{% set size_map = {'small': '400px', 'medium': '600px', 'large': '800px', 'xlarge': '1000px'} %}
<div class="lcars-modal-backdrop" id="{{ modal_id }}-backdrop" style="display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 9999; align-items: center; justify-content: center;" onclick="if(event.target===this)document.getElementById('{{ modal_id }}-backdrop').style.display='none';">
    <div class="lcars-panel" id="{{ modal_id }}" style="width: {{ size_map.get(size, '600px') }}; max-width: 95vw; max-height: 85vh; display: flex; flex-direction: column;">
        <div class="lcars-panel-header" style="flex-shrink: 0;">
            <div class="lcars-panel-cap"></div>
            <h2 class="lcars-panel-title">
                {% if icon %}<i data-lucide="{{ icon }}" style="width: 16px; height: 16px;"></i>{% endif %}
                {{ title }}
            </h2>
            <button onclick="document.getElementById('{{ modal_id }}-backdrop').style.display='none';" style="background: none; border: none; color: var(--archie-text-secondary); cursor: pointer; font-size: 1.4rem; padding: 4px 8px;">&times;</button>
        </div>
        <div class="lcars-panel-body" style="overflow-y: auto; flex: 1;">
            {{ caller() }}
        </div>
    </div>
</div>
{% endmacro %}
```

**Step 2: Verify syntax**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('layouts/lcars.html')
print('LCARS macros loaded OK')
"
```

Expected: `LCARS macros loaded OK`

**Step 3: Commit**

```bash
git add platform_v2/templates/layouts/lcars.html
git commit -m "feat(theme): LCARS layout family macros — 8 components matching existing patterns"
```

---

### Task 5: Create Corporate Family Macros + CSS

**Files:**
- Create: `platform_v2/templates/layouts/corporate.html`
- Create: `platform_v2/static/css/layouts/corporate-layout.css`

**Step 1: Write Corporate macro file**

Create `platform_v2/templates/layouts/corporate.html`:

```jinja2
{#
  Corporate Layout Family
  -----------------------
  Clean, professional aesthetic: rectangles, subtle shadows,
  standard nav with underline active, no accent bars.
  Used by: corporate-blue, slate-pro
#}


{# ── Page Header ── #}
{% macro page_header(title, subtitle='', icon='', actions='') %}
<header class="corp-page-header">
    <h1 class="corp-title">
        {% if icon %}<i data-lucide="{{ icon }}"></i>{% endif %}
        {{ title }}
    </h1>
    {% if subtitle %}
    <p class="corp-subtitle">{{ subtitle }}</p>
    {% endif %}
    {% if actions %}
    <div class="corp-header-actions">{{ actions }}</div>
    {% endif %}
</header>
{% endmacro %}


{# ── Stat Card ── #}
{% macro stat_card(icon, value, label, variant='default', id='') %}
<div class="corp-stat-card corp-stat--{{ variant }}" {% if id %}id="{{ id }}"{% endif %}>
    <div class="corp-stat-icon">
        <i data-lucide="{{ icon }}"></i>
    </div>
    <div class="corp-stat-content">
        <div class="corp-stat-value">{{ value }}</div>
        <div class="corp-stat-label">{{ label }}</div>
    </div>
</div>
{% endmacro %}


{# ── Tab Navigation ── #}
{% macro tab_nav(tabs, active_id='', onswitch='') %}
<div class="corp-tab-nav">
    {% for tab in tabs %}
    <button class="corp-tab{% if (loop.first and not active_id) or tab.id == active_id %} active{% endif %}"
            data-tab="{{ tab.id }}"
            {% if onswitch %}onclick="{{ onswitch }}('{{ tab.id }}')"{% endif %}>
        {% if tab.icon %}<i data-lucide="{{ tab.icon }}"></i>{% endif %}
        <span>{{ tab.label }}</span>
        {% if tab.badge_id %}
        <span class="corp-tab-badge" id="{{ tab.badge_id }}" style="display: none;">0</span>
        {% endif %}
    </button>
    {% endfor %}
</div>
{% endmacro %}


{# ── Panel ── #}
{% macro panel(title, icon='', accent='green', compact=false, id='') %}
<div class="corp-panel{% if compact %} corp-panel--compact{% endif %}" {% if id %}id="{{ id }}"{% endif %}>
    <div class="corp-panel-header">
        <h2 class="corp-panel-title">
            {% if icon %}<i data-lucide="{{ icon }}"></i>{% endif %}
            {{ title }}
        </h2>
    </div>
    <div class="corp-panel-body">
        {{ caller() }}
    </div>
</div>
{% endmacro %}


{# ── Data Table ── #}
{% macro data_table(headers, tbody_id='', table_class='') %}
<div class="corp-table-wrapper">
    <table class="corp-table {{ table_class }}">
        <thead>
            <tr>
                {% for h in headers %}
                <th>{{ h }}</th>
                {% endfor %}
            </tr>
        </thead>
        <tbody {% if tbody_id %}id="{{ tbody_id }}"{% endif %}>
            {{ caller() }}
        </tbody>
    </table>
</div>
{% endmacro %}


{# ── Card Grid ── #}
{% macro card_grid(columns='repeat(auto-fit, minmax(280px, 1fr))', gap='16px', id='') %}
<div class="corp-card-grid" {% if id %}id="{{ id }}"{% endif %} style="display: grid; grid-template-columns: {{ columns }}; gap: {{ gap }};">
    {{ caller() }}
</div>
{% endmacro %}


{# ── Filter Bar ── #}
{% macro filter_bar(search_placeholder='', search_id='', filters=[], oninput='') %}
<div class="corp-filter-bar">
    {% if search_placeholder %}
    <div class="corp-search-wrap">
        <i data-lucide="search"></i>
        <input type="text" {% if search_id %}id="{{ search_id }}"{% endif %} class="corp-input" placeholder="{{ search_placeholder }}" {% if oninput %}oninput="{{ oninput }}()"{% endif %}>
    </div>
    {% endif %}
    {% for f in filters %}
    <select {% if f.id %}id="{{ f.id }}"{% endif %} class="corp-select" {% if oninput %}onchange="{{ oninput }}()"{% endif %}>
        {% for opt in f.options %}
        <option value="{{ opt.value }}">{{ opt.label }}</option>
        {% endfor %}
    </select>
    {% endfor %}
</div>
{% endmacro %}


{# ── Modal ── #}
{% macro modal(modal_id, title, icon='', size='medium') %}
{% set size_map = {'small': '400px', 'medium': '600px', 'large': '800px', 'xlarge': '1000px'} %}
<div class="corp-modal-backdrop" id="{{ modal_id }}-backdrop" style="display: none;" onclick="if(event.target===this)document.getElementById('{{ modal_id }}-backdrop').style.display='none';">
    <div class="corp-modal" id="{{ modal_id }}" style="width: {{ size_map.get(size, '600px') }};">
        <div class="corp-modal-header">
            <h2>
                {% if icon %}<i data-lucide="{{ icon }}"></i>{% endif %}
                {{ title }}
            </h2>
            <button class="corp-modal-close" onclick="document.getElementById('{{ modal_id }}-backdrop').style.display='none';">&times;</button>
        </div>
        <div class="corp-modal-body">
            {{ caller() }}
        </div>
    </div>
</div>
{% endmacro %}
```

**Step 2: Write Corporate layout CSS**

Create `platform_v2/static/css/layouts/corporate-layout.css`:

```css
/*
 * Corporate Layout Family — Clean, professional structural styles
 * Used by: corporate-blue, slate-pro themes
 */

/* ── Page Header ── */
.corp-page-header {
    margin-bottom: 28px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
}

.corp-title {
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 1.6rem;
    font-weight: 600;
    color: var(--archie-text-primary, #e2e8f0);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.corp-title i { width: 22px; height: 22px; color: var(--archie-accent, #3b82f6); }

.corp-subtitle {
    color: var(--archie-text-secondary, #94a3b8);
    font-size: 0.9rem;
    margin: 6px 0 0 0;
}

.corp-header-actions {
    display: flex;
    gap: 8px;
    margin-top: 14px;
}

/* ── Stat Card ── */
.corp-stat-card {
    display: flex;
    align-items: center;
    gap: 16px;
    background: var(--archie-bg-secondary, #1e293b);
    border: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
    border-radius: 8px;
    padding: 16px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    transition: box-shadow 0.2s ease, transform 0.2s ease;
}

.corp-stat-card:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    transform: translateY(-1px);
}

.corp-stat-icon {
    width: 44px;
    height: 44px;
    border-radius: 8px;
    background: var(--archie-green-alpha-10, rgba(59,130,246,0.1));
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}

.corp-stat-icon i { width: 22px; height: 22px; color: var(--archie-accent, #3b82f6); }

.corp-stat--success .corp-stat-icon { background: rgba(34,197,94,0.1); }
.corp-stat--success .corp-stat-icon i { color: var(--archie-success, #22c55e); }
.corp-stat--warning .corp-stat-icon { background: rgba(245,158,11,0.1); }
.corp-stat--warning .corp-stat-icon i { color: var(--archie-warning, #f59e0b); }
.corp-stat--danger .corp-stat-icon { background: rgba(239,68,68,0.1); }
.corp-stat--danger .corp-stat-icon i { color: var(--archie-danger, #ef4444); }
.corp-stat--info .corp-stat-icon { background: rgba(96,165,250,0.1); }
.corp-stat--info .corp-stat-icon i { color: var(--archie-cyan, #60a5fa); }

.corp-stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--archie-text-primary, #e2e8f0);
    line-height: 1;
}

.corp-stat-label {
    font-size: 0.8rem;
    color: var(--archie-text-secondary, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 2px;
}

/* ── Tab Navigation ── */
.corp-tab-nav {
    display: flex;
    gap: 0;
    margin-bottom: 24px;
    border-bottom: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
}

.corp-tab {
    padding: 10px 18px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--archie-text-secondary, #94a3b8);
    cursor: pointer;
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 0.85rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    display: flex;
    align-items: center;
    gap: 8px;
    transition: all 0.2s ease;
}

.corp-tab i { width: 16px; height: 16px; }

.corp-tab.active {
    color: var(--archie-accent, #3b82f6);
    border-bottom-color: var(--archie-accent, #3b82f6);
}

.corp-tab:hover:not(.active) {
    color: var(--archie-text-primary, #e2e8f0);
    background: var(--archie-bg-hover, rgba(59,130,246,0.05));
}

.corp-tab-badge {
    background: var(--archie-accent, #3b82f6);
    color: #fff;
    border-radius: 10px;
    padding: 1px 7px;
    font-size: 0.7rem;
    font-weight: 600;
}

/* ── Panel ── */
.corp-panel {
    background: var(--archie-bg-secondary, #1e293b);
    border: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    margin-bottom: 20px;
    overflow: hidden;
}

.corp-panel-header {
    padding: 14px 20px;
    border-bottom: 1px solid var(--archie-border-muted, rgba(59,130,246,0.1));
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.corp-panel-title {
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--archie-text-primary, #e2e8f0);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.corp-panel-title i { width: 16px; height: 16px; color: var(--archie-accent, #3b82f6); }

.corp-panel-body { padding: 20px; }

.corp-panel--compact .corp-panel-body { padding: 12px 16px; }

/* ── Data Table ── */
.corp-table-wrapper { overflow-x: auto; }

.corp-table {
    width: 100%;
    border-collapse: collapse;
}

.corp-table thead th {
    padding: 10px 14px;
    text-align: left;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--archie-text-secondary, #94a3b8);
    border-bottom: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
}

.corp-table tbody td {
    padding: 12px 14px;
    border-bottom: 1px solid var(--archie-border-subtle, rgba(59,130,246,0.06));
    color: var(--archie-text-primary, #e2e8f0);
    font-size: 0.88rem;
}

.corp-table tbody tr:hover {
    background: var(--archie-bg-hover, rgba(59,130,246,0.05));
}

/* ── Filter Bar ── */
.corp-filter-bar {
    display: flex;
    gap: 10px;
    margin-bottom: 16px;
    flex-wrap: wrap;
    align-items: center;
}

.corp-search-wrap {
    flex: 1;
    min-width: 200px;
    position: relative;
}

.corp-search-wrap i {
    position: absolute;
    left: 12px;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: var(--archie-text-tertiary, #64748b);
}

.corp-input, .corp-select {
    background: var(--archie-bg-primary, #0f172a);
    border: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
    border-radius: 6px;
    color: var(--archie-text-primary, #e2e8f0);
    padding: 8px 12px;
    font-size: 0.88rem;
    transition: border-color 0.2s ease;
}

.corp-input:focus, .corp-select:focus {
    border-color: var(--archie-accent, #3b82f6);
    outline: none;
    box-shadow: 0 0 0 2px var(--archie-green-alpha-20, rgba(59,130,246,0.2));
}

.corp-search-wrap .corp-input {
    width: 100%;
    padding-left: 36px;
}

/* ── Modal ── */
.corp-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
}

.corp-modal {
    background: var(--archie-bg-secondary, #1e293b);
    border: 1px solid var(--archie-border-default, rgba(59,130,246,0.2));
    border-radius: 10px;
    max-width: 95vw;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}

.corp-modal-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--archie-border-muted, rgba(59,130,246,0.1));
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.corp-modal-header h2 {
    font-size: 1rem;
    font-weight: 600;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--archie-text-primary, #e2e8f0);
}

.corp-modal-header h2 i { width: 18px; height: 18px; color: var(--archie-accent, #3b82f6); }

.corp-modal-close {
    background: none;
    border: none;
    color: var(--archie-text-secondary, #94a3b8);
    cursor: pointer;
    font-size: 1.4rem;
    padding: 4px 8px;
    border-radius: 4px;
    transition: background 0.15s;
}

.corp-modal-close:hover { background: var(--archie-bg-hover); }

.corp-modal-body {
    padding: 20px;
    overflow-y: auto;
    flex: 1;
}

/* ── Responsive ── */
@media (max-width: 768px) {
    .corp-stat-card { padding: 12px 16px; }
    .corp-tab-nav { overflow-x: auto; flex-wrap: nowrap; }
    .corp-tab { padding: 8px 14px; font-size: 0.8rem; white-space: nowrap; }
    .corp-filter-bar { flex-direction: column; }
    .corp-search-wrap { min-width: 100%; }
}
```

**Step 3: Verify syntax**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('layouts/corporate.html')
print('Corporate macros loaded OK')
"
```

**Step 4: Commit**

```bash
git add platform_v2/templates/layouts/corporate.html platform_v2/static/css/layouts/corporate-layout.css
git commit -m "feat(theme): Corporate layout family — clean rectangles, underline tabs, horizontal stat cards"
```

---

### Task 6: Create Minimal Family Macros + CSS

**Files:**
- Create: `platform_v2/templates/layouts/minimal.html`
- Create: `platform_v2/static/css/layouts/minimal-layout.css`

**Step 1: Write Minimal macro file**

Create `platform_v2/templates/layouts/minimal.html`:

```jinja2
{#
  Minimal Layout Family
  ---------------------
  Maximum whitespace, hairline borders, no frames,
  flat cards, text-only tabs, simple stacked layout.
  Used by: warm-minimal, arctic-light
#}


{# ── Page Header ── #}
{% macro page_header(title, subtitle='', icon='', actions='') %}
<header class="min-page-header">
    <h1 class="min-title">{{ title }}</h1>
    {% if subtitle %}
    <p class="min-subtitle">{{ subtitle }}</p>
    {% endif %}
    {% if actions %}
    <div class="min-header-actions">{{ actions }}</div>
    {% endif %}
</header>
{% endmacro %}


{# ── Stat Card ── #}
{% macro stat_card(icon, value, label, variant='default', id='') %}
<div class="min-stat-card" {% if id %}id="{{ id }}"{% endif %}>
    <div class="min-stat-value">{{ value }}</div>
    <div class="min-stat-label">{{ label }}</div>
</div>
{% endmacro %}


{# ── Tab Navigation ── #}
{% macro tab_nav(tabs, active_id='', onswitch='') %}
<div class="min-tab-nav">
    {% for tab in tabs %}
    <button class="min-tab{% if (loop.first and not active_id) or tab.id == active_id %} active{% endif %}"
            data-tab="{{ tab.id }}"
            {% if onswitch %}onclick="{{ onswitch }}('{{ tab.id }}')"{% endif %}>
        <span>{{ tab.label }}</span>
        {% if tab.badge_id %}
        <span class="min-tab-badge" id="{{ tab.badge_id }}" style="display: none;">0</span>
        {% endif %}
    </button>
    {% endfor %}
</div>
{% endmacro %}


{# ── Panel ── #}
{% macro panel(title, icon='', accent='green', compact=false, id='') %}
<div class="min-panel{% if compact %} min-panel--compact{% endif %}" {% if id %}id="{{ id }}"{% endif %}>
    <h2 class="min-panel-title">{{ title }}</h2>
    <div class="min-panel-body">
        {{ caller() }}
    </div>
</div>
{% endmacro %}


{# ── Data Table ── #}
{% macro data_table(headers, tbody_id='', table_class='') %}
<div class="min-table-wrapper">
    <table class="min-table {{ table_class }}">
        <thead>
            <tr>
                {% for h in headers %}
                <th>{{ h }}</th>
                {% endfor %}
            </tr>
        </thead>
        <tbody {% if tbody_id %}id="{{ tbody_id }}"{% endif %}>
            {{ caller() }}
        </tbody>
    </table>
</div>
{% endmacro %}


{# ── Card Grid ── #}
{% macro card_grid(columns='repeat(auto-fit, minmax(280px, 1fr))', gap='20px', id='') %}
<div class="min-card-grid" {% if id %}id="{{ id }}"{% endif %} style="display: grid; grid-template-columns: {{ columns }}; gap: {{ gap }};">
    {{ caller() }}
</div>
{% endmacro %}


{# ── Filter Bar ── #}
{% macro filter_bar(search_placeholder='', search_id='', filters=[], oninput='') %}
<div class="min-filter-bar">
    {% if search_placeholder %}
    <div class="min-search-wrap">
        <input type="text" {% if search_id %}id="{{ search_id }}"{% endif %} class="min-input" placeholder="{{ search_placeholder }}" {% if oninput %}oninput="{{ oninput }}()"{% endif %}>
    </div>
    {% endif %}
    {% for f in filters %}
    <select {% if f.id %}id="{{ f.id }}"{% endif %} class="min-select" {% if oninput %}onchange="{{ oninput }}()"{% endif %}>
        {% for opt in f.options %}
        <option value="{{ opt.value }}">{{ opt.label }}</option>
        {% endfor %}
    </select>
    {% endfor %}
</div>
{% endmacro %}


{# ── Modal ── #}
{% macro modal(modal_id, title, icon='', size='medium') %}
{% set size_map = {'small': '380px', 'medium': '520px', 'large': '700px', 'xlarge': '900px'} %}
<div class="min-modal-backdrop" id="{{ modal_id }}-backdrop" style="display: none;" onclick="if(event.target===this)document.getElementById('{{ modal_id }}-backdrop').style.display='none';">
    <div class="min-modal" id="{{ modal_id }}" style="width: {{ size_map.get(size, '520px') }};">
        <div class="min-modal-header">
            <h2>{{ title }}</h2>
            <button class="min-modal-close" onclick="document.getElementById('{{ modal_id }}-backdrop').style.display='none';">&times;</button>
        </div>
        <div class="min-modal-body">
            {{ caller() }}
        </div>
    </div>
</div>
{% endmacro %}
```

**Step 2: Write Minimal layout CSS**

Create `platform_v2/static/css/layouts/minimal-layout.css`:

```css
/*
 * Minimal Layout Family — Maximum whitespace, hairline borders, flat
 * Used by: warm-minimal, arctic-light themes
 */

/* ── Page Header ── */
.min-page-header {
    margin-bottom: 32px;
}

.min-title {
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--archie-text-primary, #e2e8f0);
    margin: 0;
    letter-spacing: -0.01em;
}

.min-subtitle {
    color: var(--archie-text-tertiary, #64748b);
    font-size: 0.88rem;
    margin: 4px 0 0 0;
}

.min-header-actions {
    display: flex;
    gap: 8px;
    margin-top: 16px;
}

/* ── Stat Card ── */
.min-stat-card {
    padding: 24px 20px;
    text-align: center;
    border: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.06));
    border-radius: 4px;
    background: transparent;
    transition: border-color 0.2s ease;
}

.min-stat-card:hover {
    border-color: var(--archie-border-default);
}

.min-stat-value {
    font-size: 2.2rem;
    font-weight: 700;
    color: var(--archie-accent, #f59e0b);
    line-height: 1;
}

.min-stat-label {
    font-size: 0.78rem;
    color: var(--archie-text-tertiary, #64748b);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-top: 8px;
}

/* ── Tab Navigation ── */
.min-tab-nav {
    display: flex;
    gap: 0;
    margin-bottom: 28px;
    border-bottom: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.06));
}

.min-tab {
    padding: 10px 16px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--archie-text-tertiary, #64748b);
    cursor: pointer;
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 0.85rem;
    font-weight: 500;
    letter-spacing: 0.3px;
    transition: all 0.2s ease;
}

.min-tab.active {
    color: var(--archie-accent);
    border-bottom-color: var(--archie-accent);
}

.min-tab:hover:not(.active) {
    color: var(--archie-text-primary);
}

.min-tab-badge {
    background: var(--archie-accent);
    color: var(--archie-bg-primary);
    border-radius: 8px;
    padding: 1px 6px;
    font-size: 0.7rem;
    font-weight: 600;
    margin-left: 6px;
}

/* ── Panel ── */
.min-panel {
    margin-bottom: 28px;
}

.min-panel-title {
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--archie-text-primary, #e2e8f0);
    margin: 0 0 12px 0;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.06));
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.min-panel-body {}

.min-panel--compact .min-panel-title { margin-bottom: 8px; padding-bottom: 6px; }

/* ── Data Table ── */
.min-table-wrapper { overflow-x: auto; }

.min-table {
    width: 100%;
    border-collapse: collapse;
}

.min-table thead th {
    padding: 10px 16px;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--archie-text-tertiary, #64748b);
    border-bottom: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.06));
}

.min-table tbody td {
    padding: 14px 16px;
    color: var(--archie-text-primary, #e2e8f0);
    font-size: 0.88rem;
}

.min-table tbody tr + tr td {
    border-top: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.04));
}

.min-table tbody tr:hover td {
    background: rgba(255,255,255,0.02);
}

/* ── Filter Bar ── */
.min-filter-bar {
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
    flex-wrap: wrap;
    align-items: center;
}

.min-search-wrap {
    flex: 1;
    min-width: 200px;
}

.min-input, .min-select {
    background: transparent;
    border: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.06));
    border-radius: 4px;
    color: var(--archie-text-primary, #e2e8f0);
    padding: 9px 14px;
    font-size: 0.88rem;
    transition: border-color 0.2s ease;
    width: 100%;
}

.min-input:focus, .min-select:focus {
    border-color: var(--archie-accent);
    outline: none;
}

/* ── Modal ── */
.min-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
}

.min-modal {
    background: var(--archie-bg-primary, #0f172a);
    border: 1px solid var(--archie-border-subtle, rgba(255,255,255,0.06));
    border-radius: 6px;
    max-width: 95vw;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
}

.min-modal-header {
    padding: 20px 24px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.min-modal-header h2 {
    font-size: 1rem;
    font-weight: 600;
    margin: 0;
    color: var(--archie-text-primary, #e2e8f0);
}

.min-modal-close {
    background: none;
    border: none;
    color: var(--archie-text-tertiary, #64748b);
    cursor: pointer;
    font-size: 1.3rem;
    padding: 4px 8px;
}

.min-modal-body {
    padding: 0 24px 24px;
    overflow-y: auto;
    flex: 1;
}

/* ── Responsive ── */
@media (max-width: 768px) {
    .min-tab-nav { overflow-x: auto; flex-wrap: nowrap; }
    .min-tab { white-space: nowrap; }
    .min-filter-bar { flex-direction: column; }
    .min-search-wrap { min-width: 100%; }
}
```

**Step 3: Verify**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('layouts/minimal.html')
print('Minimal macros loaded OK')
"
```

**Step 4: Commit**

```bash
git add platform_v2/templates/layouts/minimal.html platform_v2/static/css/layouts/minimal-layout.css
git commit -m "feat(theme): Minimal layout family — whitespace, hairline borders, flat cards, text tabs"
```

---

### Task 7: Create Elegant Family Macros + CSS

**Files:**
- Create: `platform_v2/templates/layouts/elegant.html`
- Create: `platform_v2/static/css/layouts/elegant-layout.css`

**Step 1: Write Elegant macro file**

Create `platform_v2/templates/layouts/elegant.html`:

```jinja2
{#
  Elegant Layout Family
  ---------------------
  Floating rounded cards, gradient accents, glass effects,
  decorative borders, pill-shaped nav.
  Used by: midnight-purple, rose-gold, forest
#}


{# ── Page Header ── #}
{% macro page_header(title, subtitle='', icon='', actions='') %}
<header class="eleg-page-header">
    <h1 class="eleg-title">
        {% if icon %}<i data-lucide="{{ icon }}"></i>{% endif %}
        {{ title }}
    </h1>
    <div class="eleg-title-accent"></div>
    {% if subtitle %}
    <p class="eleg-subtitle">{{ subtitle }}</p>
    {% endif %}
    {% if actions %}
    <div class="eleg-header-actions">{{ actions }}</div>
    {% endif %}
</header>
{% endmacro %}


{# ── Stat Card ── #}
{% macro stat_card(icon, value, label, variant='default', id='') %}
<div class="eleg-stat-card eleg-stat--{{ variant }}" {% if id %}id="{{ id }}"{% endif %}>
    <div class="eleg-stat-accent"></div>
    <div class="eleg-stat-icon">
        <i data-lucide="{{ icon }}"></i>
    </div>
    <div class="eleg-stat-value">{{ value }}</div>
    <div class="eleg-stat-label">{{ label }}</div>
</div>
{% endmacro %}


{# ── Tab Navigation ── #}
{% macro tab_nav(tabs, active_id='', onswitch='') %}
<div class="eleg-tab-nav">
    {% for tab in tabs %}
    <button class="eleg-tab{% if (loop.first and not active_id) or tab.id == active_id %} active{% endif %}"
            data-tab="{{ tab.id }}"
            {% if onswitch %}onclick="{{ onswitch }}('{{ tab.id }}')"{% endif %}>
        {% if tab.icon %}<i data-lucide="{{ tab.icon }}"></i>{% endif %}
        <span>{{ tab.label }}</span>
        {% if tab.badge_id %}
        <span class="eleg-tab-badge" id="{{ tab.badge_id }}" style="display: none;">0</span>
        {% endif %}
    </button>
    {% endfor %}
</div>
{% endmacro %}


{# ── Panel ── #}
{% macro panel(title, icon='', accent='green', compact=false, id='') %}
<div class="eleg-panel{% if compact %} eleg-panel--compact{% endif %}" {% if id %}id="{{ id }}"{% endif %}>
    <div class="eleg-panel-header">
        <h2 class="eleg-panel-title">
            {% if icon %}<i data-lucide="{{ icon }}"></i>{% endif %}
            {{ title }}
        </h2>
    </div>
    <div class="eleg-panel-body">
        {{ caller() }}
    </div>
</div>
{% endmacro %}


{# ── Data Table ── #}
{% macro data_table(headers, tbody_id='', table_class='') %}
<div class="eleg-table-wrapper">
    <table class="eleg-table {{ table_class }}">
        <thead>
            <tr>
                {% for h in headers %}
                <th>{{ h }}</th>
                {% endfor %}
            </tr>
        </thead>
        <tbody {% if tbody_id %}id="{{ tbody_id }}"{% endif %}>
            {{ caller() }}
        </tbody>
    </table>
</div>
{% endmacro %}


{# ── Card Grid ── #}
{% macro card_grid(columns='repeat(auto-fit, minmax(280px, 1fr))', gap='20px', id='') %}
<div class="eleg-card-grid" {% if id %}id="{{ id }}"{% endif %} style="display: grid; grid-template-columns: {{ columns }}; gap: {{ gap }};">
    {{ caller() }}
</div>
{% endmacro %}


{# ── Filter Bar ── #}
{% macro filter_bar(search_placeholder='', search_id='', filters=[], oninput='') %}
<div class="eleg-filter-bar">
    {% if search_placeholder %}
    <div class="eleg-search-wrap">
        <i data-lucide="search"></i>
        <input type="text" {% if search_id %}id="{{ search_id }}"{% endif %} class="eleg-input" placeholder="{{ search_placeholder }}" {% if oninput %}oninput="{{ oninput }}()"{% endif %}>
    </div>
    {% endif %}
    {% for f in filters %}
    <select {% if f.id %}id="{{ f.id }}"{% endif %} class="eleg-select" {% if oninput %}onchange="{{ oninput }}()"{% endif %}>
        {% for opt in f.options %}
        <option value="{{ opt.value }}">{{ opt.label }}</option>
        {% endfor %}
    </select>
    {% endfor %}
</div>
{% endmacro %}


{# ── Modal ── #}
{% macro modal(modal_id, title, icon='', size='medium') %}
{% set size_map = {'small': '420px', 'medium': '620px', 'large': '820px', 'xlarge': '1020px'} %}
<div class="eleg-modal-backdrop" id="{{ modal_id }}-backdrop" style="display: none;" onclick="if(event.target===this)document.getElementById('{{ modal_id }}-backdrop').style.display='none';">
    <div class="eleg-modal" id="{{ modal_id }}" style="width: {{ size_map.get(size, '620px') }};">
        <div class="eleg-modal-header">
            <h2>
                {% if icon %}<i data-lucide="{{ icon }}"></i>{% endif %}
                {{ title }}
            </h2>
            <button class="eleg-modal-close" onclick="document.getElementById('{{ modal_id }}-backdrop').style.display='none';">&times;</button>
        </div>
        <div class="eleg-modal-body">
            {{ caller() }}
        </div>
    </div>
</div>
{% endmacro %}
```

**Step 2: Write Elegant layout CSS**

Create `platform_v2/static/css/layouts/elegant-layout.css`:

```css
/*
 * Elegant Layout Family — Floating cards, gradients, glass effects
 * Used by: midnight-purple, rose-gold, forest themes
 */

/* ── Page Header ── */
.eleg-page-header {
    margin-bottom: 32px;
}

.eleg-title {
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 1.6rem;
    font-weight: 600;
    color: var(--archie-text-primary, #e2e8f0);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 10px;
}

.eleg-title i { width: 22px; height: 22px; color: var(--archie-accent, #8b5cf6); }

.eleg-title-accent {
    width: 60px;
    height: 3px;
    background: linear-gradient(90deg, var(--archie-accent, #8b5cf6), transparent);
    border-radius: 2px;
    margin-top: 8px;
}

.eleg-subtitle {
    color: var(--archie-text-secondary, #94a3b8);
    font-size: 0.9rem;
    margin: 8px 0 0 0;
}

.eleg-header-actions {
    display: flex;
    gap: 8px;
    margin-top: 16px;
}

/* ── Stat Card ── */
.eleg-stat-card {
    background: var(--archie-bg-secondary, #1a1130);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    padding: 24px 20px;
    text-align: center;
    position: relative;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    backdrop-filter: blur(8px);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.eleg-stat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.4);
}

.eleg-stat-accent {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--archie-accent, #8b5cf6), var(--archie-cyan, #a78bfa));
    border-radius: 16px 16px 0 0;
}

.eleg-stat-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    background: linear-gradient(135deg, rgba(var(--archie-green-rgb, 139,92,246), 0.15), rgba(var(--archie-green-rgb, 139,92,246), 0.05));
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0 auto 12px;
}

.eleg-stat-icon i { width: 24px; height: 24px; color: var(--archie-accent, #8b5cf6); }

.eleg-stat--success .eleg-stat-accent { background: linear-gradient(90deg, var(--archie-success), transparent); }
.eleg-stat--success .eleg-stat-icon i { color: var(--archie-success); }
.eleg-stat--warning .eleg-stat-accent { background: linear-gradient(90deg, var(--archie-warning), transparent); }
.eleg-stat--warning .eleg-stat-icon i { color: var(--archie-warning); }
.eleg-stat--danger .eleg-stat-accent { background: linear-gradient(90deg, var(--archie-danger), transparent); }
.eleg-stat--danger .eleg-stat-icon i { color: var(--archie-danger); }
.eleg-stat--info .eleg-stat-accent { background: linear-gradient(90deg, var(--archie-cyan), transparent); }
.eleg-stat--info .eleg-stat-icon i { color: var(--archie-cyan); }

.eleg-stat-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--archie-text-primary, #e2e8f0);
    line-height: 1;
}

.eleg-stat-label {
    font-size: 0.78rem;
    color: var(--archie-text-secondary, #94a3b8);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 6px;
}

/* ── Tab Navigation ── */
.eleg-tab-nav {
    display: flex;
    gap: 6px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}

.eleg-tab {
    padding: 9px 18px;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 20px;
    color: var(--archie-text-secondary, #94a3b8);
    cursor: pointer;
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 0.85rem;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.25s ease;
}

.eleg-tab i { width: 15px; height: 15px; }

.eleg-tab.active {
    background: var(--archie-accent, #8b5cf6);
    border-color: var(--archie-accent, #8b5cf6);
    color: #fff;
    box-shadow: 0 2px 12px rgba(var(--archie-green-rgb, 139,92,246), 0.3);
}

.eleg-tab:hover:not(.active) {
    border-color: var(--archie-accent, #8b5cf6);
    color: var(--archie-text-primary, #e2e8f0);
    background: rgba(var(--archie-green-rgb, 139,92,246), 0.08);
}

.eleg-tab-badge {
    background: rgba(255,255,255,0.2);
    color: #fff;
    border-radius: 8px;
    padding: 1px 6px;
    font-size: 0.7rem;
    font-weight: 600;
}

/* ── Panel ── */
.eleg-panel {
    background: var(--archie-bg-secondary, #1a1130);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    backdrop-filter: blur(8px);
    margin-bottom: 24px;
    overflow: hidden;
}

.eleg-panel-header {
    padding: 16px 24px;
    background: linear-gradient(90deg, rgba(var(--archie-green-rgb, 139,92,246), 0.15), transparent);
    border-bottom: 1px solid rgba(255,255,255,0.06);
}

.eleg-panel-title {
    font-family: var(--archie-font-heading, 'Inter', sans-serif);
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--archie-text-primary, #e2e8f0);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

.eleg-panel-title i { width: 16px; height: 16px; color: var(--archie-accent, #8b5cf6); }

.eleg-panel-body { padding: 24px; }

.eleg-panel--compact .eleg-panel-body { padding: 16px 20px; }

/* ── Data Table ── */
.eleg-table-wrapper {
    overflow-x: auto;
    border-radius: 12px;
}

.eleg-table {
    width: 100%;
    border-collapse: collapse;
}

.eleg-table thead th {
    padding: 12px 16px;
    text-align: left;
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--archie-text-secondary, #94a3b8);
    background: rgba(var(--archie-green-rgb, 139,92,246), 0.05);
}

.eleg-table tbody td {
    padding: 14px 16px;
    color: var(--archie-text-primary, #e2e8f0);
    font-size: 0.88rem;
}

.eleg-table tbody tr {
    transition: background 0.15s ease;
}

.eleg-table tbody tr:hover {
    background: rgba(var(--archie-green-rgb, 139,92,246), 0.06);
}

.eleg-table tbody tr + tr td {
    border-top: 1px solid rgba(255,255,255,0.04);
}

/* ── Filter Bar ── */
.eleg-filter-bar {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
    flex-wrap: wrap;
    align-items: center;
}

.eleg-search-wrap {
    flex: 1;
    min-width: 200px;
    position: relative;
}

.eleg-search-wrap i {
    position: absolute;
    left: 14px;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: var(--archie-text-tertiary, #64748b);
}

.eleg-input, .eleg-select {
    background: rgba(var(--archie-green-rgb, 139,92,246), 0.05);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px;
    color: var(--archie-text-primary, #e2e8f0);
    padding: 10px 14px;
    font-size: 0.88rem;
    transition: all 0.2s ease;
}

.eleg-input:focus, .eleg-select:focus {
    border-color: var(--archie-accent, #8b5cf6);
    outline: none;
    box-shadow: 0 0 0 3px rgba(var(--archie-green-rgb, 139,92,246), 0.15);
}

.eleg-search-wrap .eleg-input {
    width: 100%;
    padding-left: 38px;
}

/* ── Modal ── */
.eleg-modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    backdrop-filter: blur(4px);
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
}

.eleg-modal {
    background: var(--archie-bg-secondary, #1a1130);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 16px;
    max-width: 95vw;
    max-height: 85vh;
    display: flex;
    flex-direction: column;
    box-shadow: 0 16px 48px rgba(0,0,0,0.5);
    overflow: hidden;
}

.eleg-modal-header {
    padding: 18px 24px;
    background: linear-gradient(90deg, rgba(var(--archie-green-rgb, 139,92,246), 0.15), transparent);
    border-bottom: 1px solid rgba(255,255,255,0.06);
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.eleg-modal-header h2 {
    font-size: 1rem;
    font-weight: 600;
    margin: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--archie-text-primary, #e2e8f0);
}

.eleg-modal-header h2 i { width: 18px; height: 18px; color: var(--archie-accent, #8b5cf6); }

.eleg-modal-close {
    background: none;
    border: none;
    color: var(--archie-text-secondary, #94a3b8);
    cursor: pointer;
    font-size: 1.4rem;
    padding: 4px 8px;
    border-radius: 8px;
    transition: background 0.15s;
}

.eleg-modal-close:hover {
    background: rgba(255,255,255,0.06);
}

.eleg-modal-body {
    padding: 24px;
    overflow-y: auto;
    flex: 1;
}

/* ── Responsive ── */
@media (max-width: 768px) {
    .eleg-stat-card { padding: 16px; border-radius: 12px; }
    .eleg-tab-nav { overflow-x: auto; flex-wrap: nowrap; }
    .eleg-tab { white-space: nowrap; padding: 8px 14px; }
    .eleg-panel { border-radius: 12px; }
    .eleg-panel-body { padding: 16px; }
    .eleg-filter-bar { flex-direction: column; }
    .eleg-search-wrap { min-width: 100%; }
}
```

**Step 3: Verify**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('layouts/elegant.html')
print('Elegant macros loaded OK')
"
```

**Step 4: Commit**

```bash
git add platform_v2/templates/layouts/elegant.html platform_v2/static/css/layouts/elegant-layout.css
git commit -m "feat(theme): Elegant layout family — floating cards, gradients, glass effects, pill nav"
```

---

### Task 8: Foundation Integration Test

**Files:**
- No new files — verification only

**Step 1: Verify all macros load through dispatcher**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))

# Test each family can be imported
for family in ['lcars', 'corporate', 'minimal', 'elegant']:
    t = env.get_template(f'layouts/{family}.html')
    # Verify all 8 macros exist
    mod = t.module
    for macro in ['page_header', 'stat_card', 'tab_nav', 'panel', 'data_table', 'card_grid', 'filter_bar', 'modal']:
        assert hasattr(mod, macro), f'{family} missing {macro}'
    print(f'{family}: all 8 macros OK')

print('Dispatcher template exists:', env.get_template('theme_macros.html') is not None)
print('ALL FOUNDATION CHECKS PASSED')
"
```

Expected: All 4 families pass, dispatcher loads.

**Step 2: Verify layout CSS files exist**

```bash
ls -la platform_v2/static/css/layouts/
```

Expected: `corporate-layout.css`, `minimal-layout.css`, `elegant-layout.css`

**Step 3: Verify context processor injects layout_family**

```bash
docker compose restart archie_platform
```

Browse to any page, view page source. Search for `layout_family` or check that no layout CSS link appears (since default is LCARS).

Then manually set a non-LCARS theme to test:

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"corporate-blue\"') WHERE username = 'admin';"
docker compose restart archie_platform
```

Browse to a SaaS module (e.g., CRM). View page source — should see:
```html
<link rel="stylesheet" href="/static/css/layouts/corporate-layout.css">
<link rel="stylesheet" href="/static/css/themes/corporate-blue.css">
```

Browse to an admin module (e.g., System Ops) — should NOT see layout or theme CSS.

**Step 4: Reset test data**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"lcars-classic\"') WHERE username = 'admin';"
docker compose restart archie_platform
```

**Step 5: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix(theme): foundation integration test fixes"
```

---

## Phase 2: Module Migrations

Each task below migrates one module template to use theme macros. The pattern is identical:
1. Import macros from `theme_macros.html`
2. Replace hardcoded HTML with macro calls
3. Keep module-specific JS and one-off elements as-is
4. Test with LCARS (should look identical to before)
5. Test with other families (should show new layout)

### Task 9: Migrate HR Management (Pilot Module)

**Files:**
- Modify: `platform_v2/templates/tools/hr_management.html`

This is the simplest module — inline CSS, basic structure. Perfect pilot.

**Step 1: Read current template**

Read `platform_v2/templates/tools/hr_management.html` fully to understand its structure.

**Step 2: Add macro imports**

At the top of the content block, add:

```jinja2
{% from 'theme_macros.html' import page_header, stat_card, tab_nav, panel, data_table, filter_bar, modal with context %}
```

**Step 3: Replace page header**

Replace the hardcoded `<header class="hr-header">...</header>` with:

```jinja2
{{ page_header('HR MANAGEMENT', subtitle='Team & Workforce Analytics', icon='users') }}
```

**Step 4: Replace stat cards**

Replace the hardcoded `.hr-stats-grid` div with macro calls wrapped in a stat grid:

```jinja2
<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">
    {{ stat_card(icon='users', value='0', label='Total Employees', id='hr-stat-total') }}
    {{ stat_card(icon='user-check', value='0', label='Active', variant='success', id='hr-stat-active') }}
    {{ stat_card(icon='user-x', value='0', label='Inactive', variant='warning', id='hr-stat-inactive') }}
</div>
```

**Step 5: Replace tab navigation**

Replace the hardcoded `.hr-tabs` div with:

```jinja2
{{ tab_nav(tabs=[
    {'id': 'directory', 'icon': 'users', 'label': 'Directory'},
    {'id': 'analytics', 'icon': 'bar-chart-2', 'label': 'Analytics'},
    {'id': 'departments', 'icon': 'building', 'label': 'Departments'}
], onswitch='switchHRTab') }}
```

**Step 6: Keep module JS and content blocks unchanged**

The tab content panels, JS functions, charts, and forms stay as-is. Only the structural wrappers get replaced.

**Step 7: Test with LCARS theme**

```bash
docker compose restart archie_platform
```

Browse to HR Management with LCARS theme — should look identical to before.

**Step 8: Test with Corporate theme**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"corporate-blue\"') WHERE username = 'admin';"
docker compose restart archie_platform
```

Browse to HR Management — should show corporate layout (clean rectangles, underline tabs, etc.)

**Step 9: Reset and commit**

```bash
docker exec -it archie_database psql -U archie -d archie -c "UPDATE users SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{theme_preference}', '\"lcars-classic\"') WHERE username = 'admin';"
git add platform_v2/templates/tools/hr_management.html
git commit -m "feat(theme): migrate HR Management to theme macros — pilot module"
```

---

### Task 10-17: Migrate Remaining Modules

Each follows the same pattern as Task 9. Migration order:

| Task | Module | Template File | Key Macros Used |
|------|--------|--------------|-----------------|
| 10 | Scheduler | `scheduler.html` | page_header, tab_nav, panel (FullCalendar untouched) |
| 11 | Invoicing | `invoicing.html` | page_header, stat_card, tab_nav, panel, data_table, filter_bar |
| 12 | CRM | `crm.html` | All 8 macros — most comprehensive migration |
| 13 | Email Manager | `email_manager.html` | page_header, stat_card, tab_nav, panel, data_table (SMTP banner stays) |
| 14 | Store Manager | `store_manager.html` | page_header, stat_card, card_grid, modal |
| 15 | SaaS Manager | `saas_manager.html` | page_header, tab_nav, panel |
| 16 | Training System | `training_system.html` | page_header, stat_card, card_grid, panel |
| 17 | Autonomy | `autonomy.html` | page_header, stat_card, tab_nav, panel |

**For each task, follow the same 9-step pattern from Task 9:**
1. Read current template
2. Add macro imports
3. Replace page header
4. Replace stat cards (if present)
5. Replace tab navigation (if present)
6. Replace panels / data tables / modals where applicable
7. Keep module-specific JS and one-offs unchanged
8. Test LCARS → identical to before
9. Test another family → shows new layout
10. Reset and commit

**Dashboard (Task 18) is intentionally last** — it's 5,200 lines with heavy JS. Do a partial migration: replace stat cards and panels where feasible, leave the complex IIFE-driven sections (CommandBar, HUD, MissionBriefing) untouched.

---

## Summary — Commit Sequence

| # | Task | Commit Message |
|---|------|---------------|
| 1 | Context processor | `feat(theme): add THEME_TO_FAMILY mapping + layout_family to context processor` |
| 2 | base.html loading | `feat(theme): add layout family CSS conditional loading to base.html` |
| 3 | Dispatcher + dirs | `feat(theme): create macro dispatcher + layout directory structure` |
| 4 | LCARS macros | `feat(theme): LCARS layout family macros — 8 components matching existing patterns` |
| 5 | Corporate macros+CSS | `feat(theme): Corporate layout family — clean rectangles, underline tabs, horizontal stat cards` |
| 6 | Minimal macros+CSS | `feat(theme): Minimal layout family — whitespace, hairline borders, flat cards, text tabs` |
| 7 | Elegant macros+CSS | `feat(theme): Elegant layout family — floating cards, gradients, glass effects, pill nav` |
| 8 | Foundation test | `fix(theme): foundation integration test fixes` (if needed) |
| 9 | HR migration | `feat(theme): migrate HR Management to theme macros — pilot module` |
| 10-17 | Module migrations | `feat(theme): migrate [Module] to theme macros` |

**Total new files:** 8 (4 macros + 1 dispatcher + 3 CSS)
**Modified files:** 2 foundation + 10 modules = 12
