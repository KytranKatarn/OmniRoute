# Navigation Pattern Audit Report
**Date**: 2026-03-31 | **Scope**: 22 templates in `templates/tools/`

---

## 1. Shared Nav Includes (9 files in `templates/includes/`)

| Include File | CSS Class | Module Buttons | Accent Color | Lines |
|---|---|---|---|---|
| `admin_ops_nav.html` | `admin-ops-nav` | 4 | (default) | 241 |
| `admin_tools_nav.html` | `admin-tools-nav` | 4 | (default) | 122 |
| `applications_nav.html` | `applications-nav` | 6 | (default) | 91 |
| `business_tools_nav.html` | `business-tools-nav` | 9 | #FF69B4 | 94 |
| `creation_tools_nav.html` | `creation-tools-nav` | 3 | (default) | 86 |
| `creative_studios_nav.html` | `creative-studios-nav` | 3 | (default) | 88 |
| `crypto_nav.html` | `crypto-nav` | 1 | #fbbf24 | 86 |
| `dev_tools_nav.html` | `dev-tools-nav` | 1 | (default) | 86 |
| `standalone_apps_nav.html` | `standalone-apps-nav` | 6 | (default) | 91 |

All share root class `category-nav` and use the `cn-` prefix for child elements (cn-zone, cn-zone-left, cn-zone-center, cn-zone-right, cn-back, cn-avatar, cn-username, cn-badge, cn-category-label, cn-icon-btn, nav-module-btn).

Common structure: `<nav class="category-nav {variant}">` > lcars-frame > cn-zone-left (back + avatar + username) | cn-zone-center (category label + module buttons) | cn-zone-right (utils).

`admin_ops_nav.html` is the largest (241 lines) because it includes a page transition overlay that the others don't.

**Shared CSS**: `static/css/category-nav.css` provides base styling for `.category-nav`, `.nav-module-btn`, responsive breakpoints. Each nav include also has an inline `<style>` block with its own accent color override.

---

## 2. Templates Grouped by Category Nav Pattern

### Group A: `admin_tools_nav.html` (4 templates)
| Template | Lines | Has Module Tabs? | Tab Pattern |
|---|---|---|---|
| `account_center.html` | 8,228 | Yes (6 tabs) | `tab-btn` + `data-tab` + `switchTab()` |
| `backup_manager.html` | 3,471 | Yes (5 tabs) | `tab-btn` + `onclick="switchTab()"` |
| `security_network.html` | 4,766 | Yes (6+ tabs) | `tab-btn` + `data-tab` |
| `system_operations.html` | 2,547 | Yes | `tab-btn` pattern |

### Group B: `admin_ops_nav.html` (3 templates)
| Template | Lines | Has Module Tabs? | Tab Pattern |
|---|---|---|---|
| `archie_chat.html` | 5,355 | No | Single-view chat interface |
| `autonomy.html` | 1,516 | Yes | `tab_nav` Jinja2 macro + `switchTab()` |
| `repair_bay.html` | 3,220 | Yes | `tab_nav` Jinja2 macro (from `layouts/lcars.html`) |

### Group C: `business_tools_nav.html` (2 templates)
| Template | Lines | Has Module Tabs? | Tab Pattern |
|---|---|---|---|
| `google_work_suite.html` | 466 | No | Minimal/placeholder |
| `social_media.html` | 2,288 | Minimal | 2 tab references only |

**Note**: `business_tools_nav.html` links to 9 modules (Social, Website, Calls, CRM, Google, Store, Invoicing, Automations, Task Planner) but most of those modules use different nav includes or none at all. Only 2 templates actually include it.

### Group D: `standalone_apps_nav.html` (6 templates)
| Template | Lines | Has Module Tabs? | Tab Pattern |
|---|---|---|---|
| `archie_pool.html` | 473 | No | Single view |
| `doc.html` | 1,368 | Yes (3 tabs) | `tab-btn` pattern |
| `fitness.html` | 2,283 | Yes (3 tabs) | `tab-btn` pattern |
| `media_hub.html` | 5,824 | Yes (6+ tabs) | `tab-btn` + `data-tab` |
| `pool_management.html` | 585 | No | Panel-based, no tabs |
| `therapy.html` | 3,009 | Yes (3 tabs) | `tab-btn` pattern |

