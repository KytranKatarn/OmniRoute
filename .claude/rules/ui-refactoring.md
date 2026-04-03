---
globs: ["platform_v2/templates/**", "platform_v2/static/css/**", "platform_v2/static/js/**"]
---

# LCARS UI Refactoring Protocol

## Golden Rule
**One component at a time. Screenshot before and after. CSS-only when possible.**

## Before Touching ANY Template

1. **Screenshot every state** — Use Playwright MCP to capture: each tab, each open modal, mobile breakpoints (480/768px). Store as baseline.
2. **If Playwright is locked** by another session — STOP. Do not edit UI blind. Work on non-UI tasks instead.
3. **Read the component** you're about to change. Understand the HTML structure, CSS classes, and JS behavior BEFORE editing.

## The Edit Loop (Repeat Per Component)

```
1. SCREENSHOT  — Capture current state of the specific component
2. EDIT CSS    — Make ONE focused change (just tabs, OR just buttons, never both)
3. DEPLOY      — docker compose restart archie_platform
4. SCREENSHOT  — Capture the same view again
5. COMPARE     — Read both screenshots, verify no regression
6. COMMIT      — Only if verified. Revert if broken.
```

## What "CSS-only" Means

- Edit `/static/css/{module}.css` — add/modify rules
- DO NOT modify HTML structure (div nesting, element order, class names in HTML)
- DO NOT modify JavaScript (DOM building, style assignments, event handlers)
- DO NOT let subagents make bulk edits to templates
- If JS changes are truly needed, do them ONE function at a time with verification

## Prohibited Actions

- Never let an agent make 50+ edits to a template in one shot
- Never use `!important` to fix display issues (signals a deeper problem)
- Never add inline `display:none` as a fix — find why the CSS rule isn't working
- Never edit a 5000+ line file without first splitting it or working on a specific section
- Never claim "done" without a screenshot showing it works

## Naming Conventions

- Module CSS prefix: `sn-` (Security Network), `ac-` (Account Center), `bm-` (Backup Manager), etc.
- Design tokens: always use `var(--archie-*)` from `lcars-tokens.css`
- New component classes: `{prefix}-{component}-{modifier}` (e.g., `sn-tab-active`, `sn-btn-danger`)

## Template Splitting (For Large Files)

Before major refactoring of templates >3000 lines:
1. Split into Jinja2 `{% include %}` blocks by tab/section
2. Extract JS into separate `.js` files
3. Each piece becomes independently editable and testable

## Playwright Multi-Session Issue

Two Claude sessions cannot share one Playwright browser. If you get "Browser is already in use":
- Close the browser: `browser_close` tool
- If still locked, the other session owns it — work on non-visual tasks
- Coordinate with user about which session gets the browser
