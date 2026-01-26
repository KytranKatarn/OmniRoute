# A.R.C.H.I.E. Platform UI Style Guide

**Last Updated:** 2026-01-17 (Phase 31 Theme System Deployment)
**Purpose:** Ensure consistent look and feel across all platform modules

---

## Overview

All A.R.C.H.I.E. platform modules use a **dark cyberpunk theme** with neon accent colors. Modules are **standalone HTML pages** (NOT extending base.html) to ensure full control over styling.

---

## Core Design Principles

1. **Dark background** (`#010409`) - Nearly black
2. **Neon accent colors** - Cyan, green, orange, red
3. **Monospace fonts** - JetBrains Mono for body, Orbitron for headings
4. **Glowing effects** - Box shadows with color matching borders
5. **Transparent backgrounds** - Cards use `#0d1117` or rgba overlays

---

## Required Fonts

```html
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=JetBrains+Mono&display=swap" rel="stylesheet">
```

---

## Color Palette

| Color Name | Hex Code | Usage |
|------------|----------|-------|
| Background | `#010409` | Page background |
| Card Background | `#0d1117` | Cards, sections, nav |
| Primary Green | `#00ff41` | Success, default borders |
| Cyan | `#00FFFF` | Primary actions, headings |
| Orange | `#FFAA00` / `#FFA500` | Warnings, filters |
| Red | `#FF6B6B` / `#ff4136` | Errors, danger, CodeRabbit |
| Light Green | `#90EE90` | Tested status |
| Text Primary | `#00ff41` | Main text |
| Text Muted | `#888` / `#666` | Labels, metadata |
| Border Dark | `#333` | Subtle borders |

---

## Module Accent Colors

Each module has a **signature accent color** for its nav border and primary buttons:

| Module | Accent Color | Hex |
|--------|-------------|-----|
| Improvements Lab | Cyan | `#00FFFF` |
| CodeRabbit | Coral Red | `#FF6B6B` |
| Consciousness | Purple | `#8B5CF6` |
| Team Management | Green | `#00ff41` |
| Website Designer | Blue | `#0EA5E9` |
| Backup Manager | Orange | `#FFAA00` |

---

## Template Structure

