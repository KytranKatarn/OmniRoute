---
globs: ["platform_v2/templates/**", "platform_v2/static/**"]
---

# Frontend Rules

## UI System
- LCARS sci-fi aesthetic | Shared: `lcars-panels.css`
- Theme system (ADR-068/069): 8 themes, 4 layout families
- Fonts: Antonio (nav), Orbitron (titles), IBM Plex Mono (code)
- Testing: `admin` / `Kyt$13ran2025`

## Shared Components
- `station-ops.css` + `station-ops.js` — LCARS station terminal (crew, jobs, commands)
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
