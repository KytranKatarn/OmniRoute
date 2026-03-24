# System Operations — Theme System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add config-driven theming to System Operations so the same UI can render with LCARS (internal) or Kytran Empowerment (standalone) branding via a `theme.json` file.

**Architecture:** Theme config loaded at startup, injected into templates via Flask context processor. CSS variables generated from theme colors. `frame_style` controls LCARS vs modern card frames via Jinja2 conditionals.

**Tech Stack:** Flask context processors, Jinja2 conditionals, CSS custom properties, JSON config

**Spec:** `docs/superpowers/specs/2026-03-24-system-operations-audit-standalone-design.md` (Section 6)

**Scope:** Phase 4 only. Depends on Phases 1-3 (complete).

---

## File Map

### Files to Create

| File | Responsibility |
|------|---------------|
| `tools/system_operations/theme.py` | Theme loader: read JSON, merge with defaults, generate CSS vars, Flask context processor |
| `tools/system_operations/themes/lcars.json` | LCARS theme config (internal A.R.C.H.I.E.) |
| `tools/system_operations/themes/kytran.json` | Kytran Empowerment theme config (standalone default) |
| `static/css/system-operations-theme-vars.css` | Generated at startup from active theme |

### Files to Modify

| File | Changes |
|------|---------|
| `tools/system_operations/__init__.py` | Register theme context processor |
| `templates/tools/system_operations.html` | Add theme-vars.css link, conditional frame rendering |
| `static/css/system-operations.css` | Replace hardcoded colors with CSS var references where they override --archie-* vars |

---

## Task 1: Create Theme Loader (`theme.py`)

**Files:**
- Create: `platform_v2/tools/system_operations/theme.py`

- [ ] **Step 1: Create theme.py with loader, merger, CSS generator, and context processor**

```python
"""
System Operations — Theme System
Config-driven theming: load theme.json, merge with defaults, generate CSS vars.
"""

import json
import os

THEMES_DIR = os.path.join(os.path.dirname(__file__), "themes")
DEFAULT_THEME = "lcars"  # Internal default

_DEFAULT_CONFIG = {
    "product_name": "System Operations",
    "product_short": "SYSOPS",
    "logo": "/static/img/archie-logo.svg",
    "favicon": "/static/img/favicon.ico",
    "frame_style": "lcars",
    "colors": {
        "accent": "#00e5ff",
        "accent_bright": "#4df0ff",
        "accent_rgb": "0, 229, 255",
        "danger": "#ef4444",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "bg_void": "#000000",
        "bg_primary": "#0a0a1a",
        "bg_secondary": "#1a1a2e",
        "bg_tertiary": "#2a2a3e",
        "text_primary": "#e0e0e0",
        "text_secondary": "#b0b0b0",
        "text_muted": "#808080",
        "border_default": "#2a2a3e",
    },
    "fonts": {
        "heading": "Orbitron",
        "body": "IBM Plex Mono",
        "mono": "IBM Plex Mono",
    },
    "layout": {
        "border_radius": "20px",
        "nav_position": "top",
        "sidebar_width": "240px",
    },
    "custom_css": "/static/css/lcars-frames.css",
}


def load_theme(theme_name=None):
    """Load a theme by name, merging with defaults."""
    if theme_name is None:
        theme_name = os.environ.get("SYSOPS_THEME", DEFAULT_THEME)

    theme_path = os.path.join(THEMES_DIR, f"{theme_name}.json")
    if not os.path.exists(theme_path):
        return dict(_DEFAULT_CONFIG)

    with open(theme_path, "r") as f:
        override = json.load(f)

    # Deep merge: override wins, defaults fill gaps
    merged = dict(_DEFAULT_CONFIG)
    for key, value in override.items():
        if isinstance(value, dict) and key in merged and isinstance(merged[key], dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value

    return merged


def generate_theme_css(theme):
    """Generate CSS custom properties from theme config."""
    colors = theme.get("colors", {})
    fonts = theme.get("fonts", {})
    layout = theme.get("layout", {})

    lines = [":root {"]
    for key, value in colors.items():
        css_key = key.replace("_", "-")
        lines.append(f"  --sysops-{css_key}: {value};")
    for key, value in fonts.items():
        lines.append(f"  --sysops-font-{key}: '{value}', sans-serif;")
    for key, value in layout.items():
        css_key = key.replace("_", "-")
        lines.append(f"  --sysops-{css_key}: {value};")
    lines.append("}")
    return "\n".join(lines)


def write_theme_css(theme, output_path):
    """Write generated CSS vars to a static file."""
    css = generate_theme_css(theme)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(css)


def init_theme(app):
    """Initialize theme system: load theme, generate CSS, register context processor."""
    theme = load_theme()

    # Generate CSS vars file
    css_path = os.path.join(app.static_folder, "css", "system-operations-theme-vars.css")
    write_theme_css(theme, css_path)

    @app.context_processor
    def inject_sysops_theme():
        return {"sysops_theme": theme}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/system_operations/theme.py
git commit -m "feat(sysops): theme loader — config-driven theming system"
```

