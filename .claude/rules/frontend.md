---
globs: ["platform_v2/templates/**", "platform_v2/static/**"]
---

# Frontend Rules

## UI System
- LCARS sci-fi aesthetic | Shared: `lcars-panels.css`
- Theme system (ADR-068/069): **7 theme files + the default = 8 selectable**, **3 layout families**
  (corporate / elegant / minimal). ⚠️ This line said "8 themes, 4 layout families" until
  2026-09-01; `ls static/css/themes/` returns 7 and `layouts/` returns 3. The 8th theme is
  **`lcars-classic`, which has NO file — it IS `theme.css`**, and `base.html` loads a
  `themes/<name>.css` override ONLY when the active theme is not lcars-classic. Importing a
  theme file by default overrides the default look.
- **Fonts** — three different questions, and this line used to blur them (revised 2026-09-01):
  - **What the design tokens use**: `--archie-font-mono` = **JetBrains Mono**,
    `--archie-font-display` = **Orbitron**. `--archie-font-body` resolves to the MONO stack
    (body copy is monospace by design) and `--archie-font-heading` to display. These two
    families are the design system; prefer the tokens over literal family names.
  - **What `base.html` LOADS**: exactly those two, via 2 Google Fonts links. No local font
    files exist anywhere (`find static -iname '*.woff*' -o -iname '*.ttf'` → empty).
  - **Antonio and IBM Plex Mono are real and still used**, but only by individual templates
    that load their own font link (Antonio ×3, IBM Plex Mono ×4 — e.g. `pool_management.html`,
    `partner_welcome.html`). ⚠️ **`base.html` REFERENCES both without loading either** —
    `base.html:122` sets `font-family: 'Antonio', sans-serif` and `:77` uses `'IBM Plex Mono'`,
    neither of which its own `<head>` fetches, so they silently fall back unless the visitor
    has them installed or a child template happens to load them. Fix by adding the family to
    base.html's font link or switching those rules to the tokens.
- Testing: `admin` / `Kyt$13ran2025`

## Shared Components
- ⚠️ **`station-ops.css` is a DEPRECATED 3-line shim** — its entire body is
  `@import url('department-ops.css')`, and **nothing loads it**; `station-ops.js` is an
  86-byte stub. This entry described them as "LCARS station terminal (crew, jobs, commands)"
  until 2026-09-01. Style station UI from `department-ops.css` directly.
- 🔴 **`sc-live` / `sc-static` DO NOT EXIST.** They are defined in **no CSS file anywhere**
  (`grep -rn '\.sc-live\|\.sc-static' static/css/` → empty), yet
  `static/js/department-hq-orchestration.js:31` still runs
  `badge.className = active > 0 ? 'sc-live' : 'sc-static'` on `#co-status-badge`. Because
  that assigns `className` (rather than `classList.add`) it also **wipes** whatever classes
  the badge had. Net effect: ACTIVE and STANDBY render identically — only the text differs,
  and the documented "pulsing teal vs dim" distinction has never existed. Use a real class
  or inline style; do not add new `sc-*` usages.
- `archie-time.js` — global timezone formatter, `|localtime` Jinja2 filter
- `archie-i18n.js` — i18n with `data-i18n` attrs and `t()` for JS

## i18n (8 languages)
- Tables: `translations` (column is `text` not `translation`), `translation_memory` (NO `notes` column)
- RTL: ar, he | Boot overlay: use `t()` NOT `data-i18n` (ADR-012)
- All LLM translation routes through Bridge (ADR-013)

## Patterns
- Black pre-commit reformats Python — always re-stage after first commit fails
- Blueprint template_folder: set `template_folder="templates"` if module has templates/ subdir
- TemplateNotFound: use `tools/` prefix in template paths
