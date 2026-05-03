# LCARS Nav Bar Strategy — Design Spec

**Date:** 2026-05-03
**Task:** #1652
**Project:** #223 — Visual Layout Communication (parent: #212 LCARS Navigation & Layout Standardization)
**Status:** Approved — ready for implementation plan
**Author:** Claude (Opus 4.7)

---

## Context

The platform has two parallel navigation includes that do the same job:

- `templates/includes/category_nav.html` — used by ~29 modules across 6 categories. 184 lines. Heavy use of inline `style="...!important"` attributes. Two parallel CSS class systems (`.nav-*` and `.cn-*`). Marked DEPRECATED in its own header comment as of 2026-04-13.
- `templates/includes/lcars-header.html` — used by AI Command modules (migrated under Project #251). 159 lines. Zero `!important`. Externalized JS. Clean Jinja parameter API with defaults. Supports per-module tabs and shortcuts.

Project #212 (LCARS Navigation & Layout Standardization) is at 77% — the foundation is built; the remaining work is platform-wide convergence onto the cleaner pattern.

Decision #398 blocks all UI nav work on this convergence shipping first. It is the #1 named blocker for Website Studio and all LCARS category headers.

This spec defines the convergence strategy.

---

## Decisions

The five clarifying decisions made during brainstorming (each chosen by the user):

| # | Decision | Choice |
|---|---|---|
| 1 | Outcome | **Converge** onto a single nav include |
| 2 | Direction | **Migrate everything to `lcars-header.html`** — keep its filename, delete `category_nav.html` |
| 3 | Sibling-list model | **Centralized siblings + per-module override** — registry computes shortcuts; routes can override |
| 4 | Migration sequence | **Wave by category** — one PR per category |
| 5 | Per-PR scope | **Nav swap only + verification checklist** — light-mode (#267) and i18n (#290/#291) stay separate |

---

## Architecture

### Single canonical include

`platform_v2/templates/includes/lcars-header.html` becomes the only nav include for non-standalone modules. Parameters (existing API, unchanged):

```
cat_accent, cat_accent_rgb, cat_accent_dark   # category accent colors
cat_label, module_title, module_back_url       # labels
header_tabs[]                                  # intra-module tabs (optional)
header_shortcuts[]                             # auto-filled by helper unless overridden
i18n_prefix                                    # i18n namespace
```

### New helper — central sibling resolver

`platform_v2/services/nav_service.py` (new file, ~80 lines, pure functions, no Flask import):

```python
def get_category_siblings(module_id: str, user) -> list[dict]:
    """Returns sibling modules in same category, RBAC-filtered, self excluded.

    Returns: [{'label': str, 'icon': str, 'url': str, 'external': bool}, ...]
    """
```

### Flask context processor

`platform_v2/app.py` registers `inject_category_siblings()`:

- Resolves `request.endpoint` to `module_id` via a static `ENDPOINT_TO_MODULE` dict built at module-load from `MODULES[*].blueprint_import`
- If `header_shortcuts` is already set in the template context (per-module override) → no-op
- Otherwise calls `get_category_siblings(module_id, current_user)` and injects result
- Memoized per-request via `flask.g`
- Wrapped in `try/except Exception` → returns empty shortcuts + logs warning on any error

---

## Components & Data Flow

```
GET /tools/backup-manager
  │
  ▼
[1] Blueprint route renders templates/tools/backup_manager.html
       which includes lcars-header.html
  │
  ▼
[2] Context processor inject_category_siblings() fires
       Looks up module_id from request.endpoint
       Skips if route already set header_shortcuts
  │
  ▼
[3] nav_service.get_category_siblings(module_id, user)
       Reads MODULES from module_registry
       Filters: same category · enabled · RBAC visible · not self
       Returns [(label, icon, url, external), ...]
  │
  ▼
[4] lcars-header.html renders shortcut pills under the LCARS bar
```

### Files touched in pilot PR (PR 1)

| File | Change | LOC |
|---|---|---|
| `services/nav_service.py` | NEW · pure functions | ~80 |
| `app.py` | +1 context_processor registration | ~5 |
| `tools/backup_manager/routes.py` | drop `cat_modules=...` from `render_template` calls | -5 |
| `templates/tools/backup_manager.html` | swap include + remove old `cat_*` set blocks | -10 |
| `tests/test_nav_service.py` | NEW · sibling resolution + RBAC + override | ~120 |
| `tests/test_nav_context_processor.py` | NEW · Flask test client integration | ~60 |

### Edge cases the helper handles explicitly

- **Self-exclusion** — current module never appears as its own sibling
- **RBAC filter** — siblings the user lacks permission for are dropped silently
- **External URL modules** (`module.external_url` set, e.g. Media Outreach: gov, civic, legal, market, wtf, creed) — link uses `target="_blank" rel="noopener noreferrer"`
- **Disabled modules** (`status='disabled'`) — never shown
- **Module not found in registry** — empty list, log warning, never crash
- **Per-module override** — route-set `header_shortcuts` bypasses the helper entirely

---

## Failure Modes & Error Handling

Context processors run on every request — defensive design is non-negotiable.

| Failure Mode | Mitigation |
|---|---|
| Context processor crashes | Wrap body in `try/except Exception` → return `{'header_shortcuts': []}` + log warning. Nav must never take down the platform. Test: `test_processor_never_raises`. |
| `request.endpoint` → `module_id` resolution | Build `ENDPOINT_TO_MODULE` dict at module load by parsing each `blueprint_import` in `MODULES`. O(1) lookup. Unknown endpoint → empty shortcuts. |
| RBAC call cost (~9 calls per page) | Memoize per-request via `flask.g`. Same user/request = compute once. |
| Anonymous / unauthenticated pages | If `current_user.is_authenticated == False` → empty shortcuts. `lcars-header.html` renders without the strip cleanly. |
| External URL safety | Render `<a target="_blank" rel="noopener noreferrer">` for `external_url` modules. |
| Migration coexistence (5 PRs of mixed state) | `category_nav.html` keeps working untouched until PR 6. The new context-processor injection is harmless to old templates (they ignore `header_shortcuts`). |
| Translation labels (registry holds English `name`) | **Accepted v1 limitation.** Helper passes `name` as-is. Followup task created against Project #290. |
| Stale browser cache (post-cleanup) | PR 6 bumps static asset version (existing pattern). One forced refresh per user post-cleanup. |

---

## Testing & Rollout

### Test pyramid

1. **Unit** (`tests/test_nav_service.py`, pytest) — sibling resolver, RBAC filter, all edge cases
2. **Integration** (`tests/test_nav_context_processor.py`, Flask test client) — real `GET /tools/X`, assert shortcuts populated, override path works
3. **Visual + functional** — `/archie-scan <module>` after each migration; Playwright dark + light screenshots every migrated module

### Wave plan

The implementation plan must derive each wave's module list from `module_registry.py` at the time the plan is written — `MODULES` is the authoritative source. Rules files in `.claude/rules/` are stale on this and must not be used as the enumeration. The wave plan defines **categories**, not modules.

| PR | Scope | Category filter |
|---|---|---|
| 1 | Pilot — helper + context processor + 1 module | One module from `ADMIN_OPERATIONS` (recommended: `backup_manager` — smallest blast radius, mature audit) |
| 2 | Admin Ops | `MODULES` where `category == ADMIN_OPERATIONS` AND `status == 'enabled'` AND not migrated in PR 1 |
| 3 | SaaS Services | `MODULES` where `category == SAAS_SERVICES` AND `status == 'enabled'` |
| 4 | Applications & Concepts | `MODULES` where `category == APPLICATIONS_CONCEPTS` AND `status == 'enabled'` |
| 5 | Creative + Crypto | `MODULES` where `category in (CREATIVE_STUDIOS, CRYPTO)` AND `status == 'enabled'` |
| 6 | Cleanup | Delete `category_nav.html`, `category-nav.css`, all `.cn-*` and `.nav-*` rules; bump static asset version |

**Note on AI Command and Media Outreach:** AI Command is already on `lcars-header.html` (Project #251) — no migration work. Media Outreach modules are external URLs without internal templates — they appear in *other* categories' shortcut strips when present, but have no nav of their own to migrate.

### Per-PR rollout cadence

1. Branch: `feat/nav-converge-<category>`
2. Run unit + integration tests locally — must pass
3. Deploy to hub: `docker compose restart archie_platform`
4. Playwright screenshots — every module in the wave, dark + light
5. Run `/archie-scan` for each migrated module — must be green
6. Open PR with screenshots + scan results in body
7. User reviews; Claude self-merges on approval (per `feedback_pr-management.md`)
8. **24h soak** before next wave kicks off
9. **48h soak** before PR 6 (cleanup is the riskiest)

### Rollback plan

- **Pre-merge regression** — fix on branch, push again. No platform impact.
- **Post-merge regression** — revert PR via `gh pr revert`. Each wave is independent; reverting wave N does not affect waves 1..N-1.
- **Context processor crash** — defensive `try/except` already returns empty list, so worst case = empty nav strip, not platform-down. `test_processor_never_raises` guards this.

### Success criteria — done when

- All 6 PRs merged and soaked
- `grep -r "category_nav.html" platform_v2/templates/` returns 0 results
- `grep -rE "\\.cn-|\\.nav-modules|\\.nav-category-label" platform_v2/static/css/` returns 0 results
- P.R.O.B.E. all-suites green
- Project #212 (LCARS Nav Standardization) progresses 77% → 100%
- Decision #398 (UI nav blocker) flipped to **resolved** — unblocks Website Studio and LCARS category headers

---

## Out of Scope (Deliberate)

- **Light-mode CSS audit** — Project #267 owns it; nav swap delivers cleaner targets for that project to operate on
- **Translating shortcut labels** — Project #290/#291 owns it; helper passes registry English names for v1
- **Mobile breakpoint redesign** — current `lcars-header.css` breakpoints are kept
- **Per-category accent color rationalization** — keep current colors; aesthetic decision belongs elsewhere
- **Standalone product navs** (KSO, KBS, Comms, Media Hub standalone, WTF) — `standalone-extraction.md` owns these; each ships its own nav stack

---

## Open Followups (Tasks to Create)

1. Translate shortcut labels via `i18n_prefix` — file under Project #290 after PR 6 merges
2. Per-module override audit — once helper ships, sweep modules to confirm none need custom shortcut lists
3. Decision #398 resolution log — close it with a `log_decision` call referencing PR 6 merge

---

## References

- Parent project: #212 LCARS Navigation & Layout Standardization (77%)
- This task: #1652 (P7, research)
- Predecessor: Project #251 (AI Command migration to `lcars-header.html`, 2026-04-13)
- Blocker referenced: Decision #398
- Rules: `.claude/rules/ui-refactoring.md`, `.claude/rules/frontend.md`
- Existing files: `platform_v2/templates/includes/lcars-header.html`, `platform_v2/templates/includes/category_nav.html`, `platform_v2/static/css/category-nav.css`, `platform_v2/module_registry.py`