### Group E: No Category Nav Include (7 templates)
| Template | Lines | Has Any Nav? | Tab Pattern |
|---|---|---|---|
| `app_builder.html` | 1,226 | **None** | None found |
| `automations.html` | 539 | **None** | Bootstrap `nav-tabs` + `nav-link` (unique pattern) |
| `game_studio.html` | 427 | **None** | Custom `gs-tab-bar` + `gs-tab` + `GS.switchTab()` |
| `products.html` | 625 | **None** | Standalone page (no `{% extends %}`, has own `<body>`) |
| `scheduler.html` | 1,068 | **None** | `tab_nav` Jinja2 macro from `theme_macros.html` |
| `team_management.html` | 1,169 | **None** | None found |
| `user_profile.html` | 1,711 | **None** | Custom `profile-nav` + `profile-nav-btn` + `switchProfileTab()` |

---

## 3. Tab Implementation Patterns (4 distinct approaches)

| Pattern | Used By | Mechanism |
|---|---|---|
| **A. `tab-btn` + `data-tab` + `switchTab()`** | account_center, backup_manager, security_network, system_operations, media_hub, doc, fitness, therapy | Inline `<button class="tab-btn">` with `data-tab` attr, JS `switchTab()` function |
| **B. `tab_nav` Jinja2 macro** | autonomy, repair_bay, scheduler | `{% from "layouts/lcars.html" import tab_nav %}` or from `theme_macros.html` |
| **C. Bootstrap nav-tabs** | automations | `<ul class="nav nav-tabs">` + `nav-link` + `data-bs-toggle="tab"` |
| **D. Custom module-specific** | game_studio (`gs-tab`), user_profile (`profile-nav-btn`) | Unique class names per module |

---

## 4. Key Findings

### Inconsistencies
1. **7 of 22 templates (32%) have NO category nav** -- they are missing the inter-module navigation bar entirely.
2. **3 different tab mechanisms** coexist (manual tab-btn, Jinja2 macro, Bootstrap). The most common is manual `tab-btn` (8 templates).
3. **`business_tools_nav.html` links to 9 modules** but only 2 templates actually include it. The other 7 SaaS modules (CRM, Website Studio, Store Builder, Call Center, Invoicing, Content Studio, Automations) either have no nav or use a different one.
4. **`admin_ops_nav.html` is 2x larger** than other navs (241 vs ~90 lines) due to a page transition overlay that should probably be shared or extracted.
5. **Each nav include has inline `<style>` blocks** duplicating the same CSS structure with only the accent color changing. This should be a single parameterized component.
6. **`products.html` is fully standalone** -- no `{% extends "base.html" %}`, has its own `<body>` tag. Completely outside the template system.
7. **`automations.html` uses Bootstrap tabs** while the rest of the platform uses LCARS-style `tab-btn`. This is a UI pattern violation.
8. **Unused nav includes**: `creation_tools_nav.html`, `creative_studios_nav.html`, `crypto_nav.html`, and `applications_nav.html` are NOT included by ANY template anywhere in the platform. `dev_tools_nav.html` is used only by `tools/repair_bay/templates/code_editor.html`. These 4 orphaned includes are dead code.

### Modules Missing Category Nav (need standardization)
| Template | Expected Category | Suggested Nav Include |
|---|---|---|
| `app_builder.html` | Business/Creation | `creation_tools_nav.html` or `business_tools_nav.html` |
| `automations.html` | Business Tools | `business_tools_nav.html` |
| `game_studio.html` | Creative Studios | `creative_studios_nav.html` |
| `products.html` | Business Tools | Needs full template rewrite (no base.html) |
| `scheduler.html` | Admin Ops | `admin_ops_nav.html` |
| `team_management.html` | Admin Tools | `admin_tools_nav.html` |
| `user_profile.html` | (user-facing) | Possibly none needed, or a user settings nav |

### Standardization Recommendations
1. **Create a single parameterized `category_nav.html`** that accepts category name, accent color, and module list as Jinja2 variables -- replacing all 9 separate nav includes.
2. **Standardize on `tab-btn` + `data-tab` pattern** (or the Jinja2 `tab_nav` macro) for all module tabs. Eliminate Bootstrap tabs from `automations.html`.
3. **Extract the page transition overlay** from `admin_ops_nav.html` into its own include or base.html.
4. **Move inline `<style>` blocks** from nav includes into `category-nav.css` using CSS custom properties.
5. **Add category nav to all 7 missing templates** using the appropriate category.
6. **Rewrite `products.html`** to extend `base.html` like every other template.