Every module template should follow this structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>[Module Name] - A.R.C.H.I.E. Platform</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <style>
        /* Reset */
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'JetBrains Mono', monospace;
            background: #010409;
            color: #00ff41;
            min-height: 100vh;
        }

        /* Navigation */
        nav {
            background: #0d1117;
            border-bottom: 2px solid [MODULE_ACCENT_COLOR];
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        nav h1 {
            font-family: 'Orbitron', sans-serif;
            font-size: 1.5rem;
            color: [MODULE_ACCENT_COLOR];
            text-shadow: 0 0 10px [MODULE_ACCENT_COLOR];
        }

        /* ... rest of styles */
    </style>
</head>
<body>
    <nav>
        <h1>[Module Name]</h1>
        <div class="nav-links">
            <a href="/">Dashboard</a>
            <a href="/tools/improvements-lab">Improvements Lab</a>
            <!-- Other relevant links -->
        </div>
    </nav>

    <div class="container">
        <!-- Stats Grid -->
        <div class="stats-grid">
            <!-- Stat cards -->
        </div>

        <!-- Tab Navigation (if needed) -->
        <div class="tab-nav">
            <!-- Tab buttons -->
        </div>

        <!-- Content Sections -->
        <div class="section">
            <!-- Section content -->
        </div>
    </div>

    <script>
        // JavaScript here
    </script>
</body>
</html>
```

---

## Common CSS Components

### Navigation

```css
nav {
    background: #0d1117;
    border-bottom: 2px solid [ACCENT_COLOR];
    padding: 1rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

nav h1 {
    font-family: 'Orbitron', sans-serif;
    font-size: 1.5rem;
    color: [ACCENT_COLOR];
    text-shadow: 0 0 10px [ACCENT_COLOR];
}

.nav-links {
    display: flex;
    gap: 10px;
}

nav a {
    color: #00ff41;
    text-decoration: none;
    padding: 0.5rem 1rem;
    border: 1px solid #00ff41;
    border-radius: 4px;
    transition: all 0.3s;
    font-size: 0.9rem;
}

nav a:hover {
    background: #00ff41;
    color: #010409;
    box-shadow: 0 0 10px #00ff41;
}
```

### Buttons

```css
.btn {
    padding: 0.75rem 1.5rem;
    border: 1px solid #00ff41;
    background: transparent;
    color: #00ff41;
    font-family: 'JetBrains Mono', monospace;
    cursor: pointer;
    border-radius: 4px;
    transition: all 0.3s;
    font-size: 0.9rem;
}

.btn:hover {
    background: #00ff41;
    color: #010409;
    box-shadow: 0 0 15px #00ff41;
}

.btn-primary {
    border-color: #00FFFF;
    color: #00FFFF;
}

.btn-primary:hover {
    background: #00FFFF;
    color: #010409;
    box-shadow: 0 0 15px #00FFFF;
}

.btn-danger {
    border-color: #ff4136;
    color: #ff4136;
}

.btn-warning {
    border-color: #FFAA00;
    color: #FFAA00;
}

.btn-small {
    padding: 0.5rem 1rem;
    font-size: 0.8rem;
}
```

### Stats Grid

```css
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}

.stat-card {
    background: #0d1117;
    border: 1px solid [ACCENT_COLOR];
    padding: 1.5rem;
    border-radius: 8px;
    text-align: center;
    box-shadow: 0 0 10px rgba([ACCENT_RGB], 0.2);
}

.stat-card h3 {
    font-family: 'Orbitron', sans-serif;
    color: #888;
    margin-bottom: 0.5rem;
    font-size: 0.75rem;
    text-transform: uppercase;
}

.stat-card .value {
    font-size: 2rem;
    font-weight: bold;
    color: [ACCENT_COLOR];
}
```

### Tab Navigation

```css
.tab-nav {
    display: flex;
    gap: 0;
    margin-bottom: 20px;
    border-bottom: 2px solid #333;
}

.tab-btn {
    padding: 12px 24px;
    background: transparent;
    border: none;
    color: #888;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.95rem;
    cursor: pointer;
    transition: all 0.3s;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
}

.tab-btn:hover {
    color: #fff;
}

.tab-btn.active {
    color: [ACCENT_COLOR];
    border-bottom-color: [ACCENT_COLOR];
}

.tab-content {
    display: none;
    animation: fadeIn 0.3s ease;
}

.tab-content.active {
    display: block;
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
```

### Sections

```css
.section {
    background: #0d1117;
    border: 1px solid #00ff41;
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
}

.section-header {
    padding: 15px 20px;
    border-bottom: 1px solid #333;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(0, 255, 65, 0.05);
}

.section-header h2 {
    margin: 0;
    color: #00FFFF;
    font-family: 'Orbitron', sans-serif;
    font-size: 1rem;
}
```

### Lists

```css
.list {
    max-height: 400px;
    overflow-y: auto;
}

.list-item {
    padding: 12px 18px;
    border-bottom: 1px solid #222;
    display: flex;
    justify-content: space-between;
    align-items: center;
    transition: background 0.3s;
}

.list-item:hover {
    background: rgba(0, 255, 65, 0.05);
}

.list-item:last-child {
    border-bottom: none;
}

.item-info {
    flex: 1;
}

.item-title {
    color: #fff;
    font-weight: bold;
    margin-bottom: 4px;
}

.item-meta {
    color: #666;
    font-size: 0.8rem;
}
```

### Badges

```css
.badge {
    padding: 4px 10px;
    font-size: 0.75rem;
    font-weight: bold;
    border-radius: 4px;
    margin-left: 10px;
}

.badge.success { background: #238636; color: #fff; }
.badge.warning { background: #FFA500; color: #000; }
.badge.danger { background: #FF6B6B; color: #fff; }
.badge.info { background: #00FFFF; color: #000; }
```

### Inputs & Forms

```css
input, textarea, select {
    padding: 10px 14px;
    background: #0d1117;
    border: 1px solid #333;
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.9rem;
    border-radius: 4px;
    outline: none;
    transition: border-color 0.3s;
}

input:focus, textarea:focus, select:focus {
    border-color: #00FFFF;
}

input::placeholder {
    color: #666;
}
```

### Modals

```css
.modal-overlay {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    z-index: 1000;
    justify-content: center;
    align-items: center;
}

.modal-overlay.active {
    display: flex;
}

.modal {
    background: #0d1117;
    border: 2px solid #00FFFF;
    border-radius: 8px;
    padding: 30px;
    max-width: 500px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
    box-shadow: 0 0 30px rgba(0, 255, 255, 0.3);
}

.modal h2 {
    font-family: 'Orbitron', sans-serif;
    color: #00FFFF;
    margin-bottom: 20px;
}
```

---

## JavaScript Tab Switching

Standard tab switching code:

```javascript
// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        // Remove active from all tabs
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

        // Add active to clicked tab
        btn.classList.add('active');
        document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    });
});
```

---

## Container Width

```css
.container {
    max-width: 1400px;
    margin: 2rem auto;
    padding: 0 2rem;
}
```

---

## Responsive Breakpoints

**Standard breakpoints for Samsung Fold 5 compatibility:**

| Breakpoint | Mode | Layout Behavior |
|------------|------|-----------------|
| >768px | Desktop | Full layouts, large spacing |
| 768px | Tablet (Fold unfolded) | Horizontal but compact, 2-col grids |
| 540px | Phone | Stack vertically, single actions |
| 480px | Small phone | Smaller fonts, minimal spacing |
| 360px | Folded/narrow | Hide non-essential elements |

```css
@media (max-width: 1200px) {
    .stats-grid {
        grid-template-columns: repeat(3, 1fr);
    }
}

/* Tablet mode - keep horizontal layouts */
@media (max-width: 768px) {
    .stats-grid {
        grid-template-columns: repeat(2, 1fr);
    }
    /* Keep header elements horizontal, just reduce spacing */
}

/* Phone mode - stack vertically */
@media (max-width: 540px) {
    .user-header {
        flex-direction: column;
    }
    .stats-grid {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 480px) {
    .stats-grid {
        grid-template-columns: 1fr;
    }
    /* Smaller fonts, minimal padding */
}

@media (max-width: 360px) {
    /* Hide non-essential, icon-only buttons */
}
```

---

## Centralized Theme System (Phase 31)

**As of Phase 31**, the theme system is centralized with shared CSS and JavaScript files deployed across all 29+ modules.

### Core Files

| File | Purpose |
|------|---------|
| `/static/css/light-mode.css` | Light mode CSS variables and overrides (~400 lines) |
| `/static/js/archie-theme.js` | Theme toggle + language placeholder (~160 lines) |
| `/templates/includes/theme_controls.html` | Reusable theme control buttons |

### Using Theme Controls in Modules

For modules that extend `base.html`, add the theme controls include to your header actions area:

```html
{% include 'includes/theme_controls.html' %}
```

This adds three buttons:
- **Sun/Moon icon**: Toggle light/dark mode
- **Globe icon**: Language selector (placeholder)
- **Arrow icon**: Back to dashboard

### Shared Navigation Includes (Auto-Themed)

These shared navigation files automatically include theme controls:

| Include File | Modules Covered |
|-------------|-----------------|
| `includes/admin_ops_nav.html` | Blueprint, Bridge, Team Management, Consciousness |
| `includes/admin_tools_nav.html` | Backup Manager, Security Network, Account Center, Pool Management |
| `includes/dev_tools_nav.html` | Code Editor, CodeRabbit, Improvements Lab, Sandbox Manager |

### For Standalone Modules (Not Extending base.html)

If your module is standalone, add these to the `<head>`:

```html
<link rel="stylesheet" href="/static/css/light-mode.css">
<script src="https://unpkg.com/lucide@latest"></script>
<script src="/static/js/archie-theme.js"></script>
```

And add inline theme buttons to your nav:

```html
<button onclick="toggleTheme()" title="Toggle Theme">
    <i data-lucide="sun" id="themeIcon"></i>
</button>
<button onclick="showLanguageMenu()" title="Language">
    <i data-lucide="globe"></i>
</button>
```

Don't forget to initialize Lucide icons:
```javascript
lucide.createIcons();
```

---

## Theme Toggle (Dark/Light Mode)

**As of Phase 29.9**, the dashboard includes a comprehensive theme toggle for Dark/Light mode with full cyberpunk aesthetic support.

### Implementation

```html
<button class="header-icon-btn theme-toggle" onclick="toggleTheme()">
    <i data-lucide="sun" id="themeIcon"></i>
</button>
```

### JavaScript

```javascript
function toggleTheme() {
    const body = document.body;
    const themeIcon = document.getElementById('themeIcon');

    if (body.classList.contains('light-mode')) {
        body.classList.remove('light-mode');
        localStorage.setItem('archie-theme', 'dark');
        themeIcon.setAttribute('data-lucide', 'sun');
    } else {
        body.classList.add('light-mode');
        localStorage.setItem('archie-theme', 'light');
        themeIcon.setAttribute('data-lucide', 'moon');
    }
    lucide.createIcons();

    // Clear matrix canvas for immediate background change
    const canvas = document.getElementById('matrix-rain');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = body.classList.contains('light-mode') ? '#f8f9fa' : '#000000';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
}
```

### Light Mode Color Palette

```css
body.light-mode {
    /* Backgrounds - Light & Clean */
    --neo-void: #f8f9fa;          /* Page background */
    --neo-deep: #ffffff;           /* Main content area */
    --neo-surface: #ffffff;        /* Cards background */
    --neo-elevated: #f0f2f5;       /* Slightly elevated elements */
    --neo-border: rgba(0, 0, 0, 0.12);

    /* Primary - Matrix Green (darkened for contrast) */
    --neo-green: #00aa33;
    --neo-green-bright: #00cc44;
    --neo-green-dim: #008828;
    --neo-green-glow: 0 2px 8px rgba(0, 170, 51, 0.3);

    /* Accent - Cyan (darkened) */
    --neo-cyan: #00a0a0;
    --neo-cyan-dim: #008080;
    --neo-cyan-glow: 0 2px 8px rgba(0, 160, 160, 0.3);

    /* Status Colors (darkened for light bg) */
    --neo-success: #00aa33;
    --neo-warning: #cc7700;
    --neo-danger: #cc2244;
    --neo-info: #0077cc;

    /* Text - High Contrast */
    --neo-text: #111827;           /* Primary text - near black */
    --neo-text-dim: #374151;       /* Secondary text */
    --neo-text-muted: #6b7280;     /* Muted/labels */
}
```

### Category Header Colors (Light Mode)

Each category uses a **darkened** version of its accent color for better contrast on light backgrounds:

| Category | Dark Mode | Light Mode |
|----------|-----------|------------|
| Creation Tools | `#00ff41` | `#00aa33` |
| Development Tools | `#00ffff` | `#00808f` |
| Admin/Admin Ops | `#ffaa00` | `#cc6600` |
| Business Tools | `#a78bfa` | `#7c3aed` |
| Standalone Apps | `#f472b6` | `#db2777` |

### Matrix Rain in Light Mode

The matrix rain effect adapts to light mode:

```javascript
function drawMatrix() {
    const isLightMode = document.body.classList.contains('light-mode');

    // Background fade
    ctx.fillStyle = isLightMode
        ? 'rgba(248, 249, 250, 0.06)'  // White fade
        : 'rgba(0, 0, 0, 0.05)';       // Black fade

    // Text color
    ctx.fillStyle = isLightMode ? '#00aa33' : '#00FF00';
}
```

### Key Light Mode Features

- **Inverted Matrix Rain**: White/cream background with dark green text
- **Category Headers**: Keep vibrant colors with subtle text shadows instead of glows
- **Tool Cards**: White backgrounds with subtle shadows, colored borders on hover
- **High Contrast Text**: Near-black (#111827) for maximum readability
- **Scanline Effect**: Hidden in light mode
- **Theme Persistence**: Uses `localStorage.setItem('archie-theme', value)`

### Visual Reference

| Element | Dark Mode | Light Mode |
|---------|-----------|------------|
| Page Background | `#000000` | `#e8eaed` (light gray) |
| Module Cards | `rgba(13,17,23,0.8)` | `rgba(255,255,255,0.98)` (solid white) |
| Category Headers | `rgba(0,255,65,0.03)` | `rgba(255,255,255,0.15)` + blur |
| Matrix Header | `rgba(0,255,65,0.02)` | `rgba(255,255,255,0.15)` + blur |
| Compact Header | `rgba(1,4,9,0.95)` | `rgba(255,255,255,0.15)` + blur |
| Primary Text | `#e6edf3` | `#111827` |
| Matrix Rain BG | `rgba(0,0,0,0.05)` | `rgba(232,234,237,0.06)` |
| Matrix Rain Text | `#00FF00` | `#00aa33` |
| Matrix Opacity | `0.25` | `0.30` |

### Transparency Hierarchy (Light Mode)

For proper visual layering in light mode:

1. **Solid Elements** (no transparency):
   - Module/Tool cards: `rgba(255,255,255,0.98)` with 2px borders
   - These stay opaque so content is easily readable

2. **Highly Transparent Elements** (15% opacity + subtle blur):
   - Matrix header (A.R.C.H.I.E. title): `rgba(255,255,255,0.15)`
   - Compact scroll header: `rgba(255,255,255,0.15)`
   - Category headers (Creation Tools, Business Tools, etc.): `rgba(255,255,255,0.15)`
   - Matrix rain clearly visible through these elements

3. **Background Offset**:
   - Page background: `#e8eaed` (light gray)
   - Module cards: Pure white
   - Creates visual separation between background and cards

### Category Header Centering

Category headers use flexbox for consistent centering across all screen sizes:

```css
.category-header {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
}

.category-header h2 {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
    text-align: center;
    width: 100%;
}

.category-header p {
    text-align: center;
    width: 100%;
    max-width: 500px;
}
```

**Responsive Behavior:**
| Breakpoint | Title Size | Description | Decorative Lines |
|------------|------------|-------------|------------------|
| Desktop | 1.1rem | 0.75rem | Visible |
| Tablet (768px) | 0.85rem | 0.7rem | Hidden |
| Phone (480px) | 0.75rem | 0.65rem | Hidden |

---

## Category Navigation System

**As of Phase 30**, modules are organized into **categories** with shared navigation bars for quick switching between related modules.

### Three Category Navigation Systems

| Category | Accent Color | Modules |
|----------|-------------|---------|
| **Admin Operations** | Orange `#FFAA00` | Blueprint, Bridge, Team Management, Consciousness |
| **Development Tools** | Cyan `#00FFFF` | Code Editor, CodeRabbit, Improvements Lab, Sandbox Manager |
| **Admin Tools** | Red `#FF6B6B` | Backup Manager, Security & Network, Account Center, Pool Management |

### Template Structure

All categorized modules **extend base.html** and use:

```html
{% extends "base.html" %}

{% block title %}Module Name - Category Name{% endblock %}
{% block module_name %}module-id{% endblock %}

{% block styles %}
    <style>
        /* Category Container Styling */
        .category-container {
            min-height: 100vh;
            background: #010409;
        }

        .category-content {
            padding-top: 70px;  /* Space for fixed nav */
        }

        .category-header {
            padding: 20px 30px;
            border-bottom: 1px solid rgba([ACCENT_COLOR], 0.2);
        }

        /* Module-specific styles */
    </style>
{% endblock %}

{% block content %}
<div class="category-container">
    {% include 'includes/category_nav.html' %}

    <div class="category-content">
        <div class="category-header">
            <h1>MODULE NAME</h1>
        </div>

        <!-- Page content -->
    </div>
</div>
{% endblock %}
```

### Navigation Components

Each category has its own navigation include:

| Category | Include File | CSS File |
|----------|-------------|----------|
| Admin Operations | `includes/admin_ops_nav.html` | `css/admin-ops.css` |
| Development Tools | `includes/dev_tools_nav.html` | `css/category-nav.css` |
| Admin Tools | `includes/admin_tools_nav.html` | `css/category-nav.css` |

### Shared CSS (`category-nav.css`)

Base styles shared by Dev Tools and Admin Tools categories:
- Fixed navigation bar at top (60px height)
- Page transition overlay with fadeout animation
- Back to Dashboard button
- Category label in center
- Module quick-switch buttons on right
- Responsive breakpoints for mobile/tablet

### Navigation Features

- **Left**: Back to Dashboard button with hover effect
- **Center**: Category label (e.g., "DEVELOPMENT TOOLS")
- **Right**: 4 module quick-switch buttons
- **Transition**: Page loading overlay fadeout animation
- **Active State**: Current module highlighted with filled background

---

## DO NOT

1. **DO NOT** use light backgrounds (white, light blue, etc.)
2. **DO NOT** extend `base.html` for standalone modules *(Exception: Admin Operations modules use base.html with shared navigation)*
3. **DO NOT** use non-monospace fonts
4. **DO NOT** use solid filled buttons by default (use transparent with borders)
5. **DO NOT** skip the neon glow effects on hover states
6. **DO NOT** forget the Orbitron font for headings

---

## Checklist for New Modules

- [ ] Standalone HTML (not extending base.html)
- [ ] Dark background `#010409`
- [ ] Google Fonts link (Orbitron + JetBrains Mono)
- [ ] Navigation with module accent color border
- [ ] Stats grid at top
- [ ] Tab navigation if needed
- [ ] Proper hover glow effects
- [ ] Consistent button styling
- [ ] Modal styling if needed
- [ ] Responsive breakpoints

---

*This style guide ensures visual consistency across the A.R.C.H.I.E. platform.*