---

## Task 2: Create Theme JSON Files

**Files:**
- Create: `platform_v2/tools/system_operations/themes/lcars.json`
- Create: `platform_v2/tools/system_operations/themes/kytran.json`

- [ ] **Step 1: Create LCARS theme (internal default)**

This is the current look — LCARS sci-fi aesthetic with A.R.C.H.I.E. branding.

- [ ] **Step 2: Create Kytran theme (standalone)**

Clean, modern, professional. Blue accent. Inter font. Modern card frames instead of LCARS.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/system_operations/themes/
git commit -m "feat(sysops): LCARS + Kytran theme configs"
```

---

## Task 3: Wire Theme into __init__.py and Template

**Files:**
- Modify: `platform_v2/tools/system_operations/__init__.py`
- Modify: `platform_v2/templates/tools/system_operations.html`

- [ ] **Step 1: Register theme in __init__.py**

Add after the route registrations:
```python
from .theme import init_theme
# Theme init is called from app.py after blueprint registration
```

Actually, `init_theme` needs the Flask `app` object (for context_processor and static_folder), not the blueprint. So it should be called from `app.py` after the blueprint is registered, or we use `record_once` on the blueprint:

```python
@system_operations_bp.record_once
def on_registered(state):
    from .theme import init_theme
    init_theme(state.app)
```

- [ ] **Step 2: Update template to use theme vars**

Add theme-vars.css link and conditional frame rendering:
```html
{% block styles %}
<link rel="stylesheet" href="/static/css/system-operations-theme-vars.css">
{% if sysops_theme.custom_css %}
<link rel="stylesheet" href="{{ sysops_theme.custom_css }}">
{% endif %}
<link rel="stylesheet" href="/static/css/system-operations.css">
{% endblock %}
```

Update the title block:
```html
{% block title %}{{ sysops_theme.product_name }} - A.R.C.H.I.E.{% endblock %}
```

- [ ] **Step 3: Restart and verify**
- [ ] **Step 4: Commit**

```bash
git commit -m "feat(sysops): wire theme system into blueprint + template"
```

---

## Task 4: Verify Theme Switching Works

- [ ] **Step 1: Test with LCARS theme (default)**

Open http://192.168.1.200:3000/tools/system-operations — should look identical to before.

- [ ] **Step 2: Test theme-vars.css is generated**

```bash
cat platform_v2/static/css/system-operations-theme-vars.css
```

Should contain `:root { --sysops-accent: #00e5ff; ... }`

- [ ] **Step 3: Test with Kytran theme**

Set `SYSOPS_THEME=kytran` env var, restart, verify the CSS vars change to blue accent.

- [ ] **Step 4: Commit verification**

```bash
git commit --allow-empty -m "milestone(sysops): theme system complete — LCARS + Kytran themes"
```
